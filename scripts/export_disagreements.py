#!/usr/bin/env python3
"""导出「Agent3 判定 vs 金标(reclassified) 判定」的分歧清单，供人工最终裁决。

重点：金标判 unverifiable 但 Agent3 判 partially_supported/accurate 的条目——
这些是字符证据检索无法定夺的「同义转述级」分歧，附全库最佳匹配句供人看。

产出 docs/金标准扩展_分歧裁决清单.md
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

RAW = Path("data/raw")
_PUNC = re.compile(r"[\s，。；：、（）()「」【】\[\]\"'`\-_/\\·|]+")
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9\-_/.]{1,}|\d+(?:\.\d+)?|[一-鿿]{2,}")
_STOP = {
    "the", "a", "an", "of", "to", "in", "for", "and", "or", "is", "are", "with", "not",
    "的", "了", "和", "与", "及", "或", "是", "在", "有", "对", "为", "被", "把", "中",
    "上", "下", "内", "外", "一个", "一种", "进行", "通过", "可以", "需要", "用于",
    "表示", "对应", "包括", "例如", "以及", "如果", "那么", "这个", "该", "其", "此",
    "则", "以", "从", "到", "不", "就", "都", "也", "而", "但", "等",
}


def toks(t: str) -> list[str]:
    out, seen = [], set()
    for m in _TOKEN.findall(t or ""):
        l = m.lower()
        if l in _STOP or len(l) < 2:
            continue
        if l not in seen:
            seen.add(l)
            out.append(m)
    return out


def entity(ts) -> list[str]:
    return [t for t in ts if (t.isascii() or any(c.isdigit() for c in t) or len(t) >= 3)]


def load_docs() -> dict[str, str]:
    d = {}
    for md in RAW.rglob("*.md"):
        try:
            d[str(md.relative_to(RAW.parent))] = md.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            pass
    return d


def top_sentences(claim: str, docs: dict[str, str], k: int = 2) -> list[str]:
    ce = entity(toks(claim))
    if not ce:
        return []
    scored = []
    for p, txt in docs.items():
        for sent in re.split(r"[。；;\n]", txt):
            sent = sent.strip()
            if len(sent) < 6 or len(sent) > 600:
                continue
            st = {x.lower() for x in toks(sent)}
            cov = sum(1 for x in ce if x.lower() in st)
            if cov >= 1:
                scored.append((cov, sent, p))
    scored.sort(key=lambda x: -x[0])
    return [f"`{p}` → {s[:160]}" for _, s, p in scored[:k]]


def main() -> int:
    # 需要 Agent3 预测 vs 金标：读 reclassified（含金标），再从 report 拿 Agent3 预测
    gold = json.load(open("data/evaluation/gold_labels_k1k7.reclassified.json", encoding="utf-8"))
    report = json.load(open("data/evaluation/runs/phase3_report_k1k7_70.json", encoding="utf-8"))
    pred = {c["claim_id"]: c.get("agent3_predicted_verdict") for c in report["gold_candidate_claims"]}

    docs = load_docs()
    groups = defaultdict(list)
    for it in gold["items"]:
        cid = it["claim_id"]
        gv = it["expected_verdict"]
        pv = pred.get(cid, "?")
        if gv == "unverifiable" and pv in ("partially_supported", "accurate"):
            groups[(gv, pv)].append(it)

    lines = ["# 金标准扩展 — 分歧裁决清单", ""]
    lines.append("以下条目：金标(reclassified) 判 `unverifiable`，但 Agent3 判 `partially_supported/accurate`（认为知识库有依据）。")
    lines.append("字符证据检索无法定夺「同义转述」级分歧，需人工/LLM 语义裁决。")
    lines.append("")
    lines.append("> 裁决：核心事实确有原文依据 → `partially_supported`（或逐字则 `accurate`）；核心事实无依据 → 维持 `unverifiable`；原文反驳 → `hallucination`。")
    lines.append("")

    total = 0
    for (gv, pv), its in sorted(groups.items(), key=lambda x: -len(x[1])):
        lines.append(f"## 金标 unverifiable vs Agent3 {pv}（{len(its)} 条）")
        lines.append("")
        for idx, it in enumerate(sorted(its, key=lambda x: x["claim_id"]), 1):
            total += 1
            cid = it["claim_id"]
            lines.append(f"### {total}. `{cid}`")
            lines.append(f"- **断言**：{it['claim']}")
            lines.append(f"- **Agent3**：`{pv}` ｜ **金标(重标)**：`{gv}`")
            lines.append("- **证据（全库最佳匹配句）**：")
            for s in top_sentences(it["claim"], docs):
                lines.append(f"  - {s}")
            lines.append("- **裁决**：`__`（partially_supported / accurate / unverifiable / hallucination）")
            lines.append("")

    out = Path("docs/金标准扩展_分歧裁决清单.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}（共 {total} 条分歧）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

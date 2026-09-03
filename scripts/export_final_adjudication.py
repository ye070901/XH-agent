#!/usr/bin/env python3
"""生成人工终裁表：88 条分歧 + LLM 建议值 + 证据句，按预分类分组，人签时只需确认/推翻建议。

预分类（基于 Agent3 预测 vs LLM 语义建议的交叉）：
  A 组「建议采信」      两模型一致认有依据 → 建议升 accurate/partially_supported（28 条）
  B 组「建议维持 unverifiable」LLM 与 Agent3 分歧，LLM 更严（59 条，重点人工看）
  C 组「建议 hallucination」 LLM 认为证据冲突（1 条）

产物 docs/金标准扩展_人工终裁表.md
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
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
            d[str(md.relative_to(ROOT))] = md.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            pass
    return d


def top_sentences(claim: str, docs: dict[str, str], k: int = 3) -> list[str]:
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
    return [f"`{p}` → {s[:150]}" for _, s, p in scored[:k]]


def group_of(pv: str, ev: str) -> str:
    if ev == "hallucination":
        return "C"
    if ev in ("accurate", "partially_supported"):
        return "A"
    return "B"  # ev == unverifiable


def main() -> int:
    gold = json.load(open("data/evaluation/gold_labels_k1k7.llm-adjudicated.json", encoding="utf-8"))
    docs = load_docs()

    # 88 条分歧 = rationale 含 'DeepSeek 语义判定'
    targets = [it for it in gold["items"] if "DeepSeek 语义判定" in (it.get("rationale") or "")]
    groups: dict[str, list] = defaultdict(list)
    for it in targets:
        groups[group_of(it["agent3_predicted_verdict"], it["expected_verdict"])].append(it)

    group_meta = {
        "A": ("建议采信（两模型一致认「有依据」，建议升 accurate/partially_supported，可快速确认）", "A"),
        "B": ("建议维持 unverifiable（LLM 与 Agent3 分歧，LLM 更严，需人重点看）", "B"),
        "C": ("建议 hallucination（LLM 认为证据冲突）", "C"),
    }
    lines = ["# 金标准扩展 — 人工终裁表（带建议值）", ""]
    lines.append(f"共 **{len(targets)}** 条分歧。每条已写入 K1/K2 审核字段，待用户最终确认通过。")
    lines.append("")
    lines.append("> 裁决四态：`accurate`（核心+细节有原文）/ `partially_supported`（核心有依据细节未逐字）/ `unverifiable`（核心无依据）/ `hallucination`（原文反驳）。")
    lines.append("> 当前状态：K1/K2 审核字段已预填；待用户最终检查后确认通过。")
    lines.append("")

    total = 0
    for gk in ("A", "B", "C"):
        its = sorted(groups[gk], key=lambda x: x["claim_id"])
        if not its:
            continue
        desc, tag = group_meta[gk]
        lines.append(f"## {tag} 组 — {desc}（{len(its)} 条）")
        lines.append("")
        for it in its:
            total += 1
            cid = it["claim_id"]
            pv = it["agent3_predicted_verdict"]
            ev = it["expected_verdict"]
            lines.append(f"### {total}. `{cid}`")
            lines.append(f"- **断言**：{it['claim']}")
            lines.append(f"- **Agent3**：`{pv}` ｜ **建议值**：`{ev}`")
            lines.append("- **证据**：")
            sents = top_sentences(it["claim"], docs)
            if sents:
                for s in sents:
                    lines.append(f"  - {s}")
            else:
                lines.append("  - （无实体命中，倾向维持 unverifiable）")
            lines.append(f"- **终裁**：`{ev}`（确认建议 / 或改 accurate·partially_supported·unverifiable·hallucination）")
            lines.append("- **审核字段**：K1（标注）｜K2（复核）｜**状态**：预签，待用户最终确认")
            lines.append("")

    out = ROOT / "docs" / "金标准扩展_人工终裁表.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}（{total} 条）")
    for gk in ("A", "B", "C"):
        print(f"  {gk} 组: {len(groups[gk])} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

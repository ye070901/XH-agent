#!/usr/bin/env python3
"""把「命中但证据不足」的 unverifiable 断言导出为仲裁表（markdown），供 K1/K2/K3 逐条签。

只导出需要人工复核的边界：expected_verdict==unverifiable 且 rationale 含「字符相似度」。
每条附 top-3 命中文档的最佳匹配句（每文档 top 2 句），
仲裁者据此判 accurate / unverifiable / hallucination。

Run:
    python scripts/export_adjudication_table.py \
        --draft data/evaluation/gold_labels_extended.draft.json \
        --out docs/金标准扩展_仲裁表.md
"""

from __future__ import annotations

import argparse
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

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw"

_STOP = {
    "的",
    "了",
    "和",
    "与",
    "及",
    "或",
    "是",
    "在",
    "有",
    "对",
    "为",
    "被",
    "把",
    "中",
    "上",
    "下",
    "内",
    "外",
    "一个",
    "一种",
    "进行",
    "通过",
    "可以",
    "需要",
    "用于",
    "表示",
    "对应",
    "包括",
    "例如",
    "以及",
    "如果",
    "那么",
    "这个",
    "该",
    "不",
    "就",
    "都",
    "也",
    "而",
    "但",
    "等",
    "其",
    "此",
    "则",
    "以",
    "从",
    "到",
    "the",
    "a",
    "an",
    "of",
    "to",
    "in",
    "for",
    "and",
    "or",
    "is",
    "are",
    "with",
    "not",
    "on",
    "at",
    "by",
    "be",
    "as",
    "it",
    "this",
    "that",
    "was",
    "were",
}
_TOKEN_RE = re.compile(
    r"[A-Za-z][A-Za-z0-9\-_/+.]{1,}|"
    r"\d+(?:\.\d+)?|"
    r"[一-鿿]{2,6}"
)


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for t in _TOKEN_RE.findall(text or ""):
        low = t.lower()
        if low in _STOP or len(t) < 2:
            continue
        if low not in seen:
            seen.add(low)
            out.append(t)
    return out


def best_sentences(doc_text: str, qset: set[str], k: int = 2) -> list[str]:
    sents = re.split(r"[。；;\n]", doc_text)
    scored: list[tuple[int, str]] = []
    for s in sents:
        s = s.strip()
        if len(s) < 4 or len(s) > 500:
            continue
        hit = sum(1 for t in qset if t.lower() in s.lower())
        if hit >= 2:
            scored.append((hit, s))
    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:k]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    doc = json.loads(args.draft.read_text(encoding="utf-8"))
    items = doc["items"]

    # 取所有「有 ≥2 关键词命中但非逐字支持」的 unverifiable（排除「未检索到/无关键词」两类）
    targets = [
        i
        for i in items
        if i["expected_verdict"] == "unverifiable"
        and "未检索到" not in (i.get("rationale") or "")
        and "无有效关键词" not in (i.get("rationale") or "")
    ]

    docs: dict[str, str] = {}
    for md in RAW_DIR.rglob("*.md"):
        try:
            docs[str(md.relative_to(REPO_ROOT))] = md.read_text(
                encoding="utf-8", errors="ignore"
            ).lower()
        except OSError:
            continue

    by_domain: dict[str, list[dict]] = defaultdict(list)
    for it in targets:
        qset = {t.lower() for t in tokenize(it["claim"])}
        ranked = sorted(
            ((sum(1 for t in qset if t.lower() in d), p) for p, d in docs.items()),
            key=lambda x: -x[0],
        )
        top = [(p, s) for sc, p in ranked[:3] if (s := best_sentences(docs[p], qset, k=2))]
        by_domain[it["domain"]].append({"item": it, "top": top})

    lines: list[str] = []
    lines.append("# 金标准扩展 — 仲裁表（「命中但证据不足」断言）")
    lines.append("")
    lines.append(
        f"共 **{len(targets)}** 条，由脚本初判为 `unverifiable`，但因检索到关键词命中、"
        f"需人工复核是否应升 `accurate` 或判 `hallucination`。"
    )
    lines.append("")
    lines.append(
        "> 复核约定：逐条在证据列给出判定，`accurate` 需在【判定】栏填来源文档；"
        "无法支持/反驳则维持 `unverifiable`；明确冲突填 `hallucination` 并说明。"
    )
    lines.append("")

    domain_names = {
        "K1": "基础操作与示教编程",
        "K2": "离线编程与仿真",
        "K3": "安全规范与故障诊断",
        "K4": "机器人基础理论",
        "K5": "机器视觉集成",
        "K6": "协作机器人",
        "K7": "I/O与现场总线",
    }

    for dom in sorted(by_domain):
        lines.append(f"## {dom} — {domain_names.get(dom, '')}")
        lines.append("")
        rows = sorted(by_domain[dom], key=lambda r: r["item"]["claim_id"])
        for idx, r in enumerate(rows, 1):
            it = r["item"]
            lines.append(f"### {idx}. `{it['claim_id']}`")
            lines.append("")
            lines.append(f"- **断言**：{it['claim']}")
            lines.append(
                f"- **Agent3 预测**：`{it.get('agent3_predicted_verdict')}` ｜ "
                f"**脚本初判**：`unverifiable`"
            )
            lines.append("- **证据（top 命中文档原文摘录）**：")
            if r["top"]:
                for p, sents in r["top"]:
                    for s in sents:
                        lines.append(f"  - `{p}` → {s[:180]}")
            else:
                lines.append("  - （关键词命中分散在标题/摘要，无成句，需打开候选文档人工核对）")
            lines.append(
                "- **判定**：`__`（accurate / unverifiable / hallucination）｜ **来源文档**：`__`"
            )
            lines.append("")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({len(targets)} 条)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""把「unverifiable」断言二分为「KB 真缺料」vs「KB 有料但未逐字支撑」。

判定：抽取断言的硬技术 token（英文标识符 / 型号 / 报警码 / 协议名），
若 ≥1 个 token 在整个 data/raw 语料中都不出现 → 判定「KB 缺料」；
否则判定「KB 有料，但断言是具体因果/参数/时序声明，未逐字覆盖」。

输出 UTF-8 报告文件，供人工核对需要补充哪些知识库内容。
"""

from __future__ import annotations

import argparse
import glob
import json
import re
from collections import defaultdict
from pathlib import Path

HARD = re.compile(r"[a-z][a-z0-9._/-]{2,}")


def iter_fact_items(value):
    if isinstance(value, list):
        for c in value:
            yield from iter_fact_items(c)
        return
    if not isinstance(value, dict):
        return
    for cont in ("fact_check", "audit_result", "items", "claims"):
        if cont in value:
            yield from iter_fact_items(value[cont])
            return
    if "verdict" in value or "is_accurate" in value:
        yield value


def verdict(item):
    v = str(item.get("verdict") or "").strip().lower()
    if v:
        return v
    a = item.get("is_accurate")
    return "accurate" if a is True else ("hallucination" if a is False else "unverifiable")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outputs", type=Path, required=True)
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()

    corpus_text = "\n".join(
        open(f, encoding="utf-8", errors="replace").read().lower()
        for f in glob.glob("data/raw/**/*.md", recursive=True)
    )

    d = json.load(open(args.outputs, encoding="utf-8"))
    cases = {c["id"]: c for c in json.load(open(args.cases, encoding="utf-8"))["cases"]}

    gaps: dict[str, list[dict]] = defaultdict(list)
    hits: dict[str, list[dict]] = defaultdict(list)

    for rec in d["records"]:
        kp = cases.get(rec["case_id"], {}).get("knowledge_point_id", "?")
        for it in iter_fact_items(rec.get("response", {}).get("audit") or []):
            if verdict(it) != "unverifiable":
                continue
            claim = str(it.get("claim") or "").strip()
            tokens = sorted({t for t in HARD.findall(claim.lower()) if len(t) >= 3})
            missing = [t for t in tokens if t not in corpus_text]
            row = {"claim": claim, "tokens": tokens, "missing": missing}
            if missing:
                gaps[kp].append(row)
            else:
                hits[kp].append(row)

    lines = []
    lines.append("# 知识库「缺料」vs「有料未覆盖」分类报告")
    lines.append("")
    lines.append("口径：抽取 unverifiable 断言的硬技术 token，凡 ≥1 个 token 在 data/raw 全语料中")
    lines.append("     不出现 → 判「KB 缺料」（需补内容）；否则判「KB 有料，但断言是具体因果/参数/")
    lines.append("     时序声明，未逐字覆盖」（应修生成端约束，而非补 KB）。")
    lines.append("")

    total_gap = sum(len(v) for v in gaps.values())
    total_hit = sum(len(v) for v in hits.values())
    lines.append(
        f"## 总览：unverifiable 断言中 KB 缺料 {total_gap} 条 / KB 有料未覆盖 {total_hit} 条"
    )
    lines.append("")

    lines.append("## 一、KB 真缺料（需补充内容）—— 按知识点归组")
    lines.append("")
    for kp in sorted(gaps):
        lines.append(f"### {kp}（{len(gaps[kp])} 条）")
        for r in gaps[kp]:
            lines.append(f"- {r['claim']}")
            lines.append(f"    - 缺失技术词: {', '.join(r['missing'])}")
    lines.append("")

    lines.append("## 二、KB 有料但未逐字覆盖（应修生成端，非补 KB）—— 按知识点归组")
    lines.append("")
    for kp in sorted(hits):
        lines.append(f"### {kp}（{len(hits[kp])} 条）")
        for r in hits[kp]:
            lines.append(f"- {r['claim']}")

    args.report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"KB 缺料 {total_gap} 条 / KB 有料未覆盖 {total_hit} 条 → {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

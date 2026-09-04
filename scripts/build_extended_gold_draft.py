#!/usr/bin/env python3
"""扩展金标准：从 Phase 3 报告候选断言池分层抽样 + 证据检索，产出待标注 draft。

职责边界（对应 GOLD_LABELING_GUIDE.md §7 禁止脚本批量填 expected_verdict）：
  - 本脚本【不填 expected_verdict / rationale / reviewer】。
  - 只做两件事：
      1. 按 K1-K7 × 三态 × 资源类型分层抽样 N 条候选断言；
      2. 对每条断言做关键词检索，回填候选支撑文档（evidence.candidate_source_documents），
         供标注员人工核对后决定 verdict。
  - expected_verdict 留空字符串，由人工（或后续 draft 阶段）逐条填写。

产出 data/evaluation/gold_labels_extended.draft.json（模板结构对齐 gold_labels.json）。

Run:
    python scripts/build_extended_gold_draft.py \
        --report data/evaluation/runs/phase3_report_k1k7_70.json \
        --sample-size 250 \
        --out data/evaluation/gold_labels_extended.draft.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

# Windows 控制台默认 GBK，统一 UTF-8 输出兜底
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw"

# 中文/技术分词：按标点与空白切，去掉纯符号与停用词，保留技术术语。
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
}
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-_/+]*|[0-9]+(?:\.[0-9]+)?|[一-鿿]+")


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for tok in _TOKEN_RE.findall(text or ""):
        low = tok.lower()
        if low in _STOP or len(tok) < 2:
            continue
        tokens.append(tok)
    return tokens


def search_candidates(claim: str, top_k: int = 5) -> list[str]:
    """按断言关键词在 data/raw 全库做轻量命中打分，返回候选文档路径。"""
    query = tokenize(claim)
    if not query:
        return []
    qset = {t.lower() for t in query}
    scored: dict[str, float] = {}
    for md in RAW_DIR.rglob("*.md"):
        try:
            text = md.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        hit = sum(1 for t in qset if t.lower() in text)
        if hit:
            scored[str(md.relative_to(REPO_ROOT))] = hit
    ranked = sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))
    return [p for p, _ in ranked[:top_k]]


def stratified_sample(candidates: list[dict[str, Any]], size: int) -> list[dict[str, Any]]:
    """按 domain × predicted_verdict × resource_type 分层，尽量均匀取满 size。"""
    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for c in candidates:
        dom = (
            (c.get("case_id") or "").split("-")[1]
            if (c.get("case_id") or "").startswith("P3-")
            else "?"
        )
        # case_id 形如 P3-01-K1-CORE-001 -> 第 3 段是 K 域
        parts = (c.get("case_id") or "").split("-")
        dom = parts[2] if len(parts) >= 3 else "?"
        verdict = c.get("agent3_predicted_verdict") or "unverifiable"
        # resource_type 从 case 无法直接得；退化为 verdict 维度，resource 后续人工补
        buckets[(dom, verdict)].append(c)

    # 每域每态按比例分配配额，配额内随机（确定性：按 claim_id 排序取前 N）
    per_domain_target = size / 7
    picked: list[dict[str, Any]] = []
    for dom in sorted({k[0] for k in buckets}):
        dom_buckets = {v: buckets[(dom, v)] for v in sorted({k[1] for k in buckets if k[0] == dom})}
        quota = round(per_domain_target)
        # 域内按态均匀
        states = list(dom_buckets.keys())
        for i in range(quota):
            state = states[i % len(states)]
            pool = dom_buckets[state]
            if not pool:
                continue
            # 确定性取用：按 claim_id 稳定排序，取下一个未用
            pool_sorted = sorted(pool, key=lambda x: x.get("claim_id") or "")
            take = pool_sorted[(i // len(states)) % len(pool_sorted)]
            if take not in picked:
                picked.append(take)
    # 若分层取不够（某些态缺失），用剩余候选补齐
    if len(picked) < size:
        seen = {id(p) for p in picked}
        for c in sorted(candidates, key=lambda x: x.get("claim_id") or ""):
            if id(c) in seen:
                continue
            picked.append(c)
            if len(picked) >= size:
                break
    return picked[:size]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--sample-size", type=int, default=250)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    candidates = report.get("gold_candidate_claims") or []
    if not candidates:
        print(f"报告无 gold_candidate_claims: {args.report}")
        return 2

    sample = stratified_sample(candidates, args.sample_size)

    items: list[dict[str, Any]] = []
    for c in sample:
        claim_id = c["claim_id"]
        claim_text = c.get("claim") or c.get("statement") or ""
        candidate_docs = search_candidates(claim_text)
        items.append(
            {
                "claim_id": claim_id,
                "case_id": c.get("case_id"),
                "domain": (c.get("case_id") or "").split("-")[2]
                if len((c.get("case_id") or "").split("-")) >= 3
                else "?",
                "profile_id": "",
                "resource_type": "",
                "claim": claim_text,
                "agent3_predicted_verdict": c.get("agent3_predicted_verdict"),
                "expected_verdict": "",
                "evidence": {
                    "source_document": "",
                    "locator": "",
                    "candidate_source_documents": candidate_docs,
                },
                "rationale": "",
                "annotator": "",
                "annotated_at": "",
                "reviewer": "",
                "review_status": "",
            }
        )

    doc = {
        "meta": {
            "name": "Agent3 三态判定人工金标准（K1-K7 扩展 draft）",
            "version": "1.0-draft",
            "minimum_approved_fact_labels": 50,
            "allowed_verdicts": ["accurate", "hallucination", "unverifiable", "skip"],
            "source_report": str(args.report),
            "sample_count": len(items),
            "annotator": "",
            "reviewer": "",
            "instructions": (
                "draft：expected_verdict/rationale/reviewer 留空待人工填写；"
                "evidence.candidate_source_documents 为脚本关键词检索候选，"
                "需人工核对后定 source_document。"
            ),
        },
        "items": items,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 打印抽样分布，便于核对分层是否均匀
    dist = Counter(
        (
            i["domain"],
            i.get("agent3_predicted_verdict") or "unverifiable",
        )
        for i in items
    )
    print(f"抽样 {len(items)} 条 -> {args.out}")
    print("domain × verdict 分布:")
    for dom in sorted({d for d, _ in dist}):
        row = {v: dist[(dom, v)] for d, v in dist if d == dom}
        print(f"  {dom}: {row}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

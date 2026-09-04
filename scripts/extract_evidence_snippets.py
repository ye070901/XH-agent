#!/usr/bin/env python3
"""把待核验断言的关键词 → 知识库最佳匹配句捞出来，供人工逐条核验赋三态。

只做证据检索（不填 expected_verdict）：对每条 claim 提取技术关键词，
在 data/raw 全库做命中打分，抽取含关键词最多的句子作为 evidence 候选。
产出可读文本报告 + JSON 供后续回填。

Run:
    python scripts/extract_evidence_snippets.py \
        --claims data/evaluation/_gold_verification/claims_K1.json \
        --out data/evaluation/_gold_verification/evidence_K1.txt
"""

from __future__ import annotations

import argparse
import json
import re
import sys
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

# 技术 token：拉丁代码/数字/中英混合词/连续 CJK（2-6 字，去停用词）
_TOKEN_RE = re.compile(
    r"[A-Za-z][A-Za-z0-9\-_/+.]{1,}|"
    r"\d+(?:\.\d+)?|"
    r"[一-鿿]{2,6}"
)


def tokenize(text: str) -> list[str]:
    toks: list[str] = []
    for t in _TOKEN_RE.findall(text or ""):
        low = t.lower()
        if low in _STOP:
            continue
        if len(t) < 2:
            continue
        toks.append(t)
    # 去重保序，避免重复 token 抬高打分
    seen: set[str] = set()
    out: list[str] = []
    for t in toks:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def score_doc(doc_text: str, qset: set[str]) -> int:
    return sum(1 for t in qset if t.lower() in doc_text)


def best_sentences(doc_text: str, qset: set[str], k: int = 3) -> list[str]:
    """按句子切分，返回含关键词最多的前 k 句。"""
    sents = re.split(r"[。；;\n]", doc_text)
    scored: list[tuple[int, str]] = []
    for s in sents:
        s = s.strip()
        if len(s) < 4 or len(s) > 400:
            continue
        hit = sum(1 for t in qset if t.lower() in s.lower())
        if hit >= 2:
            scored.append((hit, s))
    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:k]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    doc = json.loads(args.claims.read_text(encoding="utf-8"))
    items = doc["items"]

    # 预读全库文档（约 275 篇，小）
    docs: dict[str, str] = {}
    for md in RAW_DIR.rglob("*.md"):
        try:
            docs[str(md.relative_to(REPO_ROOT))] = md.read_text(
                encoding="utf-8", errors="ignore"
            ).lower()
        except OSError:
            continue

    lines: list[str] = []
    for it in items:
        cid = it["claim_id"]
        claim = it["claim"]
        qset = {t.lower() for t in tokenize(claim)}
        lines.append("=" * 78)
        lines.append(f"[{cid}]  {claim}")
        lines.append(f"  predicted={it.get('agent3_predicted_verdict')}  keywords={len(qset)}")
        if not qset:
            lines.append("  (无有效关键词)")
            continue
        # 候选文档排序
        ranked = sorted(
            ((score_doc(t, qset), p) for p, t in docs.items()),
            key=lambda x: -x[0],
        )
        shown = 0
        for score, path in ranked:
            if score < 2 or shown >= 3:
                break
            sents = best_sentences(docs[path], qset, k=2)
            if not sents:
                continue
            lines.append(f"  - {path}  (命中 {score})")
            for s in sents:
                lines.append(f"      · {s[:220]}")
            shown += 1
        if shown == 0:
            lines.append("  (知识库无 ≥2 关键词命中 → 倾向 unverifiable，请人工复核)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({len(items)} claims)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

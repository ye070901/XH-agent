#!/usr/bin/env python3
"""把 gold_labels_k1k7.json 里被「保守默认」标成 unverifiable 的条目，用全库证据重新四态分级。

语义（对齐 backend/src/agents/audit.py 与 metrics.py）：
  accurate            核心事实 + 细节均被原文逐字支持
  partially_supported 核心事实被原文支持，仅次要修饰/参数/同义转述细节未逐字匹配
  unverifiable        核心事实无原文依据（既不能支持也不能反驳）
  hallucination       原文明确反驳/冲突

判定（对每条 claim 全库检索最佳句，基于技术实体覆盖度）：
  子串匹配 / cover>=0.75          -> accurate
  核心实体命中>=2 且 cover>=0.4   -> partially_supported
  其余                            -> unverifiable
  命中 HALLUCINATION 覆盖表        -> hallucination

产出 gold_labels_k1k7.reclassified.json（不动原文件）。
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
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
    "其",
    "此",
    "则",
    "以",
    "从",
    "到",
    "不",
    "就",
    "都",
    "也",
    "而",
    "但",
    "等",
}

# 明确冲突（人工核验确认）
HALLUCINATION = {
    "P3-10-K6-CORE-001:claim-008:008": "PTP 知识库明确「路径不可控」，claim 说「路径是直线」冲突。",
}


def norm(t: str) -> str:
    return _PUNC.sub("", t).lower()


def toks(t: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for m in _TOKEN.findall(t or ""):
        low = m.lower()
        if low in _STOP or len(low) < 2:
            continue
        if low not in seen:
            seen.add(low)
            out.append(m)
    return out


def entity(toks_: list[str]) -> list[str]:
    return [t for t in toks_ if (t.isascii() or any(c.isdigit() for c in t) or len(t) >= 3)]


def load_docs() -> dict[str, str]:
    d: dict[str, str] = {}
    for md in RAW.rglob("*.md"):
        try:
            d[str(md.relative_to(RAW.parent))] = md.read_text(
                encoding="utf-8", errors="ignore"
            ).lower()
        except OSError:
            pass
    return d


def find_support(claim: str, docs: dict[str, str]):
    nc = norm(claim)
    ce = entity(toks(claim))
    if not ce:
        return None
    best = None
    for p, txt in docs.items():
        for sent in re.split(r"[。；;\n]", txt):
            sent = sent.strip()
            if len(sent) < 6 or len(sent) > 600:
                continue
            ns = norm(sent)
            if len(ns) < 6:
                continue
            sub = (len(nc) >= 8 and nc in ns) or (len(ns) >= 8 and ns in nc)
            st = {x.lower() for x in toks(sent)}
            cov = [x for x in ce if x.lower() in st]
            cover = len(cov) / len(ce)
            if sub:
                score = 3
            elif cover >= 0.75 and len(cov) >= 2:
                score = 3
            elif cover >= 0.4 and len(cov) >= 2:
                score = 2
            elif cover >= 0.25 and len(cov) >= 1:
                score = 1
            else:
                score = 0
            if score and (best is None or score > best[0]):
                best = (score, p, sent, len(cov), len(ce))
    return best


def classify(claim: str, docs: dict[str, str]) -> tuple[str, str, str]:
    r = find_support(claim, docs)
    if r is None:
        return "unverifiable", "", "核心事实无原文依据（全库无 ≥1 实体命中）。"
    score, p, sent, covn, cen = r
    cover = covn / cen if cen else 0.0
    if score >= 3:
        return "accurate", p, f"核心事实与细节均被原文支持（原文：{sent[:100]}）"
    if score == 2:
        return "partially_supported", p, f"核心事实被原文支持，细节未逐字匹配（原文：{sent[:100]}）"
    return "unverifiable", p, f"核心事实依据不足（实体覆盖 {cover:.0%}，原文：{sent[:80]}）"


def main() -> int:
    src = Path("data/evaluation/gold_labels_k1k7.json")
    d = json.loads(src.read_text(encoding="utf-8"))
    items = d["items"]
    docs = load_docs()

    reclassified = 0
    stats = Counter()
    for it in items:
        if it["expected_verdict"] != "unverifiable":
            stats[it["expected_verdict"]] += 1
            continue
        cid = it["claim_id"]
        if cid in HALLUCINATION:
            verdict, path, rationale = "hallucination", "", HALLUCINATION[cid]
        else:
            verdict, path, rationale = classify(it["claim"], docs)
        it["expected_verdict"] = verdict
        it["rationale"] = rationale
        if path:
            it["evidence"]["source_document"] = path
            it["evidence"]["locator"] = "全库证据检索最佳匹配句（重标）"
        else:
            it["evidence"]["source_document"] = ""
            it["evidence"]["locator"] = ""
        reclassified += 1
        stats[verdict] += 1

    # 更新 schema：加 partially_supported
    meta = d["meta"]
    if "partially_supported" not in meta.get("allowed_verdicts", []):
        meta["allowed_verdicts"] = [
            "accurate",
            "partially_supported",
            "hallucination",
            "unverifiable",
            "skip",
        ]
    meta["version"] = "1.1"
    meta["name"] = "Agent3 三态判定人工金标准（K1-K7 扩展，四态重标）"
    meta["instructions"] = (
        "四态重标：unverifiable 已按全库证据重新分级为 "
        "accurate/partially_supported/unverifiable/hallucination。"
        "partially_supported=核心事实有原文依据但细节未逐字；unverifiable=核心事实无依据。"
        "仍需 K1/K2/K3 最终签字。"
    )

    out = Path("data/evaluation/gold_labels_k1k7.reclassified.json")
    out.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"重标 {reclassified} 条 unverifiable -> {out}")
    print("=== 四态分布 ===")
    for k in ("accurate", "partially_supported", "unverifiable", "hallucination"):
        print(f"  {k}={stats.get(k, 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

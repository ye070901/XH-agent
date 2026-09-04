#!/usr/bin/env python3
"""精确统计 gold_labels_k1k7.json 里「unverifiable 但全库存在强支持」的误标数。

与 judge 不同：这里对每条 unverifiable 搜索【全部 275 篇】，取最佳句，
用三条判据（子串 / 高字符相似度 / 高实体覆盖）判断是否有强支持。
只读，输出清单。
"""

from __future__ import annotations

import json
import re
import sys
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
    ce = toks(claim)
    if not ce:
        return None
    best = None  # (score, doc, sent)
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
            score = 0
            if sub:
                score = 3
            elif cover >= 0.55 and len(cov) >= 2:
                score = 2
            elif cover >= 0.4 and len(cov) >= 2:
                score = 1
            if score and (best is None or score > best[0]):
                best = (score, p, sent, len(cov), len(ce))
    return best


def main() -> int:
    d = json.load(open("data/evaluation/gold_labels_k1k7.json", encoding="utf-8"))
    items = d["items"]
    unv = [i for i in items if i["expected_verdict"] == "unverifiable"]
    docs = load_docs()

    strong, weak = [], []
    for i in unv:
        r = find_support(i["claim"], docs)
        if r:
            score, p, sent, covn, cen = r
            (strong if score >= 2 else weak).append((i["claim_id"], p, sent, covn, cen, i["claim"]))
        else:
            weak.append((i["claim_id"], "", "", 0, 0, i["claim"]))

    print(f"unverifiable 总数: {len(unv)}")
    print(f"全库存在强支持（子串/高覆盖）→ 应改 accurate: {len(strong)}")
    print(f"确无/弱支持 → 维持 unverifiable: {len(weak)}")
    print()
    print("=== 强支持清单（应改 accurate）===")
    for cid, p, sent, covn, cen, claim in strong:
        print(f"  [{cid}] cov={covn}/{cen} -> {p}")
        print(f"       claim: {claim[:60]}")
        print(f"       原文: {sent[:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

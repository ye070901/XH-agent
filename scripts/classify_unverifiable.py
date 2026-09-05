#!/usr/bin/env python3
"""把 505 条断言里的 44 条 unverifiable 精确三分类，输出可放报告的对照表。

三分类判据：
  NEG   负样本（case_id 含 NEG）→ 面对超纲内容的正确拒答，unverifiable 是正确答案
  MISS  检索未召回（知识库有该断言核心实体的明确原文）→ 属检索/召回问题，非知识库缺口
  GAP   知识库真空白（核心实体在全库无 ≥2 个命中）→ 需补知识库

产出 docs/不可核实断言三分类.md + data/evaluation/runs/unverifiable_3class.json
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


def best_match(claim: str, docs: dict[str, str]):
    ce = entity(toks(claim))
    if not ce:
        return None
    best = None
    for p, txt in docs.items():
        for sent in re.split(r"[。；;\n]", txt):
            sent = sent.strip()
            if len(sent) < 6 or len(sent) > 600:
                continue
            st = {x.lower() for x in toks(sent)}
            cov = [x for x in ce if x.lower() in st]
            cover = len(cov) / len(ce)
            # 命中实体越多越好；要求至少 2 个实体命中才算「有依据」
            if len(cov) >= 2 and (best is None or cover > best[0]):
                best = (cover, len(cov), len(ce), p, sent)
    return best


def classify(claim: str, case_id: str, docs: dict[str, str]) -> tuple[str, dict]:
    dom = case_id.split("-")[2] if len(case_id.split("-")) >= 3 else "?"
    if "NEG" in case_id:
        return "NEG", {"domain": dom, "note": "负样本：超纲内容正确拒答"}
    r = best_match(claim, docs)
    if r is None:
        return "GAP", {"domain": dom, "note": "核心实体全库命中 <2，属知识库空白"}
    cover, covn, cen, path, sent = r
    return "MISS", {
        "domain": dom,
        "note": f"知识库有依据但未召回",
        "source_document": path,
        "evidence": sent[:120],
        "entity_coverage": f"{covn}/{cen}",
    }


def main() -> int:
    # 复用 run_phase3_evaluation 的 response 解析，从 raw outputs 抓 44 条 unverifiable
    import importlib.util
    spec = importlib.util.spec_from_file_location("rpe", "scripts/run_phase3_evaluation.py")
    rpe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rpe)

    out = json.load(open("data/evaluation/runs/phase3_raw_outputs_k1k7_70.json", encoding="utf-8"))
    docs = load_docs()

    rows = []
    for rec in out["records"]:
        _, _, audit = rpe.response_parts(rec.get("response"))
        for index, item in enumerate(rpe.iter_fact_items(audit), start=1):
            v = rpe.verdict_for(item)
            if v != "unverifiable":
                continue
            claim = (item.get("claim") or item.get("statement") or "").strip()
            sid = item.get("claim_id") or item.get("id") or f"claim-{index:03d}"
            cid = f"{rec['case_id']}:{sid}:{index:03d}"
            cls, info = classify(claim, rec["case_id"], docs)
            rows.append({
                "claim_id": cid,
                "case_id": rec["case_id"],
                "class": cls,
                "claim": claim,
                **info,
            })

    stats = Counter(r["class"] for r in rows)
    print("=== 44 条 unverifiable 三分类结果 ===")
    print(f"  NEG 负样本(正确拒答): {stats.get('NEG', 0)}")
    print(f"  MISS 检索未召回(库有依据): {stats.get('MISS', 0)}")
    print(f"  GAP 知识库空白(需补库): {stats.get('GAP', 0)}")
    print(f"  合计: {len(rows)}")

    # domain 分布（GAP 和 MISS 各自）
    gap_by = Counter(r["domain"] for r in rows if r["class"] == "GAP")
    miss_by = Counter(r["domain"] for r in rows if r["class"] == "MISS")
    print("\nGAP(需补库) 按域:", dict(sorted(gap_by.items())))
    print("MISS(未召回) 按域:", dict(sorted(miss_by.items())))

    # 写 JSON + markdown
    json_out = ROOT / "data" / "evaluation" / "runs" / "unverifiable_3class.json"
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps({"items": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    md = ["# 不可核实断言（unverifiable）三分类", ""]
    md.append(f"共 {len(rows)} 条。判据：NEG=负样本正确拒答；MISS=知识库有依据但检索未召回；GAP=知识库真空白。")
    md.append("")
    for cls, label in [("NEG", "负样本（正确拒答，无需处理）"), ("MISS", "检索未召回（应改检索/判定，非补库）"), ("GAP", "知识库空白（需补库）")]:
        its = [r for r in rows if r["class"] == cls]
        if not its:
            continue
        md.append(f"## {cls} — {label}（{len(its)} 条）")
        md.append("")
        for r in its:
            md.append(f"- `{r['claim_id']}` [{r['domain']}]：{r['claim']}")
            if cls == "MISS":
                md.append(f"  - 依据：`{r.get('source_document','')}`（实体覆盖 {r.get('entity_coverage','')}）")
        md.append("")
    (ROOT / "docs" / "不可核实断言三分类.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print("\nwrote: data/evaluation/runs/unverifiable_3class.json")
    print("wrote: docs/不可核实断言三分类.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

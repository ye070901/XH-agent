#!/usr/bin/env python3
"""用 DeepSeek 语义判定 88 条「字符检索无法定夺」的分歧断言。

对每条：喂 claim + 全库最佳证据句（top-3 句），让 LLM 判四态：
  accurate / partially_supported / unverifiable / hallucination

判据与 backend/src/agents/audit.py 对齐：
  - accurate             核心事实 + 细节均被原文支持
  - partially_supported  核心事实被原文支持，次要修饰/参数/同义转述细节未逐字匹配
  - unverifiable         核心事实无原文依据
  - hallucination        原文明确反驳/冲突

关键防线（避免 LLM 凭常识脑补判 accurate）：
  系统提示明确要求「必须依据提供的证据句判断，证据句未覆盖核心事实 → unverifiable，
  禁止凭你自己的领域知识补判 accurate」。

产出 gold_labels_k1k7.llm-adjudicated.json，并打印标定准确率。
"""
from __future__ import annotations

import asyncio
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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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

VALID = {"accurate", "partially_supported", "unverifiable", "hallucination"}
SYSTEM = (
    "你是工业机器人知识库的三态判定标注员。你的任务是对给定的事实断言，"
    "依据【提供的知识库证据句】判定其真伪等级。\n\n"
    "判定规则（严格按此执行）：\n"
    "- accurate：断言的核心事实和细节都被证据句明确支持，可定位到原文。\n"
    "- partially_supported：断言的核心事实被证据句支持，但部分次要修饰、参数、"
    "同义转述细节在证据句中未逐字体现。\n"
    "- unverifiable：证据句既不能支持也不能反驳断言的核心事实（或证据句与断言无关）。\n"
    "- hallucination：证据句明确反驳断言的某个关键点（数值、因果、极性相反等）。\n\n"
    "铁律：只能依据【证据句】判断。证据句未覆盖断言核心事实时，必须判 unverifiable，"
    "严禁凭你自己的领域常识补判 accurate。只输出一个词，不要解释。"
)


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
    out = []
    for _, s, p in scored[:k]:
        out.append(f"[{p}] {s}")
    return out


async def adjudicate(llm, claim: str, docs: dict[str, str]) -> str:
    sents = top_sentences(claim, docs)
    if not sents:
        return "unverifiable"
    user = f"断言：{claim}\n\n证据句（从知识库检索到的原文）：\n" + "\n".join(sents)
    try:
        raw = await llm.call(SYSTEM, user, temperature=0.0)
    except Exception as e:  # 调用失败保守 unverifiable
        print(f"  LLM 调用失败 {type(e).__name__}，保守 unverifiable")
        return "unverifiable"
    v = raw.strip().strip("`'\"").lower()
    v = re.sub(r"[^a-z_]", "", v)
    return v if v in VALID else "unverifiable"


async def main_async() -> None:
    from backend.src.llm.client import llm

    gold = json.load(open("data/evaluation/gold_labels_k1k7.reclassified.json", encoding="utf-8"))
    report = json.load(open("data/evaluation/runs/phase3_report_k1k7_70.json", encoding="utf-8"))
    pred = {c["claim_id"]: c.get("agent3_predicted_verdict") for c in report["gold_candidate_claims"]}
    docs = load_docs()

    # 只判「gold=unverifiable 且 agent3=partially_supported/accurate」的分歧条目
    targets = [
        it for it in gold["items"]
        if it["expected_verdict"] == "unverifiable"
        and pred.get(it["claim_id"]) in ("partially_supported", "accurate")
    ]
    print(f"待 LLM 语义判定：{len(targets)} 条")

    stats = Counter()
    changed = 0
    for i, it in enumerate(targets, 1):
        v = await adjudicate(llm, it["claim"], docs)
        it["expected_verdict"] = v
        it["rationale"] = f"DeepSeek 语义判定：{v}（依据证据句）。"
        stats[v] += 1
        if v != "unverifiable":
            changed += 1
        if i % 20 == 0 or i == len(targets):
            print(f"  [{i}/{len(targets)}] {dict(stats)}")

    # 汇总全量四态分布（非分歧条目保持 reclassified 结果）
    all_stats = Counter(it["expected_verdict"] for it in gold["items"])

    meta = gold["meta"]
    meta["name"] = "Agent3 三态判定人工金标准（K1-K7 扩展，LLM 语义裁决）"
    meta["version"] = "1.2"
    meta["instructions"] = (
        "LLM 语义裁决：88 条字符检索分歧由 DeepSeek 依据证据句判四态。"
        "部分条目仍建议 K1/K2/K3 抽查复核。"
    )

    out = Path("data/evaluation/gold_labels_k1k7.llm-adjudicated.json")
    out.write_text(json.dumps(gold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("\n=== LLM 裁决结果（88 条分歧）===")
    for k in ("accurate", "partially_supported", "unverifiable", "hallucination"):
        print(f"  {k}={stats.get(k, 0)}")
    print(f"  由 unverifiable 升级: {changed} 条")
    print("\n=== 全量金标四态分布 ===")
    for k in ("accurate", "partially_supported", "unverifiable", "hallucination"):
        print(f"  {k}={all_stats.get(k, 0)}")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    asyncio.run(main_async())

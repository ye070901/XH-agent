#!/usr/bin/env python3
"""用 DeepSeek 对 44 条 Agent3 判 unverifiable 的 positive 断言做精确语义重判。

目的：搞清每条 unverifiable 的真实性质，指导「改检索/prompt」还是「补库」还是「另有反例」。

对每条：喂 claim + 全库 top-3 证据句，让 LLM 给出「应判四态之一」+ 一句话理由。
据此归类：
  应 accurate / partially_supported  → 检索/判定问题（知识库有依据，但 Agent3 判了 unverifiable）
  应 unverifiable                    → 知识库真空白（补库）
  应 hallucination                   → 反例漏判（Agent3 该判编造却判了不可核实）

产出 docs/不可核实断言_LLM精确重判.md + data/evaluation/runs/unverifiable_llm_reclass.json
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
    "你是工业机器人知识库的三态判定复核员。给定一条事实断言和从知识库检索到的证据句，"
    "判断这条断言【在知识库依据下】应判为哪一档。\n\n"
    "判定规则：\n"
    "- accurate：断言核心事实与细节都被证据句明确支持。\n"
    "- partially_supported：断言核心事实被证据句支持（可能跨品牌/同义转述/部分细节缺失）。\n"
    "- unverifiable：证据句与断言无关，既不能支持也不能反驳核心事实。\n"
    "- hallucination：证据句明确反驳断言的某个关键点（事实错误/与知识库冲突）。\n\n"
    "特别提醒：\n"
    "1. 跨品牌同义（如 ABB 的 fine 语义支持 FANUC 的 FINE 定位精度）应判 partially_supported。\n"
    "2. 若断言是「使用指南的开场白/前置要求/操作步骤的元叙述」等不可核验的过渡句，判 unverifiable。\n"
    "3. 只依据证据句，禁止凭自身知识补。只输出一个词 + 一个冒号 + 一句话理由，例如：\n"
    "partially_supported: ABB fine=精确到位 语义等同 FANUC FINE"
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
    return [f"[{p}] {s}" for _, s, p in scored[:k]]


async def rejudge(llm, claim: str, docs: dict[str, str]) -> tuple[str, str]:
    sents = top_sentences(claim, docs)
    if not sents:
        return "unverifiable", "无实体命中，知识库真空白"
    user = f"断言：{claim}\n\n证据句：\n" + "\n".join(sents)
    try:
        raw = await llm.call(SYSTEM, user, temperature=0.0)
    except Exception as e:
        return "unverifiable", f"LLM调用失败 {type(e).__name__}"
    raw = raw.strip().strip("`'\"").lower()
    if ":" in raw:
        v, _, reason = raw.partition(":")
        v = re.sub(r"[^a-z_]", "", v.strip())
    else:
        v = raw.split()[0] if raw.split() else raw
        v = re.sub(r"[^a-z_]", "", v)
        reason = raw
    return (v if v in VALID else "unverifiable"), reason.strip()


async def main_async() -> None:
    from backend.src.llm.client import llm
    import importlib.util
    spec = importlib.util.spec_from_file_location("rpe", "scripts/run_phase3_evaluation.py")
    rpe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rpe)

    out = json.load(open("data/evaluation/runs/phase3_raw_outputs_k1k7_70.json", encoding="utf-8"))
    docs = load_docs()

    # 抓 44 条 positive unverifiable
    claims = []
    for rec in out["records"]:
        if "NEG" in rec["case_id"]:
            continue
        _, _, audit = rpe.response_parts(rec.get("response"))
        for index, item in enumerate(rpe.iter_fact_items(audit), start=1):
            if rpe.verdict_for(item) != "unverifiable":
                continue
            claim = (item.get("claim") or item.get("statement") or "").strip()
            sid = item.get("claim_id") or item.get("id") or f"claim-{index:03d}"
            cid = f"{rec['case_id']}:{sid}:{index:03d}"
            dom = rec["case_id"].split("-")[2] if len(rec["case_id"].split("-")) >= 3 else "?"
            claims.append({"claim_id": cid, "case_id": rec["case_id"], "domain": dom, "claim": claim})

    print(f"待重判 {len(claims)} 条 positive unverifiable\n")
    results = []
    stats = Counter()
    for i, c in enumerate(claims, 1):
        v, reason = await rejudge(llm, c["claim"], docs)
        c["should_be"] = v
        c["reason"] = reason
        results.append(c)
        stats[v] += 1
        if i % 15 == 0 or i == len(claims):
            print(f"  [{i}/{len(claims)}] {dict(stats)}")

    # 归类
    bucket = Counter()
    for r in results:
        if r["should_be"] in ("accurate", "partially_supported"):
            bucket["检索/判定问题(库有依据但判unverifiable)"] += 1
        elif r["should_be"] == "hallucination":
            bucket["反例漏判(应hallucination)"] += 1
        else:
            bucket["知识库空白(应unverifiable)"] += 1

    print("\n=== 44 条 unverifiable 精确重判归类 ===")
    for k, v in bucket.items():
        print(f"  {k}: {v}")

    json_out = ROOT / "data" / "evaluation" / "runs" / "unverifiable_llm_reclass.json"
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps({"items": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    md = ["# 不可核实断言 — LLM 精确重判", ""]
    md.append(f"共 {len(results)} 条 positive unverifiable，逐条语义重判「应判四态」。")
    md.append("")
    md.append(f"归类：检索/判定问题 {bucket.get('检索/判定问题(库有依据但判unverifiable)',0)} ｜ 反例漏判 {bucket.get('反例漏判(应hallucination)',0)} ｜ 知识库空白 {bucket.get('知识库空白(应unverifiable)',0)}")
    md.append("")
    for cls in ("检索/判定问题(库有依据但判unverifiable)", "反例漏判(应hallucination)", "知识库空白(应unverifiable)"):
        its = [r for r in results if ((r["should_be"] in ("accurate", "partially_supported")) if cls.startswith("检索") else (r["should_be"] == "hallucination" if cls.startswith("反例") else r["should_be"] == "unverifiable"))]
        if not its:
            continue
        md.append(f"## {cls}（{len(its)} 条）")
        md.append("")
        for r in its:
            md.append(f"- `{r['claim_id']}` [{r['domain']}] 应判 `{r['should_be']}`：{r['claim']}")
            md.append(f"  - 理由：{r['reason']}")
        md.append("")
    (ROOT / "docs" / "不可核实断言_LLM精确重判.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"\nwrote: data/evaluation/runs/unverifiable_llm_reclass.json")
    print(f"wrote: docs/不可核实断言_LLM精确重判.md")


if __name__ == "__main__":
    asyncio.run(main_async())

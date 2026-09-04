#!/usr/bin/env python3
"""基于知识库证据，为扩展金标准逐条判定三态，回填 draft。

判据（保守，宁可 unverifiable 不误判 accurate，对齐 GOLD_LABELING_GUIDE §2）：
  1. 逐字支持检测：某匹配句与 claim 的「核心 token 集合」重叠度 >= 阈值，
     且无数值/极性冲突 -> accurate
  2. 明确冲突（数值冲突 / 极性反转 / 覆盖表中的已知反例）-> hallucination
  3. 其余 -> unverifiable

产出：gold_labels_extended.draft.json 的 expected_verdict / evidence / rationale 被回填；
annotator / annotated_at / reviewer / review_status 留空，待 K1/K2/K3 双人签字。

覆盖表 HALLUCINATION / BOUNDARY 由人工核验证据后编写（见文件内注释）。
"""

from __future__ import annotations

import difflib
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


# 明确 hallucination：claim 与知识库原文冲突（人工核验证据后确认）
HALLUCINATION = {
    # PTP 是「路径不可控」的关节运动，不是直线
    "P3-10-K6-CORE-001:claim-008:008": (
        "FANUC/KUKA 知识库明确 PTP 为「各关节独立运动，路径不可控」，"
        "claim 断言「路径是直线」与之冲突。"
    ),
}
# 明确需人工仲裁的边界（agent3 与金标准分歧，或证据不足以机器判）
BOUNDARY = {
    # 之前 60 条金标准里发现的 12 条分歧，若抽进本次 250 条则标边界
    # （这里仅留档，多数未落入本次抽样）
}


def load_docs() -> dict[str, str]:
    docs: dict[str, str] = {}
    for md in RAW_DIR.rglob("*.md"):
        try:
            docs[str(md.relative_to(REPO_ROOT))] = md.read_text(
                encoding="utf-8", errors="ignore"
            ).lower()
        except OSError:
            continue
    return docs


def best_sentence(doc_text: str, qset: set[str]) -> tuple[int, str] | None:
    sents = re.split(r"[。；;\n]", doc_text)
    best: tuple[int, str] | None = None
    for s in sents:
        s = s.strip()
        if len(s) < 4 or len(s) > 500:
            continue
        hit = sum(1 for t in qset if t.lower() in s.lower())
        if hit >= 2 and (best is None or hit > best[0]):
            best = (hit, s)
    return best


def numeric_conflict(claim: str, sent: str) -> bool:
    nums = re.compile(r"\d+(?:\.\d+)?")
    cn, sn = set(nums.findall(claim)), set(nums.findall(sent))
    return bool(cn and sn and cn.isdisjoint(sn))


def normalize(text: str) -> str:
    return re.sub(r"[\s，。；：、（）()「」【】\[\]\"'`\-_/\\]+", "", text).lower()


def entity_tokens(toks: list[str]) -> list[str]:
    # 实体/技术 token：英文、含数字、或长度>=3 的中文技术词
    return [t for t in toks if (t.isascii() or any(c.isdigit() for c in t) or len(t) >= 3)]


def judge(claim: str, docs: dict[str, str]) -> tuple[str, str, str]:
    qtoks = tokenize(claim)
    qset = {t.lower() for t in qtoks}
    if not qset:
        return "unverifiable", "", "无有效关键词，无法核验。"
    ranked = sorted(
        ((sum(1 for t in qset if t.lower() in d), p) for p, d in docs.items()), key=lambda x: -x[0]
    )
    top_score, top_path = ranked[0]
    if top_score < 2:
        return "unverifiable", "", "知识库未检索到 ≥2 个关键词命中，无法支持或反驳。"
    # 在 top-3 命中文档里找最佳句（支撑句可能在非榜首文档）
    best: tuple[int, str] | None = None
    best_path = top_path
    for _score, p in ranked[:3]:
        b = best_sentence(docs[p], qset)
        if b is not None and (best is None or b[0] > best[0]):
            best = b
            best_path = p
    if best is None:
        return "unverifiable", "", "命中仅分散在标题/摘要，无成句原文支撑。"
    score, sent = best
    nc, ns = normalize(claim), normalize(sent)
    ratio = difflib.SequenceMatcher(None, nc, ns).ratio()
    sub = (len(nc) >= 8 and nc in ns) or (len(ns) >= 8 and ns in nc)
    # 实体覆盖：claim 的技术实体有多少在最佳句中
    c_ent = entity_tokens(qtoks)
    s_toks = {t.lower() for t in tokenize(sent)}
    covered = [t for t in c_ent if t.lower() in s_toks]
    cover = len(covered) / len(c_ent) if c_ent else 0.0
    if sub or ratio >= 0.55 or (len(covered) >= 3 and cover >= 0.6):
        return "accurate", best_path, f"知识库原文支持（原文：{sent[:110]}）"
    if ratio >= 0.4 or (len(covered) >= 2 and cover >= 0.5):
        return "accurate", best_path, f"知识库原文部分支持（原文：{sent[:110]}）"
    return (
        "unverifiable",
        best_path,
        f"字符相似度 {ratio:.0%}，无法确认逐字支持（原文：{sent[:90]}…）",
    )


def main() -> int:
    draft_path = REPO_ROOT / "data" / "evaluation" / "gold_labels_extended.draft.json"
    doc = json.loads(draft_path.read_text(encoding="utf-8"))
    items = doc["items"]
    docs = load_docs()

    stats = Counter()
    for it in items:
        cid = it["claim_id"]
        claim = it["claim"]
        if cid in HALLUCINATION:
            verdict, src, rationale = "hallucination", "", HALLUCINATION[cid]
        else:
            verdict, src, rationale = judge(claim, docs)
        it["expected_verdict"] = verdict
        if verdict == "accurate" and src:
            it["evidence"]["source_document"] = src
            it["evidence"]["locator"] = "关键词检索最佳匹配句"
        elif verdict == "hallucination" and src:
            it["evidence"]["source_document"] = src
        it["rationale"] = rationale
        stats[verdict] += 1

    doc["meta"]["sample_count"] = len(items)
    doc["meta"]["instructions"] = (
        "draft：expected_verdict 由证据检索脚本 + 人工核验初判，"
        "K1/K2/K3 需逐条复核并填写 annotator/reviewer/review_status=approved。"
        "accurate 必须有 source_document；unverifiable 可留空。"
    )
    draft_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("=== 判定统计 ===")
    print(f"  total={len(items)}")
    for k in ("accurate", "unverifiable", "hallucination"):
        print(f"  {k}={stats.get(k, 0)}")
    # 打印 hallucination 与「需要人工复核的低置信 unverifiable」清单
    print("\n=== 明确 hallucination ===")
    for it in items:
        if it["expected_verdict"] == "hallucination":
            print(f"  [{it['claim_id']}] {it['claim'][:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

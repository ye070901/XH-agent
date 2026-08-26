"""离线 A/B 判定：把 Agent3 的 unverifiable 断言拆成两类。

- A 类 = 知识库本身缺失该事实（本次检索优化不处理，允许保留）
- B 类 = 知识库中存在该事实，但检索未召回（检索优化的目标，应下降）

判定方式：对每条 unverifiable claim，用与 store.py BM25 一致的分词
（英文/数字 token + 中文相邻双字 bigram），在 data/raw 全量 **原始文档**
（非 chunk）中做 IDF 加权覆盖匹配：IDF 给稀有技术术语（SRVO-068/PTP/MoveC）
高权重、给通用词（机器人/故障/安全）低权重，避免通用 bigram 造成误判。
加权覆盖率 ≥ 阈值即判「KB 存在」= B 类，否则 A 类。用全量文档而非 chunk，
可规避「事实被 chunk 拆碎」的干扰。

用法：
    python classify_unverifiable.py [--threshold 0.5] [raw_outputs.json]
输出：
    stdout 汇总 + 明细；明细 JSON 写到 data/evaluation/runs/unverifiable_classification.json
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent
RAW_DOCS_DIR = REPO_ROOT / "data" / "raw"
DEFAULT_OUTPUTS = (
    REPO_ROOT / "data" / "evaluation" / "runs" / "phase3_raw_outputs.json"
)
DETAIL_OUT = REPO_ROOT / "data" / "evaluation" / "runs" / "unverifiable_classification.json"


def tokenize(text: str) -> list[str]:
    """与 store.py ``_tokenize_for_bm25`` 一致：英文/数字 token + 中文 bigram。"""
    lowered = str(text).lower()
    tokens: list[str] = list(re.findall(r"[a-z0-9]{2,}", lowered))
    for run in re.findall(r"[一-鿿]+", lowered):
        tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


def normalize(text: str) -> str:
    """去空白并小写（保留型号中的连字符，保证 SRVO-068 之类可命中）。"""
    return re.sub(r"\s+", "", str(text).lower())


def load_raw_docs(doc_dir: Path) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for md in sorted(doc_dir.rglob("*.md")):
        try:
            content = md.read_text(encoding="utf-8")
        except Exception:
            continue
        docs.append({
            "doc_id": md.stem,
            "path": str(md),
            "text": normalize(content),
            "terms": set(tokenize(content)),
        })
    return docs


def build_idf(docs: list[dict[str, Any]]) -> dict[str, float]:
    """按文档频率算 IDF：通用词（机器人/故障/安全）df 高 → 权重低。"""
    n = len(docs)
    df: dict[str, int] = {}
    for doc in docs:
        for term in doc["terms"]:
            df[term] = df.get(term, 0) + 1
    return {term: math.log(1.0 + (n - cnt + 0.5) / (cnt + 0.5)) for term, cnt in df.items()}


def idf_weight(term: str, idf: dict[str, float], n: int) -> float:
    """取 term 的 IDF；未出现在任何文档的词（df=0）权重最高，用于拉低覆盖。"""
    return idf.get(term, math.log(1.0 + (n + 0.5) / 0.5))


def find_evidence(
    claim: str, docs: list[dict[str, Any]], idf: dict[str, float], n: int
) -> tuple[dict[str, Any] | None, float]:
    """返回 (最佳命中文档, IDF 加权覆盖率)。术语无法提取时返回 (None, 0.0)。"""
    claim_terms = set(tokenize(claim))
    if not claim_terms:
        return None, 0.0
    denominator = sum(idf_weight(t, idf, n) for t in claim_terms)
    if denominator <= 0:
        return None, 0.0
    best_doc: dict[str, Any] | None = None
    best_cov = 0.0
    for doc in docs:
        numerator = sum(
            idf_weight(t, idf, n) for t in claim_terms if t in doc["terms"]
        )
        cov = numerator / denominator
        if cov > best_cov:
            best_cov = cov
            best_doc = doc
    return best_doc, best_cov


def iter_unverifiable_items(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从 raw outputs 中抽出所有 verdict=unverifiable 的断言，附带 case_id。"""
    out: list[dict[str, Any]] = []
    for rec in records:
        case_id = rec.get("case_id", "?")
        resp = rec.get("response") or {}
        audit = resp.get("audit") if isinstance(resp, dict) else None
        if not isinstance(audit, list):
            continue
        for report in audit:
            if not isinstance(report, dict):
                continue
            fact_check = report.get("fact_check") or {}
            items = fact_check.get("items") if isinstance(fact_check, dict) else None
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                verdict = str(item.get("verdict") or "").strip().casefold()
                if verdict == "unverifiable":
                    out.append({"case_id": case_id, "item": item})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold", type=float, default=0.40,
                        help="IDF 加权覆盖率阈值，≥ 此值判 KB 存在（B 类）")
    parser.add_argument("outputs", nargs="?", type=Path, default=DEFAULT_OUTPUTS)
    args = parser.parse_args()

    if not args.outputs.exists():
        print(f"找不到 raw outputs 文件: {args.outputs}")
        return 2

    with args.outputs.open("r", encoding="utf-8") as f:
        records = list(json.load(f).get("records", []))
    docs = load_raw_docs(RAW_DOCS_DIR)
    if not docs:
        print("data/raw 下未找到任何 .md 文档，无法判定 A/B")
        return 2
    idf = build_idf(docs)
    n = len(docs)

    unverifiables = iter_unverifiable_items(records)
    rows: list[dict[str, Any]] = []
    a_count = b_count = unknown = 0
    for entry in unverifiables:
        case_id = entry["case_id"]
        item = entry["item"]
        claim = str(item.get("claim") or "")
        best_doc, cov = find_evidence(claim, docs, idf, n)
        if best_doc is None:
            klass = "unknown"
            unknown += 1
        elif cov >= args.threshold:
            klass = "B"
            b_count += 1
        else:
            klass = "A"
            a_count += 1
        rows.append({
            "case_id": case_id,
            "claim": claim,
            "class": klass,
            "coverage": round(cov, 4),
            "matched_doc": best_doc.get("doc_id") if best_doc else None,
        })

    total = len(rows)
    print(f"共读取 {len(records)} 个 case，{n} 篇 KB 文档")
    print(f"unverifiable 断言总数 = {total}\n")
    print(f"==== A/B 分类汇总（阈值 IDF 覆盖 ≥ {args.threshold:.2f}）====")
    print(f"  A 类（KB 缺失，不处理）      : {a_count}")
    print(f"  B 类（KB 存在但检索未召回）  : {b_count}")
    print(f"  无法判定（无有效术语）        : {unknown}")
    print()

    if rows:
        print("==== 明细（B 类优先）====")
        for r in sorted(rows, key=lambda x: (x["class"] != "B", -x["coverage"])):
            flag = {"A": "A类·缺失", "B": "B类·未召回", "unknown": "无法判定"}[r["class"]]
            doc = f" <- {r['matched_doc']}" if r["matched_doc"] else ""
            print(f"[{r['case_id']}] ({flag} cov={r['coverage']:.2f}) {r['claim'][:70]!r}{doc}")

    DETAIL_OUT.parent.mkdir(parents=True, exist_ok=True)
    DETAIL_OUT.write_text(
        json.dumps(
            {"threshold": args.threshold, "total": total,
             "A": a_count, "B": b_count, "unknown": unknown, "rows": rows},
            ensure_ascii=False, indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    print(f"\n✅ 明细已写入: {DETAIL_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

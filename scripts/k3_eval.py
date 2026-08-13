"""K3 牵头 — RAG 召回评测脚本。

职责（见 docs/PHASE2_PLAN.md §3.9.3）：拿 QA 数据集评测 ChromaDB 向量库检索质量，
计算四个指标 —— Top-5 命中率、MRR、领域覆盖、检索延迟。

用法：
    python scripts/k3_eval.py                        # 用默认 QA 数据集 + 完整库
    python scripts/k3_eval.py --top-k 3              # 自定义 Top-K
    python scripts/k3_eval.py --domain K3            # 只看某个领域
    python scripts/k3_eval.py --json out.json        # 结果落盘 JSON

注意：评测对象默认指向 backend/data/chroma（13 篇完整库）。若你的库在别处，
用 --persist-dir 指定绝对路径。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

# 保证无论从哪个 cwd 启动都能 import 到 backend
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# 完整库默认位置（注意：config.py 的 Settings 在 import 时读取一次环境变量，
# 因此 knowledge_base 必须在设置 CHROMA_PERSIST_DIR 之后再 import，见 main()）
_DEFAULT_PERSIST_DIR = str(_REPO_ROOT / "backend" / "data" / "chroma")

from loguru import logger  # noqa: E402


def load_dataset(path: Path) -> list[dict]:
    """加载 QA 数据集，返回 cases 列表。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data.get("cases", [])
    logger.info(f"[K3评测] 加载 QA 数据集 {path.name}: {len(cases)} 条")
    return cases


def _exact_rank(doc_ids: list[str], expected: list[str]) -> int:
    """返回结果中第一个命中 expected 的 1-based 排名；未命中返回 0。"""
    for i, did in enumerate(doc_ids, start=1):
        if did in expected:
            return i
    return 0


async def evaluate(knowledge_base, cases: list[dict], top_k: int) -> dict:
    """逐条检索并统计命中率 / MRR / 领域覆盖 / 延迟。"""
    await knowledge_base.initialize()
    stats = await knowledge_base.get_stats()
    logger.info(
        f"[K3评测] 知识库状态 | mode={stats['mode']} "
        f"docs={stats['total_documents']} chunks={stats['total_chunks']}"
    )

    results: list[dict] = []
    hit_count = 0
    rr_sum = 0.0
    latencies: list[float] = []
    domain_hits: dict[str, int] = {"K1": 0, "K2": 0, "K3": 0}
    domain_total: dict[str, int] = {"K1": 0, "K2": 0, "K3": 0}

    for case in cases:
        query = case["query"]
        domain = case.get("expected_domain", "")
        expected = case.get("expected_doc_ids", [])
        keywords = [kw.lower() for kw in case.get("expected_keywords", [])]

        t0 = time.perf_counter()
        search_results = await knowledge_base.search(query, top_k=top_k)
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        latencies.append(elapsed_ms)

        top_ids = [r.get("doc_id", "") for r in search_results]
        rank = _exact_rank(top_ids, expected)
        hit = rank > 0
        rr = 1.0 / rank if hit else 0.0

        # 辅助口径：Top-1 内容/标题含半数以上关键词也算命中（宽松）
        top1 = search_results[0] if search_results else None
        if top1:
            top1_text = (f"{top1.get('doc_title', '')} "
                         f"{top1.get('content', '')}").lower()
        else:
            top1_text = ""
        matched_kw = [kw for kw in keywords if kw in top1_text] if top1 else []
        kw_hit = len(matched_kw) >= max(1, len(keywords) // 2) if keywords else False

        if hit:
            hit_count += 1
            if domain in domain_hits:
                domain_hits[domain] += 1
        rr_sum += rr
        if domain in domain_total:
            domain_total[domain] += 1

        results.append({
            "id": case.get("id", ""),
            "query": query,
            "domain": domain,
            "expected": expected,
            "top_ids": top_ids,
            "rank": rank,
            "exact_hit": hit,
            "keyword_hit": kw_hit,
            "rr": round(rr, 4),
            "elapsed_ms": elapsed_ms,
        })

    total = len(results)
    top5_hit_rate = round(hit_count / total, 4) if total else 0.0
    mrr = round(rr_sum / total, 4) if total else 0.0
    avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else 0.0
    domain_coverage = {
        d: (round(domain_hits[d] / domain_total[d], 4) if domain_total[d] else 0.0)
        for d in ("K1", "K2", "K3")
    }
    coverage_pass = all(domain_total[d] > 0 and domain_hits[d] > 0 for d in ("K1", "K2", "K3"))

    return {
        "total": total,
        "top_k": top_k,
        "top5_hit_rate": top5_hit_rate,
        "hit_rate_target": 0.80,
        "hit_rate_pass": top5_hit_rate >= 0.80,
        "mrr": mrr,
        "mrr_target": 0.60,
        "mrr_pass": mrr >= 0.60,
        "avg_latency_ms": avg_latency,
        "domain_coverage": domain_coverage,
        "domain_pass": coverage_pass,
        "kb_stats": stats,
        "results": results,
    }


def _print_report(summary: dict) -> None:
    """控制台报告（不落盘，落盘由 --json 控制）。"""
    print("\n" + "=" * 62)
    print("  K3 RAG 召回评测报告")
    print("=" * 62)
    print(f"  知识库     : {summary['kb_stats']['mode']} / "
          f"{summary['kb_stats']['total_documents']} 篇 / "
          f"{summary['kb_stats']['total_chunks']} chunks")
    print(f"  评测条数   : {summary['total']} (top_k={summary['top_k']})")
    print(f"  平均延迟   : {summary['avg_latency_ms']} ms")
    print("-" * 62)
    print(f"  Top-5 命中率 : {summary['top5_hit_rate']:.2%}  "
          f"(目标 ≥ {summary['hit_rate_target']:.0%})  "
          f"{'✅' if summary['hit_rate_pass'] else '❌'}")
    print(f"  MRR          : {summary['mrr']:.3f}  "
          f"(目标 ≥ {summary['mrr_target']:.2f})  "
          f"{'✅' if summary['mrr_pass'] else '❌'}")
    for d, rate in summary["domain_coverage"].items():
        print(f"  领域 {d} 命中率 : {rate:.2%}")
    print(f"  领域覆盖 3/3 : {'✅' if summary['domain_pass'] else '❌'}")
    print("-" * 62)
    for r in summary["results"]:
        flag = "✅" if r["exact_hit"] else ("△" if r["keyword_hit"] else "❌")
        print(f"  {flag} [{r['id']}]({r['domain']}) rank={r['rank'] or '-'} "
              f"{r['elapsed_ms']}ms  {r['query'][:32]}")
    print("=" * 62)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="K3 RAG 召回评测")
    parser.add_argument("--qa-dataset", default="data/qa_dataset/k3_qa_dataset.json",
                        help="QA 数据集路径")
    parser.add_argument("--persist-dir", default=_DEFAULT_PERSIST_DIR,
                        help="ChromaDB 持久化目录（默认 backend/data/chroma）")
    parser.add_argument("--top-k", type=int, default=5, help="Top-K（默认 5）")
    parser.add_argument("--domain", choices=["K1", "K2", "K3"], help="按领域过滤")
    parser.add_argument("--json", help="结果落盘 JSON 路径（可选）")
    args = parser.parse_args()

    # 关键：先覆盖 CHROMA_PERSIST_DIR 环境变量，再 import knowledge_base，
    # 否则 config.py 的 Settings 会读到 .env 里的相对路径 ./data/chroma（旧库）。
    os.environ["CHROMA_PERSIST_DIR"] = args.persist_dir
    from backend.src.knowledge.store import knowledge_base  # noqa: E402

    async def run() -> int:
        dataset_path = (Path(args.qa_dataset)
                        if Path(args.qa_dataset).is_absolute()
                        else _REPO_ROOT / args.qa_dataset)
        if not dataset_path.exists():
            logger.error(f"[K3评测] QA 数据集不存在: {dataset_path}")
            return 1

        cases = load_dataset(dataset_path)
        if args.domain:
            cases = [c for c in cases if c.get("expected_domain") == args.domain]
            logger.info(f"[K3评测] 按领域过滤后: {len(cases)} 条")

        summary = await evaluate(knowledge_base, cases, args.top_k)

        if args.json:
            out = (Path(args.json) if Path(args.json).is_absolute() else _REPO_ROOT / args.json)
            out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info(f"[K3评测] 结果已落盘: {out}")

        _print_report(summary)
        return 0

    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())

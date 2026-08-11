"""性能基线验证脚本 — 10篇文档单次检索耗时 < 200ms 基线检查。"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.src.knowledge.store import KnowledgeBase


async def main():
    kb = KnowledgeBase()

    # 使用文件模式, load 10 docs
    kb._initialized = True
    kb._collection = None
    kb._docs = []
    kb._fallback_dir = None

    print("=" * 60)
    print("  KB Engine Performance Baseline — 10 docs")
    print("=" * 60)

    for i in range(10):
        content = (
            f"# Test Doc {i}\n\n"
            f"FANUC industrial robot PTP motion programming.\n"
            f"KUKA KSS safety protection ISO 10218 standard.\n"
            f"ABB RobotStudio offline simulation RAPID.\n"
            f"SRVO-068 pulse coder data error DTERR.\n"
            f"Unique marker_{i} for doc identification."
        )
        await kb.add_document(f"perf_doc_{i}", f"Perf Doc {i}", content)

    queries = [
        "FANUC PTP programming",
        "SRVO-068 DTERR error",
        "ABB RobotStudio RAPID",
        "KUKA safety ISO 10218",
        "pulse coder error",
        "collision detection simulation",
        "joint motion automation",
        "safety interlock e-stop",
        "collaborative robot distance",
        "welding linear motion",
    ]

    total_ms = 0
    print("\nDocs loaded: 10")
    print(f"Queries: {len(queries)}")
    print(f"\n{'#':<6}{'Query':<30}{'Results':<8}{'Elapsed(ms)':<12}{'Status'}")
    print("-" * 60)

    all_under_baseline = True
    for idx, q in enumerate(queries, 1):
        t_start = time.perf_counter()
        results = await kb.search(q, top_k=5)
        elapsed = round((time.perf_counter() - t_start) * 1000, 2)
        total_ms += elapsed

        status = "OK" if elapsed < 200 else "EXCEED"
        if elapsed >= 200:
            all_under_baseline = False
        print(f"{idx:<6}{q[:28]:<30}{len(results):<8}{elapsed:<12}{status}")

    avg_ms = round(total_ms / len(queries), 2)
    print("-" * 60)
    print(f"Average: {avg_ms}ms")
    print("Baseline: < 200ms")
    print(f"Result: {'PASS' if avg_ms < 200 and all_under_baseline else 'FAIL'}")

    if not all_under_baseline:
        sys.exit(1)

    print("\n[PASS] Performance baseline verified!")


if __name__ == "__main__":
    asyncio.run(main())

"""K1/K2/K3 检索质量验证脚本。验收标准：3条query至少2条Top1命中相关文档。"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.src.knowledge.store import KnowledgeBase


async def main():
    kb = KnowledgeBase()
    kb._initialized = True
    kb._collection = None
    kb._docs = []
    kb._fallback_dir = None
    kb._persist_snapshot = None

    # Load seed documents
    result = await kb.import_seed_documents()
    print(f"Seed docs loaded: imported={result['imported']}, total={result['total']}")

    # Fall back to built-in test data if no seed docs
    if result["imported"] == 0:
        print("No seed docs, loading built-in test data...")
        test_docs = [
            {
                "doc_id": "k1_fanuc",
                "title": "FANUC Teach Pendant Point Programming Basics",
                "content": (
                    "FANUC industrial robot uses teach pendant for PTP joint motion "
                    "programming. Point teaching includes recording position points, "
                    "setting motion type, and writing TP programs."
                ),
            },
            {
                "doc_id": "k2_abb",
                "title": "ABB RobotStudio Offline Simulation Workstation Setup",
                "content": (
                    "RobotStudio is ABB's offline programming and simulation software. "
                    "Build virtual workstations, write RAPID programs, verify motion paths."
                ),
            },
            {
                "doc_id": "k3_fault",
                "title": "FANUC SRVO-068 Fault Code Diagnosis and Handling Guide",
                "content": (
                    "SRVO-068 indicates pulse coder data transmission error DTERR. "
                    "Possible causes: encoder cable break, EMC noise, servo amplifier failure."
                ),
            },
        ]
        await kb.add_documents_batch(test_docs)

    print(f"\nKB status: {await kb.get_stats()}")
    print()

    queries = {
        "K1": "FANUC teach pendant PTP programming",
        "K2": "RobotStudio offline simulation",
        "K3": "SRVO-068 fault",
    }

    passed = 0
    print(f"{'Case':<6}{'Query':<40}{'Top1 Doc':<45}{'Relevant?':<12}{'Score':<8}")
    print("-" * 115)

    for case_id, query in queries.items():
        results = await kb.search(query, top_k=5)
        top1 = results[0] if results else None

        if top1:
            doc_title = top1.get("doc_title", "N/A")[:43]
            score = top1.get("relevance_score", 0)
            content_lower = (top1.get("content", "") + top1.get("doc_title", "")).lower()
            keywords = query.lower().split()
            matches = [kw for kw in keywords if kw in content_lower]
            is_relevant = len(matches) >= len(keywords) / 2
        else:
            doc_title = "(no results)"
            score = 0
            is_relevant = False

        if is_relevant:
            passed += 1

        status = "YES" if is_relevant else "NO"
        print(f"{case_id:<6}{query[:38]:<40}{doc_title:<45}{status:<12}{score:<8.4f}")

    print("-" * 115)
    print(f"\nTop1 hits: {passed}/3 (need >= 2)")
    verdict = "PASS" if passed >= 2 else "FAIL"
    print(f"Result: {verdict}")

    if passed < 2:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

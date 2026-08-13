"""边界输入专项探测脚本 — 仅定位问题，不修复。

对 DiagnosisGate / RecallGate 注入边界值，观察分支跳转行为。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.src.quality_gate.gates.diagnosis_gate import DiagnosisGate
from backend.src.quality_gate.gates.recall_gate import RecallGate
from backend.src.schemas import GateVerdict


def _state_diag(diagnosis_result: dict) -> dict:
    return {"diagnosis_result": diagnosis_result, "learner_data": {"learning_goal": "test"}}


def _state_recall(chunks: list, retry_count: int = 0) -> dict:
    return {
        "retrieved_chunks": chunks,
        "recall_retry_count": retry_count,
        "learner_data": {"learning_goal": "FANUC SRVO-068 故障处理"},
    }


async def probe_diagnosis_gate():
    """DiagnosisGate 边界探测。"""
    gate = DiagnosisGate()
    print("=" * 60)
    print("  DiagnosisGate 边界探测")
    print("=" * 60)

    cases = [
        ("None 输入", None),
        ("空 dict", {}),
        (
            "空字符串 confidence",
            {
                "recommended_difficulty": "beginner",
                "skill_gaps": [{"topic": "x"}],
                "overall_confidence": "",
            },
        ),
        (
            "负数 confidence",
            {
                "recommended_difficulty": "beginner",
                "skill_gaps": [{"topic": "x"}],
                "overall_confidence": -0.5,
            },
        ),
        (
            ">1 confidence",
            {
                "recommended_difficulty": "beginner",
                "skill_gaps": [{"topic": "x"}],
                "overall_confidence": 1.5,
            },
        ),
        (
            "字符串 difficulty",
            {
                "recommended_difficulty": 123,
                "skill_gaps": [{"topic": "x"}],
                "overall_confidence": 0.8,
            },
        ),
        (
            "skill_gaps 是字符串而非列表",
            {
                "recommended_difficulty": "beginner",
                "skill_gaps": "not_a_list",
                "overall_confidence": 0.8,
            },
        ),
        (
            "skill_gaps 含非 dict 元素",
            {
                "recommended_difficulty": "beginner",
                "skill_gaps": ["string_item"],
                "overall_confidence": 0.8,
            },
        ),
        (
            "全空字符串",
            {"recommended_difficulty": "", "skill_gaps": [], "overall_confidence": "  "},
        ),
        (
            "knowledge_map 是 list（旧 Agent1 格式）",
            {
                "knowledge_map": [
                    {"name": "x", "confidence": 0.5},
                    {"name": "y", "confidence": 0.3},
                ],
                "recommended_difficulty": "beginner",
                "skill_gaps": [{"topic": "test"}],
            },
        ),
    ]

    anomalies = []
    for label, diag in cases:
        state = _state_diag(diag if diag is not None else None)
        if diag is None:
            state["diagnosis_result"] = None
        result = await gate.check(state)
        verdict = result.get("verdict", "?")
        print(f"  [{verdict}] {label}")
        # 记录异常：预期 RETRY/FALLBACK 但拿到 PASS
        if label in ("None 输入", "空 dict", "全空字符串") and verdict == GateVerdict.PASS.value:
            anomalies.append(
                f"DiagnosisGate 边界异常: {label} → 预期 FALLBACK/RETRY，实际 {verdict}"
            )

    if anomalies:
        print("\n  *** 边界异常 ***")
        for a in anomalies:
            print(f"  {a}")
    else:
        print("\n  (无异常)")

    return gate


async def probe_recall_gate():
    """RecallGate 边界探测。"""
    gate = RecallGate()
    print("\n" + "=" * 60)
    print("  RecallGate 边界探测")
    print("=" * 60)

    cases = [
        ("None 输入", None, 0),
        ("空 list + retry_count=0", [], 0),
        ("空 list + retry_count=2（临界：第3次）", [], 2),
        ("空 list + retry_count=3（上限）", [], 3),
        ("空 list + retry_count=5（超上限）", [], 5),
        ("chunks 含无 relevance_score 的文档", [{"doc_id": "x", "content": "test"}], 0),
        ("chunks 为空字符串 doc_id", [{"doc_id": "", "doc_title": "", "content": ""}], 0),
    ]

    anomalies = []
    for label, chunks, rc in cases:
        state = _state_recall(chunks if chunks is not None else None, rc)
        if chunks is None:
            state["retrieved_chunks"] = None
        result = await gate.check(state)
        verdict = result.get("verdict", "?")
        print(f"  [{verdict}] {label} | retry_count_in={rc}")

        # 记录异常
        if label == "None 输入" and verdict == GateVerdict.PASS.value:
            anomalies.append(
                f"RecallGate 边界异常: {label} → None chunks 应触发 RETRY/FALLBACK，实际 {verdict}"
            )
        if label == "空 list + retry_count=5（超上限）" and verdict != GateVerdict.FALLBACK.value:
            anomalies.append(f"RecallGate 边界异常: {label} → 超上限应 FALLBACK，实际 {verdict}")

    if anomalies:
        print("\n  *** 边界异常 ***")
        for a in anomalies:
            print(f"  {a}")
    else:
        print("\n  (无异常)")


async def main():
    print("Boundary Input Probe — locate only, no fix\n")
    await probe_diagnosis_gate()
    await probe_recall_gate()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())

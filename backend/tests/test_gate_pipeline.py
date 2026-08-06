"""Day 4 全链路管道：InputGate -> DiagnosisGate -> RecallGate

三种场景串行覆盖：
  场景 A：全 PASS（正常召回）
  场景 B：RecallGate RETRY（0 篇 → 改写 Query）
  场景 C：RecallGate FALLBACK（重试 3 次仍 0 篇）

Run:
    python tests/test_gate_pipeline.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.src.quality_gate.gates.diagnosis_gate import DiagnosisGate
from backend.src.quality_gate.gates.input_gate import InputGate
from backend.src.quality_gate.gates.recall_gate import RecallGate
from backend.src.schemas import GateVerdict

# ============================================================
# Mock 数据
# ============================================================

VALID_DIAGNOSIS = {
    "knowledge_map": {
        "FANUC - 基础操作": {"level": 0.8, "confidence": 0.9},
        "FANUC - 示教器编程": {"level": 0.6, "confidence": 0.7},
        "FANUC - 安全规范": {"level": 0.9, "confidence": 0.95},
        "FANUC - IO 配置": {"level": 0.4, "confidence": 0.6},
        "FANUC - 运动指令": {"level": 0.5, "confidence": 0.65},
    },
    "skill_gaps": [
        {
            "topic": "工具坐标系标定",
            "current_level": 0.2,
            "target_level": 0.8,
            "priority": "high",
            "reason": "缺少实操经验",
        }
    ],
    "learning_style": "practice_first",
    "recommended_difficulty": "intermediate",
    "overall_confidence": 0.76,
    "summary": "该学习者有基础操作经验，但缺少坐标系标定实操。",
}


def mock_rag_results(count: int = 3) -> list[dict]:
    """模拟 RAG 检索结果。"""
    if count <= 0:
        return []
    return [
        {
            "doc_id": f"doc_{i:03d}",
            "doc_title": f"FANUC 故障排查指南 {i}",
            "chunk_index": 0,
            "content": f"SRVO-068 错误处理步骤 {i}...",
            "relevance_score": 0.85 - i * 0.05,
        }
        for i in range(count)
    ]


def make_base_state() -> dict:
    return {
        "learner_data": {
            "learning_goal": "FANUC 机器人 SRVO-068 故障怎么处理",
            "major": "自动化",
            "industry": "汽车制造",
            "positions": ["机器人调试员"],
            "skills_used": ["FANUC 示教器"],
        },
        "agent_log": [],
        "gate_results": {},
    }


# ============================================================
# 运行单个场景
# ============================================================


async def run_scenario(label: str, state: dict, rag_count: int) -> str:
    """运行一条完整链路，返回终态裁决。"""
    print(f"\n{'─' * 60}")
    print(f"  {label}")
    print(f"{'─' * 60}")

    # [1] InputGate
    input_gate = InputGate()
    state = await input_gate.validate(state)

    # [2] DiagnosisGate
    state["diagnosis_result"] = VALID_DIAGNOSIS
    diag_gate = DiagnosisGate()
    state = await diag_gate.validate(state)
    diag_verdict = state["gate_results"][DiagnosisGate.GATE_NAME]["verdict"]
    print(f"  InputGate: PASS  |  DiagnosisGate: {diag_verdict}")

    # [3] RecallGate (mock RAG)
    state["retrieved_chunks"] = mock_rag_results(rag_count)
    recall_gate = RecallGate()
    state = await recall_gate.validate(state)
    recall_result = state["gate_results"][RecallGate.GATE_NAME]
    recall_verdict = recall_result["verdict"]
    details = recall_result.get("details", {})

    if recall_verdict == GateVerdict.PASS.value:
        print(f"  RecallGate: PASS  |  chunks={details.get('total_chunks')}")
    elif recall_verdict == GateVerdict.RETRY.value:
        new_q = details.get("new_query", "?")
        print(f"  RecallGate: RETRY | new_query='{new_q[:60]}'")
    elif recall_verdict == GateVerdict.FALLBACK.value:
        print(f"  RecallGate: FALLBACK | {recall_result['violations'][0][:60]}")

    print(f"  >>> 终态: {recall_verdict}")
    return recall_verdict


# ============================================================
# 主入口
# ============================================================


async def main():
    print("=" * 60)
    print("  Day 4: 三闸门全链路管道测试")
    print("=" * 60)

    results: dict[str, str] = {}

    # 场景 A：正常召回 3 篇 → 全 PASS
    state_a = make_base_state()
    results["A"] = await run_scenario("A: normal (3 docs)", state_a, rag_count=3)

    # 场景 B：0 篇召回 → RecallGate RETRY
    state_b = make_base_state()
    results["B"] = await run_scenario("B: 0 docs -> RETRY", state_b, rag_count=0)

    # 场景 C：0 篇召回 + retry_count=3 → RecallGate FALLBACK
    state_c = make_base_state()
    state_c["recall_retry_count"] = 3
    results["C"] = await run_scenario("C: 0 docs after 3 retries -> FALLBACK", state_c, rag_count=0)

    # 汇总
    print(f"\n{'=' * 60}")
    print("  Summary")
    print(f"{'=' * 60}")
    for k, v in results.items():
        status = "OK" if v == GateVerdict.PASS.value else v
        print(f"  Scenario {k}: {status}")
    print(f"{'=' * 60}")

    # 验证预期
    assert results["A"] == GateVerdict.PASS.value, f"A 预期 PASS, 实际 {results['A']}"
    assert results["B"] == GateVerdict.RETRY.value, f"B 预期 RETRY, 实际 {results['B']}"
    assert results["C"] == GateVerdict.FALLBACK.value, f"C 预期 FALLBACK, 实际 {results['C']}"
    print("  All scenarios match expected verdicts.")

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

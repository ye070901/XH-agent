"""v0 vs 旧版管道全链路对比脚本。

对同一输入分别跑 v0 管道和旧版管道，对比：
  1. 终态 (status)
  2. 耗时 (elapsed_ms)
  3. 闸门判定路径 (gate trace)
  4. 最终输出结构

旧管道仅做 mock 对比（部分 Agent 需真实 LLM）。

Run:
    python scripts/compare_pipelines.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.src.quality_gate.gates.input_gate import InputGate
from backend.src.scheduler.pipeline_v0 import (
    PipelineSchedulerV0,
    _build_default_steps,
    make_initial_state,
)

# ============================================================
# v0 管道运行
# ============================================================


async def _mock_rag_with_results(state: dict) -> dict:
    """v0 对比专用：始终返回 3 条模拟文档。"""
    state["retrieved_chunks"] = [
        {
            "doc_id": "cmp_001",
            "doc_title": "FANUC 故障排查",
            "chunk_index": 0,
            "content": "SRVO-068 处理步骤...",
            "relevance_score": 0.90,
        },
        {
            "doc_id": "cmp_002",
            "doc_title": "示教器编程指南",
            "chunk_index": 0,
            "content": "KUKA 示教器操作...",
            "relevance_score": 0.82,
        },
        {
            "doc_id": "cmp_003",
            "doc_title": "安全操作规范",
            "chunk_index": 0,
            "content": "急停与安全门配置...",
            "relevance_score": 0.75,
        },
    ]
    return {"verdict": "PASS"}


async def run_v0_pipeline(learning_goal: str) -> dict:
    """运行 v0 管道，返回结果摘要。"""
    state = make_initial_state(learning_goal=learning_goal, major="自动化")
    scheduler = PipelineSchedulerV0()
    steps = _build_default_steps()
    # 替换 RAG 为 mock（保证对比可控）
    steps[4] = ("RAG_search(mock)", _mock_rag_with_results, -1)

    t0 = time.monotonic()
    result = await scheduler.run(state, steps=steps)
    elapsed = int((time.monotonic() - t0) * 1000)

    # 提取闸门链路
    gate_trace = []
    for gate_name, gate_result in result.get("gate_results", {}).items():
        gate_trace.append(
            {
                "gate": gate_name,
                "verdict": gate_result.get("verdict", "?"),
                "score": gate_result.get("score", 0),
            }
        )

    return {
        "pipeline": "v0",
        "pipeline_state": result.get("pipeline_state", "?"),
        "elapsed_ms": elapsed,
        "gate_trace": gate_trace,
        "final_output": result.get("final_output", {}),
        "is_fallback": result.get("_is_fallback", False),
    }


# ============================================================
# 旧版管道 mock（本地占位）
# ============================================================
# Day8：pipeline_v0 已移除 mock_agent 并注册真实 Agent。
# 旧版管道仅做 mock 对比，此处内联等效占位数据（不再依赖 pipeline_v0 的 mock）。


async def _legacy_agent1_diagnosis(state: dict) -> dict:
    """旧版 Agent1 mock：返回模拟诊断结果。"""
    state["diagnosis_result"] = {
        "knowledge_map": {
            "FANUC - 基础操作": {"level": 0.8, "confidence": 0.9},
            "FANUC - 示教器编程": {"level": 0.6, "confidence": 0.7},
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
        "recommended_difficulty": "beginner",
        "overall_confidence": 0.85,
        "summary": "mock 学情诊断。",
    }
    return state


async def _legacy_agent2_generate(state: dict) -> dict:
    """旧版 Agent2 mock：模拟 KB 约束生成。"""
    chunks = state.get("retrieved_chunks", [])
    state["generated_resources"] = [
        {
            "resource_id": "mock_gen_001",
            "title": f"基于 {len(chunks)} 篇知识库文档生成的学习方案",
            "content": "[mock] 个性化学习资源内容...",
            "citations": [],
        }
    ]
    return state


async def _legacy_agent3_review(state: dict) -> dict:
    """旧版 Agent3 mock：模拟内容审核。"""
    state["audit_result"] = {
        "verdict": "approved",
        "confidence_score": 0.85,
    }
    return state


async def _legacy_output(state: dict) -> dict:
    """旧版 Output mock：格式化最终输出。"""
    diag = state.get("diagnosis_result", {})
    resources = state.get("generated_resources", [])
    audit = state.get("audit_result", {})
    state["final_output"] = {
        "status": "ok",
        "pipeline_state": "done",
        "diagnosis": {
            "difficulty": diag.get("recommended_difficulty", "?"),
            "confidence": diag.get("overall_confidence", 0),
            "gaps": len(diag.get("skill_gaps", [])),
        },
        "resources_count": len(resources),
        "audit_verdict": audit.get("verdict", "unknown"),
    }
    return state


# ============================================================
# 旧版管道模拟
# ============================================================


async def run_legacy_pipeline(learning_goal: str) -> dict:
    """模拟旧版管道路径（严格串行，闸门失败即终止）。

    旧版阶段：
      InputGate → Agent1(mock) → DiagnosisGate(旧) → RAG → RecallGate(旧)
      → Agent2(mock) → Agent3(mock) → Output
    """
    t0 = time.monotonic()

    state = {
        "learner_data": {"learning_goal": learning_goal, "major": "自动化"},
        "agent_log": [],
        "gate_results": {},
    }

    gate_trace = []

    # [1] InputGate
    input_gate = InputGate()
    state = await input_gate.validate(state)
    ir = state["gate_results"][InputGate.GATE_NAME]
    gate_trace.append(
        {
            "gate": InputGate.GATE_NAME,
            "verdict": "PASS" if ir["passed"] else "FAIL",
            "score": ir["score"],
        }
    )
    if not ir["passed"]:
        elapsed = int((time.monotonic() - t0) * 1000)
        return {
            "pipeline": "legacy",
            "pipeline_state": "gate_blocked",
            "elapsed_ms": elapsed,
            "gate_trace": gate_trace,
            "final_output": {},
            "blocked_at": "InputGate",
        }

    # [2] Agent1 mock（本地占位）
    await _legacy_agent1_diagnosis(state)

    # [3] DiagnosisGate (旧版)
    from backend.src.quality_gate.gates import DiagnosisGate

    diag_gate = DiagnosisGate()
    state = await diag_gate.validate(state)
    dr = state["gate_results"][DiagnosisGate.GATE_NAME]
    gate_trace.append(
        {
            "gate": DiagnosisGate.GATE_NAME,
            "verdict": "PASS" if dr["passed"] else "FAIL",
            "score": dr["score"],
        }
    )
    if not dr["passed"]:
        elapsed = int((time.monotonic() - t0) * 1000)
        return {
            "pipeline": "legacy",
            "pipeline_state": "gate_blocked",
            "elapsed_ms": elapsed,
            "gate_trace": gate_trace,
            "final_output": {},
            "blocked_at": "DiagnosisGate",
        }

    # [4] RAG mock (same data as v0)
    state["retrieved_chunks"] = [
        {"doc_id": "cmp_001", "doc_title": "FANUC", "content": "...", "relevance_score": 0.90},
        {"doc_id": "cmp_002", "doc_title": "示教器", "content": "...", "relevance_score": 0.82},
        {"doc_id": "cmp_003", "doc_title": "安全", "content": "...", "relevance_score": 0.75},
    ]

    # [5] RecallGate (旧版)
    from backend.src.quality_gate.gates import RecallGate

    recall_gate = RecallGate()
    state = await recall_gate.validate(state)
    rr = state["gate_results"][RecallGate.GATE_NAME]
    gate_trace.append(
        {
            "gate": RecallGate.GATE_NAME,
            "verdict": "PASS" if rr["passed"] else "FAIL",
            "score": rr["score"],
        }
    )
    if not rr["passed"]:
        elapsed = int((time.monotonic() - t0) * 1000)
        return {
            "pipeline": "legacy",
            "pipeline_state": "gate_blocked",
            "elapsed_ms": elapsed,
            "gate_trace": gate_trace,
            "final_output": {},
            "blocked_at": "RecallGate",
        }

    # [6-8] Agent2 + Agent3 + Output (mock，本地占位)
    await _legacy_agent2_generate(state)
    await _legacy_agent3_review(state)
    await _legacy_output(state)

    elapsed = int((time.monotonic() - t0) * 1000)
    return {
        "pipeline": "legacy",
        "pipeline_state": "completed",
        "elapsed_ms": elapsed,
        "gate_trace": gate_trace,
        "final_output": state.get("final_output", {}),
    }


# ============================================================
# 对比
# ============================================================


def compare(v0: dict, legacy: dict) -> dict:
    """逐项对比两条管道的结果。"""
    diffs = []

    # 终态对比
    if v0["pipeline_state"] != legacy["pipeline_state"]:
        diffs.append(f"终态不同: v0={v0['pipeline_state']} vs legacy={legacy['pipeline_state']}")

    # 耗时对比
    speedup = legacy["elapsed_ms"] / max(1, v0["elapsed_ms"])
    diffs.append(
        f"耗时: v0={v0['elapsed_ms']}ms, legacy={legacy['elapsed_ms']}ms "
        f"(v0 {'快' if speedup > 1 else '慢'} {abs(speedup):.1f}x)"
    )

    # 闸门路径对比
    v0_gates = [(g["gate"], g["verdict"]) for g in v0["gate_trace"]]
    legacy_gates = [(g["gate"], g["verdict"]) for g in legacy["gate_trace"]]
    if v0_gates != legacy_gates:
        diffs.append(f"闸门路径不同:\n  v0:     {v0_gates}\n  legacy: {legacy_gates}")
    else:
        diffs.append("闸门路径一致")

    # 输出结构对比
    v0_fo = v0["final_output"]
    legacy_fo = legacy["final_output"]
    v0_keys = set(v0_fo.keys()) if v0_fo else set()
    legacy_keys = set(legacy_fo.keys()) if legacy_fo else set()
    if v0_keys != legacy_keys:
        diffs.append(
            f"输出字段不同: v0有={v0_keys - legacy_keys}, legacy有={legacy_keys - v0_keys}"
        )

    return {
        "match": len([d for d in diffs if "不同" in d]) == 0,
        "details": diffs,
    }


# ============================================================
# 主入口
# ============================================================


async def main():
    print("=" * 70)
    print("  v0 vs Legacy Pipeline Comparison")
    print("=" * 70)

    test_cases = [
        "FANUC 机器人 SRVO-068 故障处理",
        "KUKA 示教器工具坐标系标定步骤",
    ]

    for i, goal in enumerate(test_cases, 1):
        print(f"\n{'─' * 70}")
        print(f"  Case {i}: {goal}")
        print(f"{'─' * 70}")

        v0_result = await run_v0_pipeline(goal)
        legacy_result = await run_legacy_pipeline(goal)

        cmp = compare(v0_result, legacy_result)

        print(
            f"\n  v0:     state={v0_result['pipeline_state']}, "
            f"{v0_result['elapsed_ms']}ms, "
            f"fallback={v0_result.get('is_fallback')}"
        )
        print(f"  legacy: state={legacy_result['pipeline_state']}, {legacy_result['elapsed_ms']}ms")

        print("\n  Comparison:")
        for detail in cmp["details"]:
            print(f"    {detail}")

        if cmp["match"]:
            print("  >>> 结果一致")
        else:
            print("  >>> 存在差异，需人工判断")

    print(f"\n{'=' * 70}")
    print("  Comparison complete")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())

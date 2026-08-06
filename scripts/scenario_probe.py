"""全链路三场景探测 — PASS / RETRY / FALLBACK 各注入一次。
仅定位问题模块，不修复。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.src.quality_gate.gates.diagnosis_gate import DiagnosisGate
from backend.src.quality_gate.gates.recall_gate import RecallGate
from backend.src.quality_gate.gates.input_gate import InputGate
from backend.src.scheduler.pipeline_v0 import (
    PipelineSchedulerV0,
    _build_default_steps,
    make_initial_state,
)
from backend.src.schemas import GateVerdict


# ============================================================
# Mock helpers
# ============================================================

async def _mock_rag_pass(state: dict) -> dict:
    state["retrieved_chunks"] = [
        {"doc_id": "d1", "doc_title": "FANUC 故障", "chunk_index": 0,
         "content": "...", "relevance_score": 0.9},
    ]
    return {"verdict": "PASS"}


async def _mock_rag_empty(state: dict) -> dict:
    state["retrieved_chunks"] = []
    return {"verdict": "PASS"}


# ============================================================
# 场景探测器
# ============================================================


async def probe_pass_scenario():
    """PASS 场景：正常输入 → 全链路通过。"""
    print("=" * 60)
    print("  SCENE A: PASS")
    print("=" * 60)

    state = make_initial_state(learning_goal="FANUC SRVO-068 故障处理", major="自动化")
    scheduler = PipelineSchedulerV0()
    steps = _build_default_steps()
    steps[4] = ("RAG_search(mock_pass)", _mock_rag_pass, -1)

    result = await scheduler.run(state, steps=steps)
    fo = result.get("final_output", {})
    trace = [(name, result.get("gate_results", {}).get(name, {}).get("verdict", "?"))
             for name, _, _ in steps if "Gate" in name]

    print(f"  final_output.status = {fo.get('status')}")
    print(f"  pipeline_state      = {result.get('pipeline_state')}")
    print(f"  gate_trace          = {trace}")
    print(f"  elapsed_ms          = {result.get('elapsed_ms')}")
    print(f"  _is_fallback        = {result.get('_is_fallback')}")

    anomalies = []
    if fo.get("status") != "ok":
        anomalies.append(f"[diagnosis_gate] status 非预期: {fo.get('status')}")
    if result.get("pipeline_state") != "done":
        anomalies.append(f"[scheduler/pipeline_v0] pipeline_state 非 done: {result.get('pipeline_state')}")

    return anomalies


async def probe_retry_scenario():
    """RETRY 场景：低置信度 → DiagnosisGate RETRY → 回跳 Agent1。"""
    print("\n" + "=" * 60)
    print("  SCENE B: RETRY (low diagnosis confidence)")
    print("=" * 60)

    state = make_initial_state(learning_goal="test", major="test")
    scheduler = PipelineSchedulerV0()

    # 自定义 Agent1 mock：输出低置信度诊断
    async def mock_agent1_low_conf(state: dict) -> dict:
        state["diagnosis_result"] = {
            "knowledge_map": {"K": {"level": 0.1, "confidence": 0.2}},
            "skill_gaps": [{"topic": "基础", "current_level": 0, "target_level": 0.5, "priority": "critical", "reason": "缺基础"}],
            "learning_style": "practice_first",
            "recommended_difficulty": "beginner",
            "overall_confidence": 0.25,
            "summary": "低置信度 mock",
        }
        return {"verdict": "PASS"}

    steps = _build_default_steps()
    steps[1] = ("Agent1(low_conf)", mock_agent1_low_conf, -1)
    steps[4] = ("RAG_search(mock_pass)", _mock_rag_pass, -1)

    result = await scheduler.run(state, steps=steps)

    # 提取关键日志
    gate_results = result.get("gate_results", {})
    diag_result = gate_results.get("学情诊断质量检测", {})
    verdict = diag_result.get("verdict", "?")
    retry_hint = diag_result.get("retry_hint", "")
    retry_counts = result.get("_retry_counts", {})

    print(f"  DiagnosisGate verdict     = {verdict}")
    print(f"  retry_hint                = {retry_hint[:100]}")
    print(f"  _retry_counts             = {retry_counts}")
    print(f"  pipeline_state            = {result.get('pipeline_state')}")
    print(f"  recall_retry_count        = {result.get('recall_retry_count')}")
    print(f"  final_output.status       = {result.get('final_output', {}).get('status')}")

    anomalies = []
    if verdict != GateVerdict.RETRY.value:
        anomalies.append(f"[diagnosis_gate] 低置信度(0.25<0.6) 预期 RETRY，实际 {verdict}")
    if "overall_confidence" not in retry_hint.lower() and "置信度" not in retry_hint:
        anomalies.append(f"[diagnosis_gate] retry_hint 未提及置信度相关信息: '{retry_hint[:80]}'")
    if not retry_counts:
        anomalies.append("[scheduler/pipeline_v0] _retry_counts 为空，重试计数未记录")

    return anomalies


async def probe_fallback_scenario():
    """FALLBACK 场景：知识库空 → RecallGate 3次 RETRY → FALLBACK。"""
    print("\n" + "=" * 60)
    print("  SCENE C: FALLBACK (RAG empty, 3 retries)")
    print("=" * 60)

    state = make_initial_state(learning_goal="FANUC SRVO-068 故障处理", major="自动化")
    scheduler = PipelineSchedulerV0()
    steps = _build_default_steps()
    steps[4] = ("RAG_search(mock_empty)", _mock_rag_empty, -1)

    result = await scheduler.run(state, steps=steps)

    gate_results = result.get("gate_results", {})
    recall_result = gate_results.get("RAG召回质量检测", {})
    fo = result.get("final_output", {})

    print(f"  RecallGate verdict        = {recall_result.get('verdict')}")
    print(f"  recall_retry_count final  = {result.get('recall_retry_count')}")
    print(f"  _is_fallback              = {result.get('_is_fallback')}")
    print(f"  pipeline_state            = {result.get('pipeline_state')}")
    print(f"  final_output.status       = {fo.get('status')}")
    print(f"  final_output.message      = {fo.get('message', 'N/A')}")

    anomalies = []
    if result.get("_is_fallback") is not True:
        anomalies.append("[scheduler/pipeline_v0] _is_fallback 应为 True，实际 False")
    if fo.get("status") != "fallback":
        anomalies.append(f"[scheduler/pipeline_v0] final_output.status 预期 'fallback'，实际 '{fo.get('status')}'")
    if result.get("recall_retry_count", 0) > 3:
        anomalies.append(f"[recall_gate] retry_count={result.get('recall_retry_count')} 超过上限3但未终止")

    return anomalies


# ============================================================
# Main
# ============================================================


async def main():
    print("Full-Chain Scenario Probe — locate only, no fix\n")

    all_anomalies = {}

    a = await probe_pass_scenario()
    all_anomalies["PASS"] = a

    b = await probe_retry_scenario()
    all_anomalies["RETRY"] = b

    c = await probe_fallback_scenario()
    all_anomalies["FALLBACK"] = c

    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    total = 0
    for scene, issues in all_anomalies.items():
        if issues:
            print(f"  [{scene}] {len(issues)} 异常:")
            for issue in issues:
                print(f"    - {issue}")
                total += 1
        else:
            print(f"  [{scene}] 无异常")
    print(f"\n  总异常数: {total}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

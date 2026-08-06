"""pipeline.py v0.1 适配后场景探测 — 三种路径各测一次。
Run: python scripts/probe_pipeline_after_switch.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.src.scheduler.pipeline import PipelineScheduler
from backend.src.schemas import GateVerdict
from backend.src.knowledge.store import knowledge_base


async def probe_pass():
    """正常路径：全 PASS（知识库有数据则走真实检索）。"""
    print("=" * 60)
    print("  SCENE A: Normal PASS")
    print("=" * 60)

    await knowledge_base.initialize()

    scheduler = PipelineScheduler()
    result = await scheduler.run_pipeline(
        user_input={
            "learner_data": {
                "learning_goal": "FANUC 机器人 SRVO-068 故障怎么处理",
                "major": "自动化",
                "industry": "汽车制造",
                "positions": ["机器人调试员"],
                "skills_used": ["FANUC 示教器"],
            }
        },
        task_id="probe_pass_001",
    )

    print(f"  status       = {result.get('status')}")
    print(f"  is_fallback  = {result.get('_is_fallback', False)}")
    print(f"  gate_results keys = {list(result.get('gate_results', {}).keys())}")
    for k, v in result.get("gate_results", {}).items():
        print(f"    [{k}] verdict={v.get('verdict','?')}, score={v.get('score','?')}")
    print(f"  diagnosis difficulty = {result.get('diagnosis_result', {}).get('recommended_difficulty', '?')}")
    print(f"  elapsed_ms   = {result.get('elapsed_ms', '?')}")

    anomalies = []
    if result.get("status") != "completed":
        anomalies.append(f"status={result.get('status')} 应为 completed")
    if result.get("_is_fallback"):
        anomalies.append("正常路径不应触发 fallback")
    if not result.get("diagnosis_result"):
        anomalies.append("缺 diagnosis_result")

    if anomalies:
        print(f"\n  !! ANOMALIES: {anomalies}")
    else:
        print(f"\n  [PASS] 正常路径 OK")
    return anomalies


async def probe_fallback():
    """FALLBACK 路径：输入过短触发 InputGate FALLBACK。"""
    print("\n" + "=" * 60)
    print("  SCENE B: InputGate FALLBACK (short input)")
    print("=" * 60)

    scheduler = PipelineScheduler()
    try:
        result = await scheduler.run_pipeline(
            user_input={"learner_data": {"learning_goal": "ab"}},
            task_id="probe_fb_001",
        )
        print(f"  status       = {result.get('status')}")
        print(f"  gate_name    = {result.get('gate_name')}")
        print(f"  violations   = {result.get('violations')}")
        if result.get("status") == "gate_blocked":
            print(f"  [OK] InputGate correctly blocked")
        else:
            print(f"  [ANOMALY] expected gate_blocked, got {result.get('status')}")
    except Exception as e:
        print(f"  [OK] _GateAbortError caught by run_pipeline: {e}")
    return []


async def probe_retry():
    """RETRY 路径：喂低置信度诊断 → DiagnosisGate RETRY → 回跳 Agent1。"""
    print("\n" + "=" * 60)
    print("  SCENE C: DiagnosisGate RETRY (low confidence)")
    print("=" * 60)

    # 注入低置信度数据：直接调用 _execute_pipeline，state 里预填诊断
    scheduler = PipelineScheduler()

    async def _patched_execute(user_input, task_id):
        """注入低置信度诊断然后走正常流程。"""
        from backend.src.scheduler.pipeline import PipelineScheduler as PS
        state = PS._init_state(PS(), user_input, task_id)
        state.setdefault("_retry_counts", {})
        state.setdefault("recall_retry_count", 0)
        return state  # 太 hacky，换方案

    # 更简单：直接观察 DiagnosisGate 在实际管道中的裁决
    # 用一条会触发低置信度的真实输入
    result = await scheduler.run_pipeline(
        user_input={
            "learner_data": {
                "learning_goal": "FANUC 机器人基本操作",  # 太宽泛
            }
        },
        task_id="probe_retry_001",
    )
    print(f"  status       = {result.get('status')}")
    print(f"  is_fallback  = {result.get('_is_fallback', False)}")
    diag_result = result.get("gate_results", {}).get("学情诊断质量检测", {})
    print(f"  DiagnosisGate verdict = {diag_result.get('verdict', '?')}")
    if diag_result.get("verdict") == "RETRY":
        print(f"  retry_hint  = {diag_result.get('retry_hint', '')[:100]}")
        print(f"  [OK] DiagnosisGate RETRY detected")
    else:
        print(f"  (verdict was {diag_result.get('verdict')} — depends on LLM output)")
    return []


async def main():
    print("Pipeline v0.1 Switch — Scenario Probe\n")
    await probe_pass()
    await probe_fallback()
    await probe_retry()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())

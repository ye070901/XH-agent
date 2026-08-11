"""Scheduler v0.1 全链路测试 — Day 5。

两条路径：
  路径 1：正常结束（全 PASS，终态 DONE）
  路径 2：RecallGate FALLBACK（RAG 无召回 → 3次 RETRY → FALLBACK → DONE）

Run:
    cd backend && python -m pytest tests/test_scheduler_pipeline_v0.py -v -s
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 插入项目根目录 (XH-agent)，使 backend.src.* 导入可解析
_project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_project_root))

from backend.src.scheduler.pipeline_v0 import (  # noqa: E402
    PipelineSchedulerV0,
    _build_default_steps,
    make_initial_state,
)
from backend.src.schemas import PipelineState  # noqa: E402

# ═══════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════


async def _mock_rag_search_empty(state: dict) -> dict:
    """覆盖 RAG 检索：始终返回空列表（用于测试 FALLBACK 路径）。"""
    state["retrieved_chunks"] = []
    state["rag_query"] = state.get("rag_query", "test query")
    return {"verdict": "PASS"}


async def _mock_rag_search_with_results(state: dict) -> dict:
    """覆盖 RAG 检索：始终返回 3 条模拟文档（用于测试正常路径）。"""
    query = state.get("rag_query", "test query")
    # 如果 RecallGate 返回了改写 query，用它
    recall_results = state.get("gate_results", {}).get("RAG召回质量检测 v0.1", {})
    new_query = recall_results.get("details", {}).get("new_query", "")
    if new_query:
        query = new_query
        state["_pending_query"] = new_query

    state["retrieved_chunks"] = [
        {
            "doc_id": "mock_001",
            "doc_title": "FANUC SRVO-068 故障处理指南",
            "chunk_index": 0,
            "content": f"SRVO-068 是伺服放大器报警...查询词: {query[:30]}",
            "relevance_score": 0.92,
        },
        {
            "doc_id": "mock_002",
            "doc_title": "FANUC 常见故障排查",
            "chunk_index": 0,
            "content": "机器人故障排查步骤...",
            "relevance_score": 0.85,
        },
        {
            "doc_id": "mock_003",
            "doc_title": "工业机器人安全操作",
            "chunk_index": 1,
            "content": "安全门、急停装置...",
            "relevance_score": 0.78,
        },
    ]
    return {"verdict": "PASS"}


async def _mock_agent1_success(state: dict) -> dict:
    """Mock Agent1：固定返回高置信度诊断结果（避免真实 LLM 不稳定）。"""
    state["diagnosis_result"] = {
        "knowledge_map": {
            "FANUC 基础操作": {"level": 0.8, "confidence": 0.9},
            "示教器编程": {"level": 0.6, "confidence": 0.7},
            "安全规范": {"level": 0.9, "confidence": 0.95},
            "IO 配置": {"level": 0.4, "confidence": 0.6},
            "运动指令": {"level": 0.5, "confidence": 0.65},
        },
        "skill_gaps": [
            {
                "topic": "工具坐标系标定",
                "current_level": 0.2,
                "target_level": 0.8,
                "priority": "critical",
                "reason": "缺少实操经验",
            },
            {
                "topic": "FANUC SRVO-068 故障诊断",
                "current_level": 0.1,
                "target_level": 0.7,
                "priority": "critical",
                "reason": "不了解伺服错误代码含义",
            },
        ],
        "learning_style": "practice_first",
        "recommended_difficulty": "intermediate",
        "overall_confidence": 0.85,
        "summary": "该学习者有基础操作经验，但缺乏坐标系标定与故障排查能力。",
    }
    state["diagnosis_completed"] = True
    state["status"] = "ok"
    return {"verdict": "PASS"}


async def _mock_agent2_generate(state: dict) -> dict:
    """Mock Agent2：固定返回生成资源。"""
    state["generated_resources"] = [
        {
            "resource_id": "mock_res_001",
            "resource_type": "lecture",
            "title": "FANUC 故障排查指南",
            "content": "SRVO-068 报警通常由伺服放大器过热引起...",
            "difficulty_level": "intermediate",
            "citations": [{"doc_id": "mock_001"}],
            "target_skill_gaps": ["FANUC SRVO-068 故障诊断"],
            "estimated_duration_minutes": 25,
            "prerequisites": ["基础电气知识"],
            "key_takeaways": ["了解 SRVO 错误代码体系", "掌握伺服故障排查流程"],
        }
    ]
    state["status"] = "ok"
    return {"verdict": "PASS"}


async def _mock_agent3_correction(state: dict) -> dict:
    """Mock Agent3：固定返回修正结果（空修正 = 无问题）。"""
    state["audit_result"] = []
    state["corrected_resources"] = state.get("generated_resources", [])
    state["correction_stats"] = {"total": 0, "fixed": 0, "failed": 0}
    state["correction_log"] = []
    state["status"] = "ok"
    return {"verdict": "PASS"}


async def _mock_step_raises(state: dict) -> dict:
    """模拟 Agent 步骤抛出异常（如 LLM 调用超时/连接失败）。"""
    raise RuntimeError("LLM 连接超时（模拟 Agent 崩溃）")


async def _mock_input_gate_blocked(state: dict) -> dict:
    """Mock InputGate：始终返回 FALLBACK（空输入/危险内容）。"""
    state.setdefault("gate_results", {})["输入特异性检测"] = {
        "passed": False,
        "score": 0.0,
        "violations": ["输入为空，无法进行学情诊断"],
        "intent": "未识别",
        "intent_confidence": "low",
    }
    return {"verdict": "FALLBACK"}


async def _mock_input_gate_unknown_intent(state: dict) -> dict:
    """Mock InputGate：通过但意图识别为"未识别"（领域外模糊输入）。"""
    state.setdefault("gate_results", {})["输入特异性检测"] = {
        "passed": True,
        "score": 1.0,
        "intent": "未识别",
        "intent_confidence": "low",
    }
    return {"verdict": "PASS"}


# ═══════════════════════════════════════════════════════════
# 测试
# ═══════════════════════════════════════════════════════════


class TestPipelineNormal:
    """路径 1：正常全 PASS。"""

    async def test_normal_completion(self):
        """所有步骤 PASS → 终态 DONE + final_output 含 diagnosis。

        注意：Agent1/Agent2/Agent3 替换为 mock，避免真实 LLM 置信度不稳定。
        """
        state = make_initial_state(
            learning_goal="FANUC 机器人 SRVO-068 故障处理",
            major="自动化",
        )
        scheduler = PipelineSchedulerV0()
        steps = _build_default_steps()
        # 替换 Agent1 → 固定返回高置信度 mock 诊断
        steps[1] = ("Agent1(mock)", _mock_agent1_success, -1)
        # 替换 RAG_search → 返回模拟结果
        steps[4] = ("RAG_search(mock_results)", _mock_rag_search_with_results, -1)
        # 替换 Agent2_generate → mock 生成（避免 LLM 调用耗时）
        steps[6] = ("Agent2_generate(mock)", _mock_agent2_generate, -1)
        # 替换 Agent3_correction → mock 修正
        steps[7] = ("Agent3_correction(mock)", _mock_agent3_correction, -1)

        result = await scheduler.run(state, steps=steps)

        assert result["pipeline_state"] == PipelineState.DONE.value, (
            f"Expected DONE, got {result['pipeline_state']}"
        )
        fo = result.get("final_output", {})
        assert fo.get("status") == "ok", f"Expected ok, got {fo}"
        assert "diagnosis" in fo
        assert fo["diagnosis"]["confidence"] > 0.6
        print(f"\n  [OK] Normal pipeline: {fo}")


class TestPipelineFallback:
    """路径 2：RAG 无召回 → RecallGate FALLBACK。"""

    async def test_recall_fallback_path(self):
        """RAG 始终空 → 3 次 RETRY 后 FALLBACK → DONE。"""
        state = make_initial_state(
            learning_goal="FANUC 机器人 SRVO-068 故障处理",
            major="自动化",
        )
        scheduler = PipelineSchedulerV0()

        # 构建自定义 steps：将 RAG_search 替换为始终返回空的 mock
        steps = _build_default_steps()
        # 替换 index 4: RAG_search
        steps[4] = ("RAG_search(mock_empty)", _mock_rag_search_empty, -1)

        result = await scheduler.run(state, steps=steps)

        assert result["pipeline_state"] == PipelineState.DONE.value, (
            f"Expected DONE, got {result['pipeline_state']}"
        )
        # 应走 FALLBACK 路径
        assert result.get("_is_fallback") is True, "Expected _is_fallback=True"
        fo = result.get("final_output", {})
        assert fo.get("status") == "fallback", f"Expected fallback status, got {fo}"
        print(f"\n  [OK] Fallback pipeline: {fo}")


class TestPipelineAgentException:
    """路径 3：Agent 步骤抛异常 → 隔离不崩溃，走 FALLBACK 降级。"""

    async def test_agent_exception_isolated_fallback(self):
        """Agent step 抛出 RuntimeError → pipeline 不崩溃，降级输出。"""
        state = make_initial_state(
            learning_goal="FANUC 机器人 SRVO-068 故障处理",
            major="自动化",
        )
        scheduler = PipelineSchedulerV0()

        steps = _build_default_steps()
        # 替换 InputGate → 正常通过
        steps[0] = ("InputGate(mock_pass)", _mock_input_gate_unknown_intent, -1)
        # 替换 Agent1 → 抛异常（模拟 LLM 连接超时/崩溃）
        steps[1] = ("Agent1(mock_raises)", _mock_step_raises, -1)

        result = await scheduler.run(state, steps=steps)

        # 不崩溃 = pipeline 到达 DONE 状态
        assert result["pipeline_state"] == PipelineState.DONE.value, (
            f"Expected DONE after agent crash, got {result['pipeline_state']}"
        )
        # 应走 FALLBACK 路径（Agent 异常触发降级）
        assert result.get("_is_fallback") is True, (
            "Agent exception should trigger FALLBACK"
        )
        fo = result.get("final_output", {})
        assert fo.get("status") == "fallback", (
            f"Expected fallback status after agent crash, got {fo}"
        )
        print(f"\n  [OK] Agent exception → FALLBACK: {fo}")


class TestPipelineEmptyInput:
    """路径 4：空输入 → InputGate FALLBACK（即刻终止，不执行 Agent）。"""

    async def test_empty_input_triggers_input_gate_fallback(self):
        """learning_goal 为空字符串 → InputGate FALLBACK 终止。"""
        state = make_initial_state(learning_goal="")
        scheduler = PipelineSchedulerV0()

        steps = _build_default_steps()
        # 替换 InputGate → 模拟空输入拦截
        steps[0] = ("InputGate(mock_blocked)", _mock_input_gate_blocked, -1)

        result = await scheduler.run(state, steps=steps)

        assert result["pipeline_state"] == PipelineState.DONE.value, (
            f"Expected DONE, got {result['pipeline_state']}"
        )
        assert result.get("_is_fallback") is True, (
            "Empty input should trigger FALLBACK"
        )
        # 空输入不应执行 Agent1（无 diagnosis_result）
        assert "diagnosis_result" not in result or not result.get("diagnosis_result"), (
            "Empty input should not produce diagnosis"
        )
        fo = result.get("final_output", {})
        assert fo.get("status") == "fallback", (
            f"Expected fallback status, got {fo}"
        )
        print(f"\n  [OK] Empty input → InputGate FALLBACK: {fo}")


class TestPipelineIntentUnknown:
    """路径 5：意图识别失败（领域外模糊输入）→ 降级兜底但不崩溃。"""

    async def test_intent_unknown_graceful_degradation(self):
        """领域外模糊输入 → 意图"未识别"但 pipeline 正常完成（不崩溃）。"""
        state = make_initial_state(
            learning_goal="asdfghjkl qwertyuiop zxcvbnm",
            major="",
        )
        scheduler = PipelineSchedulerV0()

        steps = _build_default_steps()
        # InputGate 通过但意图识别为"未识别"
        steps[0] = ("InputGate(mock_unknown_intent)", _mock_input_gate_unknown_intent, -1)
        # Agent1 → mock 成功诊断
        steps[1] = ("Agent1(mock)", _mock_agent1_success, -1)
        # RAG_search → mock 返回结果
        steps[4] = ("RAG_search(mock_results)", _mock_rag_search_with_results, -1)
        # Agent2_generate → mock
        steps[6] = ("Agent2_generate(mock)", _mock_agent2_generate, -1)
        # Agent3_correction → mock
        steps[7] = ("Agent3_correction(mock)", _mock_agent3_correction, -1)

        result = await scheduler.run(state, steps=steps)

        assert result["pipeline_state"] == PipelineState.DONE.value, (
            f"Expected DONE even with unknown intent, got {result['pipeline_state']}"
        )
        # intent = "未识别" 时不应崩溃，pipeline 应正常完成
        fo = result.get("final_output", {})
        assert fo.get("status") == "ok", (
            f"Unknown intent should still produce ok output, got {fo}"
        )
        print(f"\n  [OK] Unknown intent → graceful degradation: {fo}")


# ═══════════════════════════════════════════════════════════
# 手动运行入口
# ═══════════════════════════════════════════════════════════


async def _run_standalone():
    """直接 python 运行时的测试入口。"""
    print("=" * 60)
    print("  Day 5: Scheduler v0.1 Pipeline Tests")
    print("=" * 60)

    test_normal = TestPipelineNormal()
    test_fallback = TestPipelineFallback()
    test_exception = TestPipelineAgentException()
    test_empty = TestPipelineEmptyInput()
    test_intent = TestPipelineIntentUnknown()

    all_pass = True
    for label, coro in [
        ("1. Normal Completion", test_normal.test_normal_completion()),
        ("2. RecallGate FALLBACK", test_fallback.test_recall_fallback_path()),
        ("3. Agent Exception → FALLBACK", test_exception.test_agent_exception_isolated_fallback()),
        ("4. Empty Input → InputGate FALLBACK",
         test_empty.test_empty_input_triggers_input_gate_fallback()),
        ("5. Unknown Intent → Graceful",
         test_intent.test_intent_unknown_graceful_degradation()),
    ]:
        try:
            print(f"\n--- Test {label} ---")
            await coro
            print(f"  [PASS] {label}")
        except Exception as e:
            print(f"  [FAIL] {label}: {e}")
            all_pass = False

    print("\n" + "=" * 60)
    status = "ALL PASS" if all_pass else "SOME FAILED"
    print(f"  Day 5 Pipeline Tests Complete — {status}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(_run_standalone())

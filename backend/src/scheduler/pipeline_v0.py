"""流水线调度器 v0.1 — 状态机驱动的顺序调度器。

与 pipeline.py（Phase2 严格串行 + 闸门失败即终止）不同，
v0.1 支持：
  - PipelineState 状态机：IDLE → RUNNING → WAITING_RETRY / FALLBACK → DONE
  - step 列表可配置，按顺序执行
  - RETRY：回跳到指定步骤重新执行，最多 N 次
  - FALLBACK：跳过剩余步骤走降级输出
  - 未就绪的 Agent 用 mock_agent 占位

架构约束：
  - 全部阈值从 config.settings 读取
  - 全局 state dict 贯穿全流程
  - 每个 step 执行后打印状态切换日志
"""

from __future__ import annotations

import time
from typing import Any, Callable

from loguru import logger

from backend.src.config import settings
from backend.src.quality_gate.gates.diagnosis_gate import DiagnosisGate
from backend.src.quality_gate.gates.input_gate import InputGate
from backend.src.quality_gate.gates.recall_gate import RecallGate
from backend.src.schemas import GateVerdict, PipelineState


# ═══════════════════════════════════════════════════════════
# Step 返回值结构
# ═══════════════════════════════════════════════════════════


def _step_result(
    verdict: str,
    retry_target: int = -1,
    **extra,
) -> dict[str, Any]:
    """每一步执行后的标准化返回值。"""
    return {
        "verdict": verdict,
        "retry_target": retry_target,
        **extra,
    }


# ═══════════════════════════════════════════════════════════
# mock Agent 占位函数
# ═══════════════════════════════════════════════════════════


async def mock_agent1_diagnosis(state: dict) -> dict:
    """mock Agent1：返回模拟诊断结果。"""
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
    return _step_result(GateVerdict.PASS.value)


async def mock_agent2_query(state: dict) -> dict:
    """mock Agent2 Step1：从诊断结果构建 RAG 检索 Query。"""
    diag = state.get("diagnosis_result", {})
    learner = state.get("learner_data", {})

    # 优先用 recall 改写后的 query，其次诊断 summary，最后 learner goal
    query = state.get("_pending_query") or diag.get("summary", "") or learner.get("learning_goal", "")
    state["rag_query"] = str(query) if query else "工业机器人 调试"
    state.pop("_pending_query", None)

    logger.info(f"  [mock Agent2_query] RAG Query = '{state['rag_query'][:60]}'")
    return _step_result(GateVerdict.PASS.value)


async def mock_rag_search(state: dict) -> dict:
    """mock RAG 检索：调用真实 knowledge_base.search()。

    如果 state 中有 new_query（RecallGate 改写后），优先使用。
    """
    query = state.get("_pending_query") or state.get("rag_query", "")

    # 如果 RecallGate 返回了改写 query，用它
    recall_results = state.get("gate_results", {}).get("RAG召回质量检测 v0.1", {})
    new_query = recall_results.get("details", {}).get("new_query", "")
    if new_query:
        query = new_query
        state["_pending_query"] = new_query

    try:
        from backend.src.knowledge.store import knowledge_base

        chunks = await knowledge_base.search(str(query), top_k=8)
        state["retrieved_chunks"] = chunks
        logger.info(f"  [mock RAG_search] '{str(query)[:50]}' -> {len(chunks)} chunks")
    except Exception as exc:
        logger.warning(f"  [mock RAG_search] 检索失败: {exc}，返回空列表")
        state["retrieved_chunks"] = []

    return _step_result(GateVerdict.PASS.value)


async def mock_agent2_generate(state: dict) -> dict:
    """mock Agent2 Step2：模拟 KB 约束生成。"""
    chunks = state.get("retrieved_chunks", [])
    state["generated_resources"] = [
        {
            "resource_id": "mock_gen_001",
            "title": f"基于 {len(chunks)} 篇知识库文档生成的学习方案",
            "content": "[mock] 个性化学习资源内容...",
            "citations": [],
        }
    ]
    logger.info(f"  [mock Agent2_generate] 资源数=1")
    return _step_result(GateVerdict.PASS.value)


async def mock_agent3_review(state: dict) -> dict:
    """mock Agent3：模拟内容审核。"""
    state["audit_result"] = {
        "verdict": "approved",
        "confidence_score": 0.85,
    }
    logger.info(f"  [mock Agent3_review] verdict=approved")
    return _step_result(GateVerdict.PASS.value)


async def mock_output(state: dict) -> dict:
    """mock Output：格式化最终输出。降级模式返回 fallback status。"""
    diag = state.get("diagnosis_result", {})
    resources = state.get("generated_resources", [])
    audit = state.get("audit_result", {})
    is_fallback = state.get("_is_fallback", False)

    state["final_output"] = {
        "status": "fallback" if is_fallback else "ok",
        "pipeline_state": PipelineState.DONE.value,
        "diagnosis": {
            "difficulty": diag.get("recommended_difficulty", "?"),
            "confidence": diag.get("overall_confidence", 0),
            "gaps": len(diag.get("skill_gaps", [])),
        },
        "resources_count": len(resources),
        "audit_verdict": audit.get("verdict", "unknown"),
    }
    if is_fallback:
        state["final_output"]["message"] = "知识库暂无相关数据，请尝试更换问题描述"
    logger.info(f"  [Output] 最终输出: {state['final_output']}")
    return _step_result(GateVerdict.PASS.value)


# ═══════════════════════════════════════════════════════════
# Step 定义表
# ═══════════════════════════════════════════════════════════

# 每个 step: (name, handler, retry_on_retry)
#   name:            步骤显示名
#   handler:         async (state) -> step_result dict
#   retry_on_retry:  当本步骤返回 RETRY 时，应回跳到哪个 step 下标


def _build_default_steps() -> list[tuple[str, Callable, int]]:
    """构建默认 step 列表。"""
    return [
        ("InputGate",         _run_input_gate,         -1),  # 0
        ("Agent1",            mock_agent1_diagnosis,    -1),  # 1
        ("DiagnosisGate",   _run_diagnosis_gate,      1),  # 2 → RETRY 回跳 Agent1
        ("Agent2_query",      mock_agent2_query,        -1),  # 3
        ("RAG_search",        mock_rag_search,          -1),  # 4
        ("RecallGate",      _run_recall_gate,          4),  # 5 → RETRY 回跳 RAG_search
        ("Agent2_generate",   mock_agent2_generate,     -1),  # 6
        ("Agent3_review",     mock_agent3_review,       -1),  # 7
        ("Output",            mock_output,              -1),  # 8
    ]


# ═══════════════════════════════════════════════════════════
# Gate 调用包装
# ═══════════════════════════════════════════════════════════

async def _run_input_gate(state: dict) -> dict:
    gate = InputGate()
    state = await gate.validate(state)
    result = state["gate_results"][InputGate.GATE_NAME]
    if not result.get("passed"):
        return _step_result(GateVerdict.FALLBACK.value)
    return _step_result(GateVerdict.PASS.value)


async def _run_diagnosis_gate(state: dict) -> dict:
    gate = DiagnosisGate()
    state = await gate.validate(state)
    result = state["gate_results"][DiagnosisGate.GATE_NAME]
    verdict = result.get("verdict", GateVerdict.FALLBACK.value)

    # RETRY 时，把 retry_hint 写入 state 供 Agent1 重试时参考
    if verdict == GateVerdict.RETRY.value:
        hint = result.get("retry_hint", "")
        state["_diagnosis_retry_hint"] = hint
        logger.info(f"  [DiagnosisGate] RETRY hint: {hint[:100]}")

    return _step_result(verdict)


async def _run_recall_gate(state: dict) -> dict:
    gate = RecallGate()
    state = await gate.validate(state)
    result = state["gate_results"][RecallGate.GATE_NAME]
    verdict = result.get("verdict", GateVerdict.FALLBACK.value)
    return _step_result(verdict)


# ═══════════════════════════════════════════════════════════
# PipelineSchedulerV0
# ═══════════════════════════════════════════════════════════


class PipelineSchedulerV0:
    """v0.1 流水线调度器：状态机 + step 列表 + RETRY/FALLBACK。

    用法：
        scheduler = PipelineSchedulerV0()
        result = await scheduler.run(state, steps=...)
    """

    def __init__(self) -> None:
        self._state_machine: PipelineState = PipelineState.IDLE

    # ═══════════════════════════════════════════════════════════
    # 主入口
    # ═══════════════════════════════════════════════════════════

    async def run(
        self,
        state: dict[str, Any],
        steps: list[tuple[str, Callable, int]] | None = None,
    ) -> dict[str, Any]:
        """执行流水线。

        Args:
            state: 初始状态 dict（需含 learner_data）。
            steps: step 列表，为空则使用默认列表。

        Returns:
            含 pipeline_state / final_output 的最终 state。
        """
        if steps is None:
            steps = _build_default_steps()

        state.setdefault("agent_log", [])
        state.setdefault("gate_results", {})
        state.setdefault("recall_retry_count", 0)
        state.setdefault("_retry_counts", {})

        t_start = time.monotonic()
        self._set_state(PipelineState.RUNNING)
        logger.info("=" * 60)
        logger.info("  PipelineSchedulerV0 start")
        logger.info(f"  Steps: {' -> '.join(s[0] for s in steps)}")
        logger.info("=" * 60)

        idx = 0
        max_steps = len(steps) * 10  # 防死循环

        while idx < len(steps):
            if idx >= max_steps:
                logger.error("Pipeline exceeded max steps, aborting")
                break

            name, handler, retry_target = steps[idx]
            step_num = idx + 1

            # 执行 step
            logger.info(f"[{step_num}/{len(steps)}] {name} ...")
            step_result = await handler(state)

            verdict = step_result.get("verdict", GateVerdict.PASS.value)
            logger.info(f"  [{step_num}/{len(steps)}] {name} -> {verdict}")

            # ── PASS → 继续 ──
            if verdict == GateVerdict.PASS.value:
                idx += 1
                continue

            # ── RETRY → 回跳 ──
            if verdict == GateVerdict.RETRY.value:
                # 追踪重试次数
                retry_key = f"step_{idx}"
                state["_retry_counts"][retry_key] = state["_retry_counts"].get(retry_key, 0) + 1
                retry_count = state["_retry_counts"][retry_key]

                # 特殊处理 RecallGate：递增 recall_retry_count
                if "RecallGate" in name:
                    state["recall_retry_count"] = state.get("recall_retry_count", 0) + 1

                if retry_target >= 0 and retry_count <= settings.RECALL_MAX_RETRIES:
                    self._set_state(PipelineState.WAITING_RETRY)
                    logger.info(
                        f"  [RETRY #{retry_count}] {name} -> back to step[{retry_target}] "
                        f"'{steps[retry_target][0]}'"
                    )
                    idx = retry_target
                    self._set_state(PipelineState.RUNNING)
                    continue
                else:
                    # retry 超限 → 转 FALLBACK
                    logger.warning(
                        f"  [RETRY] {name} 已达最大重试次数，转 FALLBACK"
                    )
                    verdict = GateVerdict.FALLBACK.value

            # ── FALLBACK → 走降级输出 ──
            if verdict == GateVerdict.FALLBACK.value:
                self._set_state(PipelineState.FALLBACK)
                logger.warning(f"  [FALLBACK] {name} 触发降级路径")
                # 跳到最后一步 Output
                last_step = steps[-1]
                logger.info(f"  [FALLBACK] -> {last_step[0]}")
                state = await self._run_fallback_output(state, last_step[0], last_step[1])
                break

            # 未知 verdict → 继续（保守）
            idx += 1

        # ── 终态 ──
        self._set_state(PipelineState.DONE)
        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        state["pipeline_state"] = PipelineState.DONE.value
        state["elapsed_ms"] = elapsed_ms

        logger.info("=" * 60)
        logger.info(f"  PipelineSchedulerV0 DONE ({elapsed_ms}ms)")
        logger.info("=" * 60)
        return state

    # ═══════════════════════════════════════════════════════════
    # 私有
    # ═══════════════════════════════════════════════════════════

    def _set_state(self, new_state: PipelineState) -> None:
        old = self._state_machine
        self._state_machine = new_state
        logger.info(f"  [State] {old.value} -> {new_state.value}")

    async def _run_fallback_output(
        self,
        state: dict,
        name: str,
        handler: Callable,
    ) -> dict:
        """执行 FALLBACK 输出。"""
        # 注入降级标记
        state["_is_fallback"] = True
        try:
            await handler(state)
        except Exception as exc:
            logger.error(f"  [FALLBACK] Output handler 失败: {exc}")
            state["final_output"] = {
                "status": "fallback",
                "message": "知识库暂无相关数据，请尝试更换问题描述",
                "pipeline_state": PipelineState.FALLBACK.value,
            }
        return state


# ═══════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════


def make_initial_state(learning_goal: str = "", **learner_data) -> dict[str, Any]:
    """构建流水线初始 state。"""
    data = {"learning_goal": learning_goal}
    data.update(learner_data)
    return {
        "learner_data": data,
        "agent_log": [],
        "gate_results": {},
        "recall_retry_count": 0,
        "_retry_counts": {},
    }

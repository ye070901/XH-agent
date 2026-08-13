"""流水线调度器 v0.1 — 状态机驱动的顺序调度器。

与 pipeline.py（Phase2 严格串行 + 闸门失败即终止）不同，
v0.1 支持：
  - PipelineState 状态机：IDLE → RUNNING → WAITING_RETRY / FALLBACK → DONE
  - step 列表可配置，按顺序执行
  - RETRY：回跳到指定步骤重新执行，最多 N 次
  - FALLBACK：跳过剩余步骤走降级输出
  - Day8 联调：移除 mock_agent，注册 diagnosis / generation / correction
    三个真实 Agent 到 step 执行列表；执行步骤输出 [AgentX] 终端日志；
    EventBus 事件落盘 logs/eventbus.log（gate → agent → gate 事件链）

架构约束：
  - 全部阈值从 config.settings 读取
  - 全局 state dict 贯穿全流程
  - 每个 step 执行后打印状态切换日志
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable

from loguru import logger

from backend.src.agents.correction import CorrectionAgent
from backend.src.agents.diagnosis import DiagnosisAgent
from backend.src.agents.generation_v2 import GenerationAgent as GenerationAgentV2
from backend.src.config import settings
from backend.src.event_broadcast import EventType, event_bus
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
# 真实 Agent 注册与执行包装（Day8 联调）
# ═══════════════════════════════════════════════════════════


async def _run_agent_step(state: dict, agent, label: str) -> dict:
    """执行单个真实 Agent，并输出 [AgentX] 终端日志 + EventBus 广播。

    BaseAgent.run() 不抛异常，失败时 state["status"]="error"，
    据此判定执行失败并广播 agent_error。
    """
    task_id = state.get("task_id", "")
    logger.info(f"[{label}] {agent.name} 开始执行 (task_id={task_id[:8]}...)")
    await event_bus.broadcast(
        task_id,
        EventType.AGENT_START,
        {"agent": agent.name, "label": label},
    )

    state = await agent.run(state)

    if state.get("status") == "error":
        logger.error(f"[{label}] {agent.name} 执行失败")
        await event_bus.broadcast(
            task_id,
            EventType.AGENT_ERROR,
            {
                "agent": agent.name,
                "label": label,
                "error": state.get("error", ""),
                "error_type": state.get("error_type", ""),
            },
        )
        return _step_result(GateVerdict.FALLBACK.value)

    logger.info(f"[{label}] {agent.name} 执行完成")
    await event_bus.broadcast(
        task_id,
        EventType.AGENT_DONE,
        {"agent": agent.name, "label": label},
    )
    return _step_result(GateVerdict.PASS.value)


async def _run_agent1_diagnosis(state: dict) -> dict:
    """Agent1：注册真实 DiagnosisAgent（学情诊断）。"""
    return await _run_agent_step(state, DiagnosisAgent(), "Agent1")


async def _run_agent2_generate(state: dict) -> dict:
    """Agent2_generate：注册真实 GenerationAgent（领域知识生成，融合版 v2）。"""
    return await _run_agent_step(state, GenerationAgentV2(), "Agent2")


async def _run_agent3_correction(state: dict) -> dict:
    """Agent3_correction：注册真实 CorrectionAgent（保真修正）。

    3-Agent 链路无审核 Agent，审计结果置空列表 → 修正直通（仅一致性检查）。
    """
    state.setdefault("audit_result", [])
    return await _run_agent_step(state, CorrectionAgent(), "Agent3")


# ═══════════════════════════════════════════════════════════
# 胶水步骤（非 LLM Agent，去 mock_ 前缀）
# ═══════════════════════════════════════════════════════════


async def _build_rag_query(state: dict) -> dict:
    """mock Agent2 Step1：从诊断结果构建 RAG 检索 Query。"""
    diag = state.get("diagnosis_result", {})
    learner = state.get("learner_data", {})

    # 优先用 recall 改写后的 query，其次 learner 实际学习目标（域相关），
    # 最后诊断 summary（demo 诊断 summary 为通用画像，不适合做检索词）
    query = (
        state.get("_pending_query") or learner.get("learning_goal", "") or diag.get("summary", "")
    )
    state["rag_query"] = str(query) if query else "工业机器人 调试"
    state.pop("_pending_query", None)

    logger.info(f"  [Agent2_query] RAG Query = '{state['rag_query'][:60]}'")
    return _step_result(GateVerdict.PASS.value)


async def _run_rag_search(state: dict) -> dict:
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
        logger.info(f"  [RAG_search] '{str(query)[:50]}' -> {len(chunks)} chunks")
    except Exception as exc:
        logger.warning(f"  [RAG_search] 检索失败: {exc}，返回空列表")
        state["retrieved_chunks"] = []

    return _step_result(GateVerdict.PASS.value)


def _calc_output_confidence(diag: dict) -> float:
    """计算诊断置信度：优先 overall_confidence，缺失时按 knowledge_map 求均值。

    真实 DiagnosisAgent（demo 模式）输出无 overall_confidence 字段，
    对齐 DiagnosisGate._calc_avg_confidence 的均值逻辑。
    """
    confidence = diag.get("overall_confidence", 0)
    if confidence:
        return float(confidence)
    knowledge_map = diag.get("knowledge_map", {})
    confs = [
        v.get("confidence", 0)
        for v in knowledge_map.values()
        if isinstance(v, dict) and v.get("confidence")
    ]
    return round(sum(confs) / len(confs), 4) if confs else 0


async def _run_output(state: dict) -> dict:
    """Output：格式化最终输出。降级模式返回 fallback status。"""
    diag = state.get("diagnosis_result", {})
    resources = state.get("generated_resources", [])
    audit = state.get("audit_result", {})
    is_fallback = state.get("_is_fallback", False)

    # audit_result 可能是 dict（旧 mock）或 list（3-Agent 真实链路置空表）
    audit_verdict = audit.get("verdict", "unknown") if isinstance(audit, dict) else "unknown"

    state["final_output"] = {
        "status": "fallback" if is_fallback else "ok",
        "pipeline_state": PipelineState.DONE.value,
        "diagnosis": {
            "difficulty": diag.get("recommended_difficulty", "?"),
            "confidence": _calc_output_confidence(diag),
            "gaps": len(diag.get("skill_gaps", [])),
        },
        "resources_count": len(resources),
        "audit_verdict": audit_verdict,
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
    """构建默认 step 列表（Day8：注册 diagnosis / generation / correction 真实 Agent）。"""
    return [
        ("InputGate", _run_input_gate, -1),  # 0
        ("Agent1", _run_agent1_diagnosis, -1),  # 1
        ("DiagnosisGate", _run_diagnosis_gate, 1),  # 2 → RETRY 回跳 Agent1
        ("Agent2_query", _build_rag_query, -1),  # 3
        ("RAG_search", _run_rag_search, -1),  # 4
        ("RecallGate", _run_recall_gate, 4),  # 5 → RETRY 回跳 RAG_search
        ("Agent2_generate", _run_agent2_generate, -1),  # 6
        ("Agent3_correction", _run_agent3_correction, -1),  # 7
        ("Output", _run_output, -1),  # 8
    ]


# ═══════════════════════════════════════════════════════════
# Gate 调用包装
# ═══════════════════════════════════════════════════════════


async def _run_input_gate(state: dict) -> dict:
    gate = InputGate()
    state = await gate.validate(state)
    result = state["gate_results"][InputGate.GATE_NAME]
    task_id = state.get("task_id", "")
    if not result.get("passed"):
        await event_bus.broadcast(
            task_id,
            EventType.GATE_FAIL,
            {"gate": InputGate.GATE_NAME, "verdict": GateVerdict.FALLBACK.value},
        )
        return _step_result(GateVerdict.FALLBACK.value)
    await event_bus.broadcast(
        task_id,
        EventType.GATE_PASS,
        {"gate": InputGate.GATE_NAME, "verdict": GateVerdict.PASS.value},
    )
    return _step_result(GateVerdict.PASS.value)


async def _run_diagnosis_gate(state: dict) -> dict:
    gate = DiagnosisGate()
    state = await gate.validate(state)
    result = state["gate_results"][DiagnosisGate.GATE_NAME]
    verdict = result.get("verdict", GateVerdict.FALLBACK.value)
    task_id = state.get("task_id", "")

    # RETRY 时，把 retry_hint 写入 state 供 Agent1 重试时参考
    if verdict == GateVerdict.RETRY.value:
        hint = result.get("retry_hint", "")
        state["_diagnosis_retry_hint"] = hint
        logger.info(f"  [DiagnosisGate] RETRY hint: {hint[:100]}")

    if verdict == GateVerdict.PASS.value:
        await event_bus.broadcast(
            task_id,
            EventType.GATE_PASS,
            {"gate": DiagnosisGate.GATE_NAME, "verdict": verdict},
        )
    else:
        await event_bus.broadcast(
            task_id,
            EventType.GATE_FAIL,
            {
                "gate": DiagnosisGate.GATE_NAME,
                "verdict": verdict,
                "retry_hint": result.get("retry_hint", ""),
            },
        )

    return _step_result(verdict)


async def _run_recall_gate(state: dict) -> dict:
    gate = RecallGate()
    state = await gate.validate(state)
    result = state["gate_results"][RecallGate.GATE_NAME]
    verdict = result.get("verdict", GateVerdict.FALLBACK.value)
    task_id = state.get("task_id", "")

    if verdict == GateVerdict.PASS.value:
        await event_bus.broadcast(
            task_id,
            EventType.GATE_PASS,
            {"gate": RecallGate.GATE_NAME, "verdict": verdict},
        )
    else:
        await event_bus.broadcast(
            task_id,
            EventType.GATE_FAIL,
            {
                "gate": RecallGate.GATE_NAME,
                "verdict": verdict,
                "retry_hint": result.get("retry_hint", ""),
            },
        )

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
        # EventBus 定向广播依赖 task_id；缺失则自动生成
        state.setdefault("task_id", str(uuid.uuid4()))

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

            # 执行 step（异常隔离：单步崩溃不终止流水线，转 FALLBACK）
            logger.info(f"[{step_num}/{len(steps)}] {name} ...")
            try:
                step_result = await handler(state)
            except Exception as exc:
                logger.error(
                    f"[{step_num}/{len(steps)}] {name} 抛出异常: "
                    f"{type(exc).__name__}: {exc}，转 FALLBACK"
                )
                step_result = {
                    "verdict": GateVerdict.FALLBACK.value,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                }

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
                    logger.warning(f"  [RETRY] {name} 已达最大重试次数，转 FALLBACK")
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

        # ── 广播工作流完成事件（含降级标记）──
        await event_bus.broadcast(
            state["task_id"],
            EventType.WORKFLOW_COMPLETE,
            {
                "pipeline_state": state["pipeline_state"],
                "elapsed_ms": elapsed_ms,
                "is_fallback": state.get("_is_fallback", False),
            },
        )

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

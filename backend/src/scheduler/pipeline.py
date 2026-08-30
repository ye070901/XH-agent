"""全局流水线调度器 — Phase2 完整业务链路编排（v0.1 三路裁决版）。

链路（支持 RETRY 回跳 / FALLBACK 降级）：
  用户输入 → Gate1 InputGate → Agent1 学情诊断 → Gate2 DiagnosisGate
  → Agent2 Step1 检索Query → RAG检索 → Gate3 RecallGate
  → Agent2 Step2 KB约束生成 → Agent3 内容审核 → 博弈引擎
  → Agent4 保真修正 → Agent3 二次审核 → 标准化输出

三路裁决模型（v0.1）：
  - PASS      → 继续下一步
  - RETRY     → 回跳到指定步骤重试（最多 N 次，超限转 FALLBACK）
  - FALLBACK  → 跳过剩余步骤，走降级兜底输出

架构约束：
  - Gate / Agent 内部不导入、不调用 EventBus；所有事件广播由 Scheduler 统一发起
  - 全部阈值从 config.settings 读取，禁止硬编码
  - 全局 state dict 贯穿全流程，增量追加中间结果，禁止覆盖核心数据
  - state 在各阶段间显式传递（返回值赋值），不依赖隐式引用突变
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from loguru import logger

from backend.src.agents.audit import AuditAgent
from backend.src.agents.correction import CorrectionAgent
from backend.src.agents.diagnosis import DiagnosisAgent
from backend.src.agents.generation_v2 import GenerationAgent
from backend.src.config import settings
from backend.src.event_broadcast import EventType, event_bus
from backend.src.knowledge.store import knowledge_base
from backend.src.quality_gate import BaseGate
from backend.src.quality_gate.gates import DiagnosisGate, InputGate, RecallGate
from backend.src.schemas import GateVerdict

# ═══════════════════════════════════════════════════════════
# 标准化错误结构体
# ═══════════════════════════════════════════════════════════


def _make_error_response(
    task_id: str,
    error_type: str,
    message: str,
    state: dict | None = None,
    elapsed_ms: int = 0,
) -> dict[str, Any]:
    """组装标准化错误返回体。"""
    return {
        "task_id": task_id,
        "status": "error",
        "error_type": error_type,
        "error_message": message,
        "elapsed_ms": elapsed_ms,
        "state_snapshot": {
            k: v
            for k, v in (state or {}).items()
            if k
            in (
                "gate_results",
                "agent_log",
                "diagnosis_result",
                "generated_resources",
                "retrieved_chunks",
                "learner_data",
            )
        },
    }


# ═══════════════════════════════════════════════════════════
# PipelineScheduler
# ═══════════════════════════════════════════════════════════


class PipelineScheduler:
    """全局流水线调度器 — 单例，所有任务通过此调度器执行。

    职责：
      - 并发控制：信号量限制最大并行任务数
      - 超时控制：asyncio.wait_for 全局超时
      - 事件广播：每个阶段统一推送事件
      - 异常隔离：捕获所有异常，组装标准化错误返回体
      - 闸门失败立刻终止，不执行后续阶段
      - Agent 失败不终止链路，仅广播 agent_error

    注意：Agent 和 Gate 的初始化是惰性的（首次使用时创建）。
    """

    def __init__(self) -> None:
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(
            settings.SCHEDULER_MAX_CONCURRENT_TASKS
        )
        self._agents: dict[str, Any] = {}
        self._gates: dict[str, BaseGate] = {}

    # ═══════════════════════════════════════════════════════════
    # 主入口
    # ═══════════════════════════════════════════════════════════

    async def run_pipeline(self, user_input: dict, task_id: str = "") -> dict[str, Any]:
        """执行完整 Phase2 业务链路。

        Args:
            user_input: 前端传入的用户数据（含 learner_data 字段）。
            task_id:    任务唯一标识，为空自动生成。

        Returns:
            dict: 标准化执行结果，始终含 task_id / status / elapsed_ms。
        """
        if not task_id:
            task_id = str(uuid.uuid4())

        t_start: float = time.monotonic()
        acquired: bool = False

        try:
            # ── 并发控制 ──
            await self._semaphore.acquire()
            acquired = True

            # ── 超时控制 ──
            result: dict[str, Any] = await asyncio.wait_for(
                self._execute_pipeline(user_input, task_id),
                timeout=settings.SCHEDULER_TASK_TIMEOUT_SECONDS,
            )
            return result

        except asyncio.TimeoutError:
            elapsed_ms: int = int((time.monotonic() - t_start) * 1000)
            logger.error(f"[Scheduler] task_id={task_id[:8]}… 任务超时")
            await event_bus.broadcast(
                task_id,
                EventType.AGENT_ERROR,
                {
                    "agent": "scheduler",
                    "error_type": "timeout",
                    "error_message": (f"任务超时 ({settings.SCHEDULER_TASK_TIMEOUT_SECONDS}s)"),
                    "elapsed_ms": elapsed_ms,
                },
            )
            return _make_error_response(
                task_id,
                "task_timeout",
                f"任务超时 ({settings.SCHEDULER_TASK_TIMEOUT_SECONDS}s)",
                elapsed_ms=elapsed_ms,
            )

        except _GateAbortError as gate_abort:
            elapsed_ms = int((time.monotonic() - t_start) * 1000)
            logger.warning(
                f"[Scheduler] task_id={task_id[:8]}… "
                f"闸门 '{gate_abort.gate_name}' 未通过，流水线终止"
            )
            return {
                "task_id": task_id,
                "status": "gate_blocked",
                "gate_name": gate_abort.gate_name,
                "violations": gate_abort.violations,
                "elapsed_ms": elapsed_ms,
                "gate_results": gate_abort.state.get("gate_results", {}),
                "agent_log": gate_abort.state.get("agent_log", []),
            }

        except Exception as exc:
            elapsed_ms = int((time.monotonic() - t_start) * 1000)
            logger.error(f"[Scheduler] task_id={task_id[:8]}… 异常: {type(exc).__name__}: {exc}")
            await event_bus.broadcast(
                task_id,
                EventType.AGENT_ERROR,
                {
                    "agent": "scheduler",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "elapsed_ms": elapsed_ms,
                },
            )
            return _make_error_response(
                task_id,
                type(exc).__name__,
                str(exc),
                elapsed_ms=elapsed_ms,
            )

        finally:
            if acquired:
                self._semaphore.release()

    # ═══════════════════════════════════════════════════════════
    # 核心流水线（私有）— step 列表 + while 循环 + 三路裁决
    # ═══════════════════════════════════════════════════════════

    async def _execute_pipeline(
        self,
        user_input: dict,
        task_id: str,
    ) -> dict[str, Any]:
        """串行执行流水线，支持 RETRY 回跳 / FALLBACK 降级。

        维护 step 列表，按序执行。每个 step 返回 verdict：
          PASS     → idx+1 继续
          RETRY    → idx 回跳到 retry_target
          FALLBACK → 跳到兜底输出，循环结束
        """
        state: dict[str, Any] = self._init_state(user_input, task_id)
        state.setdefault("_retry_counts", {})
        state.setdefault("recall_retry_count", 0)

        # step 定义: (name, retry_target_index)
        # retry_target=-1 表示该步骤不触发回跳（InputGate 失败直接终止）
        steps = [
            ("InputGate", -1),  # 0
            ("Agent1", -1),  # 1
            ("DiagnosisGate", 1),  # 2 → RETRY 回跳 Agent1
            ("Agent2_query", -1),  # 3
            ("RAG_search", -1),  # 4
            ("RecallGate", 4),  # 5 → RETRY 回跳 RAG_search
            ("Agent2_generate", -1),  # 6
            ("Agent3_audit", -1),  # 7
            ("Agent4_correction", -1),  # 8
            ("Agent3_recheck", -1),  # 9
            ("Output", -1),  # 10
        ]

        idx = 0
        max_iterations = len(steps) * 10  # 防死循环

        while idx < len(steps) and max_iterations > 0:
            max_iterations -= 1
            name, retry_target = steps[idx]

            logger.info(f"[Scheduler] task_id={task_id[:8]}… [{idx + 1}/{len(steps)}] {name}")

            # 执行当前 step
            verdict = await self._dispatch_step(idx, name, state, task_id)

            # ── PASS → 继续 ──
            if verdict == GateVerdict.PASS.value:
                idx += 1
                continue

            # ── RETRY → 回跳 ──
            if verdict == GateVerdict.RETRY.value:
                self._track_retry(state, idx)
                rc = state["_retry_counts"].get(f"step_{idx}", 1)
                if retry_target >= 0 and rc <= settings.RECALL_MAX_RETRIES:
                    logger.info(
                        f"[Scheduler] RETRY #{rc}: {name} "
                        f"-> step[{retry_target}] '{steps[retry_target][0]}'"
                    )
                    if "RecallGate" in name:
                        state["recall_retry_count"] = state.get("recall_retry_count", 0) + 1
                    idx = retry_target
                    continue
                else:
                    logger.warning(f"[Scheduler] {name} 重试已达上限 ({rc})，转 FALLBACK")
                    verdict = GateVerdict.FALLBACK.value

            # ── FALLBACK ──
            if verdict == GateVerdict.FALLBACK.value:
                # RecallGate 兜底：知识库无匹配素材 → 不再终止，接续到 Agent2 无素材自生成
                # （方案 B2）。清除兜底提示/引文跳过标记，保留 downgrade_mode 走无 KB 一致性检查。
                if name == "RecallGate":
                    state.pop("_offline_fallback_message", None)
                    state.pop("_online_fallback_raw", None)
                    state.pop("_online_fallback_sources", None)
                    state.pop("_skip_kb_citation", None)
                    state["downgrade_mode"] = True
                    state["_no_kb_mode"] = True
                    logger.info(
                        f"[Scheduler] task_id={task_id[:8]}… "
                        f"RecallGate 无素材，接续 Agent2 无素材自生成（downgrade_mode=True）"
                    )
                    idx += 1
                    continue

                state["_is_fallback"] = True
                logger.warning(f"[Scheduler] FALLBACK triggered by {name}")
                await self._broadcast(
                    task_id,
                    EventType.GATE_FAIL,
                    {"gate": name, "verdict": "FALLBACK"},
                )
                break

        # 终态
        state["status"] = "completed"
        if not state.get("_is_fallback"):
            await self._broadcast(
                task_id,
                EventType.WORKFLOW_COMPLETE,
                {
                    "status": "completed",
                    "resources_count": len(state.get("corrected_resources", [])),
                    "audit_verdict": self._extract_verdict(state),
                },
            )
        return state

    # ═══════════════════════════════════════════════════════════
    # Step 调度器（按 step_index 分发到具体执行方法）
    # ═══════════════════════════════════════════════════════════

    async def _dispatch_step(
        self,
        step_idx: int,
        name: str,
        state: dict[str, Any],
        task_id: str,
    ) -> str:
        """根据 step 名称分发到对应 handler，返回 verdict 字符串。"""
        if name == "InputGate":
            return await self._step_input_gate(state, task_id)
        if name == "Agent1":
            return await self._step_agent1(state, task_id)
        if name == "DiagnosisGate":
            return await self._step_diagnosis_gate(state, task_id)
        if name == "Agent2_query":
            return await self._step_agent2_query(state, task_id)
        if name == "RAG_search":
            return await self._step_rag_search(state, task_id)
        if name == "RecallGate":
            return await self._step_recall_gate(state, task_id)
        if name == "Agent2_generate":
            return await self._step_agent2_generate(state, task_id)
        if name == "Agent3_audit":
            return await self._step_agent3(state, task_id)
        if name == "Agent4_correction":
            return await self._step_agent4(state, task_id)
        if name == "Agent3_recheck":
            return await self._step_agent3_recheck(state, task_id)
        if name == "Output":
            return await self._step_output(state, task_id)
        return GateVerdict.PASS.value

    # ═══════════════════════════════════════════════════════════
    # Step 0: InputGate — 输入安全过滤
    # ═══════════════════════════════════════════════════════════

    async def _step_input_gate(self, state: dict[str, Any], task_id: str) -> str:
        """InputGate 只做二元判断：通过 → PASS，拦截 → FALLBACK（终止）。"""
        gate = InputGate()
        state = await gate.validate(state)
        result = state["gate_results"][InputGate.GATE_NAME]

        if result.get("passed"):
            await self._broadcast(
                task_id,
                EventType.GATE_PASS,
                {
                    "gate": gate.GATE_NAME,
                    "score": result.get("score", 0.0),
                },
            )
            return GateVerdict.PASS.value

        await self._broadcast(
            task_id,
            EventType.GATE_FAIL,
            {
                "gate": gate.GATE_NAME,
                "violations": result.get("violations", []),
            },
        )
        raise _GateAbortError(
            gate_name=gate.GATE_NAME,
            violations=result.get("violations", []),
            state=state,
            task_id=task_id,
        )

    # ═══════════════════════════════════════════════════════════
    # Step 1: Agent1 — 学情诊断
    # ═══════════════════════════════════════════════════════════

    async def _step_agent1(self, state: dict[str, Any], task_id: str) -> str:
        # 如果 DiagnosisGate 之前给了 RETRY hint，注入 learner_data
        hint = state.pop("_diagnosis_retry_hint", "")
        if hint:
            learner = state.get("learner_data", {})
            learner["_retry_hint"] = hint
            state["learner_data"] = learner
            logger.info(f"[Scheduler] Agent1 收到 RETRY hint: {hint[:80]}")

        return await self._run_agent(self._get_diagnosis(), state, task_id, "diagnosis")

    # ═══════════════════════════════════════════════════════════
    # Step 2: DiagnosisGate — 三路裁决
    # ═══════════════════════════════════════════════════════════

    async def _step_diagnosis_gate(self, state: dict[str, Any], task_id: str) -> str:
        gate = DiagnosisGate()
        state = await gate.validate(state)
        result = state["gate_results"][DiagnosisGate.GATE_NAME]
        verdict = result.get("verdict", GateVerdict.FALLBACK.value)

        if verdict == GateVerdict.PASS.value:
            await self._broadcast(
                task_id,
                EventType.GATE_PASS,
                {
                    "gate": gate.GATE_NAME,
                    "score": result.get("score", 0.0),
                },
            )
        elif verdict == GateVerdict.RETRY.value:
            state["_diagnosis_retry_hint"] = result.get("retry_hint", "")
            logger.info(f"[Scheduler] DiagnosisGate RETRY: {result.get('retry_hint', '')[:100]}")
        else:
            # FALLBACK：降级诊断已写入 gate_result.fallback_data
            await self._broadcast(
                task_id,
                EventType.GATE_FAIL,
                {
                    "gate": gate.GATE_NAME,
                    "verdict": "FALLBACK",
                },
            )

        return verdict

    # ═══════════════════════════════════════════════════════════
    # Step 3: Agent2_query — 构建 RAG 检索 Query
    # ═══════════════════════════════════════════════════════════

    async def _step_agent2_query(self, state: dict[str, Any], task_id: str) -> str:
        diag = state.get("diagnosis_result", {})
        learner = state.get("learner_data", {})

        # 优先用 RecallGate 改写后的 query
        pending = state.pop("_pending_query", None)
        if pending:
            query = pending
        else:
            query = diag.get("summary", "") or learner.get("learning_goal", "") or "工业机器人 调试"

        state["rag_query"] = str(query)
        logger.info(f"[Scheduler] task_id={task_id[:8]}… RAG Query: '{str(query)[:60]}'")
        return GateVerdict.PASS.value

    # ═══════════════════════════════════════════════════════════
    # Step 4: RAG_search — 执行向量检索
    # ═══════════════════════════════════════════════════════════

    async def _step_rag_search(self, state: dict[str, Any], task_id: str) -> str:
        query = state.pop("_pending_query", None) or state.get("rag_query", "")

        # 如果 RecallGate 返回了改写 query，优先用
        recall_key = RecallGate.GATE_NAME
        prev = state.get("gate_results", {}).get(recall_key, {})
        new_q = prev.get("details", {}).get("new_query", "")
        if new_q:
            query = new_q
            state["_pending_query"] = new_q

        chunks = await knowledge_base.search(str(query), top_k=8)
        state["retrieved_chunks"] = chunks
        logger.info(f"[KB引擎接管RAG检索] query={str(query)[:50]}")
        logger.info(
            f"[Scheduler] task_id={task_id[:8]}… RAG: '{str(query)[:50]}' -> {len(chunks)} chunks"
        )
        return GateVerdict.PASS.value

    # ═══════════════════════════════════════════════════════════
    # Step 5: RecallGate — 三路裁决
    # ═══════════════════════════════════════════════════════════

    async def _step_recall_gate(self, state: dict[str, Any], task_id: str) -> str:
        gate = RecallGate(is_offline=settings.OFFLINE_MODE)
        state = await gate.validate(state)
        result = state["gate_results"][RecallGate.GATE_NAME]
        verdict = result.get("verdict", GateVerdict.FALLBACK.value)

        # 兜底分支：识别 fallback_data 中的兜底内容并写入 state，标记跳过 Agent3 引文校验
        # （无检索片段，避免无 KB 比对时报错）；同时写 downgrade_mode=True 作显式降级留痕（B1）。
        fb = result.get("fallback_data") or {}
        if isinstance(fb, dict):
            # 在线兜底：外部检索原始摘要（不含免责头，免责头由输出层硬拼接）
            if fb.get("online_fallback_raw"):
                state["_online_fallback_raw"] = fb["online_fallback_raw"]
                state["_online_fallback_sources"] = fb.get("sources", [])
                state["_skip_kb_citation"] = True
                state["downgrade_mode"] = True
                logger.info(
                    f"[Scheduler] task_id={task_id[:8]}… 在线兜底：跳过 Agent3 知识库引文校验"
                )
            # 离线兜底：固定提示文本（防御性，同样跳过引文校验）
            if fb.get("offline_message"):
                state["_offline_fallback_message"] = fb["offline_message"]
                state["_skip_kb_citation"] = True
                state["downgrade_mode"] = True
                logger.info(
                    f"[Scheduler] task_id={task_id[:8]}… 离线兜底：跳过 Agent3 知识库引文校验"
                )

        if verdict == GateVerdict.PASS.value:
            await self._broadcast(
                task_id,
                EventType.GATE_PASS,
                {
                    "gate": gate.GATE_NAME,
                    "score": result.get("score", 0.0),
                },
            )
        elif verdict == GateVerdict.RETRY.value:
            new_q = result.get("details", {}).get("new_query", "")
            logger.info(f"[Scheduler] RecallGate RETRY: new_query='{new_q[:60]}'")
        else:
            await self._broadcast(
                task_id,
                EventType.GATE_FAIL,
                {
                    "gate": gate.GATE_NAME,
                    "verdict": "FALLBACK",
                },
            )

        return verdict

    # ═══════════════════════════════════════════════════════════
    # Step 6: Agent2_generate — KB 约束生成
    # ═══════════════════════════════════════════════════════════

    async def _step_agent2_generate(self, state: dict[str, Any], task_id: str) -> str:
        return await self._run_agent(self._get_generation(), state, task_id, "generation")

    # ═══════════════════════════════════════════════════════════
    # Step 7: Agent3_audit — 初次内容审核
    # ═══════════════════════════════════════════════════════════

    async def _step_agent3(self, state: dict[str, Any], task_id: str) -> str:
        # 【B1：降级标记显式化】_step_recall_gate 在 FALLBACK 写入 state["downgrade_mode"]=True，
        # 但 FALLBACK 会 break 终止流水线（见 run_pipeline），Agent3/4 不会被调度到，
        # 故 downgrade_mode 当前仅作留痕，此处保留 _skip_kb_citation 防御。
        # 若未来 FALLBACK 不再 break（方案 B2），需让 Agent3 读 downgrade_mode 走无 KB 检查。
        if state.get("_skip_kb_citation"):
            logger.info(
                f"[Scheduler] task_id={task_id[:8]}… 在线兜底内容，跳过 Agent3 知识库引文校验"
            )
            return GateVerdict.PASS.value
        return await self._run_agent(self._get_audit(), state, task_id, "audit")

    # ═══════════════════════════════════════════════════════════
    # Step 8: Agent4_correction — 保真修正 + 博弈引擎
    # ═══════════════════════════════════════════════════════════

    async def _step_agent4(self, state: dict[str, Any], task_id: str) -> str:
        # 博弈引擎（在修正之前执行）
        state = await self._run_debate(state, task_id)
        return await self._run_agent(self._get_correction(), state, task_id, "correction")

    # ═══════════════════════════════════════════════════════════
    # Step 9: Agent3_recheck — 二次审核（对修正后内容）
    # ═══════════════════════════════════════════════════════════

    async def _step_agent3_recheck(self, state: dict[str, Any], task_id: str) -> str:
        # 在线兜底内容来自外部大模型，无 KB 检索片段，跳过二次引文校验
        if state.get("_skip_kb_citation"):
            logger.info(
                f"[Scheduler] task_id={task_id[:8]}… 在线兜底内容，跳过 Agent3 二次引文校验"
            )
            return GateVerdict.PASS.value
        if state.get("corrected_resources"):
            state["_original_generated_resources"] = state.get("generated_resources", [])
            state["generated_resources"] = state["corrected_resources"]
        return await self._run_agent(self._get_audit(), state, task_id, "audit_recheck")

    # ═══════════════════════════════════════════════════════════
    # Step 10: Output — 最终汇总
    # ═══════════════════════════════════════════════════════════

    async def _step_output(self, state: dict[str, Any], task_id: str) -> str:
        # 【死代码】FALLBACK 时 _execute_pipeline 在 RecallGate 后即 break，
        # 本 step（index 10）永不执行，此处 fallback 注入分支不可达，仅保留结构占位。
        if state.get("_is_fallback"):
            # 降级输出：从最后一次 gate 结果取 fallback_data
            for gate_name in (
                RecallGate.GATE_NAME,
                DiagnosisGate.GATE_NAME,
            ):
                gr = state.get("gate_results", {}).get(gate_name, {})
                fb = gr.get("fallback_data") or gr.get("details", {}).get("fallback_data")
                if fb and isinstance(fb, dict):
                    state["diagnosis_result"] = fb
                    break
            logger.info(f"[Scheduler] task_id={task_id[:8]}… FALLBACK output: 已注入降级诊断数据")
        return GateVerdict.PASS.value

    # ═══════════════════════════════════════════════════════════
    # Agent 统一执行包装（供 _step_agent* 复用）
    # ═══════════════════════════════════════════════════════════

    async def _run_agent(
        self,
        agent: Any,
        state: dict[str, Any],
        task_id: str,
        agent_name: str,
    ) -> str:
        """执行 Agent → 广播事件，异常隔离，始终返回 PASS。

        单 Agent 失败不终止流水线（与闸门不同）。
        """
        await self._broadcast(
            task_id,
            EventType.AGENT_START,
            {"agent": agent_name},
        )
        try:
            state = await agent.run(state)

            if state.get("status") == "error":
                await self._broadcast(
                    task_id,
                    EventType.AGENT_ERROR,
                    {
                        "agent": agent_name,
                        "error_message": state.get("error", "Agent 返回 error 状态"),
                    },
                )
            else:
                await self._broadcast(
                    task_id,
                    EventType.AGENT_DONE,
                    {"agent": agent_name},
                )
            return GateVerdict.PASS.value

        except Exception as exc:
            logger.error(
                f"[Scheduler] task_id={task_id[:8]}… "
                f"Agent '{agent_name}' 异常: {type(exc).__name__}: {exc}"
            )
            await self._broadcast(
                task_id,
                EventType.AGENT_ERROR,
                {
                    "agent": agent_name,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            state["status"] = "partial_error"
            state.setdefault("agent_log", []).append(
                {
                    "agent": agent_name,
                    "level": "error",
                    "message": str(exc),
                    "error_type": type(exc).__name__,
                }
            )
            return GateVerdict.PASS.value

    # ═══════════════════════════════════════════════════════════
    # RETRY 计数
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _track_retry(state: dict[str, Any], step_idx: int) -> None:
        """记录某步骤的重试次数。"""
        key = f"step_{step_idx}"
        state["_retry_counts"][key] = state["_retry_counts"].get(key, 0) + 1

    # ═══════════════════════════════════════════════════════════
    # 博弈引擎（Opt-2 接入 — 三态裁决 + 权威加权 + 终止边界）
    # ═══════════════════════════════════════════════════════════

    async def _run_debate(self, state: dict[str, Any], task_id: str) -> dict[str, Any]:
        """博弈引擎裁决：Agent3 三态断言 → 争议断言进 debate → 裁决结果回写资源。

        裁决纯规则（不调 LLM），写入 state["debate_result"] 供 Agent4 修正消费
        （correction.py 逐条落地 replace/delete/keep）。引擎不可用时降级跳过，
        返回原 state（修正走既有 LLM 路径）。
        """
        try:
            from backend.src.graph.orchestrator import workflow_engine

            engine = getattr(workflow_engine, "debate", None)
            if engine is None:
                logger.info(f"[Scheduler] task_id={task_id[:8]}… 博弈引擎未就绪，降级跳过辩论环节")
                return state

            logger.info(f"[Scheduler] task_id={task_id[:8]}… 启动博弈引擎")
            debate_result = engine.adjudicate(
                audit_result=state.get("audit_result", []),
                generated_resources=state.get("generated_resources", []),
            )
            state["debate_result"] = debate_result
            stats = debate_result.get("stats", {})
            await self._broadcast(
                task_id,
                EventType.DEBATE_ROUND,
                {
                    "adjudications": stats.get("total_adjudications", 0),
                    "decisions": stats.get("decisions", {}),
                    "unresolved": stats.get("unresolved_count", 0),
                },
            )
            return state
        except ImportError:
            pass
        except Exception as exc:
            logger.warning(f"[Scheduler] task_id={task_id[:8]}… 博弈引擎不可用，降级跳过: {exc}")

        logger.info(f"[Scheduler] task_id={task_id[:8]}… 博弈引擎未就绪，降级跳过辩论环节")
        return state

    # ═══════════════════════════════════════════════════════════
    # 私有辅助
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _init_state(user_input: dict, task_id: str) -> dict[str, Any]:
        """初始化全局 state dict。"""
        return {
            "task_id": task_id,
            "learner_data": user_input.get("learner_data", user_input),
            "resource_types": user_input.get("resource_types", ["lecture", "guide", "quiz"]),
            "status": "starting",
            "agent_log": [],
            "gate_results": {},
        }

    @staticmethod
    def _build_rag_query(state: dict[str, Any]) -> str:
        """从诊断结果构建 RAG 检索 Query。

        优先级：diagnosis_result.summary
        + critical/high skill_gaps → 兜底 learning_goal。
        """
        diag: dict = state.get("diagnosis_result", {})
        parts: list[str] = []

        summary: str = diag.get("summary", "")
        if summary:
            parts.append(summary)

        gaps: list = diag.get("skill_gaps", [])
        critical_topics: list[str] = [
            g.get("topic", "")
            for g in gaps
            if isinstance(g, dict) and g.get("priority") in ("critical", "high")
        ]
        if critical_topics:
            parts.append("相关知识点: " + ", ".join(critical_topics[:5]))

        if parts:
            return "。".join(parts)

        learner: dict = state.get("learner_data", {})
        goal: str = learner.get("learning_goal", "")
        return str(goal) if goal else "AI Agent 开发"

    @staticmethod
    async def _broadcast(task_id: str, event_type: EventType, data: dict) -> None:
        """Scheduler 统一广播入口。

        所有事件广播由 Scheduler 发起，Gate/Agent 内部不调用。
        """
        await event_bus.broadcast(task_id, event_type, data)

    @staticmethod
    def _extract_verdict(state: dict[str, Any]) -> str:
        """从状态中提取最终审核结论。"""
        audit = state.get("audit_result", {})
        if isinstance(audit, dict):
            return audit.get("verdict", "unknown")
        if isinstance(audit, list) and audit:
            last = audit[-1]
            return last.get("verdict", "unknown") if isinstance(last, dict) else "unknown"
        return "unknown"

    # ═══════════════════════════════════════════════════════════
    # 惰性 Agent 初始化
    # ═══════════════════════════════════════════════════════════

    def _get_diagnosis(self) -> DiagnosisAgent:
        if "diagnosis" not in self._agents:
            self._agents["diagnosis"] = DiagnosisAgent()
        return self._agents["diagnosis"]  # type: ignore[return-value]

    def _get_generation(self) -> GenerationAgent:
        if "generation" not in self._agents:
            self._agents["generation"] = GenerationAgent()
        return self._agents["generation"]  # type: ignore[return-value]

    def _get_audit(self) -> AuditAgent:
        if "audit" not in self._agents:
            self._agents["audit"] = AuditAgent()
        return self._agents["audit"]  # type: ignore[return-value]

    def _get_correction(self) -> CorrectionAgent:
        if "correction" not in self._agents:
            self._agents["correction"] = CorrectionAgent()
        return self._agents["correction"]  # type: ignore[return-value]


# ═══════════════════════════════════════════════════════════
# 内部异常：闸门终止信号
# ═══════════════════════════════════════════════════════════


class _GateAbortError(Exception):
    """闸门失败终止信号 —— 仅 Scheduler 内部使用。

    被 run_pipeline 的 try/except 链捕获，
    组装标准化失败结果返回。
    """

    def __init__(
        self,
        gate_name: str,
        violations: list[str],
        state: dict[str, Any],
        task_id: str,
    ) -> None:
        super().__init__(f"闸门 '{gate_name}' 未通过")
        self.gate_name: str = gate_name
        self.violations: list[str] = violations
        self.state: dict[str, Any] = state
        self.task_id: str = task_id


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

scheduler: PipelineScheduler = PipelineScheduler()

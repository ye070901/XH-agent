"""全局流水线调度器 — Phase2 完整业务链路编排。

链路（严格串行，不可擅自改动顺序）：
  用户输入 → Gate1 InputGate → Agent1 学情诊断 → Gate2 DiagnosisGate
  → Agent2 Step1 检索Query → RAG检索 → Gate3 RecallGate
  → Agent2 Step2 KB约束生成 → Agent3 内容审核 → 博弈引擎
  → Agent4 保真修正 → Agent3 二次审核 → 标准化输出

架构约束：
  - Gate / Agent 内部不导入、不调用 EventBus；所有事件广播由 Scheduler 统一发起
  - 全部阈值从 config.settings 读取，禁止硬编码
  - 全局 state dict 贯穿全流程，增量追加中间结果，禁止覆盖核心数据
  - 任意闸门失败立刻终止链路，组装失败结果并推送事件
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
    # 核心流水线（私有）— state 在各阶段间显式传递
    # ═══════════════════════════════════════════════════════════

    async def _execute_pipeline(self, user_input: dict, task_id: str) -> dict[str, Any]:
        """串行执行 7 阶段流水线，每阶段返回值显式赋值 state。"""
        state: dict[str, Any] = self._init_state(user_input, task_id)

        # ── 阶段 I：前置闸门 + 学情诊断 ──
        state = await self._do_gate(InputGate(), state, task_id, "输入特异性检测")
        state = await self._do_agent(self._get_diagnosis(), state, task_id, "diagnosis")
        state = await self._do_gate(DiagnosisGate(), state, task_id, "学情诊断质量检测")

        # ── 阶段 II：RAG 检索 + 召回闸门 ──
        rag_query: str = self._build_rag_query(state)
        state["retrieved_chunks"] = await knowledge_base.search(rag_query, top_k=8)
        logger.info(
            f"[Scheduler] task_id={task_id[:8]}… "
            f"RAG 检索: query='{rag_query[:60]}…' "
            f"→ {len(state['retrieved_chunks'])} 篇"
        )
        state = await self._do_gate(RecallGate(), state, task_id, "RAG召回质量检测")

        # ── 阶段 III：KB 约束生成 ──
        state = await self._do_agent(self._get_generation(), state, task_id, "generation")

        # ── 阶段 IV：Agent3 初次审核 ──
        state = await self._do_agent(self._get_audit(), state, task_id, "audit")

        # ── 阶段 V：博弈引擎（多Agent对抗迭代）──
        state = await self._run_debate(state, task_id)

        # ── 阶段 VI：Agent4 保真修正 ──
        state = await self._do_agent(self._get_correction(), state, task_id, "correction")

        # ── 阶段 VII：Agent3 二次审核（对修正后内容）──
        if state.get("corrected_resources"):
            state["_original_generated_resources"] = state.get("generated_resources", [])
            state["generated_resources"] = state["corrected_resources"]
        state = await self._do_agent(self._get_audit(), state, task_id, "audit_recheck")

        # ── 汇总 ──
        await self._broadcast(
            task_id,
            EventType.WORKFLOW_COMPLETE,
            {
                "status": "completed",
                "resources_count": len(state.get("corrected_resources", [])),
                "audit_verdict": self._extract_verdict(state),
            },
        )
        state["status"] = "completed"
        return state

    # ═══════════════════════════════════════════════════════════
    # Gate / Agent 统一执行包装 — 显式返回 state
    # ═══════════════════════════════════════════════════════════

    async def _do_gate(
        self,
        gate: BaseGate,
        state: dict[str, Any],
        task_id: str,
        gate_label: str,
    ) -> dict[str, Any]:
        """执行闸门判定 → 通过返回新 state，失败抛 _GateAbortError。

        闸门校验成功：广播 gate_pass，state 注入了 gate_results
        闸门校验失败：广播 gate_fail，抛出 _GateAbortError
        """
        state = await gate.validate(state)
        gate_result: dict[str, Any] = state.get("gate_results", {}).get(gate.GATE_NAME, {})

        if gate_result.get("passed"):
            await self._broadcast(
                task_id,
                EventType.GATE_PASS,
                {
                    "gate": gate.GATE_NAME,
                    "label": gate_label,
                    "score": gate_result.get("score", 0.0),
                },
            )
            return state

        # 失败 → 广播 + 终止
        await self._broadcast(
            task_id,
            EventType.GATE_FAIL,
            {
                "gate": gate.GATE_NAME,
                "label": gate_label,
                "score": gate_result.get("score", 0.0),
                "violations": gate_result.get("violations", []),
            },
        )
        raise _GateAbortError(
            gate_name=gate.GATE_NAME,
            violations=gate_result.get("violations", []),
            state=state,
            task_id=task_id,
        )

    async def _do_agent(
        self,
        agent: Any,
        state: dict[str, Any],
        task_id: str,
        agent_name: str,
    ) -> dict[str, Any]:
        """执行 Agent → 返回合并后的 state，异常广播 agent_error 并继续。

        单个 Agent 失败不终止流水线（与闸门不同）。
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

            return state

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
            # 写入 state 错误标记但不抛异常 —— 单 Agent 故障不阻断链路
            state["status"] = "partial_error"
            state.setdefault("agent_log", []).append(
                {
                    "agent": agent_name,
                    "level": "error",
                    "message": str(exc),
                    "error_type": type(exc).__name__,
                }
            )
            return state

    # ═══════════════════════════════════════════════════════════
    # 博弈引擎（占位 — 等待模板5完整实现）
    # ═══════════════════════════════════════════════════════════

    async def _run_debate(self, state: dict[str, Any], task_id: str) -> dict[str, Any]:
        """多Agent博弈辩论引擎调用。

        当前为占位实现：尝试从 graph 模块加载辩论引擎。
        加载成功 → 执行多Agent对抗迭代；加载失败 → 降级跳过。

        TODO: 模板5完成后替换为正式辩论引擎调用。
        """
        try:
            from backend.src.graph.orchestrator import workflow_engine

            if hasattr(workflow_engine, "debate") and callable(workflow_engine.debate):
                logger.info(f"[Scheduler] task_id={task_id[:8]}… 启动博弈引擎")
                debate_state = await workflow_engine.debate(state)
                await self._broadcast(
                    task_id,
                    EventType.DEBATE_ROUND,
                    {
                        "rounds": len(debate_state.get("debate_rounds", [])),
                        "verdict": debate_state.get("debate_verdict", "unknown"),
                    },
                )
                return debate_state
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

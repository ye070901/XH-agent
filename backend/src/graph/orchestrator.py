"""LangGraph 工作流 — 3 Agent 协同调度 + 辩论回环。角色1 在此实现。"""
import uuid
from typing import TypedDict

from loguru import logger

from ..agents.diagnosis import DiagnosisAgent
from ..agents.generation import GenerationAgent
from ..agents.audit import AuditAgent
from ..knowledge.store import knowledge_base

# LangGraph imports（无 LangGraph 时回退到顺序执行）
try:
    from langgraph.graph import StateGraph, END
    from langgraph.checkpoint.memory import MemorySaver
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    logger.warning("[工作流] LangGraph 未安装，使用简化顺序模式")


class WorkflowState(TypedDict, total=False):
    """LangGraph 全局状态 — 所有 Agent 共享"""

    # 输入
    task_id: str
    learner_data: dict
    resource_types: list[str]

    # Agent 1 输出
    diagnosis_completed: bool
    diagnosis_result: dict

    # 检索输出
    retrieved_chunks: list[dict]

    # Agent 2 输出
    generated_resources: list[dict]

    # Agent 3 输出
    audit_reports: list[dict]

    # 辩论输出
    debate_records: list[dict]
    final_resources: list[dict]
    rejected_resources: list[dict]

    # 状态追踪（用于可视化）
    status: str
    current_agent: str
    errors: list[str]
    agent_log: list[dict]


class AgentWorkflow:
    """3 Agent 协同工作流引擎 — 角色1 实现"""

    def __init__(self):
        self._diagnosis_agent = None
        self._generation_agent = None
        self._audit_agent = None
        self.graph = None
        if LANGGRAPH_AVAILABLE:
            self._build_graph()

    @property
    def diagnosis(self):
        if self._diagnosis_agent is None:
            self._diagnosis_agent = DiagnosisAgent()
        return self._diagnosis_agent

    @property
    def generation(self):
        if self._generation_agent is None:
            self._generation_agent = GenerationAgent()
        return self._generation_agent

    @property
    def audit(self):
        if self._audit_agent is None:
            self._audit_agent = AuditAgent()
        return self._audit_agent

    def _build_graph(self):
        """构建 LangGraph: diagnose → retrieve → generate → review → [debate] → finalize"""
        workflow = StateGraph(WorkflowState)

        workflow.add_node("diagnose", self._node_diagnose)
        workflow.add_node("retrieve", self._node_retrieve)
        workflow.add_node("generate", self._node_generate)
        workflow.add_node("review", self._node_review)
        workflow.add_node("debate", self._node_debate)
        workflow.add_node("finalize", self._node_finalize)

        workflow.set_entry_point("diagnose")
        workflow.add_edge("diagnose", "retrieve")
        workflow.add_edge("retrieve", "generate")
        workflow.add_edge("generate", "review")

        workflow.add_conditional_edges(
            "review",
            self._should_debate,
            {"debate": "debate", "finalize": "finalize"},
        )
        workflow.add_edge("debate", "finalize")
        workflow.add_edge("finalize", END)

        memory = MemorySaver()
        self.graph = workflow.compile(checkpointer=memory)
        logger.info("[工作流] LangGraph 状态图构建完成")

    # ── 节点实现 ──

    async def _node_diagnose(self, state: WorkflowState) -> dict:
        logger.info(f"[工作流] 学情诊断: {state['task_id']}")
        result = await self.diagnosis.process(state)
        result["status"] = "diagnosing"
        result["current_agent"] = "diagnosis"
        result["agent_log"] = [{"agent": "diagnosis", "action": "completed"}]
        return result

    async def _node_retrieve(self, state: WorkflowState) -> dict:
        logger.info(f"[工作流] 知识检索: {state['task_id']}")
        diagnosis = state.get("diagnosis_result", {})
        skill_gaps = diagnosis.get("skill_gaps", [])
        query = " ".join([g.get("topic", "") for g in skill_gaps[:3]])
        try:
            chunks = await knowledge_base.search(query, top_k=10)
        except Exception as e:
            logger.error(f"[工作流] 检索失败: {e}")
            chunks = []
        return {
            "retrieved_chunks": chunks,
            "status": "retrieving",
            "current_agent": "retriever",
            "agent_log": [{"agent": "retriever", "action": f"retrieved {len(chunks)} chunks"}],
        }

    async def _node_generate(self, state: WorkflowState) -> dict:
        logger.info(f"[工作流] 资源生成: {state['task_id']}")
        result = await self.generation.process(state)
        result["status"] = "generating"
        result["current_agent"] = "generation"
        result["agent_log"] = [{
            "agent": "generation",
            "action": f"generated {len(result.get('generated_resources', []))} resources",
        }]
        return result

    async def _node_review(self, state: WorkflowState) -> dict:
        logger.info(f"[工作流] 内容审核: {state['task_id']}")
        result = await self.audit.process(state)
        result["status"] = "reviewing"
        result["current_agent"] = "audit"
        result["agent_log"] = [{"agent": "audit", "action": "completed"}]
        return result

    async def _node_debate(self, state: WorkflowState) -> dict:
        logger.info(f"[工作流] 进入辩论: {state['task_id']}")
        from ..debate.engine import DebateEngine

        engine = DebateEngine()
        debate_records = []
        final_resources = list(state.get("final_resources", []))
        rejected = list(state.get("rejected_resources", []))

        for i, resource in enumerate(state.get("generated_resources", [])):
            audit = state["audit_reports"][i] if i < len(state["audit_reports"]) else {}
            if audit.get("verdict") != "approved":
                result = await engine.run(
                    resource, audit, state.get("retrieved_chunks", []),
                    self.generation, self.audit,
                )
                debate_records.extend(result.get("debate_records", []))
                final_resources.extend(result.get("final_resources", []))
                rejected.extend(result.get("rejected_resources", []))
            else:
                final_resources.append(resource)

        return {
            "debate_records": debate_records,
            "final_resources": final_resources,
            "rejected_resources": rejected,
            "status": "debating",
            "current_agent": "debate",
            "agent_log": [{"agent": "debate", "action": f"{len(debate_records)} rounds"}],
        }

    async def _node_finalize(self, state: WorkflowState) -> dict:
        logger.info(f"[工作流] 流程完成: {state['task_id']}")
        return {
            "status": "completed",
            "current_agent": "system",
        }

    # ── 条件路由 ──

    def _should_debate(self, state: WorkflowState) -> str:
        for audit in state.get("audit_reports", []):
            if audit.get("verdict") not in ("approved", None):
                return "debate"
        return "finalize"

    # ── 公开接口 ──

    async def run(
        self,
        task_id: str = "",
        learner_data: dict = None,
        resource_types: list[str] = None,
    ) -> dict:
        """运行完整工作流"""
        if task_id == "":
            task_id = str(uuid.uuid4())
        if learner_data is None:
            learner_data = {}
        if resource_types is None:
            resource_types = ["lecture", "guide", "quiz"]

        initial_state: WorkflowState = {
            "task_id": task_id,
            "learner_data": learner_data,
            "resource_types": resource_types,
            "diagnosis_completed": False,
            "diagnosis_result": {},
            "retrieved_chunks": [],
            "generated_resources": [],
            "audit_reports": [],
            "debate_records": [],
            "final_resources": [],
            "rejected_resources": [],
            "status": "queued",
            "current_agent": "",
            "errors": [],
            "agent_log": [],
        }

        if self.graph and LANGGRAPH_AVAILABLE:
            config = {"configurable": {"thread_id": task_id}}
            final_state = self.graph.invoke(initial_state, config)
            return final_state
        else:
            return await self._run_sequential(initial_state)

    async def _run_sequential(self, state: dict) -> dict:
        """无 LangGraph 时的顺序执行（用于快速原型验证）"""
        logger.warning("[工作流] 无 LangGraph，使用顺序模式")

        state["status"] = "diagnosing"
        state.update(await self._node_diagnose(state))

        state["status"] = "retrieving"
        state.update(await self._node_retrieve(state))

        state["status"] = "generating"
        state.update(await self._node_generate(state))

        state["status"] = "reviewing"
        state.update(await self._node_review(state))

        if self._should_debate(state) == "debate":
            state["status"] = "debating"
            state.update(await self._node_debate(state))

        state["status"] = "completed"
        state.update(await self._node_finalize(state))
        return state


# 全局单例
workflow_engine = AgentWorkflow()

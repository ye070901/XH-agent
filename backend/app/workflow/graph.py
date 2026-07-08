"""LangGraph工作流 — 多Agent协同决策完整闭环"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

import uuid
from typing import TypedDict, Annotated, Optional
from loguru import logger

# LangGraph imports (fail gracefully if not installed)
try:
    from langgraph.graph import StateGraph, END
    from langgraph.graph.message import add_messages
    from langgraph.checkpoint.memory import MemorySaver
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    logger.warning("[工作流] LangGraph未安装，使用简化模式")


class WorkflowState(TypedDict):
    """LangGraph全局状态"""
    # 输入
    task_id: str
    learner_data: dict
    resource_types: list[str]

    # 诊断阶段
    diagnosis_completed: bool
    diagnosis_result: dict

    # 检索阶段
    retrieved_chunks: list[dict]

    # 生成阶段
    generated_resources: list[dict]

    # 审核阶段
    audit_reports: list[dict]

    # 辩论阶段
    debate_records: list[dict]

    # 最终输出
    final_resources: list[dict]
    rejected_resources: list[dict]
    learning_path: Optional[dict]

    # 状态
    status: str  # diagnosing/generating/reviewing/debating/completed/failed
    current_agent: str
    errors: list[str]

    # 消息历史
    messages: Annotated[list, add_messages]


class AgentWorkflow:
    """多Agent协同工作流引擎"""

    def __init__(self):
        self.graph = None
        if LANGGRAPH_AVAILABLE:
            self._build_graph()

    def _build_graph(self):
        """构建LangGraph状态图"""
        workflow = StateGraph(WorkflowState)

        # 添加节点
        workflow.add_node("diagnose", self._node_diagnose)
        workflow.add_node("retrieve", self._node_retrieve)
        workflow.add_node("generate", self._node_generate)
        workflow.add_node("review", self._node_review)
        workflow.add_node("debate", self._node_debate)
        workflow.add_node("plan", self._node_plan)
        workflow.add_node("finalize", self._node_finalize)

        # 设置边
        workflow.set_entry_point("diagnose")
        workflow.add_edge("diagnose", "retrieve")
        workflow.add_edge("retrieve", "generate")
        workflow.add_edge("generate", "review")

        # 条件分支：审核通过 → 规划路径；不通过 → 辩论
        workflow.add_conditional_edges(
            "review",
            self._should_debate,
            {
                "debate": "debate",
                "plan": "plan",
            },
        )
        workflow.add_conditional_edges(
            "debate",
            self._after_debate,
            {
                "plan": "plan",
                "reject": "finalize",
            },
        )
        workflow.add_edge("plan", "finalize")
        workflow.add_edge("finalize", END)

        # 编译
        memory = MemorySaver()
        self.graph = workflow.compile(checkpointer=memory)
        logger.info("[工作流] LangGraph状态图构建完成")

    # ── 节点实现 ──

    def _node_diagnose(self, state: WorkflowState) -> dict:
        """学情诊断节点"""
        logger.info(f"[工作流] 开始学情诊断: {state['task_id']}")
        from ..agents.diagnosis import DiagnosisAgent
        agent = DiagnosisAgent()
        result = agent.process(state)
        return {
            **result,
            "status": "diagnosing",
            "current_agent": "diagnosis",
        }

    def _node_retrieve(self, state: WorkflowState) -> dict:
        """知识检索节点"""
        import asyncio
        logger.info(f"[工作流] 开始知识检索: {state['task_id']}")
        diagnosis = state.get("diagnosis_result", {})
        skill_gaps = diagnosis.get("skill_gaps", [])
        query = " ".join([g.get("topic", "") for g in skill_gaps[:3]])

        from ..knowledge.rag import knowledge_base
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import nest_asyncio
                nest_asyncio.apply()
            chunks = asyncio.run(knowledge_base.search(query, top_k=10))
        except Exception:
            chunks = asyncio.run(knowledge_base.search(query, top_k=10))

        return {
            "retrieved_chunks": chunks,
            "status": "retrieving",
            "current_agent": "retriever",
        }

    def _node_generate(self, state: WorkflowState) -> dict:
        """资源生成节点"""
        logger.info(f"[工作流] 开始资源生成: {state['task_id']}")
        from ..agents.generator import GeneratorAgent
        agent = GeneratorAgent()
        resources = []
        for rtype in state.get("resource_types", ["lecture", "guide", "quiz"]):
            s = {**state, "resource_type": rtype}
            result = agent.process(s)
            if result.get("generated_resource"):
                result["generated_resource"]["resource_type"] = rtype
                result["generated_resource"]["resource_id"] = str(uuid.uuid4())
                resources.append(result["generated_resource"])
        return {
            "generated_resources": resources,
            "status": "generating",
            "current_agent": "generator",
        }

    def _node_review(self, state: WorkflowState) -> dict:
        """审核节点"""
        logger.info(f"[工作流] 开始内容审核: {state['task_id']}")
        from ..agents.reviewer import ReviewerAgent
        agent = ReviewerAgent()
        audit_reports = []
        for resource in state.get("generated_resources", []):
            s = {**state, "generated_resource": resource}
            result = agent.process(s)
            if result.get("audit_report"):
                result["audit_report"]["resource_id"] = resource.get("resource_id")
                audit_reports.append(result["audit_report"])
        return {
            "audit_reports": audit_reports,
            "status": "reviewing",
            "current_agent": "reviewer",
        }

    def _node_debate(self, state: WorkflowState) -> dict:
        """辩论节点"""
        logger.info(f"[工作流] 进入辩论: {state['task_id']}")
        from ..debate.engine import DebateEngine
        engine = DebateEngine()
        debate_records = state.get("debate_records", [])
        final_resources = list(state.get("final_resources", []))
        rejected = list(state.get("rejected_resources", []))

        for i, resource in enumerate(state.get("generated_resources", [])):
            audit = state["audit_reports"][i] if i < len(state["audit_reports"]) else {}
            if audit.get("verdict") != "approved":
                result = engine.run_debate(
                    resource,
                    audit,
                    state.get("retrieved_chunks", []),
                )
                debate_records.append(result)
                if result.get("final_verdict") == "approved":
                    final_resources.append(result.get("final_resource", resource))
                else:
                    rejected.append(result.get("final_resource", resource))
            else:
                final_resources.append(resource)

        return {
            "debate_records": debate_records,
            "final_resources": final_resources,
            "rejected_resources": rejected,
            "status": "debating",
            "current_agent": "debate",
        }

    def _node_plan(self, state: WorkflowState) -> dict:
        """学习路径规划节点"""
        logger.info(f"[工作流] 开始路径规划: {state['task_id']}")
        from ..agents.planner import PlannerAgent
        agent = PlannerAgent()
        result = agent.process(state)
        return {
            **result,
            "status": "planning",
            "current_agent": "planner",
        }

    def _node_finalize(self, state: WorkflowState) -> dict:
        """最终化节点"""
        logger.info(f"[工作流] 流程完成: {state['task_id']}")
        return {
            "status": "completed",
            "current_agent": "system",
        }

    # ── 条件路由 ──

    def _should_debate(self, state: WorkflowState) -> str:
        """判断是否需要辩论"""
        for audit in state.get("audit_reports", []):
            if audit.get("verdict") != "approved":
                return "debate"
        return "plan"

    def _after_debate(self, state: WorkflowState) -> str:
        """辩论后的路由"""
        if state.get("final_resources"):
            return "plan"
        return "reject"

    # ── 公开接口 ──

    def run(self, task_id: str, learner_data: dict, resource_types: list[str] = None) -> dict:
        """运行完整工作流"""
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
            "learning_path": None,
            "status": "queued",
            "current_agent": "",
            "errors": [],
            "messages": [],
        }

        if self.graph and LANGGRAPH_AVAILABLE:
            config = {"configurable": {"thread_id": task_id}}
            final_state = self.graph.invoke(initial_state, config)
            return final_state
        else:
            # 无LangGraph时的简化顺序执行
            logger.warning("[工作流] 无LangGraph，使用简化顺序模式")
            return self._run_sequential(initial_state)

    def _run_sequential(self, state: dict) -> dict:
        """无LangGraph时的顺序执行"""
        state["status"] = "diagnosing"
        state.update(self._node_diagnose(state))

        state["status"] = "retrieving"
        state.update(self._node_retrieve(state))

        state["status"] = "generating"
        state.update(self._node_generate(state))

        state["status"] = "reviewing"
        state.update(self._node_review(state))

        should_debate = self._should_debate(state)
        if should_debate == "debate":
            state["status"] = "debating"
            state.update(self._node_debate(state))

        if self._after_debate(state) == "plan":
            state["status"] = "planning"
            state.update(self._node_plan(state))

        state["status"] = "completed"
        state.update(self._node_finalize(state))
        return state


# 全局单例
workflow_engine = AgentWorkflow()

"""MVP 工作流 — 2 Agent 顺序执行: 诊断 → 生成（LLM自身知识）。Agent 3 后面再加。"""
import uuid

from loguru import logger

from ..agents.diagnosis import DiagnosisAgent
from ..agents.generation import GenerationAgent


class AgentWorkflow:
    """2 Agent 工作流引擎 — MVP 版本（不需要知识库）"""

    def __init__(self):
        self._diagnosis = None
        self._generation = None

    @property
    def diagnosis(self):
        if self._diagnosis is None:
            self._diagnosis = DiagnosisAgent()
        return self._diagnosis

    @property
    def generation(self):
        if self._generation is None:
            self._generation = GenerationAgent()
        return self._generation

    async def run(
        self,
        task_id: str = "",
        learner_data: dict = None,
        resource_types: list[str] = None,
    ) -> dict:
        """MVP: diagnose → generate，两步完成"""
        if task_id == "":
            task_id = str(uuid.uuid4())
        if learner_data is None:
            learner_data = {}
        if resource_types is None:
            resource_types = ["lecture", "guide", "quiz"]

        state = {
            "task_id": task_id,
            "learner_data": learner_data,
            "resource_types": resource_types,
            "retrieved_chunks": [],  # MVP 不使用外部知识库，LLM 自身知识生成
            "status": "starting",
            "agent_log": [],
        }

        # Step 1: 学情诊断
        logger.info(f"[MVP] Step 1/2: 学情诊断")
        state["status"] = "diagnosing"
        result = await self.diagnosis.process(state)
        state.update(result)
        state["agent_log"].append({"agent": "diagnosis", "status": "done"})

        # Step 2: 知识生成（LLM 自身知识，不检索外部知识库）
        logger.info(f"[MVP] Step 2/2: 知识生成（LLM自身知识）")
        state["status"] = "generating"
        result = await self.generation.process(state)
        state.update(result)
        state["agent_log"].append({
            "agent": "generation",
            "status": "done",
            "count": len(result.get("generated_resources", [])),
        })

        state["status"] = "completed"
        logger.info(f"[MVP] 完成 — 生成了 {len(state.get('generated_resources', []))} 个资源")
        return state


# 全局单例
workflow_engine = AgentWorkflow()

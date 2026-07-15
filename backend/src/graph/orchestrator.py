"""MVP 工作流 — 2 Agent 顺序执行: 诊断 → 检索 → 生成。Agent 3 后面再加。"""
import uuid

from loguru import logger

from ..agents.diagnosis import DiagnosisAgent
from ..agents.generation import GenerationAgent
from ..knowledge.store import knowledge_base


class AgentWorkflow:
    """2 Agent 工作流引擎 — MVP 版本"""

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
        """运行 MVP 工作流: 诊断 → 检索 → 生成"""
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
            "status": "starting",
            "agent_log": [],
        }

        # Step 1: 学情诊断
        logger.info(f"[MVP] Step 1/3: 学情诊断")
        state["status"] = "diagnosing"
        result = await self.diagnosis.process(state)
        state.update(result)
        state["agent_log"].append({"agent": "diagnosis", "status": "done"})

        # Step 2: 知识检索
        logger.info(f"[MVP] Step 2/3: 知识检索")
        state["status"] = "retrieving"
        diagnosis = state.get("diagnosis_result", {})
        skill_gaps = diagnosis.get("skill_gaps", [])
        query = " ".join([g.get("topic", "") for g in skill_gaps[:3]])
        try:
            chunks = await knowledge_base.search(query, top_k=10)
        except Exception as e:
            logger.warning(f"[MVP] 检索失败，降级为空知识库: {e}")
            chunks = []
        state["retrieved_chunks"] = chunks
        state["agent_log"].append({"agent": "retriever", "status": "done", "chunks": len(chunks)})

        # Step 3: 资源生成
        logger.info(f"[MVP] Step 3/3: 资源生成")
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

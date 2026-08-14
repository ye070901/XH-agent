"""工作流引擎 — 4 Agent 顺序执行: 诊断 → 生成 → 审核 → 修正。

完整链路:
  Agent 1 学情诊断 → Agent 2 知识生成 → Agent 3 内容审核 → Agent 4 保真修正

Agent 3 只审不修，Agent 4 根据审核结果修正内容。

Agent 入口文件:
  Agent 1: backend/src/agents/diagnosis.py   → DiagnosisAgent
  Agent 2: backend/src/agents/generation_v2.py → GenerationAgent
  Agent 3: backend/src/agents/audit.py        → AuditAgent
  Agent 4: backend/src/agents/correction.py   → CorrectionAgent（主实现）
           backend/src/agents/agent4.py       → CorrectionAgent（标准入口，re-export）
"""

from __future__ import annotations

import uuid

from loguru import logger

from ..agents.agent4 import CorrectionAgent  # Agent 4 标准入口（→ correction.py）
from ..agents.audit import AuditAgent
from ..agents.diagnosis import DiagnosisAgent
from ..agents.generation_v2 import GenerationAgent as GenerationAgent
from ..knowledge import knowledge_base


class AgentWorkflow:
    """4 Agent 工作流引擎：诊断 → 生成 → 审核 → 修正"""

    def __init__(self):
        self._diagnosis = None
        self._generation = None
        self._audit = None
        self._correction = None

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

    @property
    def audit(self):
        if self._audit is None:
            self._audit = AuditAgent()
        return self._audit

    @property
    def correction(self):
        if self._correction is None:
            self._correction = CorrectionAgent()
        return self._correction

    async def run(
        self,
        task_id: str = "",
        learner_data: dict = None,
        resource_types: list[str] = None,
    ) -> dict:
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

        # Step 1: Agent 1 学情诊断
        logger.info("[工作流] Step 1/4: 学情诊断")
        state["status"] = "diagnosing"
        result = await self.diagnosis.run(state)
        state.update(result)
        state["agent_log"].append({"agent": "diagnosis", "status": result.get("status", "done")})

        # 诊断失败时终止工作流
        if result.get("status") == "error":
            state["status"] = "error"
            return state

        # Step 1.5: 知识库检索（RAG 约束生成）
        logger.info("[工作流] Step 1.5/4: 知识库检索")
        state["status"] = "retrieving"
        retrieved_chunks = await self._retrieve_knowledge(
            learner_data, state.get("diagnosis_result", {})
        )
        state["retrieved_chunks"] = retrieved_chunks
        state["agent_log"].append(
            {"agent": "retrieval", "status": "done", "count": len(retrieved_chunks)}
        )

        # Step 2: Agent 2 知识生成
        logger.info("[工作流] Step 2/4: 知识生成")
        state["status"] = "generating"
        result = await self.generation.run(state)
        state.update(result)
        state["agent_log"].append(
            {
                "agent": "generation",
                "status": result.get("status", "done"),
                "count": len(result.get("generated_resources", [])),
            }
        )

        if result.get("status") == "error":
            state["status"] = "error"
            return state

        # Step 3: Agent 3 内容审核（只审不修）
        logger.info("[工作流] Step 3/4: 内容审核")
        state["status"] = "auditing"
        result = await self.audit.run(state)
        state.update(result)
        state["agent_log"].append({"agent": "audit", "status": result.get("status", "done")})

        if result.get("status") == "error":
            state["status"] = "error"
            return state

        # Step 4: Agent 4 保真修正（根据审核结果修正内容）
        logger.info("[工作流] Step 4/4: 保真修正")
        state["status"] = "correcting"
        result = await self.correction.run(state)
        state.update(result)
        state["agent_log"].append(
            {
                "agent": "correction",
                "status": result.get("status", "done"),
                "stats": result.get("correction_stats", {}),
            }
        )

        if result.get("status") == "error":
            state["status"] = "error"
            return state

        state["status"] = "completed"
        return state

    async def _retrieve_knowledge(self, learner_data: dict, diagnosis: dict) -> list[dict]:
        """知识库检索：用学习目标 + 关键盲区构造查询，检索 data/raw 语料。

        检索失败或知识库为空时返回空列表（优雅降级），生成/修正 Agent 会
        在 retrieved_chunks 为空时回退到 LLM 自身知识生成。
        """
        query_parts = [learner_data.get("learning_goal", "")]
        gaps = diagnosis.get("skill_gaps", [])
        for gap in gaps[:3]:
            topic = gap.get("topic", "")
            if topic:
                query_parts.append(topic)
        query = " ".join(p for p in query_parts if p).strip()

        if not query:
            logger.info("[工作流] 知识库检索：无查询词，跳过")
            return []

        try:
            chunks = await knowledge_base.search(query=query, top_k=6)
            logger.info(f"[工作流] 知识库检索：命中 {len(chunks)} 条")
            return chunks
        except Exception as e:
            logger.warning(f"[工作流] 知识库检索失败（降级为无 KB 约束）: {e}")
            return []


workflow_engine = AgentWorkflow()

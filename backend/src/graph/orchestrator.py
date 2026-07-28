"""工作流引擎 — 3 Agent 顺序执行: 诊断 → 生成 → 审核。Agent 3 只审不修。"""

from __future__ import annotations

import uuid

from loguru import logger

from ..agents.audit import AuditAgent
from ..agents.diagnosis import DiagnosisAgent
from ..agents.generation_v2 import GenerationAgent as GenerationAgent


class AgentWorkflow:
    """3 Agent 工作流引擎"""

    def __init__(self):
        self._diagnosis = None
        self._generation = None
        self._audit = None

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
        logger.info("[工作流] Step 1/3: 学情诊断")
        state["status"] = "diagnosing"
        result = await self.diagnosis.run(state)
        state.update(result)
        state["agent_log"].append({"agent": "diagnosis", "status": result.get("status", "done")})

        # 诊断失败时终止工作流
        if result.get("status") == "error":
            state["status"] = "error"
            return state

        # Step 2: Agent 2 知识生成
        logger.info("[工作流] Step 2/3: 知识生成")
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
        logger.info("[工作流] Step 3/3: 内容审核")
        state["status"] = "auditing"
        result = await self.audit.run(state)
        state.update(result)
        state["agent_log"].append({"agent": "audit", "status": result.get("status", "done")})

        if result.get("status") == "error":
            state["status"] = "error"
            return state

        state["status"] = "completed"
        return state


workflow_engine = AgentWorkflow()

"""工作流引擎 — 4 Agent 顺序执行: 诊断 → 生成 → 审核 → 修正。

角色定位（防误判）:
  AgentWorkflow 不是任何 HTTP 入口——真正的对外交付链路是 PipelineScheduler
  （backend/src/scheduler/pipeline.py），本模块的 debate 引擎被
  PipelineScheduler._run_debate 懒加载消费；regenerate() 供动态反馈路径
  （exams 反馈）复用。

完整链路:
  Agent 1 学情诊断 → Agent 2 知识生成 → Agent 3 内容审核 → Agent 4 保真修正

Agent 3 只审不修，Agent 4 根据审核结果修正内容。

Phase 3（Arch-L 接入）:
  - 博弈引擎接入流水线: Agent3 三态断言 → 争议断言进 debate 引擎 → 裁决结果回写资源
    （Step 3.5 博弈裁决，产出 state["debate_result"]，由 Agent 4 消费落地）
  - 追问流程接入: regenerate() 提供「反馈 → 资源重生成」调度入口（D8 / §4.5）

Agent 入口文件:
  Agent 1: backend/src/agents/diagnosis.py   → DiagnosisAgent
  Agent 2: backend/src/agents/generation_v2.py → GenerationAgent
  Agent 3: backend/src/agents/audit.py        → AuditAgent
  Agent 4: backend/src/agents/correction.py   → CorrectionAgent（主实现）
           backend/src/agents/agent4.py       → CorrectionAgent（标准入口，re-export）
"""

from __future__ import annotations

import re
import uuid

from loguru import logger

from ..agents.agent4 import CorrectionAgent  # Agent 4 标准入口（→ correction.py）
from ..agents.audit import AuditAgent
from ..agents.diagnosis import DiagnosisAgent
from ..agents.generation_v2 import GenerationAgent as GenerationAgent
from ..config import settings
from ..debate.engine import debate_engine
from ..event_broadcast import EventType, event_bus
from ..knowledge import knowledge_base
from ..knowledge.demo_fallback import DEMO_FALLBACK_CHUNKS

# ── 状态文案动态化：枚举值 → 中文标签（避免文案写死） ──
_DIFFICULTY_LABELS = {
    "beginner": "初级",
    "intermediate": "中级",
    "advanced": "高级",
}
_RESOURCE_TYPE_LABELS = {
    "lecture": "讲义",
    "guide": "实操指南",
    "quiz": "测试题",
    "pitfall_guide": "避坑指南",
    "project": "项目实战",
}


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

    @property
    def debate(self):
        """博弈引擎（Opt-2）— 编排器（Arch-L）通过此属性接入三态裁决。

        返回 debate/engine.py 的全局单例，供 Scheduler 的 _run_debate 复用；
        本工作流在 _generate_and_refine 中直接调用其 adjudicate()。
        """
        return debate_engine

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
        # 双模式隔离：audit_mode 由请求体透传至 learner_data，提升到 state 顶层供 audit 消费
        audit_mode = str((learner_data or {}).get("audit_mode") or "demo").strip().lower()
        state["audit_mode"] = audit_mode if audit_mode in ("demo", "eval") else "demo"
        await self._broadcast_status(
            task_id, "workflow", EventType.AGENT_START, "工作流已启动，正在准备 Agent 协作。"
        )

        # Step 1: Agent 1 学情诊断
        logger.info("[工作流] Step 1/4: 学情诊断")
        state["status"] = "diagnosing"
        await self._broadcast_status(
            task_id, "diagnosis", EventType.AGENT_START, "正在分析学习者画像与学习目标。"
        )
        result = await self.diagnosis.run(state)
        state.update(result)
        state["agent_log"].append({"agent": "diagnosis", "status": result.get("status", "done")})
        diag = state.get("diagnosis_result") or {}
        gap_count = len(diag.get("skill_gaps") or [])
        difficulty = str(diag.get("recommended_difficulty") or "").lower()
        difficulty_label = _DIFFICULTY_LABELS.get(difficulty, difficulty or "未知")
        await self._broadcast_status(
            task_id,
            "diagnosis",
            EventType.AGENT_ERROR if result.get("status") == "error" else EventType.AGENT_DONE,
            "学情诊断失败。"
            if result.get("status") == "error"
            else f"学情画像已完成：识别出 {gap_count} 个知识缺口，难度等级 {difficulty_label}",
            {"count": gap_count},
        )

        # 诊断失败时终止工作流
        if result.get("status") == "error":
            state["status"] = "error"
            return state

        # Step 1.5: 知识库检索（RAG 约束生成）
        logger.info("[工作流] Step 1.5/4: 知识库检索")
        state["status"] = "retrieving"
        await self._broadcast_status(
            task_id, "retrieval", EventType.AGENT_START, "正在从知识库检索相关依据。"
        )
        retrieved_chunks = await self._retrieve_knowledge(
            learner_data, state.get("diagnosis_result", {}), resource_types
        )
        state["retrieved_chunks"] = retrieved_chunks
        state["agent_log"].append(
            {"agent": "retrieval", "status": "done", "count": len(retrieved_chunks)}
        )
        hit_count = len(retrieved_chunks)
        doc_count = len({c.get("doc_id") for c in retrieved_chunks if c.get("doc_id")})
        await self._broadcast_status(
            task_id,
            "retrieval",
            EventType.AGENT_DONE,
            f"知识库检索完成，命中 {hit_count} 个片段（{doc_count} 篇文档）",
            {"count": hit_count, "doc_count": doc_count},
        )

        # Step 2~4: 生成 → 审核 → 博弈裁决 → 修正
        await self._generate_and_refine(state)
        if state.get("status") == "error":
            return state

        state["status"] = "completed"
        await self._broadcast_status(
            task_id, "workflow", EventType.WORKFLOW_COMPLETE, "全部 Agent 已完成协作。"
        )
        return state

    async def regenerate(self, state: dict, feedback: dict = None) -> dict:
        """反馈 → 资源重生成 调度入口（追问流程接入 / 后置动态反馈 D8）。

        复用既有 diagnosis_result / retrieved_chunks，仅重跑 生成→审核→博弈→修正，
        不重跑学情诊断（收窄后的目标 / 回写后的画像由上游写回 diagnosis_result）。

        feedback 可选字段:
          - action: "simplify"（答错 → 降维解释）/ "advance"（答对 → 进阶挑战）
          - hint:   目标收窄后的细化方向，注入生成上下文
        """
        feedback = feedback or {}
        state.setdefault("agent_log", [])
        task_id = state.get("task_id", "")

        # ── 动态决策：答错→降维、答对→进阶（D8），在诊断结果副本上调整 ──
        diagnosis = dict(state.get("diagnosis_result") or {})
        action = str(feedback.get("action", "") or "").strip().lower()
        if action == "simplify":
            diagnosis["recommended_difficulty"] = "beginner"
        elif action == "advance":
            diagnosis["recommended_difficulty"] = "advanced"
        hint = str(feedback.get("hint", "") or "").strip()
        if hint:
            summary = str(diagnosis.get("summary", "") or "").strip()
            diagnosis["summary"] = f"{summary}（细化方向：{hint}）" if summary else hint
        state["diagnosis_result"] = diagnosis

        state["status"] = "regenerating"
        await self._broadcast_status(
            task_id, "workflow", EventType.AGENT_START, "收到反馈，正在重新生成学习资源。"
        )
        await self._generate_and_refine(state)
        if state.get("status") == "error":
            return state

        state["status"] = "completed"
        await self._broadcast_status(
            task_id, "workflow", EventType.WORKFLOW_COMPLETE, "资源重生成完成。"
        )
        return state

    async def _generate_and_refine(self, state: dict) -> None:
        """生成 → 审核 → 博弈裁决 → 修正 四步链（run 与 regenerate 共用）。"""
        task_id = state.get("task_id", "")

        # Step 2: Agent 2 知识生成
        logger.info("[工作流] Step 2/4: 知识生成")
        state["status"] = "generating"
        await self._broadcast_status(
            task_id, "generation", EventType.AGENT_START, "正在依据诊断与知识库内容生成学习资源。"
        )
        result = await self.generation.run(state)
        state.update(result)
        state["agent_log"].append(
            {
                "agent": "generation",
                "status": result.get("status", "done"),
                "count": len(result.get("generated_resources", [])),
            }
        )
        generated = result.get("generated_resources") or []
        gen_count = len(generated)
        gen_type_order: list[str] = []
        for res in generated:
            rt = str(res.get("resource_type") or "")
            if rt and rt not in gen_type_order:
                gen_type_order.append(rt)
        type_names = "、".join(_RESOURCE_TYPE_LABELS.get(t, t) for t in gen_type_order)
        gen_msg = (
            f"已生成 {len(gen_type_order)} 种资源：{type_names}"
            if type_names
            else f"已生成 {gen_count} 个资源"
        )
        await self._broadcast_status(
            task_id,
            "generation",
            EventType.AGENT_ERROR if result.get("status") == "error" else EventType.AGENT_DONE,
            "知识生成失败。" if result.get("status") == "error" else gen_msg,
            {"count": gen_count},
        )

        if result.get("status") == "error":
            state["status"] = "error"
            return

        # Step 3: Agent 3 内容审核（只审不修）
        logger.info("[工作流] Step 3/4: 内容审核")
        state["status"] = "auditing"
        await self._broadcast_status(
            task_id, "audit", EventType.AGENT_START, "正在审核资源的依据、难度与表达质量。"
        )
        result = await self.audit.run(state)
        state.update(result)
        state["agent_log"].append({"agent": "audit", "status": result.get("status", "done")})
        audit_reports = result.get("audit_result") or []
        passed = sum(1 for r in audit_reports if r.get("verdict") == "approved")
        need_rev = sum(1 for r in audit_reports if r.get("verdict") == "needs_revision")
        await self._broadcast_status(
            task_id,
            "audit",
            EventType.AGENT_ERROR if result.get("status") == "error" else EventType.AGENT_DONE,
            "内容审核失败。"
            if result.get("status") == "error"
            else f"内容审核完成：{passed} 项通过，{need_rev} 项需修正",
            {"count": len(audit_reports), "passed": passed, "needs_revision": need_rev},
        )

        if result.get("status") == "error":
            state["status"] = "error"
            return

        # Step 3.5: 博弈引擎裁决（Agent3 三态断言 → 争议断言进 debate → 裁决结果回写）
        logger.info("[工作流] Step 3.5/4: 博弈引擎裁决")
        state["status"] = "debating"
        await self._broadcast_status(
            task_id, "debate", EventType.AGENT_START, "正在进行事实核查与博弈裁决。"
        )
        debate_result = self.debate.adjudicate(
            audit_result=state.get("audit_result", []),
            generated_resources=state.get("generated_resources", []),
        )
        state["debate_result"] = debate_result
        state["agent_log"].append(
            {"agent": "debate", "status": "done", "stats": debate_result.get("stats", {})}
        )
        await self._broadcast_status(task_id, "debate", EventType.AGENT_DONE, "博弈裁决完成。")

        # Step 4: Agent 4 保真修正（消费 audit_result + debate_result 落地裁决）
        logger.info("[工作流] Step 4/4: 保真修正")
        state["status"] = "correcting"
        await self._broadcast_status(
            task_id, "correction", EventType.AGENT_START, "正在根据审核与裁决结果进行保真修正。"
        )
        result = await self.correction.run(state)
        state.update(result)
        state["agent_log"].append(
            {
                "agent": "correction",
                "status": result.get("status", "done"),
                "stats": result.get("correction_stats", {}),
            }
        )
        corr_stats = result.get("correction_stats") or {}
        fixed_count = int(corr_stats.get("total_issues") or 0)
        await self._broadcast_status(
            task_id,
            "correction",
            EventType.AGENT_ERROR if result.get("status") == "error" else EventType.AGENT_DONE,
            "保真修正失败。"
            if result.get("status") == "error"
            else f"保真修正完成：修正 {fixed_count} 处内容",
            {"count": fixed_count},
        )

        if result.get("status") == "error":
            state["status"] = "error"

    @staticmethod
    async def _broadcast_status(
        task_id: str,
        agent: str,
        event_type: EventType,
        message: str,
        extra: dict | None = None,
    ) -> None:
        """推送当前工作流节点状态；广播失败不影响实际任务。"""
        data = {"agent": agent, "message": message, "status": event_type.value}
        if extra:
            data.update(extra)
        try:
            await event_bus.broadcast(task_id, event_type, data)
        except Exception as exc:
            logger.debug(f"[工作流] 状态广播失败（不影响任务）: {exc}")

    @staticmethod
    def _dynamic_top_k(query: str, resource_types: list[str] | None) -> int:
        """按查询词数量 + 资源类型数动态调整检索 top_k，夹在 [MIN, MAX] 区间。

        检索结果最终仍由知识库按 doc_id 去重、并受库内文档数天然封顶，
        故这里只决定「请求多少个 chunk」：查询越复杂 / 资源类型越多，需要越多素材覆盖。
        """
        query_terms = [t for t in re.split(r"[\s,，、;；]+", query) if t]
        n_types = len(resource_types) if resource_types else 3
        top_k = settings.RETRIEVAL_TOP_K_BASE
        top_k += min(max(len(query_terms) - 1, 0), 3)  # 查询词越多 +0~3
        top_k += max(n_types - 1, 0)  # 资源类型越多，素材覆盖越多
        top_k = max(settings.RETRIEVAL_TOP_K_MIN, min(settings.RETRIEVAL_TOP_K_MAX, top_k))
        logger.info(
            f"[工作流] 知识库检索 top_k 动态调整：{top_k} "
            f"（查询词 {len(query_terms)} 个 / 资源类型 {n_types} 种）"
        )
        return top_k

    async def _retrieve_knowledge(
        self, learner_data: dict, diagnosis: dict, resource_types: list[str] | None = None
    ) -> list[dict]:
        """知识库检索：用学习目标 + 关键盲区构造查询，检索 data/raw 语料。

        空知识库时的双分支行为（与生成 Agent 的空 KB 硬拦截配套）：
        - 正式模式（is_demo_mode=False）：检索失败 / 空库 / 无查询词 → 返回空列表，
          生成 Agent 触发 `no_knowledge_base_chunks` 硬拦截，知识库无素材绝不生成。
        - 演示模式（is_demo_mode=True）：上述空库场景 → 注入人工预置兜底知识块，
          生成 Agent 照常基于素材生成，防幻觉护栏不绕过、不凭空生成。
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
            return self._empty_kb_fallback()

        top_k = self._dynamic_top_k(query, resource_types)
        try:
            chunks = await knowledge_base.search(query=query, top_k=top_k)
            logger.info(f"[工作流] 知识库检索：命中 {len(chunks)} 条")
            if chunks:
                return self._append_sibling_chunks(chunks)
            return self._empty_kb_fallback()
        except Exception as e:
            logger.warning(f"[工作流] 知识库检索失败（空 KB 降级）: {e}")
            return self._empty_kb_fallback()

    @staticmethod
    def _append_sibling_chunks(chunks: list[dict]) -> list[dict]:
        """检索去重后补回正文后续段（确定性，不调 LLM）。

        ``knowledge_base.search`` 按 doc_id 去重，每篇文档只保留得分最高的单个
        chunk，通常是 chunk 0（标题/摘要/引言），正文参数与步骤在 chunk 1、2 未被
        召回，导致生成端把正文内容误判为「知识库未覆盖」。这里对每个命中文档补齐
        其前 3 个 chunk，确保正文主体进入检索上下文。
        """
        if not chunks:
            return chunks
        merged: list[dict] = []
        seen: set[tuple[str, int]] = set()
        for c in chunks:
            key = (str(c.get("doc_id") or ""), int(c.get("chunk_index", 0) or 0))
            if not key[0] or key in seen:
                continue
            seen.add(key)
            merged.append(c)
        doc_ids = {key[0] for key in seen if key[0]}
        for doc_id in doc_ids:
            for sibling in knowledge_base.get_document_chunks(doc_id)[:3]:
                key = (
                    str(sibling.get("doc_id") or ""),
                    int(sibling.get("chunk_index", 0) or 0),
                )
                if key not in seen:
                    seen.add(key)
                    merged.append(sibling)
        return merged

    def _empty_kb_fallback(self) -> list[dict]:
        """空知识库降级出口：演示模式注入预置兜底块，正式模式返回空列表。

        返回兜底块的副本，避免调用方就地修改模块级常量。
        """
        if settings.is_demo_mode:
            logger.info("[工作流] 演示模式：知识库为空，注入人工预置演示知识块")
            return list(DEMO_FALLBACK_CHUNKS)
        return []


workflow_engine = AgentWorkflow()

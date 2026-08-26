"""闸门3 v0.1：RAG 召回质量检测（三路裁决 PASS / RETRY / FALLBACK）。

v0.1 采用「双层相似度阈值 + 三路裁决」防误判模型：

判定流程（以每轮召回的最高相似度 max_score 为准）：
  1. 提取 state["retrieved_chunks"] 与每篇 relevance_score
  2. max_score > RECALL_HIGH_CONFIDENCE_SCORE → 高置信放行 high_pass（PASS）
  3. RECALL_LOW_TOLERATE_SCORE < max_score ≤ high → 低置信放行 low_pass（PASS，禁止兜底）
  4. 全部 ≤ low（含空召回）：
     - retry_count < RECALL_MAX_RETRIES(3) → RETRY（轻量 LLM 改写 Query）
     - retry_count >= RECALL_MAX_RETRIES → FALLBACK（离线固定提示 / 在线外部检索摘要）

Query 改写策略：
  - 从原始 Query 中提取核心名词/技术术语
  - 强制保留工业专业名词（SRVO-068 / FANUC / KUKA / 示教器 等），禁止过度泛化
  - LLM 不可用时降级为简单关键词拼接

防误判日志：每轮 query / 相似度分数 / 判定类型写入 state["gate_results"]["recall"]。
"""

from __future__ import annotations

from backend.src.config import settings
from backend.src.quality_gate.base import (
    BaseGate,
    GateResult,
    GateStrategy,
    make_gate_result,
)
from backend.src.schemas import GateVerdict


# 离线模式兜底提示：命中 FALLBACK 时禁止调用外部 LLM，直接返回该标准化字符串
OFFLINE_FALLBACK_MESSAGE = "【离线模式‑知识库暂无该主题素材，无法生成对应学习资料，请更换提问主题或者补充知识库素材】"

# 在线模式兜底：免责声明头部（代码层面硬拼接，禁止 LLM 改写润色）
ONLINE_FALLBACK_DISCLAIMER = "【提示：以下内容来自外部网络检索，不属于项目本地知识库，仅供学习参考，不保证工业实操准确性】"

# 外部检索工具未接入时的确定性占位（非 LLM 生成，杜绝兜底路径幻觉）
EXTERNAL_RETRIEVAL_UNAVAILABLE = "（外部网络检索暂不可用，未获取到相关资料摘要）"


class RecallGate(BaseGate):
    """闸门3：RAG 召回质量检测 — 三路裁决 PASS / RETRY / FALLBACK。

    RETRY 时调用轻量 LLM 改写 Query 并附带 new_query。
    """

    GATE_NAME = "RAG召回质量检测"
    STRATEGY = GateStrategy.HARD_RULE_ONLY  # 判定本身不调 LLM
    REQUIRED_STATE_KEYS = {"retrieved_chunks"}

    def __init__(self, is_offline: bool = False) -> None:
        """离线模式标志：True 时命中 FALLBACK 不调用外部 LLM，返回标准化离线提示。"""
        super().__init__()
        self.is_offline = is_offline

    # Query 改写的 LLM system prompt
    QUERY_REWRITE_SYSTEM_PROMPT = (
        "你是一个搜索引擎查询优化助手。"
        "你的任务是将用户输入的自然语言问题改写为更简洁、关键词密集的检索查询。"
        "输出仅为改写后的查询字符串，不要有任何额外内容。"
        "规则："
        "1. 提取核心技术术语和名词（如产品型号、错误代码、协议名）"
        "2. 去除语气词和冗余描述"
        "3. 保持原意，不要引入新概念"
        "4. 长度控制在 5-20 个词"
        "5. 【强制】保留用户输入的工业专业名词原文（如 SRVO-068、FANUC、KUKA、ABB、"
        "   PTP/LIN/CIRC、示教器、坐标系、急停链路、离线仿真等），禁止过度泛化改写检索词"
        "6. 【禁止】不得把专业名词替换为通用词（如把「SRVO-068」改成「故障代码」、"
        "   把「FANUC」改成「机器人」、把「示教器」改成「操作面板」）"
    )

    # 在线模式 FALLBACK 的兜底生成 system prompt
    # 【已废弃】不再调用 LLM 产出兜底回答，改为外部检索原始摘要（见 _external_retrieve）。
    # 该 LLM 生成 prompt 保留为空注释，避免误用大模型在兜底路径凭空生成内容。

    async def check(self, state: dict) -> GateResult:
        """双层相似度阈值三路裁决核心逻辑。

        1. 提取 retrieved_chunks 与每篇相似度分数
        2. 最高分 > RECALL_HIGH_CONFIDENCE_SCORE → high_pass（高置信放行）
        3. RECALL_LOW_TOLERATE_SCORE < 最高分 ≤ high → low_pass（低置信放行，禁止兜底）
        4. 全部 ≤ low（含空召回）→ retry_count < max → RETRY，否则 FALLBACK
        """
        chunks_raw = state.get("retrieved_chunks", [])
        retry_count: int = state.get("recall_retry_count", 0)
        query = (
            state.get("_pending_query")
            or state.get("rag_query")
            or self._extract_query(state)
        )
        high = settings.RECALL_HIGH_CONFIDENCE_SCORE
        low = settings.RECALL_LOW_TOLERATE_SCORE

        # ── 防御：None / 非 list → 上游异常，直接 FALLBACK ──
        if not isinstance(chunks_raw, list):
            self._record_round(state, query, [], 0.0, "fallback_external")
            return make_gate_result(
                passed=False,
                score=0.0,
                verdict=GateVerdict.FALLBACK.value,
                violations=[
                    f"retrieved_chunks 类型异常（{type(chunks_raw).__name__}），"
                    "上游 RAG 检索可能发生错误"
                ],
                gate_name=self.GATE_NAME,
                total_chunks=0,
                recall_type="fallback_external",
                max_similarity=0.0,
            )

        chunk_count = len(chunks_raw)
        scores = [self._chunk_score(c) for c in chunks_raw]
        max_score = max(scores) if scores else 0.0

        # ── ① 高置信放行：最高分 > high ──
        if max_score > high:
            self._record_round(state, query, scores, max_score, "high_pass")
            return make_gate_result(
                passed=True,
                score=max_score,
                verdict=GateVerdict.PASS.value,
                gate_name=self.GATE_NAME,
                total_chunks=chunk_count,
                recall_type="high_pass",
                max_similarity=max_score,
            )

        # ── ② 低置信放行：low < 最高分 ≤ high（禁止触发 FALLBACK 兜底）──
        if max_score > low:
            state["_low_confidence"] = True
            self._record_round(state, query, scores, max_score, "low_pass")
            return make_gate_result(
                passed=True,
                score=max_score,
                verdict=GateVerdict.PASS.value,
                gate_name=self.GATE_NAME,
                total_chunks=chunk_count,
                low_confidence=True,
                recall_type="low_pass",
                max_similarity=max_score,
            )

        # ── ③ 全部 ≤ low（含空召回）→ 重试 / 兜底 ──
        if retry_count < settings.RECALL_MAX_RETRIES:
            # RETRY：改写 Query
            original_query = self._extract_query(state)
            new_query = await self._rewrite_query(original_query)

            self._record_round(state, query, scores, max_score, "retry")
            return make_gate_result(
                passed=False,
                score=0.0,
                verdict=GateVerdict.RETRY.value,
                violations=[
                    f"召回最高相似度 {max_score:.2f} ≤ {low}"
                    f"（第 {retry_count + 1}/{settings.RECALL_MAX_RETRIES} 次）"
                ],
                gate_name=self.GATE_NAME,
                retry_hint=f"已改写 Query: '{new_query}'，请用新 Query 重新检索",
                total_chunks=chunk_count,
                retry_count=retry_count + 1,
                new_query=new_query,
                original_query=original_query,
                recall_type="retry",
                max_similarity=max_score,
            )

        # ── FALLBACK：重试已达上限 ──
        if self.is_offline:
            # 离线模式：禁止调用外部 LLM，跳过联网兜底生成，直接返回标准化离线提示
            self._log("【离线模式触发兜底，禁止调用外部API】")
            self._record_round(state, query, scores, max_score, "fallback_offline")
            return make_gate_result(
                passed=False,
                score=0.0,
                verdict=GateVerdict.FALLBACK.value,
                violations=[OFFLINE_FALLBACK_MESSAGE],
                gate_name=self.GATE_NAME,
                total_chunks=chunk_count,
                retry_count=retry_count,
                fallback_data={"offline_message": OFFLINE_FALLBACK_MESSAGE},
                recall_type="fallback_offline",
                max_similarity=max_score,
            )

        # 在线模式：调用外部检索工具拿到原始摘要，仅做简单拼接整理（禁止 LLM 改写润色）
        original_query = self._extract_query(state)
        raw_summary, sources = await self._external_retrieve(original_query)

        self._record_round(state, query, scores, max_score, "fallback_external")
        return make_gate_result(
            passed=False,
            score=0.0,
            verdict=GateVerdict.FALLBACK.value,
            violations=[f"连续 {settings.RECALL_MAX_RETRIES} 次召回为 0，知识库暂无相关数据"],
            gate_name=self.GATE_NAME,
            total_chunks=chunk_count,
            retry_count=retry_count,
            fallback_data={
                "online_fallback_raw": raw_summary,
                "sources": sources,
            },
            recall_type="fallback_external",
            max_similarity=max_score,
        )

    # ═══════════════════════════════════════════════════════════
    # 防误判辅助：相似度提取 + 每轮检索日志
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _chunk_score(chunk: dict) -> float:
        """安全提取 chunk 相似度分数，缺失/非法时返回 0.0。"""
        try:
            return float(chunk.get("relevance_score", 0.0))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _record_round(
        state: dict,
        query: str,
        scores: list[float],
        max_score: float,
        type_: str,
    ) -> None:
        """将本轮检索记录追加到 state["gate_results"]["recall"]["rounds"]（防误判日志）。

        记录每一轮 query、chunk 相似度分数、最高分、判定类型；出现终态
        （high_pass / low_pass / fallback_external / fallback_offline）时更新 final_type。
        """
        state.setdefault("gate_results", {})
        recall = state["gate_results"].setdefault("recall", {"rounds": []})
        rounds = recall.setdefault("rounds", [])
        rounds.append(
            {
                "round": len(rounds) + 1,
                "query": query,
                "scores": scores,
                "max_score": max_score,
                "type": type_,
            }
        )
        if type_ in ("high_pass", "low_pass", "fallback_external", "fallback_offline"):
            recall["final_type"] = type_

    # ═══════════════════════════════════════════════════════════
    # Query 改写
    # ═══════════════════════════════════════════════════════════

    async def _rewrite_query(self, original_query: str) -> str:
        """调用轻量 LLM 改写检索 Query。

        LLM 不可用时降级为简单关键词提取（取最长的 3-5 个词拼接）。
        """
        if not original_query.strip():
            return "工业机器人 调试"

        try:
            from backend.src.llm.client import llm

            model = (
                settings.RECALL_QUERY_REWRITE_MODEL or settings.GATE_LLM_MODEL or settings.LLM_MODEL
            )

            rewritten = await llm.call(
                system_prompt=self.QUERY_REWRITE_SYSTEM_PROMPT,
                user_message=f"原始问题：{original_query}",
                model=model,
                temperature=0.2,
            )

            if rewritten and len(rewritten.strip()) >= 3:
                self._log(f"Query 改写: '{original_query[:50]}...' → '{rewritten[:80]}'")
                return rewritten.strip()

        except Exception as exc:
            self._log(f"LLM Query 改写失败 ({exc})，降级为关键词提取")

        # 降级：关键词提取
        return self._keyword_extract_fallback(original_query)

    @staticmethod
    def _keyword_extract_fallback(query: str) -> str:
        """LLM 不可用时的关键词提取降级策略。

        提取最长的 3-5 个词作为检索 Query。
        """
        import re

        # 去掉标点，按空格/标点分词
        tokens = re.split(r"[，,。\.！!？?\s]+", query)
        # 过滤过短词（< 2 字符），按长度降序取 top 5
        meaningful = sorted(
            [t for t in tokens if len(t) >= 2],
            key=len,
            reverse=True,
        )[:5]
        if not meaningful:
            return "工业机器人 故障排查"
        return " ".join(meaningful)

    # ═══════════════════════════════════════════════════════════
    # 在线模式兜底：外部检索原始摘要（禁止 LLM 改写润色）
    # ═══════════════════════════════════════════════════════════

    async def _external_retrieve(self, query: str) -> tuple[str, list[str]]:
        """调用外部检索工具，拿到外部资料摘要，仅做简单拼接整理。

        严禁调用 LLM 改写/润色/生成内容。外部检索工具未接入或检索失败时，
        返回确定性空摘要（非 LLM 生成），杜绝兜底路径凭空生成幻觉。

        Returns:
            (摘要文本, 来源标签列表[str])
        """
        sources: list[dict] = []
        try:
            # 可选：真实外部检索工具（如搜索引擎 / 文档抓取）。未接入时 ImportError 降级。
            from backend.src.llm.external_search import external_search  # noqa: F401

            if external_search is not None:
                sources = (await external_search(query)) or []
        except Exception as exc:  # ImportError / 工具未接入 / 网络失败
            self._log(f"外部检索工具不可用 ({exc})，返回空摘要")

        if not sources:
            return EXTERNAL_RETRIEVAL_UNAVAILABLE, []

        parts: list[str] = []
        labels: list[str] = []
        for i, s in enumerate(sources, 1):
            if not isinstance(s, dict):
                continue
            title = str(s.get("title") or "未知来源")
            snippet = str(s.get("snippet") or s.get("content") or "")
            url = str(s.get("url") or "")
            parts.append(f"[{i}] {title}\n{snippet}")
            labels.append(title + (f"（{url}）" if url else ""))
        return "\n\n".join(parts), labels

    # ═══════════════════════════════════════════════════════════
    # 私有：提取原始 Query
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _extract_query(state: dict) -> str:
        """从 state 中提取用户原始 Query。

        优先级：learner_data.learning_goal → diagnosis_result.summary → 兜底。
        """
        learner: dict = state.get("learner_data", {})
        goal = learner.get("learning_goal", "")
        if goal:
            return str(goal)

        diag: dict = state.get("diagnosis_result", {})
        summary = diag.get("summary", "")
        if summary:
            return str(summary)

        return "未指定学习目标"

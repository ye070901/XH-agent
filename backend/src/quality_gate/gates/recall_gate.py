"""闸门3 v0.1：RAG 召回质量检测（三路裁决 PASS / RETRY / FALLBACK）。

与原 recall_gate.py（硬规则 + LLM 复核相似度分类）不同，
v0.1 采用简明的三路裁决模型：

判定流程：
  1. 提取 state["retrieved_chunks"]
  2. 召回文档数 >= 1 → PASS
  3. 召回数 == 0 且 retry_count < RECALL_MAX_RETRIES(3) → RETRY
     - 调用轻量 LLM 改写 Query
     - 新 Query 写入 retry_hint / details["new_query"]
  4. 召回数 == 0 且 retry_count >= RECALL_MAX_RETRIES → FALLBACK

Query 改写策略：
  - 从原始 Query 中提取核心名词/技术术语
  - 用轻量 LLM 生成同义但不完全相同的检索 Query
  - LLM 不可用时降级为简单关键词拼接
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


class RecallGate(BaseGate):
    """闸门3：RAG 召回质量检测 — 三路裁决 PASS / RETRY / FALLBACK。

    RETRY 时调用轻量 LLM 改写 Query 并附带 new_query。
    """

    GATE_NAME = "RAG召回质量检测"
    STRATEGY = GateStrategy.HARD_RULE_ONLY  # 判定本身不调 LLM
    REQUIRED_STATE_KEYS = {"retrieved_chunks"}

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
    )

    async def check(self, state: dict) -> GateResult:
        """三路裁决核心逻辑。

        1. 提取 retrieved_chunks
        2. 数量 >= 1 → PASS
        3. 数量 == 0 → 判断 retry_count → RETRY 或 FALLBACK
        """
        chunks_raw = state.get("retrieved_chunks", [])
        retry_count: int = state.get("recall_retry_count", 0)

        # ── 防御：None / 非 list → 上游异常，直接 FALLBACK ──
        if not isinstance(chunks_raw, list):
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
            )

        chunk_count = len(chunks_raw)

        # ── PASS：有召回结果 ──
        if chunk_count >= 1:
            return make_gate_result(
                passed=True,
                score=1.0,
                verdict=GateVerdict.PASS.value,
                gate_name=self.GATE_NAME,
                total_chunks=chunk_count,
            )

        # ── 无召回 → 判断重试次数 ──
        if retry_count < settings.RECALL_MAX_RETRIES:
            # RETRY：改写 Query
            original_query = self._extract_query(state)
            new_query = await self._rewrite_query(original_query)

            return make_gate_result(
                passed=False,
                score=0.0,
                verdict=GateVerdict.RETRY.value,
                violations=[
                    f"召回文档数为 0（第 {retry_count + 1}/{settings.RECALL_MAX_RETRIES} 次）"
                ],
                gate_name=self.GATE_NAME,
                retry_hint=f"已改写 Query: '{new_query}'，请用新 Query 重新检索",
                total_chunks=0,
                retry_count=retry_count + 1,
                new_query=new_query,
                original_query=original_query,
            )

        # ── FALLBACK：重试已达上限 ──
        return make_gate_result(
            passed=False,
            score=0.0,
            verdict=GateVerdict.FALLBACK.value,
            violations=[
                f"连续 {settings.RECALL_MAX_RETRIES} 次召回为 0，知识库暂无相关数据"
            ],
            gate_name=self.GATE_NAME,
            total_chunks=0,
            retry_count=retry_count,
        )

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
                settings.RECALL_QUERY_REWRITE_MODEL
                or settings.GATE_LLM_MODEL
                or settings.LLM_MODEL
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

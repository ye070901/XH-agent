"""闸门3：RAG 召回质量检测（硬规则 + 临界区间 LLM 复核）。

硬规则：
  - 召回文档数量 ≥ GATE3_MIN_RECALL_COUNT
  - 每篇文档 relevance_score ≥ GATE3_MIN_SIMILARITY

LLM复核区间：
  - 相似度 ≥ GATE3_LLM_REVIEW_SIM_UPPER → 直接采纳
  - 相似度 <  GATE3_LLM_REVIEW_SIM_LOWER → 直接丢弃
  - 相似度落入 [lower, upper] 区间 → LLM 校验文档与 Query 的语义相关性
"""

from __future__ import annotations

from backend.src.config import settings
from backend.src.quality_gate.base import (
    BaseGate,
    GateResult,
    GateStrategy,
    make_gate_result,
)


class RecallGate(BaseGate):
    """闸门3：RAG 召回质量检测。

    判定流程：
      1. 提取 state["retrieved_chunks"]
      2. 硬规则：数量阈值 + 相似度阈值
      3. 对相似度落入临界区间的文档，LLM 复核语义相关性
      4. 综合判定：通过/驳回 + 过滤后的有效文档列表
    """

    GATE_NAME = "RAG召回质量检测"
    STRATEGY = GateStrategy.HARD_RULE_WITH_LLM_FALLBACK
    REQUIRED_STATE_KEYS = {"retrieved_chunks"}

    async def check(self, state: dict) -> GateResult:
        """硬规则：召回数量 + 相似度阈值校验。

        Args:
            state: 含 retrieved_chunks 和 learner_data 字段的全局状态。

        Returns:
            GateResult: 综合评分 + 违规列表 + 过滤后的有效文档。
        """
        chunks: list[dict] = state.get("retrieved_chunks", [])
        violations: list[str] = []
        scores: list[float] = []

        # ── 校验1：召回数量 ──
        total_count = len(chunks)
        if total_count < settings.GATE3_MIN_RECALL_COUNT:
            violations.append(
                f"召回文档数量不足：{total_count}篇 < {settings.GATE3_MIN_RECALL_COUNT}篇"
            )

        # ── 校验2：逐文档相似度分类 ──
        direct_pass: list[dict] = []
        llm_review_list: list[dict] = []
        direct_drop: list[dict] = []

        for chunk in chunks:
            sim = chunk.get("relevance_score", 0.0)
            if sim >= settings.GATE3_LLM_REVIEW_SIM_UPPER:
                direct_pass.append(chunk)
                scores.append(sim)
            elif sim >= settings.GATE3_LLM_REVIEW_SIM_LOWER:
                llm_review_list.append(chunk)
                scores.append(sim)
            else:
                direct_drop.append(chunk)
                # 低于下限仍计入评分但不纳入有效

        if direct_drop:
            violations.append(
                f"{len(direct_drop)}篇文档相似度过低（< "
                f"{settings.GATE3_LLM_REVIEW_SIM_LOWER}），已自动丢弃"
            )

        # ── 综合评分 ──
        if scores:
            avg_score = sum(scores) / len(scores)
        else:
            avg_score = 0.0

        # 有效文档数（直接通过）不足时标记
        effective_remaining = len(direct_pass) + len(llm_review_list)
        if effective_remaining < settings.GATE3_MIN_RECALL_COUNT:
            violations.append(
                f"有效文档数不足：{effective_remaining}篇 < "
                f"{settings.GATE3_MIN_RECALL_COUNT}篇（不含已丢弃文档）"
            )

        passed = len(violations) == 0 and effective_remaining >= settings.GATE3_MIN_RECALL_COUNT

        return make_gate_result(
            passed=passed,
            score=avg_score,
            violations=violations,
            gate_name=self.GATE_NAME,
            total_chunks=total_count,
            direct_pass_count=len(direct_pass),
            llm_review_count=len(llm_review_list),
            direct_drop_count=len(direct_drop),
            # 附上分类后的文档列表，供后续 LLM 复核和下游使用
            direct_pass_chunks=direct_pass,
            llm_review_chunks=llm_review_list,
        )

    # ═══════════════════════════════════════════════════════════
    # LLM 复核
    # ═══════════════════════════════════════════════════════════

    def _should_trigger_llm_review(self, result: GateResult) -> bool:
        """存在临界区间文档时触发 LLM 复核。"""
        details = result.get("details", {})
        return details.get("llm_review_count", 0) > 0

    async def _llm_review(self, state: dict, hard_result: GateResult) -> GateResult:
        """对临界区间文档逐篇 LLM 复核语义相关性。

        核心逻辑：对每一篇落入 [lower, upper] 区间的文档，
        用轻量 LLM 判断其内容是否与用户 Query 语义相关。
        相关 → 纳入；不相关 → 丢弃。

        LLM复核任意环节失败时，保守沿用原始硬规则判定结果。
        """
        details = hard_result.get("details", {})
        llm_review_list: list[dict] = details.get("llm_review_chunks", [])
        direct_pass_chunks: list[dict] = details.get("direct_pass_chunks", [])

        if not llm_review_list:
            return hard_result

        query = self._extract_query(state)
        self._log(f"LLM 复核 {len(llm_review_list)} 篇临界文档的语义相关性")

        confirmed: list[dict] = []
        rejected: int = 0
        llm_failed_count: int = 0

        for idx, chunk in enumerate(llm_review_list):
            content = chunk.get("content", "")[:800]
            prompt = (
                f"## 用户Query\n{query}\n\n"
                f"## 文档内容\n{content}\n\n"
                f"请判断以上文档内容是否与用户Query语义相关。"
                f'只输出 JSON：{{"relevant": true/false, "reason": "简短理由"}}'
            )

            try:
                from backend.src.llm.client import llm

                review = await llm.call_json(
                    system_prompt=(
                        "你是一个RAG检索质量审核助手。"
                        "判断文档内容与用户查询是否语义相关。"
                        "宽松标准：只要文档主题与查询领域有交集即可认为相关。"
                    ),
                    user_message=prompt,
                    temperature=0.1,
                )

                if isinstance(review, dict) and not review.get("_parse_error"):
                    if review.get("relevant", False):
                        confirmed.append(chunk)
                    else:
                        rejected += 1
                else:
                    # JSON 解析失败，保守沿用硬规则：将文档保留在临界区间
                    llm_failed_count += 1
                    confirmed.append(chunk)

            except Exception as e:
                # LLM 调用异常，保守沿用硬规则：保留文档
                self._log(f"LLM 复核 chunk#{idx} 异常: {e}，保守沿用硬规则保留文档")
                llm_failed_count += 1
                confirmed.append(chunk)

        # 如果 LLM 复核大面积失败（≥50% chunk 出错），直接回退硬规则结果
        total_reviewed = len(llm_review_list)
        if total_reviewed > 0 and llm_failed_count / total_reviewed >= 0.5:
            self._log(
                f"LLM 复核大面积失败 ({llm_failed_count}/{total_reviewed})，"
                f"保守沿用原始硬规则判定结果"
            )
            return hard_result

        # ── 汇总最终有效文档 ──
        final_chunks = direct_pass_chunks + confirmed
        final_count = len(final_chunks)

        all_scores = [c.get("relevance_score", 0.0) for c in final_chunks]
        final_score = sum(all_scores) / len(all_scores) if all_scores else 0.0

        passed = final_count >= settings.GATE3_MIN_RECALL_COUNT
        violations: list[str] = []
        if not passed:
            violations.append(
                f"LLM复核后有效文档数不足：{final_count}篇 < {settings.GATE3_MIN_RECALL_COUNT}篇"
            )

        return make_gate_result(
            passed=passed,
            score=final_score,
            violations=violations,
            gate_name=self.GATE_NAME,
            llm_consulted=True,
            total_chunks=details.get("total_chunks", 0),
            direct_pass_count=details.get("direct_pass_count", 0),
            llm_review_count=len(llm_review_list),
            llm_confirmed_count=len(confirmed),
            llm_rejected_count=rejected,
            llm_failed_count=llm_failed_count,
            final_valid_count=final_count,
            final_chunks=final_chunks,
        )

    # ═══════════════════════════════════════════════════════════
    # 私有
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _extract_query(state: dict) -> str:
        """从 state 中提取用户原始 Query，用于 LLM 复核语义匹配。

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

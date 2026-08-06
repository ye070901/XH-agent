"""闸门2：学情诊断质量检测（硬规则 + 临界区间 LLM 复核）。

硬规则：
  - skill_gaps 不少于 GATE2_MIN_SKILL_GAPS 条
  - knowledge_map 不少于 GATE2_MIN_KNOWLEDGE_ITEMS 条
  - recommended_difficulty 必须为合法枚举值
  - 各 knowledge_item.level 和 confidence 必须在 [0, 1] 区间

LLM复核区间：
  - 诊断质量综合评分 ≥ GATE2_LLM_REVIEW_UPPER → 直接放行
  - 诊断质量综合评分 <  GATE2_LLM_REVIEW_LOWER → 直接驳回
  - 评分落入 [lower, upper] 区间 → 轻量 LLM 复核诊断有效性
"""

from __future__ import annotations

from backend.src.config import settings
from backend.src.quality_gate.base import (
    BaseGate,
    GateResult,
    GateStrategy,
    make_gate_result,
)
from backend.src.schemas import Difficulty


class DiagnosisGate(BaseGate):
    """闸门2：学情诊断质量检测。

    判定流程：
      1. 提取 state["diagnosis_result"]
      2. 硬规则：字段完整性 + 值域合法性
      3. 综合评分，判断是否落入临界区间
      4. 临界区间时调用轻量 LLM 复核诊断有效性
    """

    GATE_NAME = "学情诊断质量检测"
    STRATEGY = GateStrategy.HARD_RULE_WITH_LLM_FALLBACK
    REQUIRED_STATE_KEYS = {"diagnosis_result"}

    # 合法难度枚举值集合（从 schemas.Difficulty 动态获取，避免硬编码）
    _VALID_DIFFICULTIES: frozenset[str] = frozenset(d.value for d in Difficulty)

    async def check(self, state: dict) -> GateResult:
        """硬规则：完整性 + 值域校验，返回综合评分。

        Args:
            state: 含 diagnosis_result 字段的全局状态。

        Returns:
            GateResult: 综合评分 + 违规列表。
        """
        diag: dict = state.get("diagnosis_result", {})
        violations: list[str] = []
        checks_passed = 0
        checks_total = 5

        # ── 校验1：skill_gaps 数量 ──
        skill_gaps: list = diag.get("skill_gaps", [])
        if len(skill_gaps) < settings.GATE2_MIN_SKILL_GAPS:
            violations.append(
                f"skill_gaps 不足：{len(skill_gaps)}条 < {settings.GATE2_MIN_SKILL_GAPS}条"
            )
        else:
            checks_passed += 1

        # ── 校验2：knowledge_map 数量 ──
        knowledge_map: dict = diag.get("knowledge_map", {})
        if len(knowledge_map) < settings.GATE2_MIN_KNOWLEDGE_ITEMS:
            violations.append(
                f"knowledge_map 不足：{len(knowledge_map)}条 "
                f"< {settings.GATE2_MIN_KNOWLEDGE_ITEMS}条"
            )
        else:
            checks_passed += 1

        # ── 校验3：recommended_difficulty 合法 ──
        diff = diag.get("recommended_difficulty", "")
        if diff not in self._VALID_DIFFICULTIES:
            violations.append(
                f"recommended_difficulty 非法：'{diff}' "
                f"不在合法枚举值 {sorted(self._VALID_DIFFICULTIES)} 中"
            )
        else:
            checks_passed += 1

        # ── 校验4：knowledge_map 各条目 level 在 [0,1] ──
        level_violations = self._validate_knowledge_levels(knowledge_map)
        if level_violations:
            violations.extend(level_violations)
        else:
            checks_passed += 1

        # ── 校验5：skill_gaps 各条目 current/target level 在 [0,1] ──
        gap_violations = self._validate_gap_levels(skill_gaps)
        if gap_violations:
            violations.extend(gap_violations)
        else:
            checks_passed += 1

        # ── 综合评分 ──
        score = checks_passed / checks_total

        return make_gate_result(
            passed=len(violations) == 0,
            score=score,
            violations=violations,
            gate_name=self.GATE_NAME,
        )

    # ═══════════════════════════════════════════════════════════
    # LLM 复核
    # ═══════════════════════════════════════════════════════════

    def _should_trigger_llm_review(self, result: GateResult) -> bool:
        """分数落入 [GATE2_LLM_REVIEW_LOWER, GATE2_LLM_REVIEW_UPPER] 区间时触发。"""
        score = result.get("score", 0.0)
        lower = settings.GATE2_LLM_REVIEW_LOWER
        upper = settings.GATE2_LLM_REVIEW_UPPER
        return lower <= score < upper

    async def _llm_review(self, state: dict, hard_result: GateResult) -> GateResult:
        """轻量 LLM 复核诊断结果的有效性。

        向 LLM 发送诊断摘要 + 违规项，请求判定诊断是否可信。
        LLM 返回 {"pass": bool, "reason": str}。

        复核失败时回退到硬规则结果（偏保守：不放行）。
        """
        diag: dict = state.get("diagnosis_result", {})
        prompt = self._build_review_prompt(diag, hard_result)
        llm_error_msg: str = ""

        try:
            from backend.src.llm.client import llm

            review = await llm.call_json(
                system_prompt=(
                    "你是一个学情诊断质量审核助手。"
                    "根据提供的诊断结果和违规项，判断该诊断是否仍然可信。"
                    '只输出 JSON：{"pass": true/false, "reason": "..."}'
                ),
                user_message=prompt,
                temperature=0.1,
            )

            if isinstance(review, dict) and not review.get("_parse_error"):
                llm_pass = review.get("pass", False)
                reason = review.get("reason", "LLM未提供理由")
                new_score = 0.8 if llm_pass else 0.3  # LLM 复核后的修正分数
                return make_gate_result(
                    passed=llm_pass,
                    score=new_score,
                    violations=([] if llm_pass else [f"LLM复核不通过: {reason}"]),
                    gate_name=self.GATE_NAME,
                    llm_consulted=True,
                    llm_reason=reason,
                )

        except Exception as exc:
            self._log(f"LLM 复核异常，回退硬规则结果: {exc}")
            llm_error_msg = str(exc)

        # 回退：保守策略，LLM 复核失败不放行
        return make_gate_result(
            passed=False,
            score=hard_result.get("score", 0.0),
            violations=hard_result.get("violations", []) + ["LLM复核调用失败，保守驳回"],
            gate_name=self.GATE_NAME,
            llm_consulted=False,
            llm_error=llm_error_msg,
        )

    # ═══════════════════════════════════════════════════════════
    # 私有
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _validate_knowledge_levels(knowledge_map: dict) -> list[str]:
        """校验 knowledge_map 中各条目的 level/confidence 是否在 [0,1]。"""
        violations: list[str] = []
        for topic, item in knowledge_map.items():
            if not isinstance(item, dict):
                continue
            level = item.get("level")
            confidence = item.get("confidence")
            if level is not None and not (0 <= level <= 1):
                violations.append(f"knowledge_map['{topic}'].level={level} 不在 [0,1] 区间")
            if confidence is not None and not (0 <= confidence <= 1):
                violations.append(
                    f"knowledge_map['{topic}'].confidence={confidence} 不在 [0,1] 区间"
                )
        return violations

    @staticmethod
    def _validate_gap_levels(skill_gaps: list) -> list[str]:
        """校验 skill_gaps 中各条目的 current_level/target_level 是否在 [0,1]。"""
        violations: list[str] = []
        for idx, gap in enumerate(skill_gaps):
            if not isinstance(gap, dict):
                continue
            for field in ("current_level", "target_level"):
                val = gap.get(field)
                if val is not None and not (0 <= val <= 1):
                    violations.append(f"skill_gaps[{idx}].{field}={val} 不在 [0,1] 区间")
        return violations

    @staticmethod
    def _build_review_prompt(diag: dict, hard_result: GateResult) -> str:
        """构建 LLM 复核 prompt。"""
        skill_gaps_summary = [
            {
                "topic": g.get("topic", ""),
                "priority": g.get("priority", ""),
                "current": g.get("current_level", 0),
                "target": g.get("target_level", 0),
            }
            for g in diag.get("skill_gaps", [])[:10]
        ]

        import json

        return (
            f"## 诊断结果摘要\n"
            f"- 推荐难度：{diag.get('recommended_difficulty', '未知')}\n"
            f"- 学习风格：{diag.get('learning_style', '未知')}\n"
            f"- skill_gaps 数量：{len(diag.get('skill_gaps', []))}\n"
            f"- knowledge_map 数量：{len(diag.get('knowledge_map', {}))}\n"
            f"- 硬规则评分：{hard_result.get('score', 0):.2f}\n"
            f"- 违规项：{json.dumps(hard_result.get('violations', []), ensure_ascii=False)}\n"
            f"\n## skill_gaps 详情\n"
            f"{json.dumps(skill_gaps_summary, ensure_ascii=False, indent=2)}\n"
            f"\n请判断这个诊断结果是否可信，只输出 JSON："
            f'{{"pass": true/false, "reason": "你的判断理由"}}'
        )

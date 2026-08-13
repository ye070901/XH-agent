"""闸门2 v0.1：学情诊断质量检测（三路裁决 PASS / RETRY / FALLBACK）。

与原 diagnosis_gate.py（硬规则 + LLM 复核打分模型）不同，
v0.1 采用简明的三路裁决，直接对接 Scheduler RETRY 回跳 / FALLBACK 降级机制。

判定流程：
  1. 提取 state["diagnosis_result"]
  2. JSON 完全不可解析 → FALLBACK（返回默认初级用户诊断）
  3. 检查 overall_confidence ≥ DIAGNOSIS_CONFIDENCE_THRESHOLD（0.6）
  4. 检查 recommended_difficulty 非空（用户水平）
  5. 检查 skill_gaps 非空（薄弱环节）
  6. 任一不满足 → RETRY（附带缺失提示，引导 Agent1 补充信息后重新诊断）
  7. 全部满足 → PASS

RETRY 时通过 retry_hint 告知上游具体缺失项；
FALLBACK 时通过 fallback_data 返回默认初级用户诊断结果。
"""

from __future__ import annotations

from loguru import logger

from backend.src.config import settings
from backend.src.quality_gate.base import (
    BaseGate,
    GateResult,
    GateStrategy,
    make_gate_result,
)
from backend.src.schemas import GateVerdict


class DiagnosisGate(BaseGate):
    """闸门2：学情诊断质量检测 — 三路裁决 PASS / RETRY / FALLBACK。"""

    GATE_NAME = "学情诊断质量检测"
    STRATEGY = GateStrategy.HARD_RULE_ONLY  # v0.1 纯规则，不调 LLM
    REQUIRED_STATE_KEYS = {"diagnosis_result"}

    # 必填字段（从 diagnosis_result 中检查）
    REQUIRED_OUTPUT_FIELDS = [
        ("recommended_difficulty", "用户水平"),
        ("skill_gaps", "薄弱环节"),
    ]

    async def check(self, state: dict) -> GateResult:
        """三路裁决核心逻辑。

        1. 解析 JSON → 失败则 FALLBACK
        2. 逐项检查 → 任一失败则 RETRY
        3. 全过 → PASS

        learner_data 稀疏时（仅 learning_goal 无其他信息），
        自动放松置信度阈值：模型数据依据不足时不应强行打高分。
        """
        diag: dict = state.get("diagnosis_result", {})

        # ── 情况1：JSON 完全不可解析 → FALLBACK ──
        if not isinstance(diag, dict) or not diag:
            effective_threshold = settings.DIAGNOSIS_CONFIDENCE_THRESHOLD
            logger.info(
                f"[DiagnosisGate] overall_confidence=N/A, "
                f"threshold={effective_threshold}, "
                f"verdict=FALLBACK"
            )
            return make_gate_result(
                passed=False,
                score=0.0,
                verdict=GateVerdict.FALLBACK.value,
                violations=["diagnosis_result 为空或不是有效 JSON 对象"],
                gate_name=self.GATE_NAME,
                fallback_data=self._build_fallback_diagnosis(state),
            )

        # ── 根据 learner_data 稀疏程度调整阈值 ──
        effective_threshold = self._get_effective_threshold(state)

        violations: list[str] = []
        retry_reasons: list[str] = []

        # ── 校验1：overall_confidence 存在 + 值域 [0,1] + 阈值比较 ──
        confidence = diag.get("overall_confidence")
        if confidence is None:
            # 兼容旧版 Agent1（未输出 overall_confidence）：从 knowledge_map 计算平均值
            confidence = self._calc_avg_confidence(diag.get("knowledge_map", {}))

        if not isinstance(confidence, (int, float)):
            violations.append("overall_confidence 缺失且无法从 knowledge_map 推断")
            retry_reasons.append(
                "诊断结果缺少 overall_confidence，"
                "请补充诊断置信度（取 knowledge_map 各条目 confidence 平均值）"
            )
        elif isinstance(confidence, bool):
            violations.append("overall_confidence 类型异常（bool），期望 0-1 之间的数值")
            retry_reasons.append("overall_confidence 数据类型错误，请输出数值类型（如 0.85）")
        elif not (0.0 <= confidence <= 1.0):
            violations.append(f"overall_confidence={confidence} 超出合法范围 [0, 1]")
            retry_reasons.append(
                f"overall_confidence 值域异常（{confidence}），"
                "置信度必须在 0-1 之间，请检查诊断逻辑后重新输出"
            )
        elif confidence < effective_threshold:
            violations.append(f"overall_confidence={confidence:.2f} < {effective_threshold}")
            retry_reasons.append(
                f"诊断置信度过低（{confidence:.2f}），"
                "请补充更多学习者背景信息（学历、工作经历、前置测试结果）后重新诊断"
            )

        # ── 校验2：recommended_difficulty 非空且为字符串类型（用户水平）──
        difficulty = diag.get("recommended_difficulty", "")
        if not isinstance(difficulty, str):
            violations.append(
                f"recommended_difficulty 类型异常（{type(difficulty).__name__}），期望字符串"
            )
            retry_reasons.append(
                f"recommended_difficulty 必须为字符串类型"
                f"（如 'beginner' / 'intermediate' / 'advanced'），"
                f"当前为 {type(difficulty).__name__}"
            )
        elif not difficulty.strip():
            violations.append("recommended_difficulty 缺失（用户水平）")
            retry_reasons.append("请输出 recommended_difficulty 字段标注用户当前水平")

        # ── 校验3：skill_gaps 非空且每项均为 dict（薄弱环节）──
        gaps = diag.get("skill_gaps", [])
        if not isinstance(gaps, list) or len(gaps) == 0:
            violations.append("skill_gaps 为空（薄弱环节）")
            retry_reasons.append("请至少识别 1 个薄弱环节，标注学习者缺少哪些前置知识/技能")
        else:
            non_dict_items = [i for i, g in enumerate(gaps) if not isinstance(g, dict)]
            if non_dict_items:
                violations.append(
                    f"skill_gaps[{non_dict_items}] 包含非 dict 类型元素，期望每个薄弱项为对象格式"
                )
                retry_reasons.append(
                    f"skill_gaps 第 {non_dict_items} 项类型错误，"
                    "每个薄弱环节必须为对象格式（含 topic / current_level / target_level 等字段）"
                )

        # ── 全过 → PASS ──
        if not violations:
            conf_val = confidence if isinstance(confidence, (int, float)) else 0.0
            default_threshold = settings.DIAGNOSIS_CONFIDENCE_THRESHOLD
            sparse = "（稀疏模式）" if effective_threshold != default_threshold else ""
            logger.info(
                f"[DiagnosisGate] overall_confidence={conf_val}, "
                f"threshold={effective_threshold}{sparse}, "
                f"verdict=PASS"
            )
            return make_gate_result(
                passed=True,
                score=1.0,
                verdict=GateVerdict.PASS.value,
                gate_name=self.GATE_NAME,
            )

        # ── 有违规 → RETRY ──
        conf_val = confidence if isinstance(confidence, (int, float)) else 0.0
        logger.info(
            f"[DiagnosisGate] overall_confidence={conf_val}, "
            f"threshold={effective_threshold}, "
            f"verdict=RETRY"
        )
        return make_gate_result(
            passed=False,
            score=conf_val,
            verdict=GateVerdict.RETRY.value,
            violations=violations,
            gate_name=self.GATE_NAME,
            retry_hint="；".join(retry_reasons),
        )

    # ═══════════════════════════════════════════════════════════
    # 私有辅助
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _get_effective_threshold(state: dict) -> float:
        """根据 learner_data 稀疏程度调整置信度阈值。

        learner_data 只含 learning_goal（无学历/专业/经历/测试数据）
        → 模型依据不足，使用宽松阈值 0.05，避免无限 RETRY。
        learner_data 包含丰富画像 → 使用配置的标准阈值。

        Returns:
            float: 适用于当前 learner_data 的有效置信度阈值。
        """
        learner = state.get("learner_data", {}) or {}
        has_rich_data = any(
            learner.get(k)
            for k in ("education_level", "major", "work_years", "skills_used", "pretest_results")
            if learner.get(k)  # 过滤掉 0 / "" / [] / None
        )
        if not has_rich_data:
            return 0.05
        return settings.DIAGNOSIS_CONFIDENCE_THRESHOLD

    @staticmethod
    def _calc_avg_confidence(knowledge_map: dict) -> float:
        """从 knowledge_map 各条目 confidence 计算平均值。

        兼容 knowledge_map 为 dict（后端格式 {topic: {confidence: ...}}）
        或 list（Agent1 独立版格式 [{confidence: ...}]）。
        """
        if not knowledge_map:
            return 0.0

        confidences: list[float] = []

        if isinstance(knowledge_map, dict):
            for item in knowledge_map.values():
                if isinstance(item, dict):
                    conf = item.get("confidence")
                    if isinstance(conf, (int, float)):
                        confidences.append(float(conf))
        elif isinstance(knowledge_map, list):
            for item in knowledge_map:
                if isinstance(item, dict):
                    conf = item.get("confidence")
                    if isinstance(conf, (int, float)):
                        confidences.append(float(conf))

        if not confidences:
            return 0.0

        return round(sum(confidences) / len(confidences), 2)

    @staticmethod
    def _build_fallback_diagnosis(state: dict) -> dict:
        """构建默认初级用户诊断（FALLBACK 降级用）。

        从 state 中尽可能提取 learner_data.learning_goal 作为兜底信息。
        """
        learner = state.get("learner_data", {})
        goal = learner.get("learning_goal", "未指定学习目标")

        return {
            "knowledge_map": {},
            "skill_gaps": [
                {
                    "topic": "基础前置知识",
                    "current_level": 0.0,
                    "target_level": 0.5,
                    "priority": "critical",
                    "reason": "诊断数据不足，默认标记为基础薄弱",
                }
            ],
            "learning_style": "practice_first",
            "recommended_difficulty": "beginner",
            "overall_confidence": 0.1,
            "summary": (
                f"[FALLBACK] 诊断数据不可用，已降级为默认初级用户。"
                f"学习目标：{goal}。建议从基础入门内容开始。"
            ),
        }

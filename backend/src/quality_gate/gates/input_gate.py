"""闸门1：输入特异性检测（纯规则，不调用 LLM）。

拦截场景：
  - 空输入 / 过短输入
  - 包含危险关键词（违法/暴力/色情/赌博/毒品）
  - 领域外话题（政治/军事/金融交易/医疗诊断）

架构约束：GATE1 为 HARD_RULE_ONLY 策略，绝不调用 LLM。
全部阈值从 config.settings 读取。
"""

from __future__ import annotations

from backend.src.config import settings
from backend.src.quality_gate.base import (
    BaseGate,
    GateResult,
    GateStrategy,
    make_gate_result,
)


class InputGate(BaseGate):
    """闸门1：特异性检测 —— 最前端的输入安全过滤器。

    判定流程：
      1. 提取 state["learner_data"]["learning_goal"] + 其他文本字段
      2. 逐级检测：空输入 → 过短 → 危险关键词 → 领域外话题
      3. 全部通过返回 passed=True，命中任一拦截返回 passed=False
    """

    GATE_NAME = "输入特异性检测"
    STRATEGY = GateStrategy.HARD_RULE_ONLY  # 永不调 LLM
    REQUIRED_STATE_KEYS = {"learner_data"}

    # ── 危险关键词匹配策略 ──
    _BANNED_MIN_LENGTH_THRESHOLD = 2
    """关键词最短长度：过滤过短无意义匹配（如单字命中）"""

    async def check(self, state: dict) -> GateResult:
        """执行纯规则特异性检测。

        Args:
            state: 含 learner_data 字段的全局状态。

        Returns:
            GateResult: score=1.0 表示完全通过，0.0 表示被拦截。
        """
        learner_data: dict = state.get("learner_data", {})

        # 收集所有待检测文本
        texts: list[str] = self._collect_texts(learner_data)
        combined = " ".join(texts).strip()

        violations: list[str] = []

        # ── 检测1：空输入 ──
        if not combined:
            return make_gate_result(
                passed=False,
                score=0.0,
                violations=["输入为空，无法进行学情诊断"],
                gate_name=self.GATE_NAME,
            )

        # ── 检测2：输入过短 ──
        if len(combined) < settings.GATE1_MIN_INPUT_LENGTH:
            violations.append(
                f"输入过短（{len(combined)}字符 < {settings.GATE1_MIN_INPUT_LENGTH}字符），"
                "请提供更详细的学习目标和背景信息"
            )

        # ── 检测3：危险关键词 ──
        banned_hits = self._match_keywords(combined, settings.GATE1_BANNED_KEYWORDS)
        if banned_hits:
            violations.append(f"输入包含违规内容，命中关键词: {', '.join(banned_hits)}")

        # ── 检测4：领域外话题 ──
        domain_hits = self._match_keywords(combined, settings.GATE1_BLOCKED_DOMAINS)
        if domain_hits:
            violations.append(f"输入涉及领域外话题，不在本系统支持范围: {', '.join(domain_hits)}")

        # ── 汇总 ──
        if violations:
            return make_gate_result(
                passed=False,
                score=0.0,
                violations=violations,
                gate_name=self.GATE_NAME,
            )

        return make_gate_result(
            passed=True,
            score=1.0,
            gate_name=self.GATE_NAME,
        )

    # ═══════════════════════════════════════════════════════════
    # 私有辅助
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _collect_texts(learner_data: dict) -> list[str]:
        """从 learner_data 中收集所有待检测文本字段。

        覆盖字段：learning_goal / major / industry / positions / skills_used。
        """
        texts: list[str] = []
        for key in ("learning_goal", "major", "industry", "school"):
            val = learner_data.get(key, "")
            if isinstance(val, str) and val.strip():
                texts.append(val.strip())

        # 列表字段：展开为逗号拼接
        for key in ("positions", "skills_used"):
            val = learner_data.get(key, [])
            if isinstance(val, list):
                joined = ", ".join(str(v) for v in val if v)
                if joined:
                    texts.append(joined)

        return texts

    @classmethod
    def _match_keywords(cls, text: str, keywords: list[str]) -> list[str]:
        """在文本中匹配关键词列表，返回命中项。

        匹配规则：
          - 大小写不敏感
          - 排除过短关键词（< 2 字符）的误命中
        """
        text_lower = text.lower()
        hits: list[str] = []
        for kw in keywords:
            kw_stripped = kw.strip()
            if len(kw_stripped) < cls._BANNED_MIN_LENGTH_THRESHOLD:
                continue
            if kw_stripped.lower() in text_lower:
                hits.append(kw_stripped)
        return hits

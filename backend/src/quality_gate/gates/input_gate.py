"""闸门1：输入特异性检测（纯规则，不调用 LLM）。

拦截场景：
  - 空输入 / 过短输入
  - 包含危险关键词（违法/暴力/色情/赌博/毒品）
  - 领域外话题（政治/军事/金融交易/医疗诊断）

架构约束：GATE1 为 HARD_RULE_ONLY 策略，绝不调用 LLM。
全部阈值从 config.settings 读取。
"""

from __future__ import annotations

import re

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
                intent="未识别",
                intent_confidence="low",
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

        # ── 意图识别（不阻断，仅标记标签）──
        intent_label, intent_confidence = self._detect_intent(combined)

        # ── 汇总 ──
        if violations:
            return make_gate_result(
                passed=False,
                score=0.0,
                violations=violations,
                gate_name=self.GATE_NAME,
                intent=intent_label,
                intent_confidence=intent_confidence,
            )

        return make_gate_result(
            passed=True,
            score=1.0,
            gate_name=self.GATE_NAME,
            intent=intent_label,
            intent_confidence=intent_confidence,
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

    # ═══════════════════════════════════════════════════════════
    # 意图识别（工业机器人领域）
    # ═══════════════════════════════════════════════════════════

    # 按优先级排列的意图模式：(标签, 优先级, 正则模式)
    # 优先级越高越先匹配，匹配成功后不再尝试后续模式
    _INTENT_PATTERNS: list[tuple[str, int, re.Pattern]] = [
        # P0: 故障排查 — 明确的报错/故障信号
        (
            "故障排查",
            0,
            re.compile(
                r"故障|报错|报警|异常|不工作|无法|出错|错误代码|SRVO|INTP|MOTN|"
                r"恢复|排除|排查|修理|维修|坏了|不动了|停了",
                re.IGNORECASE,
            ),
        ),
        # P1: 安全规范 — 安全相关
        (
            "安全规范",
            1,
            re.compile(
                r"安全|急停|防护|危险|警告|门锁|光栅|安全门|区域传感器|"
                r"安全回路|安全栅栏|防护罩",
                re.IGNORECASE,
            ),
        ),
        # P2: 通信调试 — 通信/IO/PLC 相关
        (
            "通信调试",
            2,
            re.compile(
                r"通信|IO|信号|总线|EtherNet|ProfiNet|DeviceNet|PLC|"
                r"调试|联调|通讯|EtherCAT|CC-Link|ProfiBus|I/?O",
                re.IGNORECASE,
            ),
        ),
        # P3: 编程操作 — 编程/示教/指令相关
        (
            "编程操作",
            3,
            re.compile(
                r"编程|示教|编写|程序|指令|轨迹|点位|运动指令|"
                r"Move[LJ]?|JMP|CALL|LBL|WAIT|Step|TP程序|"
                r"焊接|码垛|搬运|涂胶|打磨|路径",
                re.IGNORECASE,
            ),
        ),
        # P4: 参数配置 — 参数/坐标/设定
        (
            "参数配置",
            4,
            re.compile(
                r"参数|配置|设置|变量|系统变量|寄存器|坐标|TCP|"
                r"工具坐标|用户坐标|工件坐标|三点法|六点法|标定|"
                r"有效载荷|Payload|零点|校准|原点",
                re.IGNORECASE,
            ),
        ),
        # P5: 概念理解 — 疑问句式兜底
        (
            "概念理解",
            5,
            re.compile(
                r"怎么|如何|为什么|是什么|什么区别|原理|作用|功能|"
                r"介绍|概述|说明|差异|对比|优缺点",
                re.IGNORECASE,
            ),
        ),
    ]

    @classmethod
    def _detect_intent(cls, text: str) -> tuple[str, str]:
        """从输入文本中识别用户意图（计分制：统计各类别命中关键词数）。

        不再使用首匹配制，而是对每个 intent 类别分别统计命中的唯一关键词数，
        取得分最高者。得分相同时按优先级（P0 > P1 > ... > P5）裁决。

        Args:
            text: 拼接后的用户输入文本。

        Returns:
            tuple[str, str]: (意图标签, 置信度)。
        """
        if not text.strip():
            return ("未识别", "low")

        best_label = "未识别"
        best_score = 0
        best_priority = 999

        for label, priority, pattern in cls._INTENT_PATTERNS:
            # 用 finditer 统计该类别下命中的唯一关键词数
            matches = set(m.group() for m in pattern.finditer(text))
            score = len(matches)

            if score > best_score or (score == best_score and priority < best_priority):
                best_score = score
                best_priority = priority
                best_label = label

        if best_score == 0:
            return ("未识别", "low")

        # P0-P4 为高置信度，P5 为中等
        confidence = "medium" if best_label == "概念理解" else "high"
        return (best_label, confidence)

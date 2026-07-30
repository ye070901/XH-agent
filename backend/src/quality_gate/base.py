"""质量闸门抽象基类 + GateResult 数据结构。

三道闸门统一继承 BaseGate(ABC)，强制实现 check(state) -> GateResult。
外部通过 validate(state) 调用，自动获得校验 + 日志 + 异常隔离。

架构决策（不可擅自改动）：
  - 硬规则为主、临界区间启用轻量 LLM 复核
  - 全部阈值从 config.settings 读取，禁止模块内硬编码
  - 闸门1 纯规则不调 LLM；闸门2/3 临界区间才调 LLM
  - LLM 复核使用 GateStrategy 枚举区分，避免运行时误判
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, TypedDict

from loguru import logger

# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════


class GateStrategy(str, Enum):
    """闸门判定策略枚举。

    HARD_RULE_ONLY:             纯硬规则判定，不调用 LLM（闸门1）
    HARD_RULE_WITH_LLM_FALLBACK: 硬规则为主，临界区间 LLM 复核（闸门2/3）
    """

    HARD_RULE_ONLY = "hard_rule_only"
    HARD_RULE_WITH_LLM_FALLBACK = "hard_rule_with_llm_fallback"


class GateResult(TypedDict, total=False):
    """闸门判定结果统一数据结构。

    Attributes:
        passed:        整体是否通过
        score:         质量评分 0.0-1.0
        violations:    违规项描述列表
        gate_name:     闸门名称（用于日志/前端展示）
        llm_consulted: 是否经过了 LLM 复核
        details:       附加详情（各闸门自定义键）
    """

    passed: bool
    score: float
    violations: list[str]
    gate_name: str
    llm_consulted: bool
    details: dict[str, Any]


# ═══════════════════════════════════════════════════════════
# BaseGate 抽象基类
# ═══════════════════════════════════════════════════════════


class BaseGate(ABC):
    """质量闸门基类 —— 所有闸门的唯一父类。

    子类必须：
      1. 设置 GATE_NAME 类属性（中文，用于日志/前端）
      2. 设置 STRATEGY 类属性（GateStrategy 枚举值）
      3. 实现 async def check(self, state: dict) -> GateResult
      4. 硬规则判定逻辑写在 _hard_rule_check() 中
      5. （可选）覆盖 _llm_review() 实现临界区间 LLM 复核

    外部调用：
      推荐：await gate.validate(state)    # 自动校验 + 日志 + state 注入
      直接：await gate.check(state)       # 仅判定逻辑，无包装

    Attributes:
        GATE_NAME:  闸门中文名称
        STRATEGY:   判定策略枚举
        REQUIRED_STATE_KEYS:  state 中必须存在的键
    """

    GATE_NAME: str = ""
    STRATEGY: GateStrategy = GateStrategy.HARD_RULE_ONLY
    REQUIRED_STATE_KEYS: set[str] = set()

    # ═══════════════════════════════════════════════════════════
    # 公开 API
    # ═══════════════════════════════════════════════════════════

    async def validate(self, state: dict) -> dict:
        """统一入口：校验 state → 硬规则判定 → (可选)LLM复核 → 注入state。

        与 BaseAgent.run() 对齐的设计：
          - 自动完成 state 必需键校验
          - 生命周期日志（开始/通过/失败）
          - 异常隔离：错误写入 state，不向上传播
          - 结果写入 state["gate_results"][gate_name]

        Args:
            state: LangGraph 全局状态 dict。

        Returns:
            dict: 写入了 gate_results 的 state。
        """
        state.setdefault("gate_results", {})

        # ── 1. state 校验 ──
        validation_errors = self._validate_state(state)
        if validation_errors:
            self._log(f"state 校验失败: {'; '.join(validation_errors)}")
            result: GateResult = {
                "passed": False,
                "score": 0.0,
                "violations": validation_errors,
                "gate_name": self.GATE_NAME,
                "llm_consulted": False,
                "details": {"stage": "validation_failed"},
            }
            state["gate_results"][self.GATE_NAME] = result
            return state

        # ── 2. 硬规则判定 ──
        self._log("开始判定")
        try:
            result = await self.check(state)

            # 防御：补充 gate_name 和 llm_consulted 默认值
            result.setdefault("gate_name", self.GATE_NAME)
            result.setdefault("llm_consulted", False)

            # ── 3. 临界区间 LLM 复核（仅 FALLBACK 策略）──
            if self.STRATEGY == GateStrategy.HARD_RULE_WITH_LLM_FALLBACK:
                should_review = self._should_trigger_llm_review(result)
                if should_review:
                    self._log(f"进入临界区间 (score={result.get('score', 0):.2f})，启动 LLM 复核")
                    result = await self._llm_review(state, result)

            # ── 4. 写入 state ──
            state["gate_results"][self.GATE_NAME] = result

            if result["passed"]:
                self._log(f"✅ 通过 (score={result.get('score', 0):.2f})")
            else:
                self._log(
                    f"❌ 未通过 (score={result.get('score', 0):.2f}, "
                    f"violations={len(result.get('violations', []))}条)"
                )

            return state

        except Exception as e:
            logger.error(f"[{self.GATE_NAME}] 判定异常: {type(e).__name__}: {e}")
            fallback: GateResult = {
                "passed": False,
                "score": 0.0,
                "violations": [f"闸门执行异常: {e}"],
                "gate_name": self.GATE_NAME,
                "llm_consulted": False,
                "details": {"stage": "error", "error_type": type(e).__name__},
            }
            state["gate_results"][self.GATE_NAME] = fallback
            return state

    @abstractmethod
    async def check(self, state: dict) -> GateResult:
        """执行闸门判定逻辑。

        子类在此实现硬规则判定。不需要手动处理异常（由 run() 兜底）。
        LLM 复核由 _llm_review() 负责，不要在 check() 中直接调 LLM。

        Args:
            state: LangGraph 的全局状态 dict。

        Returns:
            GateResult: 判定结果。
        """
        ...

    # ═══════════════════════════════════════════════════════════
    # LLM 复核（子类覆盖）
    # ═══════════════════════════════════════════════════════════

    async def _llm_review(self, state: dict, hard_result: GateResult) -> GateResult:
        """轻量 LLM 复核。

        仅 HARD_RULE_WITH_LLM_FALLBACK 策略且分数落入临界区间时被 run() 调用。
        默认实现直接将 hard_result 原样返回（即跳过 LLM 复核）。
        子类覆盖此方法实现具体复核逻辑。

        Args:
            state:       全局状态 dict。
            hard_result: 硬规则判定结果。

        Returns:
            GateResult: 复核后的最终结果。llm_consulted 必须设为 True。
        """
        return hard_result

    def _should_trigger_llm_review(self, result: GateResult) -> bool:
        """判断是否需要触发 LLM 复核。

        默认返回 False。子类覆盖此方法定义临界区间规则。

        Args:
            result: 硬规则判定的 GateResult。

        Returns:
            bool: 是否需要 LLM 复核。
        """
        return False

    # ═══════════════════════════════════════════════════════════
    # 日志
    # ═══════════════════════════════════════════════════════════

    def _log(self, message: str) -> None:
        """闸门统一日志，自动带 [Gate名称] 前缀。"""
        logger.info(f"[{self.GATE_NAME}] {message}")

    # ═══════════════════════════════════════════════════════════
    # 私有：state 校验
    # ═══════════════════════════════════════════════════════════

    def _validate_state(self, state: dict) -> list[str]:
        """校验 state dict 是否包含闸门所需的键。

        Returns:
            list[str]: 校验错误信息列表。空列表 = 校验通过。
        """
        errors: list[str] = []
        if self.REQUIRED_STATE_KEYS:
            missing = self.REQUIRED_STATE_KEYS - set(state.keys())
            if missing:
                errors.append(f"缺少必需字段: {', '.join(sorted(missing))}")
        return errors


# ═══════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════


def make_gate_result(
    passed: bool,
    score: float,
    violations: list[str] | None = None,
    gate_name: str = "",
    llm_consulted: bool = False,
    **details: Any,
) -> GateResult:
    """GateResult 工厂函数，确保必填字段完整。

    Args:
        passed:        是否通过
        score:         质量评分 0.0-1.0
        violations:    违规项列表
        gate_name:     闸门名称
        llm_consulted: 是否经过了 LLM 复核
        **details:     附加详情键值对

    Returns:
        GateResult: 结构完整的判定结果。
    """
    return GateResult(
        passed=passed,
        score=max(0.0, min(1.0, score)),
        violations=violations or [],
        gate_name=gate_name,
        llm_consulted=llm_consulted,
        details=dict(details),
    )

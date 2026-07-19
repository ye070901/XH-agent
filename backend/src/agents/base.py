"""Agent 基类 + 接口契约。

所有 Agent 必须继承 BaseAgent(ABC)，强制实现 process(state) -> dict。
外部通过 run(state) 调用以自动获得校验 + 错误处理 + 日志。

设计原则（对应 CLAUDE.md §3）：
  - BaseAgent 不持有业务逻辑，仅提供 LLM 调用、日志、校验等横切工具
  - 子类通过 REQUIRED_STATE_KEYS / OPTIONAL_STATE_KEYS 声明输入 schema
  - run() 自动校验 state、try/except 异常隔离
  - 运行错误写入 state["agent_log"]，单个 Agent 故障不阻断系统
  - LLM 调用统一走 self.call_llm() / self.call_llm_json()
  - 日志统一走 self.log()，自动带 [Agent名称] 前缀
  - 三类 Agent 固定温度预设：诊断 0.2 / 生成 0.5 / 审核 0.1
  - 子类私有辅助方法以下划线开头
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from loguru import logger

from ..llm.client import llm

# ═══════════════════════════════════════════════════════════
# 三类 Agent 固定温度预设（CLAUDE.md §3）
# ═══════════════════════════════════════════════════════════

# 诊断/审核用低温（0.1–0.2），保证判断一致性
TEMPERATURE_DIAGNOSIS: float = 0.2
TEMPERATURE_AUDIT: float = 0.1
# 生成用中温（0.3–0.5），保证内容多样性
TEMPERATURE_GENERATION: float = 0.5


class BaseAgent(ABC):
    """Agent 基类 —— 所有 Agent 的唯一父类。

    子类必须：
      1. 实现 async def process(self, state: dict) -> dict
      2. 在 __init__ 中调用 super().__init__(name=..., system_prompt=..., temperature=...)
      3. 将 system_prompt 定义为模块顶层常量 SYSTEM_PROMPT（不内联在类体中）

    子类可选覆盖：
      - REQUIRED_STATE_KEYS: set[str]     state 中必须存在的键
      - OPTIONAL_STATE_KEYS: set[str]     state 中可选存在的键
      - _custom_validate(state) -> list[str]   自定义校验逻辑

    外部调用：
      - 推荐：await agent.run(state)      # 自动校验 + 错误隔离 + agent_log 写入
      - 直接：await agent.process(state)  # 仅业务逻辑，无包装

    Attributes:
        name:          Agent 中文名称（面向团队内部可视化）
        system_prompt: 系统提示词，来自子类模块顶层 SYSTEM_PROMPT 常量
        temperature:   LLM 温度，参考三类预设值
    """

    # ── 子类覆盖：state schema 声明 ──
    REQUIRED_STATE_KEYS: set[str] = set()
    OPTIONAL_STATE_KEYS: set[str] = {"diagnosis_completed", "resource_types"}

    def __init__(
        self,
        name: str,
        system_prompt: str,
        temperature: float = 0.3,
    ) -> None:
        """初始化 Agent。

        Args:
            name:          Agent 名称，用于日志标识。必须用中文。
            system_prompt: 系统提示词。写在模块顶层常量 SYSTEM_PROMPT 中传入。
            temperature:   LLM 温度。参考三类预设：
                             TEMPERATURE_DIAGNOSIS  = 0.2
                             TEMPERATURE_GENERATION = 0.5
                             TEMPERATURE_AUDIT      = 0.1

        Raises:
            ValueError: name 为空时抛出
        """
        if not name or not name.strip():
            raise ValueError("Agent name 不能为空")

        self.name: str = name.strip()
        self.system_prompt: str = system_prompt
        self.temperature: float = temperature

        logger.debug(f"[{self.name}] Agent 初始化完成 (temperature={self.temperature})")

    # ═══════════════════════════════════════════════════════════
    # 公开 API
    # ═══════════════════════════════════════════════════════════

    async def run(self, state: dict) -> dict:
        """统一入口：校验 state → 调用 process() → 错误兜底。

        这是外部调用 Agent 的推荐入口。与直接调用 process() 的区别：
          - 自动完成 state 表单校验（必需键 + 可选键 + 自定义规则）
          - 生命周期日志（开始/完成/失败）
          - try/except 异常隔离：错误写入 state["agent_log"]，不向上传播
          - process() 的返回值自动合并回 state

        Args:
            state: LangGraph 全局状态 dict。键名须与 schemas.py 中的字段一致。

        Returns:
            dict: 合并了 process() 返回值的 state。异常时含 status="error" 标记。
        """
        # 确保 agent_log 存在
        state.setdefault("agent_log", [])

        # ── 1. 表单校验 ──
        validation_errors = self._validate_state(state)
        if validation_errors:
            self.log(f"state 校验失败: {'; '.join(validation_errors)}")
            state["agent_log"].append({
                "agent": self.name,
                "level": "error",
                "stage": "validation",
                "message": f"state 校验失败: {'; '.join(validation_errors)}",
                "errors": validation_errors,
            })
            state["status"] = "error"
            return state

        # ── 2. 执行 process()（try/except 异常隔离）──
        self.log("开始执行")
        try:
            result = await self.process(state)

            # 防御：非 dict 返回值包装为 dict
            if not isinstance(result, dict):
                self.log(f"警告: process() 返回了 {type(result).__name__} 而非 dict，已包装")
                result = {"result": result}

            # 合并结果到 state
            state.update(result)

            # 记录成功
            state["agent_log"].append({
                "agent": self.name,
                "level": "info",
                "stage": "complete",
                "message": "执行完成",
            })
            self.log("执行完成")
            return state

        except Exception as e:
            logger.error(f"[{self.name}] 执行异常: {type(e).__name__}: {e}")
            state["agent_log"].append({
                "agent": self.name,
                "level": "error",
                "stage": "process",
                "message": str(e),
                "error_type": type(e).__name__,
            })
            state["status"] = "error"
            state["error"] = str(e)
            state["error_type"] = type(e).__name__
            # 不 raise — 单个 Agent 故障不阻断系统
            return state

    @abstractmethod
    async def process(self, state: dict) -> dict:
        """处理输入状态，返回更新后的状态字典。

        子类在此实现纯业务逻辑，不需要自行处理异常（由 run() 兜底）。
        不需要手动写 agent_log（由 run() 自动写入）。

        Args:
            state: LangGraph 的全局状态 dict。
                   键名必须与 WorkflowState / schemas.py 的字段一致。

        Returns:
            dict: 必须返回 dict。键名须与 WorkflowState 的字段名一致。
                  返回值会由 run() 自动合并到 state。
        """
        ...

    # ═══════════════════════════════════════════════════════════
    # LLM 调用工具（CLAUDE.md §2 + §3）
    # ═══════════════════════════════════════════════════════════

    async def call_llm(
        self,
        user_message: str,
        *,
        temperature: float | None = None,
    ) -> str:
        """调用 LLM，自动附带本 Agent 的 system_prompt 和预设 temperature。

        Args:
            user_message: 用户消息 / prompt 内容。
            temperature:  可显式覆盖温度，默认使用 self.temperature。

        Returns:
            str: LLM 返回的文本内容。
        """
        temp = temperature if temperature is not None else self.temperature
        logger.info(f"[{self.name}] LLM 调用 (temperature={temp})")
        return await llm.call(
            system_prompt=self.system_prompt,
            user_message=user_message,
            temperature=temp,
        )

    async def call_llm_json(
        self,
        user_message: str,
        *,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """调用 LLM 并解析为 JSON dict。解析失败返回 {}（不抛异常）。

        内置 JSON 容错（参见 llm/client.py 的 _parse_json）：
          1. 直接解析  2. ```json 代码块  3. ``` 代码块  4. 首组花括号

        Args:
            user_message: 用户消息 / prompt 内容。
            temperature:  可显式覆盖温度，默认使用 self.temperature。

        Returns:
            dict: 解析后的字典。解析失败时返回 {}。
        """
        temp = temperature if temperature is not None else self.temperature
        logger.info(f"[{self.name}] LLM JSON 调用 (temperature={temp})")
        return await llm.call_json(
            system_prompt=self.system_prompt,
            user_message=user_message,
            temperature=temp,
        )

    # ═══════════════════════════════════════════════════════════
    # 日志（CLAUDE.md §3）
    # ═══════════════════════════════════════════════════════════

    def log(self, message: str) -> None:
        """Agent 统一日志，自动带 [Agent名称] 前缀。

        所有 Agent 子类的日志必须通过此方法输出，禁止直接调用 logger。
        """
        logger.info(f"[{self.name}] {message}")

    # ═══════════════════════════════════════════════════════════
    # 私有：state 表单校验
    # ═══════════════════════════════════════════════════════════

    def _validate_state(self, state: dict) -> list[str]:
        """校验 state dict 的键是否满足当前 Agent 的 schema 声明。

        校验规则（按顺序）：
          1. REQUIRED_STATE_KEYS 中的键必须全部存在
          2. 未知键（既不在 REQUIRED 也不在 OPTIONAL）给出 warning
          3. 调用子类的 _custom_validate() 进行额外语义校验

        Returns:
            list[str]: 校验错误信息列表。空列表 = 校验通过。
        """
        errors: list[str] = []
        allowed = self.REQUIRED_STATE_KEYS | self.OPTIONAL_STATE_KEYS

        # 1. 必需键检查
        missing = self.REQUIRED_STATE_KEYS - set(state.keys())
        if missing:
            errors.append(f"缺少必需字段: {', '.join(sorted(missing))}")

        # 2. 未知键警告（仅在声明了 schema 时检查）
        if allowed:
            unknown = set(state.keys()) - allowed
            if unknown:
                logger.warning(
                    f"[{self.name}] state 包含未声明的键: "
                    f"{', '.join(sorted(unknown))}。"
                    f"请添加到 REQUIRED_STATE_KEYS 或 OPTIONAL_STATE_KEYS"
                )

        # 3. 子类自定义校验
        custom_errors = self._custom_validate(state)
        errors.extend(custom_errors)

        return errors

    def _custom_validate(self, state: dict) -> list[str]:
        """子类可覆盖此方法，实现语义级别的额外校验。

        例如：检查 learner_data 的 education_level 是否为合法枚举值、
        resource_types 列表是否为空等。

        Returns:
            list[str]: 自定义校验错误。默认返回空列表。
        """
        return []

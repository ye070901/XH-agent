"""项目级统一异常类 — XH 前缀，继承 Exception。

四层异常处理链（对应 CLAUDE.md §4）：

    LLM 调用层 (client.py)
      └─ 内置重试 → 最后一次失败抛出原始异常 + XHLLMRetryExhausted

    Agent 层 (agents/*.py)
      └─ process() 内捕获异常 → 写入 state 错误标记返回，不崩溃
         可选择性抛 XHAgentError 标记不可恢复的错误

    工作流层 (graph/orchestrator.py)
      └─ 每一步调 Agent 时捕获异常 → 记录日志 → 设置 state["status"] = "error"
         用 XHWorkflowError 包装，附加上下文（agent_name, state）

    API 层 (api/main.py)
      └─ 全局兜底 → XHAPIError → HTTPException(500)
"""

from __future__ import annotations


class XHError(Exception):
    """项目所有自定义异常的基类。

    Usage:
        raise XHError("base message")
        raise XHConfigError("LLM_API_KEY is required in production mode")
        raise XHLLMTimeout("LLM 调用超时 (120s)")
    """

    def __init__(self, message: str = "", *, context: dict | None = None) -> None:
        super().__init__(message)
        self.context: dict = context or {}
        """附加上下文信息，便于日志追踪和调试。"""


# ═══════════════════════════════════════════════════════════
# 配置层异常
# ═══════════════════════════════════════════════════════════


class XHConfigError(XHError):
    """配置错误：缺少必填配置、非法值、类型不匹配等。

    Examples:
        raise XHConfigError("LLM_API_KEY 未设置，非演示模式下必须提供")
        raise XHConfigError(f"LLM_TIMEOUT_SECONDS 必须为正整数，当前: {v}")
    """


# ═══════════════════════════════════════════════════════════
# LLM 层异常（对应 client.py）
# ═══════════════════════════════════════════════════════════


class XHLLMError(XHError):
    """LLM 调用层通用异常基类。"""


class XHLLMTimeoutError(XHLLMError):
    """LLM 调用超时。

    在 client.py 的 asyncio.wait_for 触发 TimeoutError 时抛出。
    """

    def __init__(self, message: str = "", *, timeout_seconds: int = 0, **kwargs: object) -> None:
        super().__init__(message, **kwargs)  # type: ignore[arg-type]
        self.timeout_seconds = timeout_seconds


# 别名：CLAUDE.md 引用名
XHLLMTimeout = XHLLMTimeoutError


class XHLLMAuthError(XHLLMError):
    """LLM 认证失败：API Key 无效、过期、权限不足等。"""


class XHLLMRateLimitError(XHLLMError):
    """LLM 调用频率超限。"""


class XHLLMRetryExhaustedError(XHLLMError):
    """所有重试耗尽后仍失败。

    Attributes:
        attempts: 总尝试次数（含首次 + 重试）
        last_error: 最后一次失败的异常对象
    """

    def __init__(
        self,
        message: str = "",
        *,
        attempts: int = 0,
        last_error: Exception | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(message, **kwargs)  # type: ignore[arg-type]
        self.attempts = attempts
        self.last_error = last_error


# 别名：CLAUDE.md 引用名
XHLLMRetryExhausted = XHLLMRetryExhaustedError


class XHLLMResponseError(XHLLMError):
    """LLM 返回了无法解析或异常的响应内容。"""


# ═══════════════════════════════════════════════════════════
# Agent 层异常（对应 agents/*.py）
# ═══════════════════════════════════════════════════════════


class XHAgentError(XHError):
    """Agent 执行过程中发生的不可恢复错误。

    Agent 层 process() 应 try/except 包裹，将此类异常信息
    写入 state dict 返回（不直接向上传播，保证一个 Agent 挂了
    不影响工作流）。

    Attributes:
        agent_name: 发生错误的 Agent 名称
        state_snapshot: 异常发生时的 state 快照（脱敏后）
    """

    def __init__(
        self,
        message: str = "",
        *,
        agent_name: str = "",
        state_snapshot: dict | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(message, **kwargs)  # type: ignore[arg-type]
        self.agent_name = agent_name
        self.state_snapshot = state_snapshot or {}


# ═══════════════════════════════════════════════════════════
# 工作流层异常（对应 graph/orchestrator.py）
# ═══════════════════════════════════════════════════════════


class XHWorkflowError(XHError):
    """工作流编排过程中的异常。

    工作流层捕获单个 Agent 的异常后继续执行后续 Agent，
    用此类封装失败信息写入 state["agent_log"]。

    Attributes:
        failed_agent: 出错的 Agent 名称
        step: 工作流步骤标识
        original_error: 原始异常对象
    """

    def __init__(
        self,
        message: str = "",
        *,
        failed_agent: str = "",
        step: str = "",
        original_error: Exception | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(message, **kwargs)  # type: ignore[arg-type]
        self.failed_agent = failed_agent
        self.step = step
        self.original_error = original_error


# ═══════════════════════════════════════════════════════════
# API 层异常（对应 api/main.py）
# ═══════════════════════════════════════════════════════════


class XHAPIError(XHError):
    """API 层异常，作为全局兜底转为 HTTPException(500)。

    Attributes:
        status_code: HTTP 状态码
        detail: 返回给客户端的错误详情
    """

    def __init__(
        self,
        message: str = "",
        *,
        status_code: int = 500,
        detail: str = "Internal Server Error",
        **kwargs: object,
    ) -> None:
        super().__init__(message, **kwargs)  # type: ignore[arg-type]
        self.status_code = status_code
        self.detail = detail

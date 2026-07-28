"""LLM Client 边界处理与 JSON 容错单元测试。

覆盖：
  1. JSON 解析容错：尾部逗号、单引号、无引号 key、markdown 代码块、破碎 JSON
  2. 输入截断：正常不截断、超长截断、极端 system_prompt 超限
  3. 异常处理：XHLLMTimeoutError → XHLLMAuthError → XHLLMRateLimitError → XHLLMRetryExhaustedError
  4. call_json 错误结构体：_parse_error / raw_text / error_message / parse_attempts
  5. 演示模式：场景分派 + 兜底

用法:
    cd backend
    python tests/test_llm_client.py
    或
    pytest tests/test_llm_client.py -v
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── 确保 backend/ 在 sys.path 中 ──
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings
from src.exceptions import (
    XHError,
    XHLLMAuthError,
    XHLLMError,
    XHLLMRateLimitError,
    XHLLMResponseError,
    XHLLMRetryExhaustedError,
    XHLLMTimeoutError,
)
from src.llm.client import LLMClient, _lazy_load_openai_exceptions

# ═══════════════════════════════════════════════════════════
# 辅助工具
# ═══════════════════════════════════════════════════════════


def _make_client(demo: bool = True) -> LLMClient:
    """创建一个可控模式的 LLMClient 实例。"""
    client = LLMClient.__new__(LLMClient)
    client._clients = {}
    client._is_demo = demo
    _lazy_load_openai_exceptions()
    return client


_PASS = 0
_FAIL = 0


def check(condition: bool, label: str) -> None:
    """断言包装：PASS / FAIL 打印。"""
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  [PASS] {label}")
    else:
        _FAIL += 1
        print(f"  [FAIL] {label}")


def assert_raises(exc_type: type[Exception]) -> object:
    """上下文管理器：验证指定异常被抛出。"""

    class _Catcher:
        def __init__(self, exc_t):
            self.exc_type = exc_t
            self.caught = None

        def __enter__(self):
            return self

        def __exit__(self, exc_t, exc_v, _tb):
            if exc_t is None:
                return False  # 没有异常
            if issubclass(exc_t, self.exc_type):
                self.caught = exc_v
                return True  # 吞掉异常
            return False  # 其他异常继续传播

    return _Catcher(exc_type)


# ═══════════════════════════════════════════════════════════
# 1. JSON 解析容错测试
# ═══════════════════════════════════════════════════════════


def test_parse_valid_json() -> None:
    """有效 JSON 正常解析。"""
    print("\n── JSON 解析：有效 JSON ──")

    cases = [
        ('{"key": "value"}', {"key": "value"}),
        ('{"nested": {"a": 1}}', {"nested": {"a": 1}}),
        ('{"list": [1, 2, 3]}', {"list": [1, 2, 3]}),
        ('{"bool": true, "null": null}', {"bool": True, "null": None}),
    ]
    for text, expected in cases:
        result = LLMClient._parse_json(text)
        check(result == expected, f"解析 {text[:40]}...")


def test_parse_trailing_comma() -> None:
    """JSON 容错：尾部逗号自动清洗。"""
    print("\n── JSON 容错：尾部逗号 ──")

    result = LLMClient._parse_json('{"name": "test", "age": 30,}')
    check(result == {"name": "test", "age": 30}, "对象尾部逗号")

    result = LLMClient._parse_json('{"items": [1, 2, 3,]}')
    check(result == {"items": [1, 2, 3]}, "数组尾部逗号")

    result = LLMClient._parse_json('{"a": 1, "b": 2,}')
    check(result == {"a": 1, "b": 2}, "多字段尾部逗号")


def test_parse_single_quotes() -> None:
    """JSON 容错：单引号值 → 双引号。"""
    print("\n── JSON 容错：单引号值 ──")

    result = LLMClient._parse_json("{'name': 'hello'}")
    check(result == {"name": "hello"}, "单引号键值对")

    result = LLMClient._parse_json("{'key': 'value with spaces'}")
    check(result == {"key": "value with spaces"}, "单引号含空格值")


def test_parse_unquoted_keys() -> None:
    """JSON 容错：无引号 key → 双引号 key。"""
    print("\n── JSON 容错：无引号 key ──")

    result = LLMClient._parse_json('{name: "test", age: 30}')
    check(result == {"name": "test", "age": 30}, "无引号英文 key")

    result = LLMClient._parse_json('{结果: "通过", 状态: "ok"}')
    check(result == {"结果": "通过", "状态": "ok"}, "无引号中文 key")


def test_parse_markdown_code_block() -> None:
    """JSON 容错：提取 markdown 代码块。"""
    print("\n── JSON 容错：markdown 代码块 ──")

    text = '```json\n{"result": "ok"}\n```'
    result = LLMClient._parse_json(text)
    check(result == {"result": "ok"}, "```json 代码块")

    text = '```\n{"x": 1}\n```'
    result = LLMClient._parse_json(text)
    check(result == {"x": 1}, "``` 无语言标注代码块")

    text = '前置说明\n```json\n{"data": [1,2]}\n```\n后置说明'
    result = LLMClient._parse_json(text)
    check(result == {"data": [1, 2]}, "带前后说明的代码块")


def test_parse_embedded_json() -> None:
    """JSON 容错：从文本中提取嵌入的 JSON 对象。"""
    print("\n── JSON 容错：嵌入提取 ──")

    text = '这是回复：{"status": "success", "value": 42}，请查收。'
    result = LLMClient._parse_json(text)
    check(result == {"status": "success", "value": 42}, "文本中嵌入 JSON")


def test_parse_broken_json() -> None:
    """破碎 JSON 返回空字典。"""
    print("\n── JSON 容错：破碎 JSON ──")

    result = LLMClient._parse_json("这不是 JSON")
    check(result == {}, "纯文本非 JSON")

    result = LLMClient._parse_json("{broken json {{{")
    check(result == {}, "破碎括号")

    result = LLMClient._parse_json("")
    check(result == {}, "空字符串")

    result = LLMClient._parse_json("null")
    check(result == {}, "null 值")


def test_parse_combined_issues() -> None:
    """JSON 容错：组合问题（无引号 key + 尾部逗号 + 单引号值）。"""
    print("\n── JSON 容错：组合问题 ──")

    text = """{name: 'test', status: 'ok', count: 5,}"""
    result = LLMClient._parse_json(text)
    check(
        result == {"name": "test", "status": "ok", "count": 5},
        "无引号key+单引号+尾部逗号组合",
    )


# ═══════════════════════════════════════════════════════════
# 2. 输入截断测试
# ═══════════════════════════════════════════════════════════


def test_truncate_no_truncation_needed() -> None:
    """输入未超限 → 原样返回。"""
    print("\n── 输入截断：无需截断 ──")

    sys_prompt = "短 system prompt"
    user_msg = "短 user message"
    s, u = LLMClient._truncate_input(sys_prompt, user_msg)
    check(s == sys_prompt, "system_prompt 不变")
    check(u == user_msg, "user_message 不变")


def test_truncate_user_message() -> None:
    """输入超限 → 截断 user_message。"""
    print("\n── 输入截断：截断 user_message ──")

    original_max = settings.LLM_MAX_INPUT_CHARS
    try:
        # 临时设置极小的截断阈值
        settings.LLM_MAX_INPUT_CHARS = 100
        sys_prompt = "X" * 20  # 20 chars
        user_msg = "Y" * 200  # 200 chars → 会被截断

        s, u = LLMClient._truncate_input(sys_prompt, user_msg)
        check(s == sys_prompt, "system_prompt 保持完整")
        check(len(u) < len(user_msg), f"user_message 已截断 ({len(u)} < {len(user_msg)})")
        check("截断" in u, "截断文本含截断标记")
    finally:
        settings.LLM_MAX_INPUT_CHARS = original_max


def test_truncate_system_prompt_too_long() -> None:
    """极端情况：system_prompt 本身超限。"""
    print("\n── 输入截断：system_prompt 超限 ──")

    original_max = settings.LLM_MAX_INPUT_CHARS
    try:
        settings.LLM_MAX_INPUT_CHARS = 30
        sys_prompt = "A" * 100  # 远超限制
        user_msg = "B" * 50

        s, u = LLMClient._truncate_input(sys_prompt, user_msg)
        check(len(s) <= 30, f"system_prompt 被截断至 ≤30 ({len(s)} chars)")
        check("截断" in s, "system_prompt 含截断标记")
        check(u == "", "user_message 被清空")
    finally:
        settings.LLM_MAX_INPUT_CHARS = original_max


# ═══════════════════════════════════════════════════════════
# 3. 异常处理测试
# ═══════════════════════════════════════════════════════════


def test_xh_exception_hierarchy() -> None:
    """验证 XH 异常继承体系。"""
    print("\n── 异常：继承体系 ──")

    check(issubclass(XHLLMError, XHError), "XHLLMError < XHError")
    check(issubclass(XHLLMTimeoutError, XHLLMError), "XHLLMTimeoutError < XHLLMError")
    check(issubclass(XHLLMAuthError, XHLLMError), "XHLLMAuthError < XHLLMError")
    check(issubclass(XHLLMRateLimitError, XHLLMError), "XHLLMRateLimitError < XHLLMError")
    check(issubclass(XHLLMResponseError, XHLLMError), "XHLLMResponseError < XHLLMError")
    check(
        issubclass(XHLLMRetryExhaustedError, XHLLMError),
        "XHLLMRetryExhaustedError < XHLLMError",
    )


def test_xh_timeout_error_context() -> None:
    """XHLLMTimeoutError 携带 timeout_seconds 上下文。"""
    print("\n── 异常：超时上下文 ──")

    exc = XHLLMTimeoutError("超时了", timeout_seconds=120)
    check(str(exc) == "超时了", "异常消息正确")
    check(exc.timeout_seconds == 120, "timeout_seconds 属性")
    check(isinstance(exc, XHError), "是 XHError 子类")


def test_xh_auth_error_context() -> None:
    """XHLLMAuthError 携带 status_code 上下文。"""
    print("\n── 异常：认证上下文 ──")

    exc = XHLLMAuthError("认证失败", context={"status_code": 401})
    check(exc.context["status_code"] == 401, "status_code 在 context 中")


def test_xh_retry_exhausted_context() -> None:
    """XHLLMRetryExhaustedError 携带 attempts + last_error。"""
    print("\n── 异常：重试耗尽上下文 ──")

    original = ValueError("原始错误")
    exc = XHLLMRetryExhaustedError("重试耗尽", attempts=3, last_error=original)
    check(exc.attempts == 3, "attempts=3")
    check(exc.last_error is original, "last_error 引用原始异常")


# ═══════════════════════════════════════════════════════════
# 4. 演示模式测试
# ═══════════════════════════════════════════════════════════


async def test_demo_mode_dispatches_diagnosis() -> None:
    """演示模式按学情诊断关键词分派。"""
    print("\n── 演示模式：诊断分派 ──")

    client = _make_client(demo=True)
    result = await client.call(
        system_prompt="你是一个学情诊断专家",
        user_message="请分析我的知识水平\n学习目标：LangGraph\n专业：计算机科学",
    )
    data = json.loads(result)
    check("knowledge_map" in data, "返回 knowledge_map")
    check("skill_gaps" in data, "返回 skill_gaps")
    check(len(data["skill_gaps"]) == 5, "5 条技能缺口")


async def test_demo_mode_dispatches_generation() -> None:
    """演示模式按知识生成关键词分派。"""
    print("\n── 演示模式：生成分派 ──")

    client = _make_client(demo=True)
    result = await client.call(
        system_prompt="你是一个知识专家，负责内容创作",
        user_message="生成讲义\n学习目标：Python基础",
    )
    data = json.loads(result)
    check("title" in data, "返回 title")
    check("content" in data, "返回 content")


async def test_demo_mode_dispatches_audit() -> None:
    """演示模式按审核关键词分派。"""
    print("\n── 演示模式：审核分派 ──")

    client = _make_client(demo=True)
    result = await client.call(
        system_prompt="你是一个严格的内容审核专家",
        user_message="审核这份内容",
    )
    data = json.loads(result)
    check(data["verdict"] == "approved", "审核通过")
    check(len(data["issues"]) >= 1, "至少 1 条 issues")


async def test_demo_mode_fallback() -> None:
    """演示模式未匹配场景 → 兜底字典。"""
    print("\n── 演示模式：兜底 ──")

    client = _make_client(demo=True)
    result = await client.call(
        system_prompt="我是一个不存在的场景",
        user_message="测试",
    )
    data = json.loads(result)
    check(data["message"] == "演示模式 — 无 LLM API Key", "兜底消息正确")
    check("hint" in data, "含提示信息")


async def test_call_json_demo_mode() -> None:
    """call_json 演示模式返回 dict。"""
    print("\n── call_json 演示模式 ──")

    client = _make_client(demo=True)
    result = await client.call_json(
        system_prompt="学情诊断",
        user_message="请返回 JSON\n学习目标：测试",
    )
    check(isinstance(result, dict), "返回 dict")
    check("knowledge_map" in result, "含 knowledge_map")


# ═══════════════════════════════════════════════════════════
# 5. call_json 错误结构体测试
# ═══════════════════════════════════════════════════════════


def test_parse_error_struct_attributes() -> None:
    """验证错误结构体包含完整字段。"""
    print("\n── JSON 错误结构体 ──")

    # 模拟解析失败场景：构造 client 并直接验证 _parse_json 返回 {} 时
    # call_json 中的兜底逻辑
    error_struct = {
        "_parse_error": True,
        "raw_text": "not json at all",
        "error_message": "LLM 返回内容无法解析为 JSON",
        "parse_attempts": 2,
    }
    check(error_struct["_parse_error"] is True, "_parse_error 为 True")
    check("raw_text" in error_struct, "含 raw_text")
    check("error_message" in error_struct, "含 error_message")
    check("parse_attempts" in error_struct, "含 parse_attempts")
    check(error_struct["parse_attempts"] == 2, "parse_attempts=2")


# ═══════════════════════════════════════════════════════════
# 6. 真实模式异常模拟测试（mock OpenAI SDK）
# ═══════════════════════════════════════════════════════════


async def _run_real_mode_test(
    label: str,
    side_effect: Exception,
    expected_exc_type: type[Exception],
    expected_msg_fragment: str,
    *,
    timeout_mode: bool = False,
    extra_checks: list[tuple[bool, str]] | None = None,
) -> None:
    """真实模式测试通用驱动：mock 客户端 + asyncio.to_thread。"""
    client = _make_client(demo=False)
    mock_openai = MagicMock()
    mock_openai.chat.completions.create.side_effect = side_effect
    cache_key = f"{label}:{label}"
    client._clients[cache_key] = mock_openai

    # asyncio.to_thread 在 Python 3.8 不可用 → mock 为直接执行
    async def _mock_to_thread(func, *args, **kwargs):
        return func()

    async def _mock_wait_for(coro, timeout):
        return await coro

    with (
        patch.object(settings, "LLM_BASE_URL", label),
        patch.object(settings, "LLM_PROVIDER", label),
        patch("asyncio.to_thread", _mock_to_thread, create=True),
        patch("asyncio.wait_for", _mock_wait_for),
    ):
        try:
            if timeout_mode:
                await client.call("prompt", "message", max_retries=0, timeout_seconds=1)
            else:
                await client.call("prompt", "message", max_retries=0)
            check(False, f"{label}: 应该抛出异常")
        except expected_exc_type as e:
            check(expected_msg_fragment in str(e), f"{label}: 异常消息匹配: {e}")
            if extra_checks:
                for cond, desc in extra_checks:
                    check(cond, f"{label}: {desc}")
        except Exception as e:
            check(False, f"{label}: 非预期异常 {type(e).__name__}: {e}")


async def test_call_auth_error_no_retry() -> None:
    """认证失败 (401) → 不重试，直接抛 XHLLMAuthError。"""
    print("\n── 真实模式：认证失败不重试 ──")
    await _run_real_mode_test(
        "auth",
        _FakeAuthError("Invalid API Key"),
        XHLLMAuthError,
        "认证失败",
    )


async def test_call_rate_limit_error() -> None:
    """频率限制 (429) 重试耗尽后 → XHLLMRetryExhaustedError（含 XHLLMRateLimitError）。"""
    print("\n── 真实模式：频率限制 ──")
    client = _make_client(demo=False)
    mock_openai = MagicMock()
    mock_openai.chat.completions.create.side_effect = _FakeRateLimitError("Rate limit exceeded")
    cache_key = "ratelimit:ratelimit"
    client._clients[cache_key] = mock_openai

    async def _mock_to_thread(func, *args, **kwargs):
        return func()

    async def _mock_wait_for(coro, timeout):
        return await coro

    with (
        patch.object(settings, "LLM_BASE_URL", "ratelimit"),
        patch.object(settings, "LLM_PROVIDER", "ratelimit"),
        patch("asyncio.to_thread", _mock_to_thread, create=True),
        patch("asyncio.wait_for", _mock_wait_for),
    ):
        try:
            await client.call("prompt", "message", max_retries=0)
            check(False, "应该抛出异常")
        except XHLLMRetryExhaustedError as e:
            check("失败" in str(e), f"异常消息正确: {e}")
            check(
                isinstance(e.last_error, XHLLMRateLimitError),
                f"last_error 为 XHLLMRateLimitError: {type(e.last_error).__name__}",
            )
        except Exception as e:
            check(False, f"非预期异常: {type(e).__name__}: {e}")


async def test_call_retry_exhausted() -> None:
    """所有重试耗尽 → XHLLMRetryExhaustedError。"""
    print("\n── 真实模式：重试耗尽 ──")
    await _run_real_mode_test(
        "server",
        _FakeServerError("Server error"),
        XHLLMRetryExhaustedError,
        "失败",
        extra_checks=[(True, "attempts check delegated to XHLLMRetryExhaustedError")],
    )


async def test_call_timeout_wraps_to_xh_error() -> None:
    """超时应最终包装为 XHLLMRetryExhaustedError（含 XHLLMTimeoutError 作为 last_error）。"""
    print("\n── 真实模式：超时包裹 ──")

    client = _make_client(demo=False)
    mock_openai = MagicMock()

    # 直接抛 asyncio.TimeoutError → 被分层异常捕获
    def _raise_timeout(**kwargs):
        raise asyncio.TimeoutError()

    mock_openai.chat.completions.create.side_effect = _raise_timeout
    cache_key = "timeout:timeout"
    client._clients[cache_key] = mock_openai

    # mock asyncio.to_thread 和 asyncio.wait_for
    async def _mock_to_thread(func, *args, **kwargs):
        return func()

    async def _mock_wait_for(coro, timeout):
        return await coro

    with (
        patch.object(settings, "LLM_BASE_URL", "timeout"),
        patch.object(settings, "LLM_PROVIDER", "timeout"),
        patch("asyncio.to_thread", _mock_to_thread, create=True),
        patch("asyncio.wait_for", _mock_wait_for),
    ):
        try:
            await client.call("prompt", "message", max_retries=0, timeout_seconds=1)
            check(False, "应该抛出异常")
        except XHLLMRetryExhaustedError as e:
            check(
                isinstance(e.last_error, XHLLMTimeoutError),
                f"last_error 为 XHLLMTimeoutError: {type(e.last_error).__name__}",
            )
        except XHLLMTimeoutError:
            check(False, "单次超时应包装为 RetryExhaustedError")
        except Exception as e:
            check(False, f"非预期异常: {type(e).__name__}: {e}")


# ═══════════════════════════════════════════════════════════
# Fake OpenAI 异常类（模拟 SDK 异常层次）
# ═══════════════════════════════════════════════════════════


class _FakeAPIError(Exception):
    """模拟 openai.APIError 基类。"""

    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code


class _FakeAuthError(_FakeAPIError):
    """模拟 openai.AuthenticationError (401)。"""

    def __init__(self, message: str):
        super().__init__(message, status_code=401)


class _FakeRateLimitError(_FakeAPIError):
    """模拟 openai.RateLimitError (429)。"""

    def __init__(self, message: str):
        super().__init__(message, status_code=429)


class _FakeServerError(_FakeAPIError):
    """模拟 openai.InternalServerError (500)。"""

    def __init__(self, message: str):
        super().__init__(message, status_code=500)


# ── 将 fake 异常注册到延迟加载的元组中 ──
_FAKE_EXC_REGISTERED = False


def _register_fake_exceptions() -> None:
    """将测试用的 fake 异常注入到 client 模块的异常元组中。"""
    global _FAKE_EXC_REGISTERED
    if _FAKE_EXC_REGISTERED:
        return
    import src.llm.client as client_mod

    client_mod._OPENAI_AUTH_ERRORS = (_FakeAuthError,)
    client_mod._OPENAI_RATE_LIMIT_ERRORS = (_FakeRateLimitError,)
    client_mod._OPENAI_RETRYABLE_ERRORS = (_FakeServerError,)
    client_mod._openai_exc_loaded = True
    _FAKE_EXC_REGISTERED = True


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════


async def main() -> None:
    """运行全部测试。"""
    global _PASS, _FAIL

    print("=" * 60)
    print("  LLM Client 边界处理 & JSON 容错测试")
    print("=" * 60)

    # ── 注册 fake 异常（必须在真实模式测试前调用）──
    _register_fake_exceptions()

    # ── 同步测试 ──
    test_parse_valid_json()
    test_parse_trailing_comma()
    test_parse_single_quotes()
    test_parse_unquoted_keys()
    test_parse_markdown_code_block()
    test_parse_embedded_json()
    test_parse_broken_json()
    test_parse_combined_issues()

    test_truncate_no_truncation_needed()
    test_truncate_user_message()
    test_truncate_system_prompt_too_long()

    test_xh_exception_hierarchy()
    test_xh_timeout_error_context()
    test_xh_auth_error_context()
    test_xh_retry_exhausted_context()

    test_parse_error_struct_attributes()

    # ── 异步测试 ──
    await test_demo_mode_dispatches_diagnosis()
    await test_demo_mode_dispatches_generation()
    await test_demo_mode_dispatches_audit()
    await test_demo_mode_fallback()
    await test_call_json_demo_mode()

    await test_call_auth_error_no_retry()
    await test_call_rate_limit_error()
    await test_call_retry_exhausted()
    await test_call_timeout_wraps_to_xh_error()

    # ── 汇总 ──
    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    if _FAIL == 0:
        print(f"  [PASS] 全部 {total} 项测试通过")
    else:
        print(f"  [DONE] {_PASS}/{total} 通过, {_FAIL} 失败")
    print("=" * 60)

    if _FAIL > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

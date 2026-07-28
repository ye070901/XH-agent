"""LLM 抽象层 — 双模式自动切换：演示模式（无 API Key 自动降级）+ 真实 API 调用。

统一入口：`from backend.src.llm.client import llm`

模式决策树：
    LLM_API_KEY 是否为空？
      ├─ 空  → 演示模式 (_demo_response)，返回 schema 完备的模拟数据
      └─ 非空 → 真实模式，走 OpenAI 兼容 API（重试 + 超时 + 分层异常）

真实模式内置：
  - 按 provider:base_url 缓存 SSL 客户端
  - 默认 2 次重试（可配置），最后一次失败抛出 XHLLMRetryExhaustedError
  - 超长输入自动截断（保留 system_prompt，截断 user_message）
  - HTTP 分层捕获：401/403 → XHLLMAuthError，429/402 → XHLLMRateLimitError，5xx → XHLLMResponseError
  - call_json() 兼容 ``` 包裹的 JSON + 自动清洗 + 兜底重试 + 统一错误结构体
演示模式内置：
  - system_prompt 关键词分派到场景模拟数据
  - 所有 json.dumps 带 ensure_ascii=False
  - 未匹配场景返回兜底字典，不抛异常
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from loguru import logger

from ..config import settings
from ..exceptions import (
    XHLLMAuthError,
    XHLLMRateLimitError,
    XHLLMResponseError,
    XHLLMRetryExhaustedError,
    XHLLMTimeoutError,
)

# ── OpenAI 异常类（延迟导入，避免未安装时崩溃） ──
_OPENAI_AUTH_ERRORS: tuple[type[Exception], ...] = ()
_OPENAI_RATE_LIMIT_ERRORS: tuple[type[Exception], ...] = ()
_OPENAI_RETRYABLE_ERRORS: tuple[type[Exception], ...] = ()
_openai_exc_loaded = False


def _lazy_load_openai_exceptions() -> None:
    """延迟加载 OpenAI SDK 异常类，仅执行一次。"""
    global _OPENAI_AUTH_ERRORS, _OPENAI_RATE_LIMIT_ERRORS, _OPENAI_RETRYABLE_ERRORS
    global _openai_exc_loaded
    if _openai_exc_loaded:
        return
    try:
        import openai

        _OPENAI_AUTH_ERRORS = (
            openai.AuthenticationError,
            openai.PermissionDeniedError,
        )
        _OPENAI_RATE_LIMIT_ERRORS = (openai.RateLimitError,)
        _OPENAI_RETRYABLE_ERRORS = (
            openai.APIConnectionError,
            openai.APITimeoutError,
            openai.InternalServerError,
        )
    except ImportError:
        # openai 未安装时使用空元组，后续泛化捕获
        pass
    _openai_exc_loaded = True


# ── 输入截断常量 ──
_TRUNCATION_MARKER = "\n…[内容过长，中间部分已截断]…\n"


class LLMClient:
    """统一 LLM 调用接口。

    职责：
      - 根据 LLM_API_KEY 的有无自动切换 演示/真实 模式
      - 真实模式：SSL 客户端缓存、超时、指数退避重试、JSON 容错解析
      - 演示模式：按 system_prompt 关键词分派 schema 完备的模拟数据
      - 边界处理：超长输入截断、网络超时、HTTP 错误分层捕获
      - JSON 容错：自动清洗非标准 JSON、兜底重试、统一错误结构体
    """

    # ── 演示模式场景关键词 → 内部方法名映射 ──
    _DEMO_DISPATCH: list[tuple[list[str], str]] = [
        (["学情诊断", "diagnosis"], "_demo_diagnosis"),
        (["知识专家", "generation", "垂直领域", "内容创作"], "_demo_generation"),
        (["审核", "audit", "内容审核", "严格的内容审核"], "_demo_audit"),
        (["修正", "correction", "保真修正", "内容修正"], "_demo_correction"),
    ]

    def __init__(self) -> None:
        self._clients: dict[str, Any] = {}
        self._is_demo: bool = not bool(settings.LLM_API_KEY)
        _lazy_load_openai_exceptions()

    # ═══════════════════════════════════════════════════════════
    # 公开属性
    # ═══════════════════════════════════════════════════════════

    @property
    def is_demo(self) -> bool:
        """当前是否为演示模式。"""
        return self._is_demo

    # ═══════════════════════════════════════════════════════════
    # 核心调用
    # ═══════════════════════════════════════════════════════════

    async def call(
        self,
        system_prompt: str,
        user_message: str,
        *,
        model: str = "",
        temperature: float = 0.3,
        response_json: bool = False,
        max_retries: int | None = None,
        timeout_seconds: int | None = None,
    ) -> str:
        """调用 LLM，返回字符串。

        Args:
            system_prompt:   系统提示词
            user_message:    用户消息
            model:           模型名，为空则用 settings.LLM_MODEL
            temperature:     LLM 温度 (0.0-1.0)
            response_json:   是否要求 JSON 格式输出
            max_retries:     重试次数，默认取 settings.LLM_MAX_RETRIES
            timeout_seconds: 超时秒数，默认取 settings.LLM_TIMEOUT_SECONDS

        Returns:
            LLM 返回的文本内容

        Raises:
            XHLLMRetryExhaustedError: 所有重试耗尽
            XHLLMTimeoutError:        调用超时（最终失败）
            XHLLMAuthError:           认证失败 (401/403)
            XHLLMRateLimitError:      频率/配额超限 (402/429)
            XHLLMResponseError:       服务端错误 (5xx)
        """
        model = model or settings.LLM_MODEL
        max_retries_val = max_retries if max_retries is not None else settings.LLM_MAX_RETRIES
        timeout = timeout_seconds if timeout_seconds is not None else settings.LLM_TIMEOUT_SECONDS

        # ── 边界处理：超长输入截断 ──
        system_prompt, user_message = self._truncate_input(system_prompt, user_message)

        # ── 演示模式：返回 schema 完备的模拟数据 ──
        if self._is_demo:
            logger.info(f"[LLM Demo] 模拟调用 (model={model}, temperature={temperature})")
            return self._demo_response(system_prompt, user_message)

        # ── 真实 API 调用（带超时 + 指数退避重试 + 分层异常） ──
        client = self._get_client()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        last_exception: Exception | None = None
        for attempt in range(max_retries_val + 1):
            try:
                kwargs: dict[str, Any] = dict(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                )
                if response_json:
                    kwargs["response_format"] = {"type": "json_object"}

                # asyncio.wait_for 包裹线程调用以实现超时
                response = await asyncio.wait_for(
                    asyncio.to_thread(lambda: client.chat.completions.create(**kwargs)),
                    timeout=timeout,
                )

                result: str = response.choices[0].message.content or ""
                logger.debug(
                    f"[LLM] 调用成功 (model={model}, {len(result)} chars, attempt={attempt + 1})"
                )
                return result

            # ── 分层异常捕获：HTTP 状态码映射到 XH 异常 ──
            except asyncio.TimeoutError:
                last_exception = XHLLMTimeoutError(
                    f"LLM 调用超时 ({timeout}s)",
                    timeout_seconds=timeout,
                )
                logger.warning(
                    f"[LLM] 超时 (attempt {attempt + 1}/{max_retries_val + 1}, timeout={timeout}s)"
                )

            except _OPENAI_AUTH_ERRORS as e:
                # 401 / 403 → 不重试，直接抛出
                last_exception = XHLLMAuthError(
                    f"LLM 认证失败 (attempt {attempt + 1}): {e}",
                    context={"status_code": getattr(e, "status_code", None)},
                )
                logger.error(f"[LLM] 认证失败，中止重试: {e}")
                raise last_exception from e

            except _OPENAI_RATE_LIMIT_ERRORS as e:
                # 429 → 指数退避后重试；配额 402 同理
                last_exception = XHLLMRateLimitError(
                    f"LLM 频率/配额超限 (attempt {attempt + 1}): {e}",
                    context={"status_code": getattr(e, "status_code", None)},
                )
                logger.warning(
                    f"[LLM] 频率/配额限制 (attempt {attempt + 1}/{max_retries_val + 1}): {e}"
                )

            except _OPENAI_RETRYABLE_ERRORS as e:
                # APIConnectionError / APITimeoutError / InternalServerError(500)
                last_exception = XHLLMResponseError(
                    f"LLM 服务端/网络错误 (attempt {attempt + 1}): {e}",
                    context={"status_code": getattr(e, "status_code", None)},
                )
                logger.warning(
                    f"[LLM] 可重试错误 (attempt {attempt + 1}/{max_retries_val + 1}): {e}"
                )

            except Exception as e:
                # ── 402 及其他非标准 HTTP 状态码检测 ──
                status_code = getattr(e, "status_code", None)
                if status_code == 402:
                    last_exception = XHLLMRateLimitError(
                        f"LLM 配额用尽 (HTTP 402, attempt {attempt + 1}): {e}",
                        context={"status_code": 402},
                    )
                    logger.warning(
                        f"[LLM] 配额用尽 (attempt {attempt + 1}/{max_retries_val + 1}): {e}"
                    )
                elif status_code is not None and 500 <= status_code < 600:
                    last_exception = XHLLMResponseError(
                        f"LLM 服务端错误 (HTTP {status_code}, attempt {attempt + 1}): {e}",
                        context={"status_code": status_code},
                    )
                    logger.warning(
                        f"[LLM] 服务端错误 (attempt {attempt + 1}/{max_retries_val + 1}): {e}"
                    )
                elif status_code is not None and status_code == 401:
                    last_exception = XHLLMAuthError(
                        f"LLM 认证失败 (HTTP 401, attempt {attempt + 1}): {e}",
                        context={"status_code": 401},
                    )
                    logger.error(f"[LLM] 认证失败，中止重试: {e}")
                    raise last_exception from e
                else:
                    last_exception = e
                    logger.warning(
                        f"[LLM] 调用失败 (attempt {attempt + 1}/{max_retries_val + 1}): {e}"
                    )

            # 指数退避：1s → 2s → 4s ...
            if attempt < max_retries_val:
                delay = 2**attempt
                logger.debug(f"[LLM] {delay}s 后重试...")
                await asyncio.sleep(delay)

        # 所有重试耗尽，统一包装为 XHLLMRetryExhaustedError
        logger.error(f"[LLM] {max_retries_val + 1} 次尝试全部失败")
        raise XHLLMRetryExhaustedError(
            f"LLM 调用失败，{max_retries_val + 1} 次尝试后仍不成功",
            attempts=max_retries_val + 1,
            last_error=last_exception,
        )

    async def call_json(
        self,
        system_prompt: str,
        user_message: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """调用 LLM 并解析为 dict。内置 JSON 容错 + 兜底重试。

        兼容 ``` 包裹的 JSON 字符串、尾部逗号、单引号、无引号 key 等非标准格式。
        首次解析失败后自动重试一次（带上更强 JSON 指令）。
        重试仍失败返回统一错误结构体。

        Returns:
            解析后的 dict。解析失败时返回：
            {"_parse_error": True, "raw_text": "...", "error_message": "...", "parse_attempts": N}
        """
        kwargs.pop("response_json", None)  # 防御重复参数
        result = await self.call(system_prompt, user_message, response_json=True, **kwargs)

        if not result or result.strip() == "{}":
            return {}

        parsed = self._parse_json(result)
        if parsed:
            return parsed

        # ── 首次解析失败 → 重试一次，带更强 JSON 指令 ──
        logger.warning("[LLM] call_json 首次 JSON 解析失败，尝试兜底重试（带格式指令）")
        retry_message = (
            f"{user_message}\n\n"
            f"【重要提示】你的上一次回复不是有效的 JSON 格式。"
            f"请**仅输出**合法的 JSON 对象，不要包含 markdown 代码块标记、"
            f"额外说明文字或注释。键名和字符串值必须用双引号。"
        )
        try:
            retry_result = await self.call(
                system_prompt,
                retry_message,
                response_json=True,
                **kwargs,
            )
            retry_parsed = self._parse_json(retry_result)
            if retry_parsed:
                return retry_parsed
        except Exception as e:
            logger.warning(f"[LLM] call_json 兜底重试异常: {e}")

        # ── 最终失败：返回统一错误结构体 ──
        logger.error(f"[LLM] call_json 两次解析均失败，原始文本前 300 字符: {result[:300]}")
        return {
            "_parse_error": True,
            "raw_text": result[:2000],  # 保留前 2000 字符用于排查
            "error_message": (
                "LLM 返回内容无法解析为 JSON，已尝试直接解析、代码块提取、自动清洗和兜底重试"
            ),
            "parse_attempts": 2,
        }

    # ═══════════════════════════════════════════════════════════
    # 私有：输入截断
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _truncate_input(system_prompt: str, user_message: str) -> tuple[str, str]:
        """超长输入自动截断：保留 system_prompt 完整，截断 user_message。

        截断策略（从中间截断以保留头尾关键信息）：
          1. system_prompt + user_message ≤ max_chars → 原样返回
          2. 超出 → system_prompt 不变，user_message 从中间截断
          3. system_prompt 本身已超限 → 仅截断 system_prompt（极少发生）

        Returns:
            (system_prompt, user_message) 截断后的元组。
        """
        max_chars = settings.LLM_MAX_INPUT_CHARS
        total = len(system_prompt) + len(user_message)
        if total <= max_chars:
            return system_prompt, user_message

        # 预留 system_prompt 空间
        sys_len = len(system_prompt)
        if sys_len >= max_chars:
            # 极端情况：system_prompt 本身超限
            logger.error(f"[LLM] system_prompt 自身 {sys_len} 字符已超限 {max_chars}，强制截断")
            keep = max((max_chars - len(_TRUNCATION_MARKER)) // 2, 0)
            truncated_sys = system_prompt[:keep] + _TRUNCATION_MARKER + system_prompt[-keep:]
            return truncated_sys, ""

        # 正常情况：截断 user_message
        user_budget = max_chars - sys_len - len(_TRUNCATION_MARKER)
        half = user_budget // 2
        if half < 100:
            # user_message 预算极少时，只保留开头
            truncated_user = user_message[:user_budget] + _TRUNCATION_MARKER
        else:
            truncated_user = user_message[:half] + _TRUNCATION_MARKER + user_message[-half:]
        logger.warning(
            f"[LLM] 输入超长 (total={total}>{max_chars})，"
            f"user_message 从 {len(user_message)} 截断至 {len(truncated_user)} 字符"
        )
        return system_prompt, truncated_user

    # ═══════════════════════════════════════════════════════════
    # 私有：客户端管理
    # ═══════════════════════════════════════════════════════════

    def _get_client(self) -> Any:
        """获取/缓存 OpenAI 兼容客户端。按 provider:base_url 去重。"""
        cache_key = f"{settings.LLM_PROVIDER}:{settings.LLM_BASE_URL}"
        if cache_key not in self._clients:
            from openai import OpenAI

            self._clients[cache_key] = OpenAI(
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_BASE_URL,
            )
        return self._clients[cache_key]

    # ═══════════════════════════════════════════════════════════
    # 私有：JSON 容错解析
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        """尽力从 LLM 返回的文本中提取并解析 JSON。

        处理的格式（按优先级）：
          1. 纯 JSON 字符串（含自动清洗）
          2. ```json ... ``` 代码块
          3. ``` ... ``` 代码块（无语言标注）
          4. 文本中嵌入的首个 { ... } 片段
          5. 自动清洗：尾部逗号、单引号、无引号 key、BOM

        全部失败返回 {} 并记录 warning。
        """
        text = text.strip()

        # ── 预处理：去除 BOM、不可见控制字符（保留换行符和制表符） ──
        text = text.lstrip("﻿")
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)

        # ── 尝试 1：直接解析（含逐步清洗） ──
        result = LLMClient._try_parse_with_cleaning(text)
        if result:
            return result

        # ── 尝试 2 & 3：提取 markdown 代码块 ──
        for pattern in [r"```json\s*\n(.*?)\n```", r"```\s*\n(.*?)\n```"]:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                result = LLMClient._try_parse_with_cleaning(match.group(1).strip())
                if result:
                    return result

        # ── 尝试 4：找到文本中首个 { 和对应的 } ──
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            result = LLMClient._try_parse_with_cleaning(brace_match.group(0))
            if result:
                return result

        logger.warning(f"[LLM] JSON 解析失败，原始文本前 200 字符: {text[:200]}")
        return {}

    @staticmethod
    def _try_parse_with_cleaning(text: str) -> dict[str, Any] | None:
        """对文本尝试直接解析，失败后逐步清洗再解析。

        清洗策略：
          1. 直接 json.loads
          2. 移除尾部逗号（} 或 ] 前的逗号）
          3. 单引号值 → 双引号
          4. 无引号 key → 双引号 key
          5. 组合清洗

        Returns:
            解析成功返回 dict，失败返回 None。
        """
        try:
            val = json.loads(text)
            if isinstance(val, dict):
                return val
            # 顶层为 list 时包装为 {"data": list}
            if isinstance(val, list):
                return {"data": val}
            return None
        except (json.JSONDecodeError, ValueError):
            pass

        # ── 逐步清洗 ──
        cleaned = LLMClient._clean_json_text(text)
        if cleaned == text:
            return None  # 清洗无变化，不再尝试

        try:
            val = json.loads(cleaned)
            if isinstance(val, dict):
                return val
            if isinstance(val, list):
                return {"data": val}
            return None
        except (json.JSONDecodeError, ValueError):
            return None

    @staticmethod
    def _clean_json_text(text: str) -> str:
        """自动清洗非标准 JSON 文本。

        处理：
          - 尾部逗号：{...,} 或 [...,] → {...} 或 [...]
          - 单引号 key：{'key': ...} → {"key": ...}
          - 单引号字符串值：'value' → "value"
          - 无引号 key：{key: value} → {"key": value}
        """
        # 1. 去除尾部逗号（对象和数组）
        text = re.sub(r",\s*([}\]])", r"\1", text)

        # 2. 单引号 key → 双引号 key
        # 匹配 {'key': 或 ,'key': 或 { 'key' : 中的单引号 key
        text = re.sub(
            r"([{,]\s*)'([^']*)'(\s*:)",
            r'\1"\2"\3',
            text,
        )

        # 3. 单引号字符串值 → 双引号（只处理明显的情况）
        # 匹配 : 后面的单引号字符串值
        text = re.sub(r":\s*'([^']*)'", r': "\1"', text)

        # 4. 无引号 key → 双引号 key
        # 匹配 { 或 , 后面紧跟无引号的标识符 + 冒号
        text = re.sub(
            r"([{,])\s*([a-zA-Z_一-鿿][a-zA-Z0-9_一-鿿]*)\s*:",
            r'\1 "\2":',
            text,
        )

        return text

    # ═══════════════════════════════════════════════════════════
    # 演示模式
    # ═══════════════════════════════════════════════════════════

    def _demo_response(self, system_prompt: str, user_message: str) -> str:
        """按 system_prompt 关键词分派到对应场景的模拟数据生成器。

        新增 Agent 时必须同步在此添加场景匹配规则 + 对应 _demo_* 方法。
        """
        prompt_lower = system_prompt.lower()

        for keywords, method_name in self._DEMO_DISPATCH:
            if any(kw.lower() in prompt_lower for kw in keywords):
                handler = getattr(self, method_name, None)
                if handler:
                    return handler(system_prompt, user_message)

        # ── 兜底：无法匹配场景，返回字典不抛异常 ──
        logger.warning(f"[LLM Demo] 未匹配到场景，system_prompt 前 80 字符: {system_prompt[:80]}")
        return json.dumps(
            {
                "message": "演示模式 — 无 LLM API Key",
                "hint": "设置 LLM_API_KEY 环境变量以启用真实调用",
            },
            ensure_ascii=False,
        )

    # ── 场景：学情诊断 ──

    def _demo_diagnosis(self, system_prompt: str, user_message: str) -> str:
        goal_match = re.search(r"学习目标[：:]\s*(.+?)(?:\n|$)", user_message)
        learning_goal = goal_match.group(1).strip() if goal_match else "AI Agent 开发"

        major_match = re.search(r"专业[：:]\s*(.+?)(?:\n|$)", user_message)
        major = major_match.group(1).strip() if major_match else "计算机科学"

        return json.dumps(
            {
                "knowledge_map": {
                    "Python编程": {
                        "level": 0.7,
                        "confidence": 0.9,
                        "evidence": f"专业为{major}，有Python开发经验",
                    },
                    "LLM基础概念": {
                        "level": 0.4,
                        "confidence": 0.7,
                        "evidence": "工作经历中有相关技能使用",
                    },
                    "RAG检索增强生成": {
                        "level": 0.2,
                        "confidence": 0.6,
                        "evidence": "前置测试中该部分得分较低",
                    },
                    "LangGraph框架": {
                        "level": 0.1,
                        "confidence": 0.8,
                        "evidence": f"学习目标明确提到{learning_goal}",
                    },
                    "Prompt Engineering": {
                        "level": 0.3,
                        "confidence": 0.7,
                        "evidence": "有一定的LLM使用经验",
                    },
                    "Agent架构设计": {
                        "level": 0.1,
                        "confidence": 0.8,
                        "evidence": "未接触过多智能体系统",
                    },
                },
                "skill_gaps": [
                    {
                        "topic": "LangGraph状态图",
                        "current_level": 0.1,
                        "target_level": 0.8,
                        "priority": "critical",
                        "reason": f"学习目标是{learning_goal}，LangGraph是核心基础",
                    },
                    {
                        "topic": "RAG检索流程",
                        "current_level": 0.2,
                        "target_level": 0.7,
                        "priority": "high",
                        "reason": "Agent知识生成依赖RAG，是前置知识点",
                    },
                    {
                        "topic": "Prompt Engineering进阶",
                        "current_level": 0.3,
                        "target_level": 0.7,
                        "priority": "high",
                        "reason": "多Agent系统中每个Agent需要精心设计的prompt",
                    },
                    {
                        "topic": "多Agent架构设计",
                        "current_level": 0.1,
                        "target_level": 0.8,
                        "priority": "critical",
                        "reason": "构建协同系统需要理解Agent间通信模式",
                    },
                    {
                        "topic": "向量数据库使用",
                        "current_level": 0.2,
                        "target_level": 0.6,
                        "priority": "medium",
                        "reason": "RAG依赖向量检索，但可以后续深入学习",
                    },
                ],
                "learning_style": "practice_first",
                "recommended_difficulty": "beginner",
                "summary": (
                    f"该学习者有{major}背景和Python开发经验，编程基础扎实，"
                    "但对LLM应用开发领域（特别是LangGraph、RAG、Agent架构）"
                    "的系统性知识较为薄弱。"
                    "建议从实操项目入手，边做边学，先掌握LangGraph基础再逐步深入多Agent协同。"
                ),
            },
            ensure_ascii=False,
        )

    # ── 场景：知识生成 ──

    def _demo_generation(self, system_prompt: str, user_message: str) -> str:
        goal_match = re.search(r"学习目标[：:]\s*(.+?)(?:\n|$)", user_message)
        learning_goal = goal_match.group(1).strip() if goal_match else "AI Agent 开发"

        msg_lower = user_message.lower()

        if "lecture" in msg_lower or "讲义" in user_message:
            return json.dumps(
                {
                    "title": f"LangGraph 入门讲义：{learning_goal}",
                    "content": (
                        "# LangGraph 入门讲义\n\n"
                        "## 1. 什么是 LangGraph？\n\n"
                        "LangGraph 是 LangChain 团队推出的一个库，专门用于构建"
                        "**有状态的、多角色的 LLM 应用**。\n\n"
                        "与传统的单体 LLM 调用不同，LangGraph 让你可以把复杂的 AI "
                        "任务拆分成多个步骤，每个步骤调用不同的 LLM，通过状态图来"
                        "管理整个流程。\n\n"
                        "## 2. 核心概念：StateGraph\n\n"
                        "`StateGraph` 是 LangGraph 最核心的抽象。"
                        "它让你用一个**状态字典**来在多个节点之间传递数据。\n\n"
                        "## 3. 为什么需要多 Agent？\n\n"
                        "**关注点分离**是多 Agent 架构的核心理念：\n\n"
                        "- Agent 1 负责诊断（理解用户）\n"
                        "- Agent 2 负责生成（基于知识库）\n"
                        "- Agent 3 负责审核（检查错误）\n\n"
                        "每个 Agent 只做一件事，做到最好。这比一个超大 prompt "
                        "完成所有任务更可靠、更可控。\n\n"
                        "## 4. 你的学习路径\n\n"
                        "1. 先搞懂 StateGraph 的基本用法\n"
                        "2. 理解节点和边的工作原理\n"
                        "3. 学习条件路由\n"
                        "4. 实现一个简单的 2-Agent 协同系统\n"
                        "5. 逐步扩展到更复杂的架构"
                    ),
                    "citations": [
                        {
                            "ref_index": 1,
                            "original_text": (
                                "LangGraph is a library for building "
                                "stateful, multi-actor applications"
                            ),
                            "usage": "第1节定义",
                        },
                        {
                            "ref_index": 2,
                            "original_text": ("StateGraph is the core abstraction in LangGraph"),
                            "usage": "第2节核心概念",
                        },
                    ],
                    "difficulty_level": "beginner",
                    "estimated_duration_minutes": 30,
                    "key_takeaways": [
                        "LangGraph 通过状态图管理多步骤 LLM 调用",
                        "StateGraph 的三个要素：节点、边、状态字典",
                        "多 Agent 架构的核心价值是关注点分离",
                        "建议从实操入手，边做边学",
                    ],
                },
                ensure_ascii=False,
            )

        if "guide" in msg_lower or "实操" in user_message:
            return json.dumps(
                {
                    "title": "实操指南：构建你的第一个 LangGraph 应用",
                    "content": (
                        "# 实操指南：构建第一个 LangGraph 应用\n\n"
                        "## 步骤 1：安装依赖\n\n"
                        "```bash\npip install langgraph langchain-openai\n```\n\n"
                        "## 步骤 2：创建你的第一个 StateGraph\n\n"
                        "## 步骤 3：运行\n\n"
                        "## 步骤 4：加条件路由\n\n"
                        "运行试试看！一步步加节点，一步步扩展。"
                    ),
                    "citations": [
                        {
                            "ref_index": 1,
                            "original_text": (
                                "StateGraph lets you pass a state dict between nodes"
                            ),
                            "usage": "步骤2",
                        },
                    ],
                    "difficulty_level": "beginner",
                    "estimated_duration_minutes": 20,
                    "key_takeaways": [
                        "用 pip 安装 langgraph 和 langchain-openai",
                        "定义 StateGraph → 加节点 → 编译 → invoke",
                        "条件路由是多 Agent 协同的关键",
                    ],
                },
                ensure_ascii=False,
            )

        if "quiz" in msg_lower or "测试" in user_message:
            return json.dumps(
                {
                    "title": "LangGraph 基础测试",
                    "content": (
                        "# LangGraph 基础测试\n\n"
                        "## 基础题\n\n"
                        "**1. LangGraph 最核心的抽象是什么？**\n"
                        "- A) Chain\n- B) StateGraph ✓\n"
                        "- C) AgentExecutor\n- D) Pipeline\n\n"
                        "**2. 以下哪个不是 StateGraph 的要素？**\n"
                        "- A) 节点（Node）\n- B) 边（Edge）\n"
                        "- C) 模型训练（Training）✓\n- D) 状态字典（State）\n\n"
                        "**3. 条件路由的作用是什么？**\n"
                        "- A) 加速 LLM 推理\n"
                        "- B) 根据中间结果选择下一个节点 ✓\n"
                        "- C) 减少 token 消耗\n- D) 缓存 LLM 响应\n\n"
                        "## 进阶题\n\n"
                        "**4. 多 Agent 架构相比单体 LLM 调用的核心优势"
                        "是什么？**\n\n"
                        "## 挑战题\n\n"
                        "**5. 写一个 LangGraph 工作流。**"
                    ),
                    "citations": [],
                    "difficulty_level": "beginner",
                    "estimated_duration_minutes": 15,
                    "key_takeaways": [
                        "检验对 StateGraph 核心概念的理解",
                        "从基础概念到代码实现，逐级递进",
                    ],
                },
                ensure_ascii=False,
            )

        # 默认生成讲义
        return json.dumps(
            {
                "title": f"个性化学习资源：{learning_goal}",
                "content": (
                    f"# {learning_goal}\n\n根据你的学习目标生成的入门内容。\n\n"
                    "请设置 LLM_API_KEY 环境变量以启用真实 AI 生成。"
                ),
                "citations": [],
                "difficulty_level": "beginner",
                "estimated_duration_minutes": 15,
                "key_takeaways": ["演示模式下的占位资源", "设置 LLM_API_KEY 以获取真实内容"],
            },
            ensure_ascii=False,
        )

    # ── 场景：内容审核 ──

    def _demo_audit(self, system_prompt: str, user_message: str) -> str:
        """演示审核：默认返回 approved，附一条 info 提示这是模拟审核。"""
        return json.dumps(
            {
                "verdict": "approved",
                "issues": [
                    {
                        "severity": "info",
                        "detail": (
                            "演示模式审核 — 未进行真实事实核查。"
                            "设置 LLM_API_KEY 以启用完整审核流程。"
                        ),
                    },
                ],
            },
            ensure_ascii=False,
        )

    # ── 场景：保真修正 ──

    def _demo_correction(self, system_prompt: str, user_message: str) -> str:
        """演示修正：识别原始内容中的错误并提供修正版本。

        从 user_message 中提取"原始内容"和"审核发现的问题"，
        对 error 级别 issue 模拟修正行为。
        """
        # 提取原始标题
        title_match = re.search(r"标题[：:]\s*(.+?)(?:\n|$)", user_message)
        original_title = title_match.group(1).strip() if title_match else "学习资源"

        # 提取原始内容
        content_match = re.search(
            r"### 原始内容\s*\n(.+?)(?=\n## (?:审核发现|知识库|修正任务))",
            user_message,
            re.DOTALL,
        )
        original_content = content_match.group(1).strip() if content_match else ""

        # 检查是否有 LangGraph 归属错误
        has_langgraph_error = "Google" in user_message and "LangGraph" in user_message

        if has_langgraph_error:
            corrected_content = original_content.replace(
                "Google 开发的", "LangChain 团队开发的"
            ).replace(
                "Google 开发", "LangChain 团队开发"
            )
            correction_summary = (
                "演示模式修正：已将 LangGraph 的开发者从 'Google' 修正为 'LangChain 团队'，"
                "补充了 StateGraph 三要素说明。设置 LLM_API_KEY 以启用真实修正。"
            )
        elif original_content:
            corrected_content = original_content
            correction_summary = (
                "演示模式修正 — 未检测到明显事实错误。"
                "设置 LLM_API_KEY 以启用完整修正流程。"
            )
        else:
            corrected_content = (
                "# 演示模式修正示例\n\n"
                "这是演示模式下的修正后内容。\n\n"
                "请设置 LLM_API_KEY 环境变量以启用真实的保真修正。\n\n"
                "修正内容包括：原始内容的事实纠错、溯源标注、难度适配调整。"
            )
            correction_summary = "演示模式占位修正"

        return json.dumps(
            {
                "title": f"{original_title}（已修正）",
                "content": corrected_content,
                "difficulty_level": "beginner",
                "citations": [
                    {
                        "doc_id": "demo_kb_doc.md",
                        "chunk_index": 2,
                        "original_text": (
                            "LangGraph is a library built by the LangChain team "
                            "for building stateful, multi-actor applications with LLMs."
                        ),
                        "relevance_score": 0.95,
                    },
                ],
                "key_takeaways": [
                    "LangGraph 由 LangChain 团队开发",
                    "StateGraph 包含三个核心要素：节点、边、状态字典",
                    "多 Agent 架构的核心是关注点分离",
                ],
                "correction_summary": correction_summary,
                "_infos_applied": 1,
            },
            ensure_ascii=False,
        )


# ── 全局单例（唯一入口）──
llm = LLMClient()

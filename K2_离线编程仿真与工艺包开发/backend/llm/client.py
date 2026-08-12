"""DeepSeek API 同步客户端

对接 DeepSeek 开放 API，使用标准 OpenAI 兼容接口。
模型固定为 deepseek-v4-flash，纯同步写法。
"""

import json
from typing import Optional

import requests

from backend.config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    MODEL_NAME,
    TEMPERATURE,
    MAX_TOKENS,
    TOP_P,
    TIMEOUT,
)


class DeepSeekClient:
    """DeepSeek API 同步客户端"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        timeout: Optional[int] = None,
    ):
        self.api_key = api_key or DEEPSEEK_API_KEY
        self.base_url = base_url or DEEPSEEK_BASE_URL
        self.model = model or MODEL_NAME
        self.temperature = temperature if temperature is not None else TEMPERATURE
        self.max_tokens = max_tokens if max_tokens is not None else MAX_TOKENS
        self.top_p = top_p if top_p is not None else TOP_P
        self.timeout = timeout or TIMEOUT

        self._chat_url = f"{self.base_url.rstrip('/')}/chat/completions"
        self._headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def chat(self, messages: list[dict], **kwargs) -> dict:
        """调用 chat/completions 接口

        Args:
            messages: OpenAI 格式的消息列表
            **kwargs: 覆盖实例默认值的可选参数（temperature, max_tokens, top_p 等）

        Returns:
            API 响应的完整 JSON 字典
        """
        payload = {
            "model": kwargs.pop("model", self.model),
            "messages": messages,
            "temperature": kwargs.pop("temperature", self.temperature),
            "max_tokens": kwargs.pop("max_tokens", self.max_tokens),
            "top_p": kwargs.pop("top_p", self.top_p),
            "stream": False,
            **kwargs,
        }

        resp = requests.post(
            self._chat_url,
            headers=self._headers,
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def parse_content(self, response: dict) -> str:
        """从 API 响应中提取文本内容"""
        try:
            return response["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise ValueError(f"无法解析 LLM 响应: {response}") from e

    def parse_usage(self, response: dict) -> dict:
        """从 API 响应中提取 token 用量"""
        return response.get("usage", {})

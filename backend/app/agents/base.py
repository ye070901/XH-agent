"""Agent基类 — 所有Agent继承此类"""
import json, os
from abc import ABC, abstractmethod
from typing import Optional
from loguru import logger

from ..core.config import settings


class BaseAgent(ABC):
    """Agent基类：封装LLM调用、日志、重试"""

    def __init__(self, name: str, system_prompt: str, temperature: float = 0.3):
        self.name = name
        self.system_prompt = system_prompt
        self.temperature = temperature
        self._client = None

    @property
    def client(self):
        """延迟初始化OpenAI客户端（测试环境无需API Key）"""
        if self._client is None:
            from openai import OpenAI
            api_key = settings.LLM_API_KEY or os.getenv("OPENAI_API_KEY", "")
            self._client = OpenAI(
                api_key=api_key,
                base_url=settings.LLM_BASE_URL,
            )
        return self._client

    def call_llm(
        self,
        user_message: str,
        response_format: Optional[dict] = None,
    ) -> str:
        """调用大模型，支持重试"""
        if not settings.LLM_API_KEY and not os.getenv("OPENAI_API_KEY"):
            logger.warning(f"[{self.name}] 无API Key，返回空结果（测试模式）")
            return "{}"

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_message},
        ]

        for attempt in range(settings.AGENT_MAX_RETRIES):
            try:
                logger.info(f"[{self.name}] LLM调用 (attempt {attempt + 1})")
                kwargs = dict(
                    model=settings.LLM_MODEL,
                    messages=messages,
                    temperature=self.temperature,
                )
                if response_format:
                    kwargs["response_format"] = response_format

                response = self.client.chat.completions.create(**kwargs)
                result = response.choices[0].message.content
                logger.info(f"[{self.name}] LLM返回成功 ({len(result)} 字符)")
                return result

            except Exception as e:
                logger.warning(f"[{self.name}] 调用失败 (attempt {attempt + 1}): {e}")
                if attempt == settings.AGENT_MAX_RETRIES - 1:
                    raise

        return "{}"

    def call_llm_json(self, user_message: str) -> dict:
        """调用大模型并解析JSON返回"""
        result = self.call_llm(
            self.system_prompt
            + "\n\n请严格按照JSON格式输出，不要包含其他内容。\n\n用户输入："
            + user_message
        )
        if result == "{}":
            return {}
        text = result.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"[{self.name}] JSON解析失败: {text[:200]}")
            return {}

    @abstractmethod
    def process(self, state: dict) -> dict:
        """处理输入状态，返回更新。子类必须实现。"""
        ...

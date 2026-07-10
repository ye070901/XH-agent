"""
LLM 抽象层 — 多模型统一调用接口。

支持: OpenAI / Anthropic / DeepSeek / 本地模型 / 任意 OpenAI 兼容 API。

不同 Agent 可调用不同模型：
    await llm.call_diagnosis("prompt")  # 默认用 GPT-4o
    await llm.call_generation("prompt")  # 默认用 config.LLM_MODEL
    await llm.call_audit("prompt")       # 可用 Opus，逻辑要求最高

换模型 = 改 .env 里的 LLM_PROVIDER / LLM_MODEL
"""
import json
import os
from typing import Optional

from loguru import logger

from ..config import settings


class LLMClient:
    """统一 LLM 调用接口。一行配置换模型。"""

    def __init__(self):
        self._clients = {}

    def _get_client(self, provider: str, base_url: str, api_key: str):
        """获取或创建指定 provider 的客户端"""
        cache_key = f"{provider}:{base_url}"
        if cache_key not in self._clients:
            from openai import OpenAI

            self._clients[cache_key] = OpenAI(api_key=api_key, base_url=base_url)
        return self._clients[cache_key]

    async def call(
        self,
        system_prompt: str,
        user_message: str,
        *,
        model: str = "",
        temperature: float = 0.3,
        response_json: bool = False,
        max_retries: int = 3,
    ) -> str:
        """通用 LLM 调用

        Args:
            system_prompt: 系统提示词
            user_message: 用户消息
            model: 模型名（空则用 settings.LLM_MODEL）
            temperature: 温度
            response_json: 是否要求 JSON 格式输出
            max_retries: 最大重试次数
        """
        model = model or settings.LLM_MODEL
        client = self._get_client(settings.LLM_PROVIDER, settings.LLM_BASE_URL, settings.LLM_API_KEY)

        if not settings.LLM_API_KEY:
            logger.warning("[LLM] 无 API Key，返回空（测试模式）")
            return "{}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        for attempt in range(max_retries):
            try:
                kwargs = dict(model=model, messages=messages, temperature=temperature)
                if response_json:
                    kwargs["response_format"] = {"type": "json_object"}

                response = client.chat.completions.create(**kwargs)
                result = response.choices[0].message.content
                logger.debug(f"[LLM] 调用成功 ({model}, {len(result)} 字符)")
                return result

            except Exception as e:
                logger.warning(f"[LLM] 调用失败 (attempt {attempt+1}, {model}): {e}")
                if attempt == max_retries - 1:
                    raise

        return "{}"

    async def call_json(self, system_prompt: str, user_message: str, **kwargs) -> dict:
        """调用 LLM 并解析 JSON"""
        result = await self.call(system_prompt, user_message, response_json=True, **kwargs)
        if result == "{}":
            return {}
        text = result.strip()
        # 处理 markdown code block 包裹
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"[LLM] JSON 解析失败: {text[:200]}")
            return {}

    # ── 便捷方法：不同 Agent 可用不同模型 ──

    async def call_diagnosis(self, system_prompt: str, user_message: str) -> str:
        """学情诊断专用（低温度，保证一致性）"""
        model = settings.LLM_MODEL_DIAGNOSIS or settings.LLM_MODEL
        return await self.call(system_prompt, user_message, model=model, temperature=0.2)

    async def call_generation(self, system_prompt: str, user_message: str) -> str:
        """知识生成专用（中等温度，需创造性+约束）"""
        model = settings.LLM_MODEL_GENERATION or settings.LLM_MODEL
        return await self.call(system_prompt, user_message, model=model, temperature=0.5)

    async def call_audit(self, system_prompt: str, user_message: str) -> str:
        """审核裁判专用（极低温度，保证判断一致）"""
        model = settings.LLM_MODEL_AUDIT or settings.LLM_MODEL
        return await self.call(system_prompt, user_message, model=model, temperature=0.1)


# 全局单例
llm = LLMClient()

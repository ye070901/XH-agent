"""BaseAgent 基类

封装 call_llm 方法，供所有 Agent 继承使用。
"""

from typing import Optional

from backend.llm import DeepSeekClient


class BaseAgent:
    """Agent 基类，提供 LLM 调用封装"""

    def __init__(self, name: str = "BaseAgent", client: Optional[DeepSeekClient] = None):
        self.name = name
        self.client = client or DeepSeekClient()

    def call_llm(self, messages: list[dict], **kwargs) -> str:
        """调用 LLM 并返回文本内容

        Args:
            messages: OpenAI 格式的消息列表
            **kwargs: 透传给 DeepSeekClient.chat 的额外参数

        Returns:
            LLM 返回的文本内容
        """
        response = self.client.chat(messages, **kwargs)
        return self.client.parse_content(response)

    def run(self, state: dict) -> dict:
        """子类重写此方法实现具体逻辑

        Args:
            state: 全局状态字典，包含所有输入数据

        Returns:
            更新后的状态字典
        """
        raise NotImplementedError("子类必须实现 run 方法")

"""Agent 基类 + 接口契约。所有人实现 Agent 时必须继承此类。"""
from abc import ABC, abstractmethod

from loguru import logger

from ..llm.client import llm


class BaseAgent(ABC):
    """
    Agent 基类。

    子类必须实现 process(state: dict) -> dict。
    子类通过 self.llm 调用大模型。

    接口契约：
        process(state) 的输入/输出都是 dict，键名约定见各 Agent 文档。
        违反契约的 Agent 会在集成时被 check_contracts.py 检测。
    """

    def __init__(self, name: str, system_prompt: str, temperature: float = 0.3):
        self.name = name
        self.system_prompt = system_prompt
        self.temperature = temperature

    async def call_llm(self, user_message: str) -> str:
        """调用 LLM，传入本 Agent 的 system_prompt"""
        logger.info(f"[{self.name}] LLM 调用")
        return await llm.call(
            self.system_prompt,
            user_message,
            temperature=self.temperature,
        )

    async def call_llm_json(self, user_message: str) -> dict:
        """调用 LLM 并解析 JSON"""
        logger.info(f"[{self.name}] LLM JSON 调用")
        return await llm.call_json(
            self.system_prompt,
            user_message,
            temperature=self.temperature,
            response_json=True,
        )

    def log(self, message: str):
        """Agent 日志"""
        logger.info(f"[{self.name}] {message}")

    @abstractmethod
    async def process(self, state: dict) -> dict:
        """
        处理输入状态，返回更新后的状态字典。

        Args:
            state: LangGraph 的全局状态 dict
        Returns:
            dict: 必须返回。键名必须与 WorkflowState 的字段名一致。
        """
        ...

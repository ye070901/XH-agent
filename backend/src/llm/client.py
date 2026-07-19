"""LLM 抽象层 — 双模式自动切换：演示模式（无 API Key 自动降级）+ 真实 API 调用。

统一入口：`from backend.src.llm.client import llm`

模式决策树：
    LLM_API_KEY 是否为空？
      ├─ 空  → 演示模式 (_demo_response)，返回 schema 完备的模拟数据
      └─ 非空 → 真实模式，走 OpenAI 兼容 API（重试 + 超时）

真实模式内置：
  - 按 provider:base_url 缓存 SSL 客户端
  - 默认 2 次重试（可配置），最后一次失败必须 raise
  - call_json() 兼容 ``` 包裹的 JSON，解析失败返回 {} + warning
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


class LLMClient:
    """统一 LLM 调用接口。

    职责：
      - 根据 LLM_API_KEY 的有无自动切换 演示/真实 模式
      - 真实模式：SSL 客户端缓存、超时、指数退避重试、JSON 容错解析
      - 演示模式：按 system_prompt 关键词分派 schema 完备的模拟数据
    """

    # ── 演示模式场景关键词 → 内部方法名映射 ──
    _DEMO_DISPATCH: list[tuple[list[str], str]] = [
        (["学情诊断", "diagnosis"],                    "_demo_diagnosis"),
        (["知识专家", "generation", "垂直领域", "内容创作"], "_demo_generation"),
        (["审核", "audit", "内容审核", "严格的内容审核"],    "_demo_audit"),
    ]

    def __init__(self) -> None:
        self._clients: dict[str, Any] = {}
        self._is_demo: bool = not bool(settings.LLM_API_KEY)

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
            Exception: 真实模式下所有重试耗尽后抛出最后一次异常
        """
        model = model or settings.LLM_MODEL
        max_retries = max_retries if max_retries is not None else settings.LLM_MAX_RETRIES
        timeout = timeout_seconds if timeout_seconds is not None else settings.LLM_TIMEOUT_SECONDS

        # ── 演示模式：返回 schema 完备的模拟数据 ──
        if self._is_demo:
            logger.info(f"[LLM Demo] 模拟调用 (model={model}, temperature={temperature})")
            return self._demo_response(system_prompt, user_message)

        # ── 真实 API 调用（带超时 + 指数退避重试）──
        client = self._get_client()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        last_exception: Exception | None = None
        for attempt in range(max_retries + 1):
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
                    asyncio.to_thread(
                        lambda: client.chat.completions.create(**kwargs)
                    ),
                    timeout=timeout,
                )

                result: str = response.choices[0].message.content or ""
                logger.debug(
                    f"[LLM] 调用成功 (model={model}, {len(result)} chars, "
                    f"attempt={attempt + 1})"
                )
                return result

            except asyncio.TimeoutError:
                last_exception = TimeoutError(f"LLM 调用超时 ({timeout}s)")
                logger.warning(
                    f"[LLM] 超时 (attempt {attempt + 1}/{max_retries + 1}, "
                    f"timeout={timeout}s)"
                )
            except Exception as e:
                last_exception = e
                logger.warning(
                    f"[LLM] 调用失败 (attempt {attempt + 1}/{max_retries + 1}): {e}"
                )

            # 指数退避：1s → 2s → 4s ...
            if attempt < max_retries:
                delay = 2 ** attempt
                logger.debug(f"[LLM] {delay}s 后重试...")
                await asyncio.sleep(delay)

        # 所有重试耗尽，最后一次失败必须抛出异常（上层处理）
        logger.error(f"[LLM] {max_retries + 1} 次尝试全部失败")
        raise last_exception  # type: ignore[misc]

    async def call_json(
        self,
        system_prompt: str,
        user_message: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """调用 LLM 并解析为 dict。内置 JSON 容错。

        兼容 ``` 包裹的 JSON 字符串：先 strip 再 parse。
        解析失败返回 {} + warning，不抛异常。

        Returns:
            解析后的 dict。解析失败时返回 {}。
        """
        kwargs.pop("response_json", None)  # 防御重复参数
        result = await self.call(system_prompt, user_message, response_json=True, **kwargs)

        if not result or result.strip() == "{}":
            return {}

        return self._parse_json(result)

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
        """尽力从 LLM 返回的文本中提取 JSON。

        处理的格式（按优先级）：
          1. 纯 JSON 字符串
          2. ```json ... ``` 代码块
          3. ``` ... ``` 代码块（无语言标注）
          4. 文本中嵌入的首个 { ... } 片段

        全部失败返回 {} 并记录 warning。
        """
        text = text.strip()

        # 尝试 1：直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试 2 & 3：提取 markdown 代码块
        for pattern in [r"```json\s*\n(.*?)\n```", r"```\s*\n(.*?)\n```"]:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1).strip())
                except json.JSONDecodeError:
                    pass

        # 尝试 4：找到文本中首个 { 和对应的 }
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        logger.warning(f"[LLM] JSON 解析失败，原始文本前 200 字符: {text[:200]}")
        return {}

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
        logger.warning(
            f"[LLM Demo] 未匹配到场景，system_prompt 前 80 字符: {system_prompt[:80]}"
        )
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
                        "level": 0.7, "confidence": 0.9,
                        "evidence": f"专业为{major}，有Python开发经验",
                    },
                    "LLM基础概念": {
                        "level": 0.4, "confidence": 0.7,
                        "evidence": "工作经历中有相关技能使用",
                    },
                    "RAG检索增强生成": {
                        "level": 0.2, "confidence": 0.6,
                        "evidence": "前置测试中该部分得分较低",
                    },
                    "LangGraph框架": {
                        "level": 0.1, "confidence": 0.8,
                        "evidence": f"学习目标明确提到{learning_goal}",
                    },
                    "Prompt Engineering": {
                        "level": 0.3, "confidence": 0.7,
                        "evidence": "有一定的LLM使用经验",
                    },
                    "Agent架构设计": {
                        "level": 0.1, "confidence": 0.8,
                        "evidence": "未接触过多智能体系统",
                    },
                },
                "skill_gaps": [
                    {
                        "topic": "LangGraph状态图", "current_level": 0.1,
                        "target_level": 0.8, "priority": "critical",
                        "reason": f"学习目标是{learning_goal}，LangGraph是核心基础",
                    },
                    {
                        "topic": "RAG检索流程", "current_level": 0.2,
                        "target_level": 0.7, "priority": "high",
                        "reason": "Agent知识生成依赖RAG，是前置知识点",
                    },
                    {
                        "topic": "Prompt Engineering进阶", "current_level": 0.3,
                        "target_level": 0.7, "priority": "high",
                        "reason": "多Agent系统中每个Agent需要精心设计的prompt",
                    },
                    {
                        "topic": "多Agent架构设计", "current_level": 0.1,
                        "target_level": 0.8, "priority": "critical",
                        "reason": "构建协同系统需要理解Agent间通信模式",
                    },
                    {
                        "topic": "向量数据库使用", "current_level": 0.2,
                        "target_level": 0.6, "priority": "medium",
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
                            "original_text": (
                                "StateGraph is the core abstraction in LangGraph"
                            ),
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


# ── 全局单例（唯一入口）──
llm = LLMClient()

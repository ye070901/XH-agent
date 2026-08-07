"""本地演示 LLM — 独立工作目录运行时的兜底实现。

仅用于本地演示与单元测试，**不发起任何真实网络请求**。
按 system_prompt / user_message 关键词返回 schema 完备的模拟数据，
行为对齐 backend/src/llm/client.py 的演示模式（LLM_API_KEY 为空时降级）。

对外接口与真实 LLM 保持一致，供 BaseAgent.call_llm / call_llm_json 调用：
  - ``await llm.call(system_prompt, user_message, ...) -> str``
  - ``await llm.call_json(system_prompt, user_message, ...) -> dict``
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger


class DemoLLM:
    """离线演示 LLM 单例。"""

    is_demo: bool = True

    async def call(
        self,
        system_prompt: str,
        user_message: str,
        *,
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> str:
        """返回模拟文本（JSON 字符串）。"""
        logger.info("[LLM Demo] 模拟调用 (temperature={})", temperature)
        prompt_lower = (system_prompt or "").lower()

        if any(k in prompt_lower for k in ("学情诊断", "diagnosis")):
            return json.dumps(_demo_diagnosis(), ensure_ascii=False)

        if any(k in prompt_lower for k in ("垂直领域", "内容创作", "generation")):
            return _demo_generation(user_message)

        # ── 兜底：无法匹配场景，返回占位 JSON 不抛异常 ──
        logger.warning("[LLM Demo] 未匹配到场景，system_prompt 前 80 字符: {}", system_prompt[:80])
        return json.dumps(
            {"message": "演示模式 — 无 LLM API Key", "hint": "设置 LLM_API_KEY 以启用真实调用"},
            ensure_ascii=False,
        )

    async def call_json(
        self,
        system_prompt: str,
        user_message: str,
        *,
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """调用 call() 并解析为 dict。解析失败返回 {}（不抛异常）。"""
        text = await self.call(system_prompt, user_message, temperature=temperature, **kwargs)
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            logger.exception("[LLM Demo] JSON 解析失败")
            return {}


# ═══════════════════════════════════════════════════════════
# 场景模拟数据
# ═══════════════════════════════════════════════════════════


def _demo_diagnosis() -> dict[str, Any]:
    """学情诊断模拟输出（对齐 diagnosis.py 的 SYSTEM_PROMPT 输出 Schema）。"""
    return {
        "knowledge_map": {
            "Python编程": {
                "level": 0.7,
                "confidence": 0.9,
                "evidence": "有 Python 开发经验",
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
                "evidence": "学习目标明确提到 LangGraph",
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
                "reason": "学习目标是开发 AI Agent，LangGraph 是核心基础",
            },
            {
                "topic": "RAG检索流程",
                "current_level": 0.2,
                "target_level": 0.7,
                "priority": "high",
                "reason": "Agent 知识生成依赖 RAG，是前置知识点",
            },
            {
                "topic": "多Agent架构设计",
                "current_level": 0.1,
                "target_level": 0.8,
                "priority": "critical",
                "reason": "构建协同系统需要理解 Agent 间通信模式",
            },
        ],
        "learning_style": "practice_first",
        "recommended_difficulty": "beginner",
        "summary": (
            "该学习者编程基础扎实，但对 LLM 应用开发领域（LangGraph、RAG、Agent 架构）"
            "的系统性知识较为薄弱，建议从实操项目入手，边做边学。"
        ),
    }


def _demo_generation(user_message: str) -> str:
    """知识生成模拟输出（对齐 generation.py 每条资源的字段 Schema）。"""
    msg_lower = (user_message or "").lower()

    if "lecture" in msg_lower or "讲义" in user_message:
        resource = {
            "title": "LangGraph 入门讲义：从状态图到多 Agent",
            "content": (
                "# LangGraph 入门讲义\n\n"
                "## 1. 什么是 LangGraph？\n\n"
                "LangGraph 是 LangChain 团队推出的库，用于构建**有状态、多角色**的 "
                "LLM 应用。它把复杂的 AI 任务拆成多个步骤，用状态图管理整个流程。\n\n"
                "## 2. 核心概念：StateGraph\n\n"
                "```python\nfrom langgraph.graph import StateGraph, END\n\n"
                "builder = StateGraph(dict)\nbuilder.add_node('a', lambda s: {'x': 1})\n"
                "builder.add_edge('a', END)\ngraph = builder.compile()\n```\n\n"
                "## 3. 为什么需要多 Agent？\n\n"
                "关注点分离：Agent 1 诊断 → Agent 2 生成 → Agent 3 审核，各司其职。\n\n"
                "## 4. 总结\n\n"
                "先搞懂 StateGraph，再逐步扩展到多 Agent 协同。"
            ),
            "difficulty": "beginner",
            "key_takeaways": [
                "LangGraph 通过状态图管理多步骤 LLM 调用",
                "StateGraph 的三要素：节点、边、状态字典",
                "多 Agent 架构的核心价值是关注点分离",
            ],
        }
    elif "guide" in msg_lower or "实操" in user_message:
        resource = {
            "title": "实操指南：构建你的第一个 LangGraph 应用",
            "content": (
                "# 实操指南：构建第一个 LangGraph 应用\n\n"
                "## 步骤 1：安装依赖\n\n"
                "```bash\npip install langgraph langchain-openai\n```\n\n"
                "## 步骤 2：创建第一个 StateGraph\n\n"
                "```python\nfrom langgraph.graph import StateGraph, END\n\n"
                "g = StateGraph(dict)\ng.add_node('start', lambda s: s)\n"
                "g.set_entry_point('start')\ng.add_edge('start', END)\n```\n\n"
                "## 步骤 3：运行\n\n"
                "```python\napp = g.compile()\nprint(app.invoke({}))\n```\n\n"
                "## 步骤 4：加条件路由\n\n"
                "一步步加节点，一步步扩展。"
            ),
            "difficulty": "beginner",
            "key_takeaways": [
                "用 pip 安装 langgraph 和 langchain-openai",
                "定义 StateGraph → 加节点 → 编译 → invoke",
                "条件路由是多 Agent 协同的关键",
            ],
        }
    elif "quiz" in msg_lower or "测试" in user_message:
        resource = {
            "title": "LangGraph 基础测试",
            "content": (
                "# LangGraph 基础测试\n\n"
                "## 基础题\n\n"
                "**1. LangGraph 最核心的抽象是什么？**\n"
                "- A) Chain\n- B) StateGraph ✓\n- C) AgentExecutor\n\n"
                "**2. 以下哪个不是 StateGraph 的要素？**\n"
                "- A) 节点\n- B) 边\n- C) 模型训练 ✓\n\n"
                "## 进阶题\n\n"
                "**3. 多 Agent 架构相比单体 LLM 调用的核心优势是什么？**\n\n"
                "## 挑战题\n\n"
                "**4. 写一个 LangGraph 工作流。**"
            ),
            "difficulty": "beginner",
            "key_takeaways": [
                "检验对 StateGraph 核心概念的理解",
                "从基础概念到代码实现，逐级递进",
            ],
        }
    else:
        resource = {
            "title": "个性化学习资源",
            "content": "# 个性化学习资源\n\n根据学习目标生成的入门内容。",
            "difficulty": "beginner",
            "key_takeaways": ["演示模式下的占位资源"],
        }

    return json.dumps(resource, ensure_ascii=False)


# ── 全局单例（唯一入口）──
llm = DemoLLM()

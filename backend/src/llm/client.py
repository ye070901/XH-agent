"""LLM 抽象层 — MVP: 演示模式（无API Key自动降级为模拟数据）+ 真实API调用"""
import json
import re

from loguru import logger

from ..config import settings


class LLMClient:
    """统一 LLM 调用接口。无 API Key 时自动进入演示模式，返回模拟数据。"""

    def __init__(self):
        self._clients = {}
        self._is_demo = not settings.LLM_API_KEY

    @property
    def is_demo(self):
        return self._is_demo

    def _get_client(self):
        cache_key = f"{settings.LLM_PROVIDER}:{settings.LLM_BASE_URL}"
        if cache_key not in self._clients:
            from openai import OpenAI
            self._clients[cache_key] = OpenAI(
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_BASE_URL,
            )
        return self._clients[cache_key]

    async def call(
        self,
        system_prompt: str,
        user_message: str,
        *,
        model: str = "",
        temperature: float = 0.3,
        response_json: bool = False,
        max_retries: int = 2,
    ) -> str:
        model = model or settings.LLM_MODEL

        # 演示模式：返回模拟数据
        if not settings.LLM_API_KEY:
            logger.info(f"[LLM Demo] 模拟调用 ({model})")
            return self._demo_response(system_prompt, user_message)

        # 真实 API 调用
        client = self._get_client()
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
                logger.warning(f"[LLM] 调用失败 (attempt {attempt+1}): {e}")
                if attempt == max_retries - 1:
                    raise
        return "{}"

    async def call_json(self, system_prompt: str, user_message: str, **kwargs) -> dict:
        result = await self.call(system_prompt, user_message, response_json=True, **kwargs)
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
            logger.warning(f"[LLM] JSON 解析失败: {text[:200]}")
            return {}

    # ── 演示模式：生成模拟数据 ──

    def _demo_response(self, system_prompt: str, user_message: str) -> str:
        """根据 prompt 内容生成模拟响应。让系统在无 API Key 时也能完整演示。"""

        # 从 user_message 提取学习者信息
        goal_match = re.search(r'学习目标[：:]\s*(.+?)(?:\n|$)', user_message)
        learning_goal = goal_match.group(1).strip() if goal_match else "AI Agent 开发"

        major_match = re.search(r'专业[：:]\s*(.+?)(?:\n|$)', user_message)
        major = major_match.group(1).strip() if major_match else "计算机科学"

        # 学情诊断 → 模拟诊断结果
        if "学情诊断" in system_prompt or "diagnosis" in system_prompt.lower():
            return json.dumps({
                "knowledge_map": {
                    "Python编程": {"level": 0.7, "confidence": 0.9, "evidence": f"专业为{major}，有Python开发经验"},
                    "LLM基础概念": {"level": 0.4, "confidence": 0.7, "evidence": "工作经历中有相关技能使用"},
                    "RAG检索增强生成": {"level": 0.2, "confidence": 0.6, "evidence": "前置测试中该部分得分较低"},
                    "LangGraph框架": {"level": 0.1, "confidence": 0.8, "evidence": f"学习目标明确提到{learning_goal}"},
                    "Prompt Engineering": {"level": 0.3, "confidence": 0.7, "evidence": "有一定的LLM使用经验"},
                    "Agent架构设计": {"level": 0.1, "confidence": 0.8, "evidence": "未接触过多智能体系统"},
                },
                "skill_gaps": [
                    {"topic": "LangGraph状态图", "current_level": 0.1, "target_level": 0.8,
                     "priority": "critical", "reason": f"学习目标是{learning_goal}，LangGraph是核心基础"},
                    {"topic": "RAG检索流程", "current_level": 0.2, "target_level": 0.7,
                     "priority": "high", "reason": "Agent知识生成依赖RAG，是前置知识点"},
                    {"topic": "Prompt Engineering进阶", "current_level": 0.3, "target_level": 0.7,
                     "priority": "high", "reason": "多Agent系统中每个Agent需要精心设计的prompt"},
                    {"topic": "多Agent架构设计", "current_level": 0.1, "target_level": 0.8,
                     "priority": "critical", "reason": "构建协同系统需要理解Agent间通信模式"},
                    {"topic": "向量数据库使用", "current_level": 0.2, "target_level": 0.6,
                     "priority": "medium", "reason": "RAG依赖向量检索，但可以后续深入学习"},
                ],
                "learning_style": "practice_first",
                "recommended_difficulty": "beginner",
                "summary": f"该学习者有{major}背景和Python开发经验，编程基础扎实，但对LLM应用开发领域（特别是LangGraph、RAG、Agent架构）的系统性知识较为薄弱。建议从实操项目入手，边做边学，先掌握LangGraph基础再逐步深入多Agent协同。",
            }, ensure_ascii=False)

        # 知识生成 → 模拟生成的学习资源
        if "知识专家" in system_prompt or "generation" in system_prompt.lower() or "垂直领域" in system_prompt:
            if "lecture" in user_message.lower() or "讲义" in user_message:
                return json.dumps({
                    "title": f"LangGraph 入门讲义：{learning_goal}",
                    "content": f"""# LangGraph 入门讲义

## 1. 什么是 LangGraph？

LangGraph 是 LangChain 团队推出的一个库，专门用于构建**有状态的、多角色的 LLM 应用**。

与传统的单体 LLM 调用不同，LangGraph 让你可以把复杂的 AI 任务拆分成多个步骤，每个步骤调用不同的 LLM，通过状态图来管理整个流程。

## 2. 核心概念：StateGraph

`StateGraph` 是 LangGraph 最核心的抽象。它让你用一个**状态字典**来在多个节点之间传递数据。

```python
from langgraph.graph import StateGraph, END

workflow = StateGraph(dict)

def node_a(state):
    return {{"result": "A完成"}}

workflow.add_node("a", node_a)
workflow.set_entry_point("a")
workflow.add_edge("a", END)

app = workflow.compile()
result = app.invoke({{}})
```

## 3. 为什么需要多 Agent？

**关注点分离**是多 Agent 架构的核心理念：

- Agent 1 负责诊断（理解用户）
- Agent 2 负责生成（基于知识库）
- Agent 3 负责审核（检查错误）

每个 Agent 只做一件事，做到最好。这比一个超大 prompt 完成所有任务更可靠、更可控。

## 4. 你的学习路径

1. 先搞懂 StateGraph 的基本用法
2. 理解节点和边的工作原理
3. 学习条件路由
4. 实现一个简单的 2-Agent 协同系统
5. 逐步扩展到更复杂的架构""",
                    "citations": [
                        {"ref_index": 1, "original_text": "LangGraph is a library for building stateful, multi-actor applications",
                         "usage": "第1节定义"},
                        {"ref_index": 2, "original_text": "StateGraph is the core abstraction in LangGraph",
                         "usage": "第2节核心概念"},
                    ],
                    "difficulty_level": "beginner",
                    "estimated_duration_minutes": 30,
                    "key_takeaways": [
                        "LangGraph 通过状态图管理多步骤 LLM 调用",
                        "StateGraph 的三个要素：节点、边、状态字典",
                        "多 Agent 架构的核心价值是关注点分离",
                        "建议从实操入手，边做边学",
                    ],
                }, ensure_ascii=False)

            elif "guide" in user_message.lower() or "实操" in user_message:
                return json.dumps({
                    "title": f"实操指南：构建你的第一个 LangGraph 应用",
                    "content": f"""# 实操指南：构建第一个 LangGraph 应用

## 步骤 1：安装依赖

```bash
pip install langgraph langchain-openai
```

## 步骤 2：创建你的第一个 StateGraph

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict

# 定义状态
class MyState(TypedDict):
    query: str
    result: str

# 定义节点
def analyze(state: MyState) -> dict:
    query = state["query"]
    return {{"result": f"已分析: {{query}}"}}

# 构建图
workflow = StateGraph(MyState)
workflow.add_node("analyze", analyze)
workflow.set_entry_point("analyze")
workflow.add_edge("analyze", END)

app = workflow.compile()
```

## 步骤 3：运行

```python
result = app.invoke({{"query": "学习LangGraph", "result": ""}})
print(result["result"])
# 输出: 已分析: 学习LangGraph
```

## 步骤 4：加条件路由

```python
def router(state: MyState) -> str:
    if "LangGraph" in state["query"]:
        return "langgraph_node"
    return "general_node"

workflow.add_conditional_edges("analyze", router, {{
    "langgraph_node": "specialized",
    "general_node": END,
}})
```

运行试试看！一步步加节点，一步步扩展。""",
                    "citations": [
                        {"ref_index": 1, "original_text": "StateGraph lets you pass a state dict between nodes",
                         "usage": "步骤2"},
                    ],
                    "difficulty_level": "beginner",
                    "estimated_duration_minutes": 20,
                    "key_takeaways": [
                        "用 pip 安装 langgraph 和 langchain-openai",
                        "定义 StateGraph → 加节点 → 编译 → invoke",
                        "条件路由是多 Agent 协同的关键",
                    ],
                }, ensure_ascii=False)

            elif "quiz" in user_message.lower() or "测试" in user_message:
                return json.dumps({
                    "title": "LangGraph 基础测试",
                    "content": f"""# LangGraph 基础测试

## 基础题

**1. LangGraph 最核心的抽象是什么？**
- A) Chain
- B) StateGraph ✓
- C) AgentExecutor
- D) Pipeline

**2. 以下哪个不是 StateGraph 的要素？**
- A) 节点（Node）
- B) 边（Edge）
- C) 模型训练（Training）✓
- D) 状态字典（State）

**3. 条件路由的作用是什么？**
- A) 加速 LLM 推理
- B) 根据中间结果选择下一个节点 ✓
- C) 减少 token 消耗
- D) 缓存 LLM 响应

## 进阶题

**4. 多 Agent 架构相比单体 LLM 调用的核心优势是什么？**

提示：思考关注点分离（Separation of Concerns）。

## 挑战题

**5. 写一个 LangGraph 工作流，实现：输入用户问题 → 判断问题类型 → 如果是技术问题调用 GPT-4 → 如果是普通问题调用 GPT-3.5 → 输出结果。**
""",
                    "citations": [],
                    "difficulty_level": "beginner",
                    "estimated_duration_minutes": 15,
                    "key_takeaways": [
                        "检验对 StateGraph 核心概念的理解",
                        "从基础概念到代码实现，逐级递进",
                    ],
                }, ensure_ascii=False)

        # 兜底
        return json.dumps({"message": "演示模式 — 无 LLM API Key"}, ensure_ascii=False)


# 全局单例
llm = LLMClient()

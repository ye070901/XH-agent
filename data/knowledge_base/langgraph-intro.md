# LangGraph 入门指南

LangGraph 是 LangChain 团队推出的一个库，专门用于构建有状态的、多角色（multi-actor）的 LLM 应用。

## 核心概念

### StateGraph（状态图）

StateGraph 是 LangGraph 最核心的抽象。它让你用一个**状态字典（state dict）**来在多个节点之间传递数据。

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict

class MyState(TypedDict):
    messages: list
    next_step: str

workflow = StateGraph(MyState)

def node_a(state):
    # 处理 state，返回更新
    return {"next_step": "b"}

def node_b(state):
    return {"next_step": END}

workflow.add_node("a", node_a)
workflow.add_node("b", node_b)
workflow.add_edge("a", "b")
workflow.set_entry_point("a")

app = workflow.compile()
result = app.invoke({"messages": [], "next_step": ""})
```

### 节点（Node）

节点是一个函数，接收 state 字典，返回 state 字典的部分更新。LangGraph 会自动合并返回值。

节点的核心规则：
- 输入：当前的 state
- 输出：一个 dict，只包含你要更新的字段
- 同步或异步都可以

### 边（Edge）

边定义了节点之间的流转关系：
- `add_edge("a", "b")` — A 完成后无条件转到 B
- `add_conditional_edges("a", router, {"x": "node_x", "y": "node_y"})` — A 完成后根据 router 函数的返回值选择下一个节点

### 条件路由

```python
def router(state):
    if state["next_step"] == "review":
        return "review"
    return "end"

workflow.add_conditional_edges("generate", router, {
    "review": "review_node",
    "end": END,
})
```

条件路由是实现多 Agent 协同的关键——一个 Agent 完成后，根据它的输出决定下一个 Agent 是谁。

### Checkpointer（检查点）

LangGraph 内置了状态持久化机制：

```python
from langgraph.checkpoint.memory import MemorySaver
memory = MemorySaver()
app = workflow.compile(checkpointer=memory)

# 同一个 thread_id 的多次调用会恢复上一次的状态
config = {"configurable": {"thread_id": "user-123"}}
app.invoke(state, config)
```

## 常见模式

### Agent 协同模式

```
diagnose → retrieve → generate → review → [approve | revise]
```

每个节点可以调用不同的 LLM 或使用不同的 prompt。节点之间通过 state 传递中间结果。

### 人在回路（Human-in-the-Loop）

```python
workflow.add_node("human_approval", human_node)
workflow.add_edge("generate", "human_approval")
# 在这个节点中断，等待人工输入
```

## 与单体 LLM 调用的区别

单体调用：一次 prompt → 一次回答。所有逻辑在 prompt 里。

LangGraph：多个节点 → 多次 LLM 调用 → 每个节点只做一件事 → 节点间通过状态传递上下文。

优势：
1. 每个节点的 prompt 更短、更聚焦 → 准确率更高
2. 可以在特定节点插入 RAG 检索、外部 API 调用
3. 状态可追踪、可回溯、可恢复
4. 支持条件分支和循环

# StateGraph 详解

## StateGraph 定义

StateGraph 是 LangGraph 的核心数据结构，它是一个携带状态的有向图。每个节点读取当前状态，执行计算，返回状态更新。状态在节点之间自动传递，开发者不需要手动管理数据流。

## 创建 StateGraph

```python
from langgraph.graph import StateGraph
from typing import TypedDict

class MyState(TypedDict):
    input_text: str
    processed_text: str
    final_output: str

graph = StateGraph(MyState)
```

## 添加节点

节点是 StateGraph 的基本执行单元。每个节点是一个接收 state 并返回 state 更新的函数。

```python
def process_text(state: MyState) -> dict:
    """处理输入文本"""
    text = state["input_text"]
    processed = text.upper().strip()
    return {"processed_text": processed}

graph.add_node("processor", process_text)
```

节点函数的返回值会**合并**到当前状态中，而不是替换整个状态。这意味着你只需要返回需要更新的字段。

## 添加边

边定义了节点之间的执行顺序。LangGraph 支持三种边类型：

### 普通边（Fixed Edge）
确定性地从节点 A 指向节点 B：
```python
graph.add_edge("processor", "validator")
```

### 条件边（Conditional Edge）
根据当前状态动态选择下一个节点：
```python
def route_after_check(state: MyState) -> str:
    if len(state["processed_text"]) > 100:
        return "summarizer"
    return "finalizer"

graph.add_conditional_edges("validator", route_after_check, {
    "summarizer": "summarizer",
    "finalizer": "finalizer"
})
```

### 入口点和出口点
```python
graph.set_entry_point("processor")
graph.set_finish_point("finalizer")
```

## 编译和执行

```python
app = graph.compile()
result = app.invoke({"input_text": "hello world"})
```

`compile()` 方法验证图结构的正确性（无孤立节点、入口/出口有效），返回可执行的 `Runnable` 对象。

## 状态更新机制

LangGraph 的状态更新遵循**增量合并**原则：

1. 节点函数返回 dict
2. 该 dict 的键值对合并到当前状态
3. 如果键已存在，值被覆盖
4. 如果键不存在，被添加

这种设计使得每个节点只需要关心自己的输出，不需要了解完整的状态结构。

## 常见模式

### 顺序执行
```python
graph.add_node("step1", fn1)
graph.add_node("step2", fn2)
graph.add_node("step3", fn3)
graph.add_edge("step1", "step2")
graph.add_edge("step2", "step3")
```

### 并行分支
LangGraph 支持从同一个节点出发的多条边，实现并行执行。

### 循环执行
通过条件边可以形成循环，实现迭代优化：
```python
graph.add_conditional_edges("reviewer", should_continue, {
    "continue": "generator",  # 回到 generator 重新生成
    "stop": "finalizer"
})
```

## 调试技巧

- 使用 `graph.get_graph().draw_mermaid_png()` 可视化图结构
- 每个节点的输入/输出都可以通过日志追踪
- `invoke()` 支持 streaming 模式，逐节点观察执行过程

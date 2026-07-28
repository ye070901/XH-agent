# LangGraph 工具调用

## 工具调用的概念

在 LangGraph 中，工具（Tool）是 Agent 可以调用的外部函数。工具调用让 Agent 不再局限于 LLM 的参数知识，而是能够与外部世界交互——搜索数据库、调用 API、执行代码、读取文件。

## 定义工具

### 使用 @tool 装饰器
```python
from langchain.tools import tool

@tool
def search_knowledge_base(query: str) -> str:
    """在知识库中搜索相关文档"""
    results = await knowledge_base.query(query, top_k=5)
    return format_search_results(results)
```

### 工具描述的规范
工具的 docstring 非常重要——LLM 根据它来决定何时调用该工具：

```
好的描述: "在ChromaDB知识库中搜索与查询语义相关的文档片段，返回Top-5结果及其相似度分数"
坏的描述: "搜索"
```

## 在 StateGraph 中使用工具

### ToolNode
LangGraph 提供了 `ToolNode` 类来简化工具集成：

```python
from langgraph.prebuilt import ToolNode

tools = [search_knowledge_base, calculate_difficulty, validate_content]
tool_node = ToolNode(tools)

graph.add_node("tools", tool_node)
```

### 条件路由：工具调用 vs 直接响应
```python
def should_use_tools(state: AgentState) -> str:
    """判断 LLM 响应是否需要调用工具"""
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return "respond"

graph.add_conditional_edges("llm", should_use_tools, {
    "tools": "tools",
    "respond": "responder"
})
```

## 工具调用流程

```
用户输入 → LLM 分析 → 判断是否需要工具
                         ├─ 需要 → 调用工具 → 获取结果 → 返回 LLM → 最终响应
                         └─ 不需要 → 直接响应
```

## 常见工具类型

### 检索工具
- 向量搜索（ChromaDB query）
- 关键词搜索（BM25）
- 元数据过滤

### 计算工具
- 难度评分计算
- 统计数据分析
- 时间估算

### 验证工具
- 代码语法检查
- 事实一致性验证
- 格式合规检查

### 外部工具
- 搜索引擎 API
- 学术论文检索
- 代码执行沙箱

## 工具设计原则

1. **单一职责**：一个工具只做一件事
2. **明确输入输出**：参数有类型注解，返回值有明确结构
3. **错误友好**：工具执行失败时返回有意义的错误信息，而不是抛出异常
4. **副作用可控**：读操作优先于写操作，写操作需要确认

## 安全注意事项

- 不要在工具中直接执行用户输入的代码
- 文件操作工具应限制可访问的目录范围
- API 调用工具应设置超时和重试限制
- 敏感操作需要有审计日志

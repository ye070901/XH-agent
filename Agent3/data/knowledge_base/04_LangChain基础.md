# LangChain 基础

## 什么是 LangChain

LangChain 是一个用于构建 LLM 驱动应用的开源框架。它提供了一套标准化的接口和组件，帮助开发者将 LLM 与外部数据、工具和计算资源连接起来。

## 核心组件

### LLM 抽象层

LangChain 提供了统一的 LLM 接口，支持 OpenAI、Anthropic、DeepSeek、Qwen 等多种模型提供商。无论底层模型是什么，开发者使用相同的 API。

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-4o", temperature=0.3)
response = llm.invoke("什么是RAG？")
```

### Chain（链）

Chain 是将多个组件串联起来的核心概念。最简单的链是 LLMChain，它将 prompt 模板和 LLM 调用组合在一起。

```python
from langchain.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

prompt = ChatPromptTemplate.from_template("翻译成英文: {text}")
llm = ChatOpenAI(model="gpt-4o")

chain = prompt | llm
result = chain.invoke({"text": "你好世界"})
```

### Tool（工具）

Tool 是 LLM 可以调用的外部函数。LangChain 提供了 @tool 装饰器来简化工具定义：

```python
from langchain.tools import tool

@tool
def search_database(query: str) -> str:
    """搜索知识库中的文档"""
    return f"搜索结果: {query} 相关文档..."
```

### Agent（智能体）

Agent 是能够自主决策使用哪些工具、以什么顺序调用的 LLM 应用。与 Chain 的固定执行顺序不同，Agent 的调用路径是动态的。

## LCEL（LangChain Expression Language）

LCEL 使用管道操作符 `|` 来组合组件，使得链的构建变得直观：

```python
chain = prompt | llm | output_parser
```

这种写法比传统的 `LLMChain` 更简洁，也是 LangChain 推荐的现代写法。

## 与 LangGraph 的关系

- LangChain：提供 LLM 调用、工具、prompt 等基础组件
- LangGraph：在 LangChain 基础上增加状态管理和条件路由
- 两者互补：LangChain 作为"建材"，LangGraph 作为"建筑图纸"

## 实际应用模式

### RAG 模式
```
用户问题 → 向量检索 → 拼接上下文 → LLM 生成答案
```

### ReAct 模式
```
观察 → 思考 → 行动 → 观察 → 思考 → ... → 最终答案
```

### 多 Agent 模式
```
Agent 1 分析 → Agent 2 执行 → Agent 3 审核 → 最终输出
```

## 最佳实践

1. 使用 LCEL 而非旧式 Chain 类
2. Prompt 模板外部化，便于维护和调优
3. 工具函数保持单一职责
4. 为每个 LLM 调用设置合理的 temperature
5. 始终包含错误处理逻辑

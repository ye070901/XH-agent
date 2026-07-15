# RAG（检索增强生成）基础

RAG（Retrieval-Augmented Generation）是一种将信息检索与文本生成结合的技术。它的核心思想是：**在 LLM 生成回答之前，先从外部知识库中检索相关信息，然后用这些信息作为上下文来约束生成**。

## RAG 的三步流程

### 1. 索引（Indexing）

把文档变成可检索的形式：

```
文档 → 文本分块（chunking）→ 向量化（embedding）→ 存入向量数据库
```

**分块策略：**
- 太小：上下文不完整
- 太大：检索不精确
- 推荐：512 字符，overlap 64 字符
- 更好的做法：按语义边界分块（段落 + 代码块）

**向量化（Embedding）：**
将文本转换为固定维度的向量。语义相似的文本在向量空间中距离更近。

```python
from openai import OpenAI
client = OpenAI()
response = client.embeddings.create(
    model="text-embedding-3-small",
    input="LangGraph is a library for building stateful agents."
)
embedding = response.data[0].embedding  # 1536维向量
```

### 2. 检索（Retrieval）

用户提问 → 向量化 → 在向量数据库中搜索最相似的文档片段。

**检索质量的关键指标：**
- **召回率（Recall）：** 相关文档中，有多少被检索到了？
- **精确率（Precision）：** 检索到的文档中，有多少是真正相关的？

**提高检索质量的方法：**
- 混合检索：向量相似度 + 关键词匹配（BM25）
- 重排序（Reranking）：用更强的模型对检索结果重新排序
- 多轮检索：用第一轮结果重新构造查询

### 3. 生成（Generation）

把检索到的文档片段塞进 prompt，让 LLM 基于这些片段生成回答。

```
系统提示: "你是一个知识专家。请基于以下参考资料回答问题。如果参考资料中找不到相关信息，请诚实地说'不知道'。"

用户: "什么是 LangGraph？"

参考资料:
[1] LangGraph is a library for building stateful, multi-actor applications...
[2] StateGraph is the core abstraction in LangGraph...
```

## RAG 的核心价值

1. **减少幻觉（Hallucination）：** LLM 被约束在检索到的文档范围内生成
2. **知识可溯源（Attribution）：** 每个回答都可以追溯到原始文档
3. **知识可更新：** 不需要重新训练模型，只需更新知识库
4. **领域专业化：** 通用 LLM + 垂直领域知识库 = 领域专家

## RAG 的局限性

- 检索质量决定了生成质量的上限
- 复杂推理问题（需要综合多个文档的信息）仍然有挑战
- 无法完全消除幻觉——LLM 仍可能误解检索到的内容

# CLAUDE.md — 角色3：知识库工程师

## 你的模块

`backend/src/knowledge/store.py` — ChromaDB 向量存储 + RAG

## 你要做的事情

1. 完善 `KnowledgeBase` 的 ChromaDB 集成
2. 爬取/收集大模型应用开发领域的文档（LangChain/LlamaIndex/OpenAI/Anthropic 官方文档）
3. 实现语义分块策略（按标题层级 + 代码块边界）
4. 测试检索质量（手动验证：搜"RAG pipeline"，前 5 个结果是否相关）
5. 准备 ≥1 个垂直领域的专业知识库切片（提交材料用）

## 你的接口

- `knowledge_base.add_document(doc_id, title, content) -> list[dict]`
- `knowledge_base.search(query, top_k=10) -> list[dict]`

## 检索结果的格式

```python
{
    "doc_id": str,
    "doc_title": str,
    "chunk_index": int,
    "content": str,
    "relevance_score": float
}
```

## 关键约束

- 知识库质量决定 Agent 2 和 Agent 3 的上限
- 至少准备 20 篇高质量文档（官方文档 > 博客 > 教程）
- 每条 doc 需要明确的标题和来源
- Agent 2 依赖你的检索结果生成内容，Agent 3 用你的检索结果验证

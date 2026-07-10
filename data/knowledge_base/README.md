## 👤 角色3：知识库文档目录

### 在这里放你的知识库原始文档（Markdown / TXT / PDF 都可以）

### 推荐的文档来源（大模型应用开发领域）

1. **LangChain 官方文档** — https://python.langchain.com/
2. **LangGraph 官方文档** — https://langchain-ai.github.io/langgraph/
3. **OpenAI API 文档** — https://platform.openai.com/docs/
4. **Anthropic Claude API 文档** — https://docs.anthropic.com/
5. **LlamaIndex 官方文档** — https://docs.llamaindex.ai/

### 文档质量标准

- 每条文档有明确标题和来源
- 内容包含代码示例 + 解释
- 至少 20 篇高质量文档
- 优先选官方文档，其次权威博客

### 如何导入知识库

```python
from src.knowledge.store import knowledge_base

await knowledge_base.add_document(
    doc_id="langgraph-guide-1",
    title="LangGraph StateGraph 基础",
    content=open("data/knowledge_base/langgraph.md", encoding="utf-8").read(),
)
```

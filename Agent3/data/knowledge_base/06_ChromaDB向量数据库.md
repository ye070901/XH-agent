# ChromaDB 向量数据库

## 什么是 ChromaDB

ChromaDB 是一个开源的向量数据库，专为 AI 应用设计。它提供了简单易用的 API 来存储、检索和管理向量嵌入（Embedding）。ChromaDB 是 LangChain 和 LangGraph 生态中推荐的默认向量存储方案。

## 核心概念

### Collection（集合）
Collection 是 ChromaDB 的数据组织单元，类似于关系数据库中的"表"。一个 Collection 包含多个文档及其向量嵌入。

```python
import chromadb
client = chromadb.PersistentClient(path="./chroma_data")
collection = client.get_or_create_collection(
    name="domain_knowledge",
    metadata={"hnsw:space": "cosine"}
)
```

### Embedding Function（嵌入函数）
Embedding function 负责将文本转换为向量。ChromaDB 支持多种 embedding 方式：
- OpenAI Embedding（text-embedding-3-small / text-embedding-3-large）
- Sentence Transformers（本地运行，支持中文）
- Cohere Embedding
- 自定义 embedding 函数

### 距离度量
- **Cosine**：余弦相似度，最常用的文本相似度度量，0-1 之间
- **L2（Euclidean）**：欧几里得距离
- **IP（Inner Product）**：内积

推荐使用 cosine 距离进行文本检索。

## 基本操作

### 添加文档
```python
collection.add(
    ids=["doc1_chunk0", "doc1_chunk1"],
    documents=["文档内容...", "文档内容..."],
    metadatas=[
        {"doc_id": "doc1", "chunk_idx": 0, "source": "official"},
        {"doc_id": "doc1", "chunk_idx": 1, "source": "official"},
    ]
)
```

### 查询文档
```python
results = collection.query(
    query_texts=["LangGraph 状态管理"],
    n_results=5,
    include=["documents", "metadatas", "distances"]
)
```

### 过滤查询
```python
results = collection.get(
    where={"doc_id": "doc1"},      # 元数据过滤
    where_document={"$contains": "LangGraph"}  # 文档内容过滤
)
```

### 删除文档
```python
# 按 ID 删除
collection.delete(ids=["doc1_chunk0"])

# 按元数据过滤删除
collection.delete(where={"doc_id": "doc1"})
```

## 持久化 vs 嵌入式

### 持久化模式（PersistentClient）
数据存储在磁盘上，重启后保留。适合生产环境。

### 嵌入式模式（Client / EphemeralClient）
数据存储在内存中，进程结束后消失。适合测试和原型开发。

## 性能优化

1. **批量写入**：使用 `collection.add()` 一次性添加多个文档
2. **合理分片**：chunk 太多会降低检索速度，太少影响精度
3. **适当索引**：HNSW 索引参数影响速度和精度的权衡
4. **连接复用**：使用单例模式共享 client 实例

## 与 LangChain/LangGraph 集成

ChromaDB 作为 LangChain 的 VectorStore 实现：
```python
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

vectorstore = Chroma(
    collection_name="knowledge",
    embedding_function=OpenAIEmbeddings(),
    persist_directory="./chroma_data"
)
```

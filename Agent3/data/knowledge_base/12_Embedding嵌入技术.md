# Embedding 嵌入技术

## 什么是 Embedding

Embedding（嵌入）是将文本、图像等非结构化数据转换为固定长度的数值向量的技术。语义相近的文本在向量空间中距离更近，这使得计算机能够"理解"文本的语义相似性。

## Embedding 在 RAG 中的作用

在 RAG 系统中，Embedding 是连接"检索"和"生成"的桥梁：

1. **文档索引**：将知识库文档分片后转换为向量存储
2. **查询编码**：将用户查询转换为相同维度的向量
3. **相似检索**：通过向量距离找到最相关的文档片段
4. **上下文注入**：将检索结果拼接后提供给 LLM 生成

## 主流 Embedding 模型

### OpenAI Embedding
- `text-embedding-3-small`：1536 维，性价比高
- `text-embedding-3-large`：3072 维，精度更高

### 中文专用模型
- `shibing624/text2vec-base-chinese`：本地运行，中文效果好
- `BAAI/bge-large-zh-v1.5`：中文语义理解能力强
- `moka-ai/m3e-base`：轻量级中文模型

### 多语言模型
- `intfloat/multilingual-e5-large`：支持多语言
- `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`

## 向量相似度度量

### 余弦相似度（Cosine Similarity）
```
similarity = cos(A, B) = A·B / (|A| × |B|)
```
值域：[-1, 1]，文本语义相似度通常在 [0, 1] 区间。
推荐用于文本检索场景。

### 欧几里得距离（Euclidean Distance）
```
distance = sqrt(Σ(Ai - Bi)²)
```
距离越小越相似。适合某些聚类场景。

### 点积（Dot Product）
```
score = A·B
```
值越大越相似。某些模型（如 Cohere）推荐使用。

## Embedding 维度选择

| 维度 | 优点 | 缺点 |
|------|------|------|
| 384d | 存储小、检索快 | 语义表达可能不足 |
| 768d | 平衡之选 | 中等存储开销 |
| 1536d | 语义表达丰富 | 存储和检索开销较大 |
| 3072d | 最高精度 | 存储和计算成本高 |

## 实际使用建议

1. **中文场景**：优先使用中文预训练模型，而非多语言模型
2. **批量化**：embedding 调用支持批量，一次传入多个文本效率更高
3. **缓存**：相同文本的 embedding 可以缓存复用
4. **归一化**：使用 cosine 距离时，向量归一化后可以用点积近似
5. **模型一致性**：索引和查询必须使用相同的 embedding 模型

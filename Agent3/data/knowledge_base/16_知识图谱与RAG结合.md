# 知识图谱与 RAG 结合

## 知识图谱 vs 向量检索

传统的 RAG 依赖向量相似度检索，擅长找到"语义相近"的内容，但难以处理需要结构化关系推理的查询。

知识图谱（Knowledge Graph）以实体-关系-实体的三元组形式组织知识，擅长：
- 多跳推理（A→B→C 的连锁关系）
- 精确关系查询（"LangGraph 依赖哪个库？"）
- 概念层级理解（"StateGraph 是一种图结构"）

## Graph RAG 架构

Graph RAG 将知识图谱与传统向量检索结合，融合两种范式的优势：

### 索引阶段
1. 文档分片 → 向量化 → 向量数据库（传统 RAG）
2. 实体识别 + 关系抽取 → 构建知识图谱
3. 实体与文档 chunk 关联（实体链接）

### 检索阶段
1. 查询向量检索 → 获得语义相关文档
2. 查询实体匹配 → 从知识图谱中检索相关实体和关系
3. 基于图谱关系扩展检索范围（如检索"依赖项"或"父概念"）
4. 合并两路结果，去重排序

### 生成阶段
1. 将向量检索结果和知识图谱结果拼接
2. LLM 基于综合上下文生成答案
3. 引用来源标注（文档引用 + 图谱关系引用）

## 在本项目中的应用

学习资源生成可以利用知识图谱来：

### 知识点依赖关系
```
LangGraph ← 依赖 ← [LangChain, Python async, StateGraph概念]
StateGraph ← 子类 ← [条件路由, 工具调用, 检查点]
```

当学习者需要学习 LangGraph 时，系统自动识别前置依赖，确保学习路径包含必要的前置知识。

### 概念层级关系
```
多Agent系统
  ├─ Agent架构设计模式
  │   ├─ 流水线模式
  │   ├─ 辩论模式
  │   └─ 路由模式
  └─ Agent通信协议
      ├─ 消息格式
      └─ 状态同步
```

### 错误关联检测
如果生成内容说"LangGraph 是 Google 开发的"，知识图谱中 LangGraph.creator = "LangChain Team" 的关系就能直接反驳。

## 实现方式

### 轻量级实现（Neo4j + LangChain）
```python
from langchain_community.graphs import Neo4jGraph

graph = Neo4jGraph(
    url="bolt://localhost:7687",
    username="neo4j",
    password="password"
)

# 查询前置依赖
result = graph.query("""
    MATCH (topic:Topic {name: 'LangGraph'})-[:DEPENDS_ON]->(prereq:Topic)
    RETURN prereq.name
""")
```

### 极简实现（JSON 图谱）
对于小型知识库，可以用 JSON 文件存储三元组：
```json
{
    "entities": [
        {"id": "langgraph", "type": "Framework", "creator": "LangChain Team"},
        {"id": "stategraph", "type": "Concept", "parent": "langgraph"}
    ],
    "relations": [
        {"from": "langgraph", "to": "langchain", "type": "depends_on"},
        {"from": "stategraph", "to": "langgraph", "type": "part_of"}
    ]
}
```

## 适用场景判断

| 场景 | 推荐方案 |
|------|---------|
| 概念解释、教程生成 | 传统 RAG |
| 学习路径规划 | Graph RAG |
| 前置知识检查 | 知识图谱 |
| 事实核查（实体关系） | 知识图谱 + RAG |

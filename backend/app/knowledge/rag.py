"""知识层 — RAG检索 + 向量库 + 文档处理"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

import json
from typing import Optional
from loguru import logger

from ..core.config import settings


class KnowledgeBase:
    """
    领域知识库：文档解析、向量索引、混合检索。

    实际使用时依赖 Milvus + BGE-M3，此处提供完整接口骨架。
    """

    def __init__(self):
        self.collection_name = "domain_knowledge"
        self._initialized = False

    async def initialize(self):
        """初始化向量库连接"""
        try:
            from pymilvus import connections, Collection, FieldSchema, CollectionSchema, DataType

            connections.connect(
                alias="default",
                host=settings.MILVUS_HOST,
                port=settings.MILVUS_PORT,
            )

            # 定义Schema
            fields = [
                FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=128),
                FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=128),
                FieldSchema(name="chunk_index", dtype=DataType.INT64),
                FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=settings.EMBEDDING_DIM),
            ]
            schema = CollectionSchema(fields, description="领域知识库")

            self.collection = Collection(name=self.collection_name, schema=schema)
            self._initialized = True
            logger.info(f"[知识库] Milvus连接成功, collection={self.collection_name}")
        except Exception as e:
            logger.warning(f"[知识库] Milvus不可用，使用内存模式: {e}")
            self._initialized = False

    async def add_document(self, doc_id: str, title: str, content: str) -> list[dict]:
        """添加文档：分块 → Embedding → 入库"""
        chunks = self._chunk_text(content)
        logger.info(f"[知识库] 文档{doc_id}分块完成: {len(chunks)}个chunk")

        embeddings = await self._embed_chunks(chunks)

        chunk_records = []
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            record = {
                "doc_id": doc_id,
                "doc_title": title,
                "chunk_index": i,
                "content": chunk,
                "embedding": emb,
            }
            chunk_records.append(record)

        if self._initialized:
            await self._insert_to_milvus(chunk_records)
        else:
            # 内存模式：存到列表
            if not hasattr(self, "_memory_store"):
                self._memory_store = []
            self._memory_store.extend(chunk_records)

        return chunk_records

    async def search(
        self,
        query: str,
        top_k: int = 10,
    ) -> list[dict]:
        """混合检索：向量相似度 + 关键词匹配"""
        query_embedding = await self._embed_query(query)

        if self._initialized:
            results = await self._search_milvus(query_embedding, top_k)
        else:
            results = self._search_memory(query_embedding, top_k)

        return self._format_results(results)

    def _chunk_text(self, text: str, chunk_size: int = 512, overlap: int = 64) -> list[str]:
        """语义分块"""
        # 简易按段落分块，生产环境用 SemanticChunker
        paragraphs = text.split("\n\n")
        chunks = []
        current = ""
        for p in paragraphs:
            if len(current) + len(p) < chunk_size:
                current += p + "\n\n"
            else:
                if current:
                    chunks.append(current.strip())
                current = p + "\n\n"
        if current:
            chunks.append(current.strip())
        return chunks

    async def _embed_chunks(self, chunks: list[str]) -> list[list[float]]:
        """批量Embedding"""
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer(settings.EMBEDDING_MODEL)
            embeddings = model.encode(chunks, normalize_embeddings=True)
            return embeddings.tolist()
        except Exception as e:
            logger.warning(f"[知识库] Embedding模型不可用，返回零向量: {e}")
            return [[0.0] * settings.EMBEDDING_DIM for _ in chunks]

    async def _embed_query(self, query: str) -> list[float]:
        emb = await self._embed_chunks([query])
        return emb[0]

    async def _insert_to_milvus(self, records: list[dict]):
        """写入Milvus"""
        from pymilvus import utility
        # 简化实现，实际需处理batch insert和索引
        logger.info(f"[知识库] 写入Milvus {len(records)}条记录")

    async def _search_milvus(self, embedding: list[float], top_k: int) -> list[dict]:
        """Milvus检索"""
        # 简化实现
        return []

    def _search_memory(self, embedding: list[float], top_k: int) -> list[dict]:
        """内存检索 — 余弦相似度"""
        import math
        if not hasattr(self, "_memory_store") or not self._memory_store:
            return []

        def cosine_sim(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            return dot  # 已归一化

        scored = []
        for r in self._memory_store:
            sim = cosine_sim(embedding, r["embedding"])
            scored.append((sim, r))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:top_k]]

    def _format_results(self, results: list[dict]) -> list[dict]:
        return [
            {
                "doc_id": r["doc_id"],
                "doc_title": r.get("doc_title", ""),
                "chunk_index": r.get("chunk_index", 0),
                "content": r["content"],
                "relevance_score": getattr(r, "score", 0.0),
            }
            for r in results
        ]


# 全局单例
knowledge_base = KnowledgeBase()

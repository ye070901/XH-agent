"""知识库 — ChromaDB 向量存储 + RAG 检索。角色3 在此实现。"""
from pathlib import Path
from typing import Optional

from loguru import logger

from ..config import settings


class KnowledgeBase:
    """
    领域知识库：文档切片 → Embedding → 向量检索。

    使用 ChromaDB（零配置，本地持久化）。
    切换到其他向量库只需修改此类，不影响其他模块。
    """

    def __init__(self):
        self._initialized = False
        self._collection = None
        self._embedding_fn = None

    async def initialize(self):
        """初始化 ChromaDB 和 Embedding 模型"""
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings

            persist_dir = Path(settings.CHROMA_PERSIST_DIR)
            persist_dir.mkdir(parents=True, exist_ok=True)

            self._client = chromadb.PersistentClient(
                path=str(persist_dir),
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            self._collection = self._client.get_or_create_collection(
                name="domain_knowledge",
                metadata={"hnsw:space": "cosine"},
            )
            self._initialized = True
            logger.info(f"[知识库] ChromaDB 初始化成功, dir={persist_dir}")
        except Exception as e:
            logger.warning(f"[知识库] ChromaDB 不可用，使用内存模式: {e}")
            self._initialized = False

    async def add_document(
        self, doc_id: str, title: str, content: str
    ) -> list[dict]:
        """添加文档：自动分块 → Embedding → 存入向量库"""
        chunks = self._chunk_text(content)
        chunk_ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]

        logger.info(f"[知识库] 文档 '{title}' 分块: {len(chunks)} chunks")

        if self._initialized:
            self._collection.add(
                ids=chunk_ids,
                documents=chunks,
                metadatas=[
                    {"doc_id": doc_id, "doc_title": title, "chunk_index": i}
                    for i in range(len(chunks))
                ],
            )

        return [
            {
                "doc_id": doc_id,
                "doc_title": title,
                "chunk_index": i,
                "content": chunk,
            }
            for i, chunk in enumerate(chunks)
        ]

    async def search(self, query: str, top_k: int = 10) -> list[dict]:
        """向量相似度检索"""
        if not query.strip():
            return []

        if self._initialized:
            results = self._collection.query(
                query_texts=[query],
                n_results=min(top_k, self._collection.count()),
            )
            if results["ids"] and results["ids"][0]:
                return self._format_chroma_results(results)
            return []

        logger.warning("[知识库] 未初始化，返回空结果")
        return []

    def _chunk_text(
        self, text: str, chunk_size: int = 512, overlap: int = 64
    ) -> list[str]:
        """按段落 + 语义边界分块"""
        paragraphs = text.split("\n\n")
        chunks = []
        current = ""
        for p in paragraphs:
            if len(current) + len(p) < chunk_size:
                current += p + "\n\n"
            else:
                if current.strip():
                    chunks.append(current.strip())
                current = p + "\n\n"
        if current.strip():
            chunks.append(current.strip())
        return chunks or [text[:chunk_size]]

    def _format_chroma_results(self, results: dict) -> list[dict]:
        """统一检索结果格式"""
        formatted = []
        ids_list = results.get("ids", [[]])[0]
        docs_list = results.get("documents", [[]])[0]
        metas_list = results.get("metadatas", [[]])[0]
        dists_list = results.get("distances", [[]])[0]

        for i in range(len(ids_list)):
            meta = metas_list[i] if i < len(metas_list) else {}
            dist = dists_list[i] if i < len(dists_list) else 0
            relevance = max(0, 1 - dist) if dist else 1.0
            formatted.append({
                "doc_id": meta.get("doc_id", ""),
                "doc_title": meta.get("doc_title", ""),
                "chunk_index": meta.get("chunk_index", 0),
                "content": docs_list[i] if i < len(docs_list) else "",
                "relevance_score": round(relevance, 4),
            })
        return formatted


# 全局单例
knowledge_base = KnowledgeBase()

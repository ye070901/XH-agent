"""知识库 — MVP 版本：文件系统关键词检索 + ChromaDB 可选升级。角色3 在此实现。"""

from pathlib import Path

from loguru import logger

from ..config import settings


class KnowledgeBase:
    """
    领域知识库。

    MVP 模式：从 data/knowledge_base/ 读取 .md 文件，用关键词匹配检索。
    升级模式：安装 chromadb 后自动切换到向量检索。
    """

    def __init__(self):
        self._initialized = False
        self._collection = None
        self._docs: list[dict] = []

    async def initialize(self):
        """初始化：先尝试 ChromaDB，失败则用文件系统"""
        # 尝试 ChromaDB
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
            logger.info(f"[知识库] ChromaDB 模式, dir={persist_dir}")
            return
        except Exception:
            logger.info("[知识库] ChromaDB 不可用，使用文件检索模式")

        # 回退：从文件系统加载
        kb_dir = Path(__file__).parent.parent.parent.parent / "data" / "knowledge_base"
        if kb_dir.exists():
            for md_file in kb_dir.glob("*.md"):
                try:
                    content = md_file.read_text(encoding="utf-8")
                    title = md_file.stem
                    self._docs.append(
                        {
                            "doc_id": md_file.name,
                            "doc_title": title,
                            "chunk_index": 0,
                            "content": content[:2000],
                        }
                    )
                except Exception:
                    pass
            logger.info(f"[知识库] 文件检索模式，加载了 {len(self._docs)} 篇文档")
        self._initialized = True

    async def add_document(self, doc_id: str, title: str, content: str) -> list[dict]:
        """添加文档"""
        chunks = self._chunk_text(content)

        if self._collection:
            chunk_ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
            self._collection.add(
                ids=chunk_ids,
                documents=chunks,
                metadatas=[
                    {"doc_id": doc_id, "doc_title": title, "chunk_index": i}
                    for i in range(len(chunks))
                ],
            )
        else:
            self._docs.append(
                {
                    "doc_id": doc_id,
                    "doc_title": title,
                    "chunk_index": 0,
                    "content": content[:2000],
                }
            )

        logger.info(f"[知识库] 添加文档 '{title}': {len(chunks)} chunks")
        return [
            {"doc_id": doc_id, "doc_title": title, "chunk_index": i, "content": c}
            for i, c in enumerate(chunks)
        ]

    async def search(self, query: str, top_k: int = 10) -> list[dict]:
        """检索"""
        if not query.strip():
            return self._docs[:top_k] if self._docs else []

        # ChromaDB 模式
        if self._collection:
            try:
                n_results = min(top_k, self._collection.count())
                results = self._collection.query(query_texts=[query], n_results=n_results)
                if results["ids"] and results["ids"][0]:
                    formatted = []
                    ids_list = results.get("ids", [[]])[0]
                    docs_list = results.get("documents", [[]])[0]
                    metas_list = results.get("metadatas", [[]])[0]
                    for i in range(len(ids_list)):
                        meta = metas_list[i] if i < len(metas_list) else {}
                        formatted.append(
                            {
                                "doc_id": meta.get("doc_id", ""),
                                "doc_title": meta.get("doc_title", ""),
                                "chunk_index": meta.get("chunk_index", 0),
                                "content": docs_list[i] if i < len(docs_list) else "",
                                "relevance_score": 1.0,
                            }
                        )
                    return formatted
            except Exception:
                pass

        # 文件检索模式：关键词匹配
        keywords = query.lower().split()
        scored = []
        for doc in self._docs:
            content_lower = doc["content"].lower()
            score = sum(1 for kw in keywords if kw in content_lower)
            if score > 0:
                scored.append((score, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        results = [d for _, d in scored[:top_k]]
        for r in results:
            r["relevance_score"] = 1.0
        return results

    def _chunk_text(self, text: str, chunk_size: int = 512, overlap: int = 64) -> list[str]:
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


# 全局单例
knowledge_base = KnowledgeBase()

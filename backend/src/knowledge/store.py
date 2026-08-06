"""知识库 — ChromaDB 向量检索 + 内置 Embedding。"""

from pathlib import Path

from loguru import logger

from ..config import settings


class KnowledgeBase:
    """
    领域知识库。

    优先使用 ChromaDB 内置 Embedding 进行语义向量检索。
    ChromaDB 不可用时回退到文件系统关键词匹配检索。
    """

    def __init__(self):
        self._initialized = False
        self._collection = None
        self._docs: list[dict] = []
        self._doc_count = 0

    def _build_embedding_function(self):
        """构建 Embedding 函数。

        优先级:
          1. OpenAI API (EMBEDDING_PROVIDER=openai) — 需要 LLM_API_KEY 且 API 支持 /v1/embeddings
          2. 本地模型 (EMBEDDING_PROVIDER=local) — sentence-transformers 中文模型
          3. ChromaDB 内置 ONNX (返回 None) — all-MiniLM-L6-v2, 约 80MB, 自动下载
        """
        import chromadb.utils.embedding_functions as ef

        provider = settings.EMBEDDING_PROVIDER.lower()
        api_key = settings.LLM_API_KEY
        model = settings.EMBEDDING_MODEL

        # ── OpenAI ──
        if provider == "openai":
            if not api_key:
                logger.warning("[知识库] EMBEDDING_PROVIDER=openai 但 LLM_API_KEY 为空，使用 ChromaDB 内置 ONNX")
                return None
            base_url = settings.LLM_BASE_URL or "https://api.openai.com/v1"
            logger.info(f"[知识库] OpenAI Embedding: {model}, base_url={base_url}")
            try:
                return ef.OpenAIEmbeddingFunction(
                    api_key=api_key,
                    model_name=model,
                    api_base=base_url,
                )
            except Exception as e:
                logger.warning(f"[知识库] OpenAI Embedding 初始化失败: {e}，使用 ChromaDB 内置 ONNX")
                return None

        # ── ChromaDB 内置 ONNX 模型 (all-MiniLM-L6-v2, ~80MB) ──
        elif provider == "chroma":
            logger.info("[知识库] 使用 ChromaDB 内置 ONNX Embedding (all-MiniLM-L6-v2)")
            return None

        # ── 本地中文模型 ──
        elif provider == "local":
            try:
                fn = ef.SentenceTransformerEmbeddingFunction(
                    model_name="shibing624/text2vec-base-chinese",
                )
                logger.info("[知识库] Embedding: 本地中文模型 text2vec-base-chinese")
                return fn
            except Exception as e:
                logger.warning(f"[知识库] 本地 embedding 初始化失败: {e}，使用 ChromaDB 内置 ONNX")
                return None

        # ── 默认：ChromaDB 内置 ONNX all-MiniLM-L6-v2 ──
        else:
            logger.info("[知识库] 使用 ChromaDB 内置 ONNX Embedding (all-MiniLM-L6-v2)")
            return None

    async def initialize(self):
        """初始化 ChromaDB + Embedding，失败则用文件检索模式。"""
        try:
            import os

            # 设置 HuggingFace 镜像以加速下载（国内网络）
            if "HF_ENDPOINT" not in os.environ:
                os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

            import chromadb
            from chromadb.config import Settings as ChromaSettings

            persist_dir = Path(settings.CHROMA_PERSIST_DIR)
            persist_dir.mkdir(parents=True, exist_ok=True)

            embedding_fn = self._build_embedding_function()

            self._client = chromadb.PersistentClient(
                path=str(persist_dir),
                settings=ChromaSettings(anonymized_telemetry=False),
            )

            existing = self._client.list_collections()
            coll_name = settings.CHROMA_COLLECTION_NAME

            if coll_name in [c.name for c in existing]:
                self._collection = self._client.get_collection(
                    name=coll_name,
                    embedding_function=embedding_fn,
                )
                logger.info(f"[知识库] 复用已有集合 '{coll_name}'")
            else:
                self._collection = self._client.create_collection(
                    name=coll_name,
                    embedding_function=embedding_fn,
                    metadata={"hnsw:space": "cosine"},
                )
                logger.info(f"[知识库] 创建新集合 '{coll_name}'")

            # 自检：写一条测试数据验证 embedding 可用
            try:
                self._collection.add(
                    ids=["__health_check__"],
                    documents=["health check"],
                    metadatas=[{"doc_id": "__test__"}],
                )
                self._collection.delete(ids=["__health_check__"])
            except Exception as probe_err:
                logger.warning(f"[知识库] Embedding 自检失败 ({probe_err})，降级文件检索")
                self._collection = None

            if self._collection is not None:
                self._doc_count = self._collection.count()
                self._initialized = True
                logger.info(f"[知识库] ChromaDB 模式就绪, dir={persist_dir}, 已有 {self._doc_count} chunks")
                return
        except Exception as e:
            logger.info(f"[知识库] ChromaDB 不可用 ({e})，使用文件检索模式")

        # ── 文件检索降级 ──
        await self._init_file_mode()
        self._initialized = True

    async def _init_file_mode(self):
        """从 data/raw/ 和 data/knowledge_base/ 递归加载 .md 文件。"""
        raw_dir = Path(__file__).parent.parent.parent.parent / "data" / "raw"
        kb_dir = Path(__file__).parent.parent.parent.parent / "data" / "knowledge_base"
        search_dirs = [d for d in (raw_dir, kb_dir) if d.exists()]
        loaded_ids = set()
        for search_dir in search_dirs:
            for md_file in sorted(search_dir.glob("**/*.md"), key=lambda p: p.name):
                try:
                    doc_id = md_file.stem
                    if doc_id in loaded_ids:
                        continue
                    loaded_ids.add(doc_id)
                    content = md_file.read_text(encoding="utf-8")
                    self._docs.append({
                        "doc_id": doc_id,
                        "doc_title": md_file.stem,
                        "chunk_index": 0,
                        "content": content[:2000],
                    })
                except Exception:
                    pass
        if self._docs:
            logger.info(f"[知识库] 文件检索模式，加载了 {len(self._docs)} 篇文档")

    async def add_document(self, doc_id: str, title: str, content: str) -> list[dict]:
        """添加文档，返回 chunks 列表。"""
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
            self._doc_count = self._collection.count()
        else:
            # 文件模式去重
            self._docs = [d for d in self._docs if d.get("doc_id") != doc_id]
            self._docs.append({
                "doc_id": doc_id,
                "doc_title": title,
                "chunk_index": 0,
                "content": content[:2000],
            })

        logger.info(f"[知识库] 添加文档 '{title}': {len(chunks)} chunks")
        return [
            {"doc_id": doc_id, "doc_title": title, "chunk_index": i, "content": c}
            for i, c in enumerate(chunks)
        ]

    async def add_documents_batch(self, docs: list[dict]) -> int:
        """批量导入文档。每项含 {doc_id, title, content}。返回成功导入数。"""
        count = 0
        for doc in docs:
            try:
                await self.add_document(
                    doc_id=doc.get("doc_id", ""),
                    title=doc.get("title", ""),
                    content=doc.get("content", ""),
                )
                count += 1
            except Exception as e:
                logger.warning(f"[知识库] 批量导入失败: {doc.get('title', '?')} — {e}")
        logger.info(f"[知识库] 批量导入完成: {count}/{len(docs)} 篇")
        return count

    async def delete_document(self, doc_id: str) -> bool:
        """删除文档及其所有 chunks。"""
        if not self._collection:
            logger.warning("[知识库] 文件检索模式不支持按 ID 删除")
            return False
        try:
            results = self._collection.get(where={"doc_id": doc_id})
            ids_to_delete = results.get("ids", [])
            if ids_to_delete:
                self._collection.delete(ids=ids_to_delete)
                self._doc_count = self._collection.count()
                logger.info(f"[知识库] 已删除文档 '{doc_id}', {len(ids_to_delete)} chunks")
                return True
            return False
        except Exception as e:
            logger.error(f"[知识库] 删除失败: {e}")
            return False

    async def get_stats(self) -> dict:
        """获取知识库统计信息。"""
        if self._collection:
            count = self._collection.count()
            coll = self._collection.get()
            metas = coll.get("metadatas", [])
            doc_ids = set(m.get("doc_id", "") for m in metas if m)
            return {
                "mode": "chromadb",
                "total_chunks": count,
                "total_documents": len(doc_ids),
                "collection_name": settings.CHROMA_COLLECTION_NAME,
            }
        else:
            return {
                "mode": "file",
                "total_chunks": len(self._docs),
                "total_documents": len(self._docs),
                "collection_name": None,
            }

    async def search(self, query: str, top_k: int = 10) -> list[dict]:
        """检索。ChromaDB 模式返回语义搜索结果。"""
        if not query.strip():
            return self._docs[:top_k] if self._docs else []

        # ChromaDB 向量检索
        if self._collection:
            try:
                n_results = min(top_k, max(1, self._collection.count()))
                results = self._collection.query(query_texts=[query], n_results=n_results)
                if results["ids"] and results["ids"][0]:
                    formatted = []
                    ids_list = results.get("ids", [[]])[0]
                    docs_list = results.get("documents", [[]])[0]
                    metas_list = results.get("metadatas", [[]])[0]
                    distances = results.get("distances", [[]])[0]
                    for i in range(len(ids_list)):
                        meta = metas_list[i] if i < len(metas_list) else {}
                        dist = distances[i] if i < len(distances) else 0
                        score = max(0.0, min(1.0, 1.0 - (dist / 2.0)))
                        formatted.append({
                            "doc_id": meta.get("doc_id", ""),
                            "doc_title": meta.get("doc_title", ""),
                            "chunk_index": meta.get("chunk_index", 0),
                            "content": docs_list[i] if i < len(docs_list) else "",
                            "relevance_score": round(score, 4),
                        })
                    return formatted
            except Exception as e:
                logger.warning(f"[知识库] ChromaDB 检索异常: {e}")

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
            r["relevance_score"] = round(
                r.get("score", 0) / max(1, len(keywords)), 4
            )
        return results

    def _chunk_text(self, text: str, chunk_size: int = 512, overlap: int = 64) -> list[str]:
        """按段落切分文本，含滑动窗口 overlap。"""
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not paragraphs:
            return [text[:chunk_size]] if text.strip() else []

        chunks = []
        current = ""
        for p in paragraphs:
            if len(current) + len(p) < chunk_size:
                current += p + "\n\n"
            else:
                if current.strip():
                    chunks.append(current.strip())
                if overlap > 0 and chunks:
                    tail = current.strip()[-overlap:] if len(current.strip()) > overlap else ""
                    current = tail + "\n\n" + p + "\n\n" if tail else p + "\n\n"
                else:
                    current = p + "\n\n"
        if current.strip():
            chunks.append(current.strip())
        return chunks or [text[:chunk_size]]


# 全局单例
knowledge_base = KnowledgeBase()

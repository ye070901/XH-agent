"""知识库存储引擎 — ChromaDB 向量检索 + Embedding 自动切换 + 文件降级模式。

Opt‑2 KB 引擎核心模块。只做存储检索，不包含 Agent / LLM 逻辑。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from loguru import logger

from ..config import settings


class KnowledgeBase:
    """领域知识库存储引擎。

    ChromaDB 模式：PersistentClient + EmbeddingFunction → 语义向量检索。
    文件降级模式：ChromaDB 不可用时自动切换，读写本地 md 文件兜底。
    """

    def __init__(self) -> None:
        self._initialized: bool = False
        self._client: Optional[object] = None
        self._collection: Optional[object] = None
        self._docs: list[dict] = []
        self._fallback_dir: Optional[Path] = None

    # ═══════════════════════════════════════════════════════════
    # Day1: Embedding 兼容 + 基础客户端
    # ═══════════════════════════════════════════════════════════

    def _build_embedding_function(self) -> Optional[object]:
        """读取 EMBEDDING_PROVIDER + API Key 决策 Embedding 函数。

        有 API Key → OpenAIEmbeddingFunction（支持 base_url 自定义中转地址）。
        无 API Key → 返回 None，ChromaDB 自动使用内置 all-MiniLM-L6-v2。
        无论有无 Key 程序均不崩溃。
        """
        import chromadb.utils.embedding_functions as ef

        api_key = settings.LLM_API_KEY
        provider = settings.EMBEDDING_PROVIDER.lower()

        if provider == "chroma":
            logger.info("[知识库] 使用 ChromaDB 内置 ONNX Embedding (all-MiniLM-L6-v2)")
            return None

        if provider == "openai" and api_key:
            base_url = settings.LLM_BASE_URL or "https://api.openai.com/v1"
            logger.info(
                f"[知识库] OpenAI Embedding: {settings.EMBEDDING_MODEL} "
                f"({settings.EMBEDDING_DIM}d) @ {base_url}"
            )
            return ef.OpenAIEmbeddingFunction(
                api_key=api_key,
                model_name=settings.EMBEDDING_MODEL,
                api_base=base_url,
            )

        logger.info(
            f"[知识库] EMBEDDING_PROVIDER={provider}, "
            f"API Key={'有' if api_key else '无'} → 使用 ChromaDB 内置 DefaultEmbeddingFunction"
        )
        return None

    # ═══════════════════════════════════════════════════════════
    # Day2: 初始化启动逻辑
    # ═══════════════════════════════════════════════════════════

    async def initialize(self) -> None:
        """启动时调用一次。ChromaDB 优先，失败自动切换文件降级模式。"""
        if self._initialized:
            return
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
            coll_name = settings.CHROMA_COLLECTION_NAME
            existing = [c.name for c in self._client.list_collections()]
            if coll_name in existing:
                self._collection = self._client.get_collection(
                    name=coll_name, embedding_function=embedding_fn,
                )
                logger.info(f"[知识库] 复用已有集合 '{coll_name}'")
            else:
                self._collection = self._client.create_collection(
                    name=coll_name, embedding_function=embedding_fn,
                    metadata={"hnsw:space": "cosine"},
                )
                logger.info(f"[知识库] 创建新集合 '{coll_name}' (hnsw:space=cosine)")

            self._initialized = True
            logger.info(f"【知识库】ChromaDB模式, chunks={self._collection.count()}")
            return
        except Exception as e:
            logger.warning(f"[知识库] ChromaDB 启动失败 ({e})，切换文件降级模式")

        await self._init_fallback_mode()

    async def _init_fallback_mode(self) -> None:
        """文件降级：加载已有降级 md + 扫描 data/raw/ 目录作为初始语料。"""
        fb_dir = Path(settings.CHROMA_PERSIST_DIR) / "fallback_docs"
        fb_dir.mkdir(parents=True, exist_ok=True)
        self._fallback_dir = fb_dir

        for md_file in fb_dir.glob("*.md"):
            try:
                text = md_file.read_text(encoding="utf-8")
                self._docs.append({
                    "doc_id": md_file.stem, "doc_title": md_file.stem,
                    "chunk_index": 0, "content": text,
                })
            except Exception:
                pass

        raw_dir = Path(__file__).parent.parent.parent.parent / "data" / "raw"
        if raw_dir.exists():
            seen = {d["doc_id"] for d in self._docs}
            for md_file in raw_dir.glob("**/*.md"):
                if md_file.stem in seen:
                    continue
                try:
                    text = md_file.read_text(encoding="utf-8")
                    self._docs.append({
                        "doc_id": md_file.stem, "doc_title": md_file.stem,
                        "chunk_index": 0, "content": text[:2000],
                    })
                except Exception:
                    pass

        self._initialized = True
        logger.info(f"[知识库] 文件降级模式就绪, docs={len(self._docs)}")

    # ═══════════════════════════════════════════════════════════
    # Day3: 文本切分 + 入库接口
    # ═══════════════════════════════════════════════════════════

    def _chunk_text(self, text: str, chunk_size: int = 512, overlap: int = 64) -> list[str]:
        """按换行分段，累积至 chunk_size 字符生成 chunk，overlap 从上一段末尾截取。"""
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not paragraphs:
            return [text[:chunk_size]] if text.strip() else []

        chunks: list[str] = []
        current = ""
        for p in paragraphs:
            if len(current) + len(p) < chunk_size:
                current += p + "\n\n"
            else:
                if current.strip():
                    chunks.append(current.strip())
                tail = current.strip()[-overlap:] if len(current.strip()) > overlap else ""
                current = (tail + "\n\n" + p + "\n\n") if tail else (p + "\n\n")

        if current.strip():
            chunks.append(current.strip())
        return chunks or [text[:chunk_size]]

    async def add_document(self, doc_id: str, title: str, content: str) -> list[dict]:
        """添加单篇文档。切分 → 向量化写入 / 文件追加 → 返回 chunk 列表。

        Returns:
            list[dict]: 每个元素含 doc_id, doc_title, chunk_index, content。
        """
        chunks = self._chunk_text(content)
        chunk_ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]

        if self._collection is not None:
            metadatas = [
                {"doc_id": doc_id, "doc_title": title, "chunk_index": i}
                for i in range(len(chunks))
            ]
            self._collection.add(ids=chunk_ids, documents=chunks, metadatas=metadatas)
            logger.info(f"[知识库] ChromaDB 写入: '{title}' → {len(chunks)} chunks")
        else:
            if self._fallback_dir:
                (self._fallback_dir / f"{doc_id}.md").write_text(content, encoding="utf-8")
            # 文件模式去重：先移除旧记录再追加
            self._docs = [d for d in self._docs if d.get("doc_id") != doc_id]
            for i, c in enumerate(chunks):
                self._docs.append({
                    "doc_id": doc_id, "doc_title": title,
                    "chunk_index": i, "content": c,
                })
            logger.info(f"[知识库] 文件降级写入: '{title}' → {len(chunks)} chunks")

        return [
            {"doc_id": doc_id, "doc_title": title, "chunk_index": i, "content": c}
            for i, c in enumerate(chunks)
        ]

    async def add_documents_batch(self, docs: list[dict]) -> int:
        """批量入库。每项含 {doc_id, title, content}，单篇失败不中断整体流程。

        Returns:
            int: 成功入库文档数量。
        """
        success = 0
        for doc in docs:
            try:
                await self.add_document(
                    doc_id=doc.get("doc_id", ""),
                    title=doc.get("title", ""),
                    content=doc.get("content", ""),
                )
                success += 1
            except Exception as e:
                logger.warning(f"[知识库] 批量导入单篇失败: {doc.get('title', '?')} — {e}")
        logger.info(f"[知识库] 批量导入完成: {success}/{len(docs)}")
        return success

    # ═══════════════════════════════════════════════════════════
    # Day4: 检索 + CRUD
    # ═══════════════════════════════════════════════════════════

    async def search(self, query: str, top_k: int = 10) -> list[dict]:
        """语义检索。ChromaDB 模式用向量检索，文件降级模式用关键词匹配。

        relevance_score = 1 - distance/2，限制在 [0, 1] 区间。
        """
        if not query.strip():
            return []
        if self._collection is not None:
            try:
                n = min(top_k, max(1, self._collection.count()))
                if n == 0:
                    return []
                results = self._collection.query(query_texts=[query], n_results=n)
                return self._format_search_results(results)
            except Exception as e:
                logger.warning(f"[知识库] ChromaDB 检索异常 ({e})，降级到关键词匹配")
        return self._keyword_search(query, top_k)

    def _format_search_results(self, results: dict) -> list[dict]:
        """ChromaDB 原始结果 → 统一格式，relevance_score = 1 - distance/2。"""
        formatted: list[dict] = []
        ids_list = results.get("ids", [[]])[0]
        docs_list = results.get("documents", [[]])[0]
        metas_list = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        for i in range(len(ids_list)):
            meta = metas_list[i] if i < len(metas_list) else {}
            dist = distances[i] if i < len(distances) else 0.0
            score = round(max(0.0, min(1.0, 1.0 - dist / 2.0)), 4)
            formatted.append({
                "doc_id": meta.get("doc_id", ""),
                "doc_title": meta.get("doc_title", ""),
                "chunk_index": meta.get("chunk_index", 0),
                "content": docs_list[i] if i < len(docs_list) else "",
                "relevance_score": score,
            })
        return formatted

    def _keyword_search(self, query: str, top_k: int) -> list[dict]:
        """关键词匹配检索（文件降级模式）。"""
        keywords = query.lower().split()
        scored: list[tuple[int, dict]] = []
        for doc in self._docs:
            hits = sum(1 for kw in keywords if kw in doc["content"].lower())
            if hits > 0:
                d = doc.copy()
                d["_score"] = hits
                scored.append((hits, d))
        scored.sort(key=lambda x: x[0], reverse=True)
        results = [d for _, d in scored[:top_k]]
        max_kw = max(1, len(keywords))
        for r in results:
            r["relevance_score"] = round(min(1.0, r.get("_score", 0) / max_kw), 4)
        return results

    async def delete_document(self, doc_id: str) -> bool:
        """删除文档全部 chunks。ChromaDB 模式按 doc_id 过滤删除，文件模式移除内存及落盘文件。"""
        if not doc_id:
            return False
        if self._collection is not None:
            try:
                existing = self._collection.get(where={"doc_id": doc_id})
                if existing and existing.get("ids"):
                    self._collection.delete(ids=existing["ids"])
                    logger.info(f"[知识库] 删除: {doc_id} ({len(existing['ids'])} chunks)")
                    return True
            except Exception as e:
                logger.warning(f"[知识库] ChromaDB 删除异常: {e}")
            return False
        before = len(self._docs)
        self._docs = [d for d in self._docs if d.get("doc_id") != doc_id]
        if self._fallback_dir:
            fb_file = self._fallback_dir / f"{doc_id}.md"
            if fb_file.exists():
                fb_file.unlink()
        deleted = len(self._docs) < before
        if deleted:
            logger.info(f"[知识库] 文件模式删除: {doc_id}")
        return deleted

    async def get_stats(self) -> dict:
        """返回知识库统计信息: {mode, total_chunks, total_documents, collection_name}。"""
        if self._collection is not None:
            try:
                total_chunks = self._collection.count()
                ids = self._collection.get()["ids"]
                doc_ids = {cid.rsplit("_chunk_", 1)[0] for cid in ids}
                total_documents = len(doc_ids)
            except Exception:
                total_chunks, total_documents = 0, 0
            return {
                "mode": "chroma",
                "total_chunks": total_chunks,
                "total_documents": total_documents,
                "collection_name": settings.CHROMA_COLLECTION_NAME,
            }
        doc_ids = {d.get("doc_id", "") for d in self._docs}
        return {
            "mode": "file",
            "total_chunks": len(self._docs),
            "total_documents": len(doc_ids),
            "collection_name": "file_fallback",
        }


# 全局单例
knowledge_base = KnowledgeBase()
 # ═══════════════════════════════════════════════════════════
    # Day4: 检索 + CRUD
    # ═══════════════════════════════════════════════════════════

async def search(self, query: str, top_k: int = 10) -> list[dict]:
        """语义检索。ChromaDB 模式用向量检索，文件降级模式用关键词匹配。

        relevance_score = 1 - distance/2，限制在 [0, 1] 区间。
        """
        if not query.strip():
            return []
        if self._collection is not None:
            try:
                n = min(top_k, max(1, self._collection.count()))
                if n == 0:
                    return []
                results = self._collection.query(query_texts=[query], n_results=n)
                return self._format_search_results(results)
            except Exception as e:
                logger.warning(f"[知识库] ChromaDB 检索异常 ({e})，降级到关键词匹配")
        return self._keyword_search(query, top_k)

def _format_search_results(self, results: dict) -> list[dict]:
        """ChromaDB 原始结果 → 统一格式，relevance_score = 1 - distance/2。"""
        formatted: list[dict] = []
        ids_list = results.get("ids", [[]])[0]
        docs_list = results.get("documents", [[]])[0]
        metas_list = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        for i in range(len(ids_list)):
            meta = metas_list[i] if i < len(metas_list) else {}
            dist = distances[i] if i < len(distances) else 0.0
            score = round(max(0.0, min(1.0, 1.0 - dist / 2.0)), 4)
            formatted.append({
                "doc_id": meta.get("doc_id", ""),
                "doc_title": meta.get("doc_title", ""),
                "chunk_index": meta.get("chunk_index", 0),
                "content": docs_list[i] if i < len(docs_list) else "",
                "relevance_score": score,
            })
        return formatted

def _keyword_search(self, query: str, top_k: int) -> list[dict]:
        """关键词匹配检索（文件降级模式）。"""
        keywords = query.lower().split()
        scored: list[tuple[int, dict]] = []
        for doc in self._docs:
            hits = sum(1 for kw in keywords if kw in doc["content"].lower())
            if hits > 0:
                d = doc.copy()
                d["_score"] = hits
                scored.append((hits, d))
        scored.sort(key=lambda x: x[0], reverse=True)
        results = [d for _, d in scored[:top_k]]
        max_kw = max(1, len(keywords))
        for r in results:
            r["relevance_score"] = round(min(1.0, r.get("_score", 0) / max_kw), 4)
        return results

async def delete_document(self, doc_id: str) -> bool:
        """删除文档全部 chunks。ChromaDB 模式按 doc_id 过滤删除，文件模式移除内存及落盘文件。"""
        if not doc_id:
            return False
        if self._collection is not None:
            try:
                existing = self._collection.get(where={"doc_id": doc_id})
                if existing and existing.get("ids"):
                    self._collection.delete(ids=existing["ids"])
                    logger.info(f"[知识库] 删除: {doc_id} ({len(existing['ids'])} chunks)")
                    return True
            except Exception as e:
                logger.warning(f"[知识库] ChromaDB 删除异常: {e}")
            return False
        before = len(self._docs)
        self._docs = [d for d in self._docs if d.get("doc_id") != doc_id]
        if self._fallback_dir:
            fb_file = self._fallback_dir / f"{doc_id}.md"
            if fb_file.exists():
                fb_file.unlink()
        deleted = len(self._docs) < before
        if deleted:
            logger.info(f"[知识库] 文件模式删除: {doc_id}")
        return deleted

async def get_stats(self) -> dict:
        """返回知识库统计信息: {mode, total_chunks, total_documents, collection_name}。"""
        if self._collection is not None:
            try:
                total_chunks = self._collection.count()
                ids = self._collection.get()["ids"]
                doc_ids = {cid.rsplit("_chunk_", 1)[0] for cid in ids}
                total_documents = len(doc_ids)
            except Exception:
                total_chunks, total_documents = 0, 0
            return {
                "mode": "chroma",
                "total_chunks": total_chunks,
                "total_documents": total_documents,
                "collection_name": settings.CHROMA_COLLECTION_NAME,
            }
        doc_ids = {d.get("doc_id", "") for d in self._docs}
        return {
            "mode": "file",
            "total_chunks": len(self._docs),
            "total_documents": len(doc_ids),
            "collection_name": "file_fallback",
        }


# 全局单例
knowledge_base = KnowledgeBase()
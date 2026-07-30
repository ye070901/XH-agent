"""知识库 — ChromaDB 向量检索 + 文件系统降级。

角色：人员4 — RAG 基础设施核心。
提供统一的文档存储/检索/删除/统计接口。

ChromaDB 模式：向量语义检索，支持相似度阈值过滤、批量查询、metadata 过滤。
文件降级模式：关键词匹配，ChromaDB 不可用时自动切换。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from loguru import logger

from ..config import settings

# ═══════════════════════════════════════════════════════════
# KnowledgeBase 主类
# ═══════════════════════════════════════════════════════════


class KnowledgeBase:
    """领域知识库。

    自动模式选择：
      - ChromaDB 可用 → 向量语义检索（持久化存储）
      - ChromaDB 不可用 → 文件关键词检索（内存降级）

    所有公开方法均为 async，返回结构化的 dict 列表。
    """

    def __init__(self) -> None:
        self._initialized: bool = False
        self._client: Any = None
        self._collection: Any = None
        self._embedding_fn: Any = None
        self._docs: list[dict] = []  # 文件降级模式的文档缓存

    # ═══════════════════════════════════════════════════════════
    # 初始化
    # ═══════════════════════════════════════════════════════════

    async def initialize(self) -> None:
        """初始化知识库：优先 ChromaDB，失败则降级为文件检索。

        幂等调用：已初始化时直接返回。
        """
        if self._initialized:
            return

        # 尝试 ChromaDB 模式
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings

            persist_dir = Path(settings.CHROMA_PERSIST_DIR)
            persist_dir.mkdir(parents=True, exist_ok=True)

            self._client = chromadb.PersistentClient(
                path=str(persist_dir),
                settings=ChromaSettings(anonymized_telemetry=False),
            )

            # 配置 embedding 函数
            self._embedding_fn = _build_embedding_function()

            collection_name = settings.CHROMA_COLLECTION_NAME
            self._collection = self._client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
                embedding_function=self._embedding_fn,
            )
            self._initialized = True
            logger.info(
                f"[知识库] ChromaDB 模式就绪 "
                f"(collection={collection_name}, dir={persist_dir}, "
                f"count={self._collection.count()})"
            )
            return
        except Exception as e:
            logger.warning(f"[知识库] ChromaDB 初始化失败: {e}，降级为文件检索模式")

        # 降级：从文件系统加载
        await self._init_fallback()
        self._initialized = True

    async def _init_fallback(self) -> None:
        """文件检索降级模式：加载 data/knowledge_base/*.md + *.txt 到内存。"""
        kb_dir = Path(__file__).parent.parent.parent.parent / "data" / "knowledge_base"
        if not kb_dir.exists():
            logger.info(f"[知识库] 知识库目录不存在: {kb_dir}，降级模式无文档")
            return

        loaded = 0
        for doc_file in sorted(kb_dir.glob("*"), key=lambda p: p.name):
            if doc_file.suffix.lower() not in (".md", ".txt"):
                continue
            try:
                content = doc_file.read_text(encoding="utf-8")
                self._docs.append(
                    {
                        "doc_id": doc_file.stem,
                        "content": content[:2000],
                        "metadata": {
                            "doc_title": doc_file.stem,
                            "source_level": "unknown",
                            "reviewer": "",
                            "code_verified": False,
                        },
                    }
                )
                loaded += 1
            except UnicodeDecodeError:
                try:
                    content = doc_file.read_text(encoding="gbk")
                    self._docs.append(
                        {
                            "doc_id": doc_file.stem,
                            "content": content[:2000],
                            "metadata": {
                                "doc_title": doc_file.stem,
                                "source_level": "unknown",
                                "reviewer": "",
                                "code_verified": False,
                            },
                        }
                    )
                    loaded += 1
                except Exception as e:
                    logger.warning(f"[知识库] 编码失败: {doc_file.name}: {e}")
            except Exception as e:
                logger.warning(f"[知识库] 读取失败: {doc_file.name}: {e}")

        logger.info(f"[知识库] 文件检索降级模式，加载了 {loaded} 篇文档")

    # ═══════════════════════════════════════════════════════════
    # 检索
    # ═══════════════════════════════════════════════════════════

    async def query(
        self,
        query_text: str,
        top_k: int = 5,
        min_similarity: float = 0.6,
    ) -> list[dict]:
        """语义检索，返回相似度 ≥ min_similarity 的 Top-K 结果。

        Args:
            query_text:      检索查询文本。
            top_k:           返回的最大结果数。
            min_similarity:  最低相似度阈值（0-1），低于此值的结果被过滤。

        Returns:
            list[dict]: 每个元素:
                - doc_id:      文档 ID
                - content:     匹配的 chunk 文本
                - score:       相似度分数 (0-1)
                - metadata:    {source_level, reviewer, code_verified, doc_title}
                - chunk_idx:   分片序号
        """
        if not query_text.strip():
            return []

        # ChromaDB 向量检索模式
        if self._collection is not None:
            return await self._query_chroma(query_text, top_k, min_similarity)

        # 文件关键词降级模式
        return await self._query_fallback(query_text, top_k, min_similarity)

    async def _query_chroma(
        self,
        query_text: str,
        top_k: int,
        min_similarity: float,
    ) -> list[dict]:
        """ChromaDB 向量检索。"""
        try:
            collection_count = self._collection.count()
            if collection_count == 0:
                return []

            n_results = min(top_k, collection_count)
            results = self._collection.query(
                query_texts=[query_text],
                n_results=n_results,
                include=["documents", "metadatas", "distances"],
            )

            ids_list: list = results.get("ids", [[]])[0]
            docs_list: list = results.get("documents", [[]])[0]
            metas_list: list = results.get("metadatas", [[]])[0]
            distances_list: list = results.get("distances", [[]])[0]

            formatted: list[dict] = []
            for i in range(len(ids_list)):
                # Cosine 距离 → 相似度: score = 1 - distance
                distance = distances_list[i] if i < len(distances_list) else 1.0
                score = max(0.0, min(1.0, 1.0 - float(distance)))

                # 相似度阈值过滤
                if score < min_similarity:
                    continue

                meta = metas_list[i] if i < len(metas_list) else {}
                item = {
                    "doc_id": meta.get("doc_id", ""),
                    "content": docs_list[i] if i < len(docs_list) else "",
                    "score": round(score, 4),
                    "metadata": {
                        "doc_title": meta.get("doc_title", ""),
                        "source_level": meta.get("source_level", "unknown"),
                        "reviewer": meta.get("reviewer", ""),
                        "code_verified": meta.get("code_verified", False),
                    },
                    "chunk_idx": meta.get("chunk_idx", i),
                }
                formatted.append(item)

            logger.debug(
                f"[知识库] query 返回 {len(formatted)}/{n_results} 条 "
                f"(min_similarity={min_similarity})"
            )
            return formatted

        except Exception as e:
            logger.error(f"[知识库] ChromaDB query 异常: {e}")
            return []

    async def _query_fallback(
        self,
        query_text: str,
        top_k: int,
        min_similarity: float,
    ) -> list[dict]:
        """文件关键词降级检索：关键词命中数 / 总关键词数 作为近似相似度。"""
        keywords = [kw.strip().lower() for kw in query_text.split() if len(kw.strip()) >= 1]
        if not keywords:
            return self._docs[:top_k] if self._docs else []

        scored: list[tuple[float, dict]] = []
        for doc in self._docs:
            content_lower = doc["content"].lower()
            hits = sum(1 for kw in keywords if kw in content_lower)
            if hits > 0:
                score = hits / len(keywords)
                if score >= min_similarity:
                    entry = {
                        "doc_id": doc["doc_id"],
                        "content": doc["content"],
                        "score": round(score, 4),
                        "metadata": doc.get("metadata", {}),
                        "chunk_idx": doc.get("chunk_idx", 0),
                    }
                    scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:top_k]]

    async def query_multi(
        self,
        queries: list[str],
        top_k: int = 3,
    ) -> list[dict]:
        """批量检索：对多个查询并行检索，合并去重。

        Args:
            queries: 检索查询文本列表。
            top_k:   每个查询返回的最大结果数。

        Returns:
            list[dict]: 合并去重后的结果列表（按 score 降序）。
        """
        if not queries:
            return []

        # 并行检索
        all_results: list[dict] = []
        seen_ids: set[tuple[str, int]] = set()

        for query_text in queries:
            results = await self.query(query_text, top_k=top_k, min_similarity=0.0)
            for r in results:
                key = (r["doc_id"], r["chunk_idx"])
                if key not in seen_ids:
                    seen_ids.add(key)
                    all_results.append(r)

        # 按 score 降序
        all_results.sort(key=lambda x: x["score"], reverse=True)
        logger.debug(f"[知识库] query_multi({len(queries)} 查询) → {len(all_results)} 条去重结果")
        return all_results

    # ═══════════════════════════════════════════════════════════
    # 写入
    # ═══════════════════════════════════════════════════════════

    async def add_document(
        self,
        doc_id: str,
        title: str,
        content: str,
        metadata: Optional[dict] = None,
    ) -> list[dict]:
        """添加/更新文档。

        内部流程：解析 → 智能分片 → 逐 chunk 入库（含 metadata 继承）。

        Args:
            doc_id:   文档唯一 ID。
            title:    文档标题。
            content:  文档全文（纯文本/Markdown）。
            metadata: 可选元数据:
                - source_level:   "official" | "community" | "personal"
                - reviewer:       人工审核人姓名
                - code_verified:  是否经过代码验证 (bool)

        Returns:
            list[dict]: 入库的 chunk 列表，每个包含:
                - doc_id / doc_title / chunk_idx / content / metadata
        """
        # 先删除旧版本（如果存在）
        await self.delete_document(doc_id)

        # 智能分片（调用 parser.py 的统一分片逻辑）
        from .parser import chunk_text as smart_chunk

        chunks = smart_chunk(content)

        # 构建 metadata
        meta = dict(metadata) if metadata else {}
        meta["doc_id"] = doc_id
        meta["doc_title"] = title

        # 补齐默认值
        meta.setdefault("source_level", "personal")
        meta.setdefault("reviewer", "")
        meta.setdefault("code_verified", False)

        # ChromaDB 模式
        if self._collection is not None:
            chunk_ids = [f"{doc_id}__chunk_{c['chunk_idx']}" for c in chunks]
            documents = [c["content"] for c in chunks]
            metadatas = []
            for c in chunks:
                chunk_meta = dict(meta)
                chunk_meta["chunk_idx"] = c["chunk_idx"]
                chunk_meta["heading_path"] = c.get("heading_path", "")
                metadatas.append(chunk_meta)

            self._collection.add(
                ids=chunk_ids,
                documents=documents,
                metadatas=metadatas,
            )
            logger.info(f"[知识库] ChromaDB 添加文档 '{title}' ({doc_id}): {len(chunks)} chunks")
        else:
            # 文件降级模式：存储全文前 2000 字符
            self._docs.append(
                {
                    "doc_id": doc_id,
                    "content": content[:2000],
                    "metadata": meta,
                    "chunk_idx": 0,
                }
            )
            logger.info(f"[知识库] 降级模式 添加文档 '{title}' ({doc_id})")

        return [
            {
                "doc_id": doc_id,
                "doc_title": title,
                "chunk_idx": c["chunk_idx"],
                "content": c["content"],
                "metadata": meta,
            }
            for c in chunks
        ]

    # ═══════════════════════════════════════════════════════════
    # 删除
    # ═══════════════════════════════════════════════════════════

    async def delete_document(self, doc_id: str) -> int:
        """删除指定文档及其所有 chunk。

        Args:
            doc_id: 要删除的文档 ID。

        Returns:
            int: 删除的 chunk 数量。0 表示文档不存在。
        """
        deleted = 0

        # ChromaDB 模式：按 doc_id 过滤查询 → 批量删除
        if self._collection is not None:
            try:
                existing = self._collection.get(
                    where={"doc_id": doc_id},
                    include=[],
                )
                chunk_ids = existing.get("ids", [])
                if chunk_ids:
                    self._collection.delete(ids=chunk_ids)
                    deleted = len(chunk_ids)
                    logger.info(f"[知识库] ChromaDB 删除文档 '{doc_id}': {deleted} chunks")
            except Exception as e:
                logger.error(f"[知识库] ChromaDB 删除异常: {e}")
                return 0
        else:
            # 文件降级模式
            before = len(self._docs)
            self._docs = [d for d in self._docs if d.get("doc_id") != doc_id]
            deleted = before - len(self._docs)
            if deleted > 0:
                logger.info(f"[知识库] 降级模式 删除文档 '{doc_id}': {deleted} 条")

        return deleted

    # ═══════════════════════════════════════════════════════════
    # 统计
    # ═══════════════════════════════════════════════════════════

    async def get_stats(self) -> dict:
        """获取知识库统计信息。

        Returns:
            dict:
                - total_chunks:     总 chunk 数
                - total_documents:  唯一文档数
                - collection_name:  集合名称
                - mode:             "chromadb" | "fallback"
                - source_breakdown: {official: N, community: N, personal: N}
        """
        if self._collection is not None:
            try:
                total_chunks = self._collection.count()
                # 获取所有 metadata 来统计文档数和来源分布
                all_data = self._collection.get(include=["metadatas"])
                metas = all_data.get("metadatas", [])

                doc_ids: set[str] = set()
                source_breakdown: dict[str, int] = {
                    "official": 0,
                    "community": 0,
                    "personal": 0,
                    "unknown": 0,
                }
                for m in metas:
                    did = m.get("doc_id", "")
                    if did:
                        doc_ids.add(did)
                    sl = m.get("source_level", "unknown")
                    source_breakdown[sl] = source_breakdown.get(sl, 0) + 1

                return {
                    "total_chunks": total_chunks,
                    "total_documents": len(doc_ids),
                    "collection_name": settings.CHROMA_COLLECTION_NAME,
                    "mode": "chromadb",
                    "source_breakdown": source_breakdown,
                }
            except Exception as e:
                logger.error(f"[知识库] get_stats 异常: {e}")

        # 降级模式
        doc_ids = {d.get("doc_id", "") for d in self._docs}
        return {
            "total_chunks": len(self._docs),
            "total_documents": len(doc_ids),
            "collection_name": settings.CHROMA_COLLECTION_NAME,
            "mode": "fallback",
            "source_breakdown": {
                "official": 0,
                "community": 0,
                "personal": len(self._docs),
                "unknown": 0,
            },
        }


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

knowledge_base = KnowledgeBase()


# ═══════════════════════════════════════════════════════════
# 私有：Embedding 函数构建
# ═══════════════════════════════════════════════════════════


def _build_embedding_function() -> Any:
    """根据 settings 构建 ChromaDB embedding function。

    支持的 provider：
      - openai:    OpenAI text-embedding-3-small（默认）
      - local:     使用 ChromaDB 内置的 Sentence Transformers
      - 其他:      回退到 ChromaDB 默认（all-MiniLM-L6-v2）

    注意：使用远程 API（OpenAI）时，chromadb 会自动调用，
    但需要 LLM_API_KEY 已配置。
    """
    provider = settings.EMBEDDING_PROVIDER.lower()

    if provider == "openai":
        try:
            from chromadb.utils import embedding_functions

            api_key = settings.LLM_API_KEY
            if not api_key:
                logger.warning(
                    "[知识库] EMBEDDING_PROVIDER=openai 但 LLM_API_KEY 为空，"
                    "回退到 ChromaDB 默认 embedding"
                )
                return None
            fn = embedding_functions.OpenAIEmbeddingFunction(
                api_key=api_key,
                model_name=settings.EMBEDDING_MODEL,
            )
            logger.info(f"[知识库] Embedding: OpenAI/{settings.EMBEDDING_MODEL}")
            return fn
        except Exception as e:
            logger.warning(f"[知识库] OpenAI embedding 初始化失败: {e}，回退默认")
            return None

    elif provider == "local":
        try:
            from chromadb.utils import embedding_functions

            fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="shibing624/text2vec-base-chinese",
            )
            logger.info("[知识库] Embedding: 本地中文模型 text2vec-base-chinese")
            return fn
        except Exception as e:
            logger.warning(f"[知识库] 本地 embedding 初始化失败: {e}，回退默认")
            return None

    else:
        logger.info(f"[知识库] Embedding: ChromaDB 默认 (provider={provider})")
        return None

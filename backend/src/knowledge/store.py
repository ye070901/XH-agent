"""知识库存储引擎 — ChromaDB 向量检索 + Embedding 自动切换 + 文件降级模式。

Opt‑2 KB 引擎核心模块。只做存储检索，不包含 Agent / LLM 逻辑。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from loguru import logger

from ..config import settings
from .kb_utils import evaluate_search_quality, import_seed_documents, verify_persistence


class KnowledgeBase:
    """领域知识库存储引擎 — ChromaDB 向量检索 / 文件降级双模式。"""

    def __init__(self) -> None:
        self._initialized: bool = False
        self._client: Optional[object] = None
        self._collection: Optional[object] = None
        self._docs: list[dict] = []
        self._fallback_dir: Optional[Path] = None
        self._persist_snapshot: Optional[dict] = None

    # ════ Embedding / 初始化 ════

    def _build_embedding_function(self) -> Optional[object]:
        """根据 EMBEDDING_PROVIDER 决策：OpenAI API Key → OpenAIEmbeddingFunction / 否则 None。"""
        import chromadb.utils.embedding_functions as ef

        api_key = settings.LLM_API_KEY
        provider = settings.EMBEDDING_PROVIDER.lower()

        if provider == "chroma":
            logger.info("[知识库] ChromaDB内置ONNX Embedding")
            return None

        if provider == "openai" and api_key:
            base_url = settings.LLM_BASE_URL or "https://api.openai.com/v1"
            logger.info(f"[知识库] OpenAI Embedding: {settings.EMBEDDING_MODEL} @ {base_url}")
            return ef.OpenAIEmbeddingFunction(
                api_key=api_key, model_name=settings.EMBEDDING_MODEL, api_base=base_url
            )

        logger.info(f"[知识库] DefaultEmbeddingFunction (provider={provider})")
        return None

    async def initialize(self) -> None:
        """ChromaDB 优先启动，失败自动切换文件降级模式。"""
        if self._initialized:
            return

        import os

        onnx_path = os.path.expanduser("~/.cache/chroma/onnx_models/all-MiniLM-L6-v2/onnx.tar.gz")
        if os.path.exists(onnx_path):
            size = os.path.getsize(onnx_path)
            if size < 70_000_000:
                logger.warning("[知识库] ONNX模型不完整，跳过ChromaDB初始化")
                await self._init_fallback_mode()
                return

        try:
            if "HF_ENDPOINT" not in os.environ:
                os.environ["HF_ENDPOINT"] = settings.HF_ENDPOINT

            import chromadb
            from chromadb.config import Settings as ChromaSettings

            persist_dir = Path(settings.CHROMA_PERSIST_DIR)
            persist_dir.mkdir(parents=True, exist_ok=True)

            embedding_fn = self._build_embedding_function()
            self._client = chromadb.PersistentClient(
                path=str(persist_dir), settings=ChromaSettings(anonymized_telemetry=False)
            )
            coll_name = settings.CHROMA_COLLECTION_NAME
            existing = [c.name for c in self._client.list_collections()]
            if coll_name in existing:
                self._collection = self._client.get_collection(
                    name=coll_name, embedding_function=embedding_fn
                )
                # 空 collection（旧版本遗留，可能无 embedding function）→ 删除重建，
                # 否则 add() 会因缺 embedding function 报错
                if self._collection.count() == 0:
                    self._client.delete_collection(coll_name)
                    self._collection = self._client.create_collection(
                        name=coll_name,
                        embedding_function=embedding_fn,
                        metadata={"hnsw:space": "cosine"},
                    )
                    logger.info(f"[知识库] 重建空集合 '{coll_name}'")
                else:
                    logger.info(f"[知识库] 复用已有集合 '{coll_name}'")
            else:
                self._collection = self._client.create_collection(
                    name=coll_name,
                    embedding_function=embedding_fn,
                    metadata={"hnsw:space": "cosine"},
                )
                logger.info(f"[知识库] 创建新集合 '{coll_name}'")

            self._initialized = True
            chroma_count = self._collection.count()
            logger.info(f"【知识库】ChromaDB模式, chunks={chroma_count}")
            # collection 为空时自动向量化导入 data/raw（首次启动 / 数据未入库）
            if chroma_count == 0:
                await self._auto_import_raw_to_chroma()
            # 兜底：无论 ChromaDB 是否有数据，都加载 data/raw 到内存，
            # 供 ChromaDB 空结果时回退关键词检索（embedding 不可用时的可靠路径）
            self._load_raw_docs()
            await self._record_persistence_snapshot()
            return
        except Exception as e:
            logger.warning(f"[知识库] ChromaDB 启动失败 ({e})，切换文件降级模式")

        await self._init_fallback_mode()

    async def _init_fallback_mode(self) -> None:
        """文件降级模式：加载持久化 md + 扫描 data/raw/ 全部 .md 文档作为语料。"""
        fb_dir = Path(settings.CHROMA_PERSIST_DIR) / "fallback_docs"
        fb_dir.mkdir(parents=True, exist_ok=True)
        self._fallback_dir = fb_dir

        for md_file in fb_dir.glob("*.md"):
            try:
                text = md_file.read_text(encoding="utf-8")
                self._docs.append(
                    {
                        "doc_id": md_file.stem,
                        "doc_title": md_file.stem,
                        "chunk_index": 0,
                        "content": text,
                    }
                )
            except Exception:
                pass

        self._load_raw_docs()

        self._initialized = True
        logger.info(f"[知识库] 文件降级模式就绪, total_chunks={len(self._docs)}")
        await self._record_persistence_snapshot()

    def _load_raw_docs(self) -> int:
        """扫描 data/raw 全部 .md 加载到内存 _docs，作为关键词检索兜底语料。

        幂等（按 doc_id 去重）。不依赖 embedding 服务与网络，纯本地文件读取，
        是 ChromaDB embedding 不可用（如 DeepSeek 不提供 embedding 端点）时的
        可靠检索路径。重启后 data/raw 本地文件恒在，自动重新加载，等价于持久化。
        """
        raw_dir = Path(__file__).parent.parent.parent.parent / "data" / "raw"
        if not raw_dir.exists():
            return 0

        seen = {d["doc_id"] for d in self._docs}
        total_loaded = 0
        for md_file in raw_dir.glob("**/*.md"):
            if md_file.stem in seen:
                continue
            try:
                text = md_file.read_text(encoding="utf-8")
                chunks = self._chunk_text(text)
                for i, chunk in enumerate(chunks):
                    self._docs.append(
                        {
                            "doc_id": md_file.stem,
                            "doc_title": md_file.stem,
                            "chunk_index": i,
                            "content": chunk,
                        }
                    )
                total_loaded += 1
                logger.debug(f"[知识库] 加载语料: {md_file.stem} → {len(chunks)} chunks")
            except Exception as e:
                logger.warning(f"[知识库] 语料加载失败: {md_file.name} — {e}")

        if total_loaded > 0:
            logger.info(
                f"[知识库] data/raw 加载完成: 新加载 {total_loaded} 篇，"
                f"累计 {len(self._docs)} chunks"
            )
        return total_loaded

    async def _auto_import_raw_to_chroma(self) -> int:
        """ChromaDB collection 为空时，自动将 data/raw 全部 .md 向量化入库。

        使用当前 collection 的 embedding function（chroma 模式为本地 ONNX
        all-MiniLM-L6-v2，384 维）。逐篇调用 add_document 做切分 + 向量化，
        单篇失败不阻断整体；若 embedding 连续失败触发降级（collection 置 None）
        则提前停止，剩余文档由 _load_raw_docs 兜底为关键词检索。
        """
        raw_dir = Path(__file__).parent.parent.parent.parent / "data" / "raw"
        if not raw_dir.exists():
            return 0
        md_files = sorted(raw_dir.glob("**/*.md"))
        if not md_files:
            return 0

        imported = 0
        for md_file in md_files:
            if self._collection is None:
                break
            try:
                text = md_file.read_text(encoding="utf-8")
                title = md_file.stem
                for line in text.split("\n"):
                    s = line.strip()
                    if s.startswith("# ") and not s.startswith("## "):
                        title = s[2:].strip()
                        break
                await self.add_document(doc_id=md_file.stem, title=title, content=text)
                imported += 1
            except Exception as e:
                logger.warning(f"[知识库] 自动向量化失败: {md_file.name} — {e}")

        if imported:
            logger.info(f"[知识库] 自动向量化导入: {imported}/{len(md_files)} 篇写入 ChromaDB")
        return imported

    # ════ 文本切分 + 入库 ════

    def _chunk_text(self, text: str, chunk_size: int = 512, overlap: int = 64) -> list[str]:
        """按换行分段累积至 chunk_size，overlap 滑动窗口切分超长段落。"""
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not paragraphs:
            if not text.strip():
                return []
            text_stripped = text.strip()
            if len(text_stripped) <= chunk_size:
                return [text_stripped]
            result: list[str] = []
            start = 0
            while start < len(text_stripped):
                result.append(text_stripped[start : start + chunk_size])
                start += chunk_size - overlap
            return result

        # 预处理超长段落：滑动窗口拆分为 chunk_size 子段
        expanded: list[str] = []
        for p in paragraphs:
            if len(p) <= chunk_size:
                expanded.append(p)
            else:
                start = 0
                while start < len(p):
                    expanded.append(p[start : start + chunk_size])
                    start += chunk_size - overlap
        paragraphs = expanded

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
        """添加单篇文档 → 切分 → 向量化写入 / 文件追加 → 返回 chunk 列表。

        幂等写入：ChromaDB 模式下先删除同名 doc_id 的旧 chunks 再写入，
        重复导入不会产生重复向量。
        """
        chunks = self._chunk_text(content)
        chunk_ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
        result = [
            {"doc_id": doc_id, "doc_title": title, "chunk_index": i, "content": c}
            for i, c in enumerate(chunks)
        ]

        if self._collection is not None:
            try:
                # 幂等写入：先清理旧 chunks，避免重复导入导致重复向量
                existing = self._collection.get(where={"doc_id": doc_id})
                if existing and existing.get("ids"):
                    self._collection.delete(ids=existing["ids"])
                    logger.debug(
                        f"[知识库] 清理旧 chunks: doc_id={doc_id}, count={len(existing['ids'])}"
                    )

                metadatas = [
                    {"doc_id": doc_id, "doc_title": title, "chunk_index": i}
                    for i in range(len(chunks))
                ]
                self._collection.add(ids=chunk_ids, documents=chunks, metadatas=metadatas)
                logger.info(f"[知识库] ChromaDB写入: '{title}' → {len(chunks)} chunks")
                return result
            except Exception as chroma_err:
                logger.warning(f"[知识库] ChromaDB写入失败: {chroma_err}，切换文件模式")
                self._collection = None
                await self._init_fallback_mode()

        if self._fallback_dir:
            (self._fallback_dir / f"{doc_id}.md").write_text(content, encoding="utf-8")
        self._docs = [d for d in self._docs if d.get("doc_id") != doc_id]
        self._docs.extend(result)
        logger.info(f"[知识库] 文件降级写入: '{title}' → {len(chunks)} chunks")
        return result

    async def add_documents_batch(self, docs: list[dict]) -> int:
        """批量入库，单篇失败不中断整体流程。返回成功入库数量。"""
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

    # ════ 检索 + CRUD ════

    async def search(self, query: str, top_k: int = 10) -> list[dict]:
        """语义检索：ChromaDB向量 / 文件关键词匹配。relevance_score ∈ [0,1]。"""
        t_start = time.perf_counter()
        if not query.strip():
            return []

        if self._collection is not None:
            try:
                collection_count = self._collection.count()
                if collection_count == 0:
                    result = []
                else:
                    n = min(top_k, collection_count)
                    results = self._collection.query(query_texts=[query], n_results=n)
                    result = self._format_search_results(results)
            except Exception as e:
                logger.warning(f"[知识库] ChromaDB检索异常 ({e})，降级到关键词匹配")
                result = self._keyword_search(query, top_k)
        else:
            result = self._keyword_search(query, top_k)

        # ChromaDB 空结果（collection 为空或 embedding 不可用）时，回退关键词检索兜底
        if not result and self._docs:
            result = self._keyword_search(query, top_k)

        elapsed_ms = round((time.perf_counter() - t_start) * 1000, 2)
        logger.info(
            f"[知识库] 检索耗时 | query='{query[:50]}' top_k={top_k} "
            f"results={len(result)} elapsed={elapsed_ms}ms"
        )
        if elapsed_ms >= 200:
            logger.warning(f"[知识库] ⚠️ 检索耗时超标: {elapsed_ms}ms ≥ 200ms基线")
        return result

    def _format_search_results(self, results: dict) -> list[dict]:
        """ChromaDB原始结果 → 统一格式。score = max(0, min(1, 1-distance/2))，保留4位小数。"""
        formatted: list[dict] = []
        ids_list = results.get("ids", [[]])[0]
        docs_list = results.get("documents", [[]])[0]
        metas_list = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        for i in range(len(ids_list)):
            meta = metas_list[i] if i < len(metas_list) else {}
            dist = distances[i] if i < len(distances) else 0.0
            score = round(max(0.0, min(1.0, 1.0 - dist / 2.0)), 4)
            formatted.append(
                {
                    "doc_id": meta.get("doc_id", ""),
                    "doc_title": meta.get("doc_title", ""),
                    "chunk_index": meta.get("chunk_index", 0),
                    "content": docs_list[i] if i < len(docs_list) else "",
                    "relevance_score": score,
                }
            )
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
        """删除文档全部chunks，双模式兼容。"""
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
                logger.warning(f"[知识库] ChromaDB删除异常: {e}")
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
        """返回知识库统计: {mode, total_chunks, total_documents, collection_name}。"""
        if self._collection is not None:
            try:
                total_chunks = self._collection.count()
                ids = self._collection.get()["ids"]
                doc_ids = {cid.rsplit("_chunk_", 1)[0] for cid in ids}
                total_documents = len(doc_ids)
            except Exception:
                total_chunks, total_documents = 0, 0
            # ChromaDB 空但内存兜底语料可用时，如实反映实际可检索的数据量
            if total_chunks == 0 and self._docs:
                fb_ids = {d.get("doc_id", "") for d in self._docs}
                return {
                    "mode": "file_fallback",
                    "total_chunks": len(self._docs),
                    "total_documents": len(fb_ids),
                    "collection_name": "file_fallback",
                }
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

    async def _record_persistence_snapshot(self) -> dict:
        """记录当前数据状态快照，initialize() 完成后自动调用。"""
        stats = await self.get_stats()
        self._persist_snapshot = {
            "total_chunks": stats["total_chunks"],
            "total_documents": stats["total_documents"],
            "mode": stats["mode"],
            "collection_name": stats["collection_name"],
        }
        logger.info(
            f"[知识库] 持久化快照已记录 | mode={self._persist_snapshot['mode']} "
            f"docs={self._persist_snapshot['total_documents']} "
            f"chunks={self._persist_snapshot['total_chunks']}"
        )
        return self._persist_snapshot

    async def verify_persistence(self) -> dict:
        """ChromaDB持久化校验：对比快照与当前数据状态。"""
        return await verify_persistence(self)

    async def import_seed_documents(self, raw_dir: Optional[str] = None) -> dict:
        """种子文档批量导入：扫描目录下 .md 文件批量入库。"""
        return await import_seed_documents(self, raw_dir)

    async def evaluate_search_quality(self, test_cases: Optional[list[dict]] = None) -> list[dict]:
        """检索质量评测：K1~K3 测试用例验证 Top1 命中。"""
        return await evaluate_search_quality(self, test_cases)


# 全局单例 — 所有模块通过此实例访问知识库
knowledge_base = KnowledgeBase()

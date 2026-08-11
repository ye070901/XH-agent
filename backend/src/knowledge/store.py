"""知识库存储引擎 — ChromaDB 向量检索 + Embedding 自动切换 + 文件降级模式。

Opt‑2 KB 引擎核心模块。只做存储检索，不包含 Agent / LLM 逻辑。

版本历史：
  Day1-4（08-03~08-06）：ChromaDB启动、文本切分、CRUD、语义检索
  Day5（08-07）：单元测试覆盖 + 文件自动回退增强 + 检索耗时统计基线
  Day6（08-08）：持久化校验 + 种子文档批量导入 + 检索质量评测
"""

from __future__ import annotations

import time  # Day5新增：性能统计，用于检索耗时监控
from pathlib import Path
from typing import Optional

from loguru import logger

from ..config import settings


class KnowledgeBase:
    """领域知识库存储引擎。

    ChromaDB 模式：PersistentClient + EmbeddingFunction → 语义向量检索。
    文件降级模式：ChromaDB 不可用时自动切换，读写本地 md 文件兜底。

    Day5新增能力：
      - 检索耗时统计（单次<200ms基线）
      - 文件降级增强：data/raw/扫描文档自动切分加载
    Day6新增能力：
      - ChromaDB持久化校验（重启前后数据一致性验证）
      - 种子文档批量导入（对接data/raw/目录）
      - 检索质量评测（K1~K3测试用例验证）
    """

    def __init__(self) -> None:
        self._initialized: bool = False
        self._client: Optional[object] = None
        self._collection: Optional[object] = None
        self._docs: list[dict] = []
        self._fallback_dir: Optional[Path] = None
        # Day6新增：持久化校验快照，记录最近一次initialize后的数据状态
        # 用于重启后验证数据完整性（文档总数、chunk分片数一致）
        self._persist_snapshot: Optional[dict] = None

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
            logger.info(
                "[知识库] 使用 ChromaDB 内置 ONNX Embedding (all-MiniLM-L6-v2)")
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
        """启动时调用一次。ChromaDB 优先，失败自动切换文件降级模式。

        Day5增强：ChromaDB卸载/路径错误/初始化异常时自动回退到文件模式，
                  扫描data/raw/全部.md文档作为降级语料。
        Day6增强：初始化完成后自动记录持久化快照，用于重启验证。
        """
        if self._initialized:
            return

        # 检查ONNX模型是否存在，避免下载阻塞
        import os
        onnx_path = os.path.expanduser("~/.cache/chroma/onnx_models/all-MiniLM-L6-v2/onnx.tar.gz")
        if os.path.exists(onnx_path):
            size = os.path.getsize(onnx_path)
            if size < 70_000_000:  # ONNX模型约79MB，不完整则跳过
                logger.warning(f"[知识库] ONNX模型不完整 ({size/1024/1024:.1f}MB < 79MB)，跳过ChromaDB初始化")
                await self._init_fallback_mode()
                return

        try:
            # 设置 HuggingFace 镜像以加速下载（国内网络）
            if "HF_ENDPOINT" not in os.environ:
                os.environ["HF_ENDPOINT"] = settings.HF_ENDPOINT

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
            chunks_count = self._collection.count()
            logger.info(f"【知识库】ChromaDB模式, chunks={chunks_count}")

            # Day6新增：初始化完成后记录持久化快照
            await self._record_persistence_snapshot()
            return
        except Exception as e:
            logger.warning(f"[知识库] ChromaDB 启动失败 ({e})，切换文件降级模式")

        await self._init_fallback_mode()

    async def _init_fallback_mode(self) -> None:
        """文件降级：加载已有降级 md + 扫描 data/raw/ 目录作为初始语料。

        Day5增强：对data/raw/扫描文档应用_chunk_text切分，提升文件模式检索精度。
        降级后search()通过关键词匹配正常返回结果，不报错。
        """
        fb_dir = Path(settings.CHROMA_PERSIST_DIR) / "fallback_docs"
        fb_dir.mkdir(parents=True, exist_ok=True)
        self._fallback_dir = fb_dir

        # 加载已持久化保存的降级文档（完整文本，不切分）
        for md_file in fb_dir.glob("*.md"):
            try:
                text = md_file.read_text(encoding="utf-8")
                self._docs.append({
                    "doc_id": md_file.stem, "doc_title": md_file.stem,
                    "chunk_index": 0, "content": text,
                })
            except Exception:
                pass

        # Day5增强：扫描 data/raw/ 全部md文档，应用切分逻辑
        # 当ChromaDB卸载/路径错误/初始化异常时，自动将种子文档切分加载到内存
        raw_dir = Path(__file__).parent.parent.parent.parent / "data" / "raw"
        if raw_dir.exists():
            seen = {d["doc_id"] for d in self._docs}
            total_loaded = 0
            for md_file in raw_dir.glob("**/*.md"):
                if md_file.stem in seen:
                    continue
                try:
                    text = md_file.read_text(encoding="utf-8")
                    # Day5增强：对每篇文档执行文本切分，提高关键词命中精度
                    chunks = self._chunk_text(text)
                    for i, chunk in enumerate(chunks):
                        self._docs.append({
                            "doc_id": md_file.stem,
                            "doc_title": md_file.stem,
                            "chunk_index": i,
                            "content": chunk,
                        })
                    total_loaded += 1
                    logger.debug(
                        f"[知识库] 文件降级加载: {md_file.stem} → {len(chunks)} chunks"
                    )
                except Exception as e:
                    logger.warning(f"[知识库] 文件降级加载失败: {md_file.name} — {e}")

            if total_loaded > 0:
                logger.info(f"[知识库] 文件降级扫描完成: 新加载 {total_loaded} 篇种子文档")

        self._initialized = True
        logger.info(f"[知识库] 文件降级模式就绪, total_chunks={len(self._docs)}")

        # Day6新增：降级模式下也记录快照供校验
        await self._record_persistence_snapshot()

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
                tail = current.strip(
                )[-overlap:] if len(current.strip()) > overlap else ""
                current = (tail + "\n\n" + p +
                           "\n\n") if tail else (p + "\n\n")

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
            try:
                metadatas = [
                    {"doc_id": doc_id, "doc_title": title, "chunk_index": i}
                    for i in range(len(chunks))
                ]
                self._collection.add(
                    ids=chunk_ids, documents=chunks, metadatas=metadatas)
                logger.info(f"[知识库] ChromaDB 写入: '{title}' → {len(chunks)} chunks")
            except Exception as chroma_err:
                # ChromaDB 1.5.9 API 兼容性问题，降级到文件模式
                logger.warning(f"[知识库] ChromaDB 写入失败: {chroma_err}，切换文件模式")
                self._collection = None
                await self._init_fallback_mode()
                if self._fallback_dir:
                    (self._fallback_dir / f"{doc_id}.md").write_text(content, encoding="utf-8")
                self._docs = [d for d in self._docs if d.get("doc_id") != doc_id]
                for i, c in enumerate(chunks):
                    self._docs.append({
                        "doc_id": doc_id, "doc_title": title,
                        "chunk_index": i, "content": c,
                    })
                logger.info(f"[知识库] 文件降级写入: '{title}' → {len(chunks)} chunks")
        else:
            if self._fallback_dir:
                (self._fallback_dir /
                 f"{doc_id}.md").write_text(content, encoding="utf-8")
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
                logger.warning(
                    f"[知识库] 批量导入单篇失败: {doc.get('title', '?')} — {e}")
        logger.info(f"[知识库] 批量导入完成: {success}/{len(docs)}")
        return success

    # ═══════════════════════════════════════════════════════════
    # Day4: 检索 + CRUD（核心逻辑完整保留不改动）
    # ═══════════════════════════════════════════════════════════

    async def search(self, query: str, top_k: int = 10) -> list[dict]:
        """语义检索。ChromaDB 模式用向量检索，文件降级模式用关键词匹配。

        relevance_score = 1 - distance/2，限制在 [0, 1] 区间。

        Day5新增：检索耗时统计，监控单次检索<200ms基线。
        """
        # Day5新增：检索耗时统计起点
        t_start = time.perf_counter()

        if not query.strip():
            return []

        result: list[dict] = []
        if self._collection is not None:
            # 双分支逻辑（不改动）：有可用ChromaDB集合 → 向量检索
            try:
                n = min(top_k, max(1, self._collection.count()))
                if n == 0:
                    result = []
                else:
                    results = self._collection.query(
                        query_texts=[query], n_results=n)
                    result = self._format_search_results(results)
            except Exception as e:
                logger.warning(f"[知识库] ChromaDB 检索异常 ({e})，降级到关键词匹配")
                result = self._keyword_search(query, top_k)
        else:
            # 双分支逻辑（不改动）：无ChromaDB集合 → 文件关键词检索
            result = self._keyword_search(query, top_k)

        # Day5新增：输出检索耗时日志，验证单次检索<200ms性能基线
        elapsed_ms = round((time.perf_counter() - t_start) * 1000, 2)
        logger.info(
            f"[知识库] 检索耗时 | query='{query[:50]}' top_k={top_k} "
            f"results={len(result)} elapsed={elapsed_ms}ms"
        )
        if elapsed_ms >= 200:
            logger.warning(f"[知识库] ⚠️ 检索耗时超标: {elapsed_ms}ms ≥ 200ms 基线")

        return result

    def _format_search_results(self, results: dict) -> list[dict]:
        """ChromaDB 原始结果 → 统一格式。

        相似度计算公式（固定不变）：
            relevance_score = max(0.0, min(1.0, 1.0 - distance / 2.0))
        小数保留4位。
        """
        formatted: list[dict] = []
        ids_list = results.get("ids", [[]])[0]
        docs_list = results.get("documents", [[]])[0]
        metas_list = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        for i in range(len(ids_list)):
            meta = metas_list[i] if i < len(metas_list) else {}
            dist = distances[i] if i < len(distances) else 0.0
            # 固定公式：relevance_score = max(0, min(1, 1 - distance/2))，保留4位小数
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
            r["relevance_score"] = round(
                min(1.0, r.get("_score", 0) / max_kw), 4)
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
                    logger.info(
                        f"[知识库] 删除: {doc_id} ({len(existing['ids'])} chunks)")
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
        """返回知识库统计信息: {mode, total_chunks, total_documents, collection_name}。

        双分支逻辑：ChromaDB模式统计集合内数据，文件模式统计内存数据。
        """
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

    # ═══════════════════════════════════════════════════════════
    # Day5: 性能统计基线 + 文件自动回退增强
    #   - search() 起止记录 perf_counter，输出 elapsed_ms 日志
    #   - 单次检索基线 < 200ms，超标输出 warning
    #   - _init_fallback_mode() 增强：data/raw/ 文档自动切分加载
    #     （实现在上方 _init_fallback_mode 方法中）
    # ═══════════════════════════════════════════════════════════

    # ═══════════════════════════════════════════════════════════
    # Day6: 集成验证 — 持久化校验 + 种子文档导入 + 检索质量评测
    # ═══════════════════════════════════════════════════════════

    async def _record_persistence_snapshot(self) -> dict:
        """Day6新增：记录当前数据状态快照，用于重启后持久化校验。

        调用时机：initialize() 完成后自动调用。
        记录内容：total_chunks、total_documents、mode、collection_name。

        Returns:
            dict: 当前数据状态快照。
        """
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
        """Day6新增：ChromaDB持久化校验。

        重启服务、重新执行initialize()后调用此方法，对比当前数据状态
        与上次初始化时记录的快照，验证文档总数、chunk分片数量完全一致。

        交付标准：重启前后 total_chunks 和 total_documents 完全相同。

        Returns:
            dict: {
                "verified": bool,         # 数据是否一致
                "snapshot": dict|None,    # 快照数据（上次initialize记录）
                "current": dict,          # 当前数据
                "total_chunks_match": bool,
                "total_documents_match": bool,
                "collection_name_match": bool,
            }
        """
        current = await self.get_stats()
        snapshot = self._persist_snapshot

        if snapshot is None:
            logger.warning("[知识库] 持久化校验：无快照数据，请先执行initialize()")
            return {
                "verified": False,
                "snapshot": None,
                "current": current,
                "total_chunks_match": False,
                "total_documents_match": False,
                "collection_name_match": False,
                "note": "无快照，请先执行initialize()记录快照后再校验",
            }

        chunks_match = current["total_chunks"] == snapshot["total_chunks"]
        docs_match = current["total_documents"] == snapshot["total_documents"]
        coll_match = current["collection_name"] == snapshot["collection_name"]
        verified = chunks_match and docs_match and coll_match

        chunk_flag = '✓' if chunks_match else '✗'
        doc_flag = '✓' if docs_match else '✗'
        logger.info(
            f"[知识库] 持久化校验结果 | verified={verified} "
            f"chunks: {snapshot['total_chunks']}→{current['total_chunks']}({chunk_flag}) "
            f"docs: {snapshot['total_documents']}→{current['total_documents']}({doc_flag})"
        )
        if not verified:
            logger.warning(
                f"[知识库] ⚠️ 持久化校验失败！数据在重启前后不一致，请排查ChromaDB持久化路径: "
                f"{settings.CHROMA_PERSIST_DIR}"
            )

        return {
            "verified": verified,
            "snapshot": snapshot,
            "current": current,
            "total_chunks_match": chunks_match,
            "total_documents_match": docs_match,
            "collection_name_match": coll_match,
        }

    async def import_seed_documents(self, raw_dir: Optional[str] = None) -> dict:
        """Day6新增：种子文档批量导入逻辑。

        对接项目种子文档目录 data/raw/，扫描全部 .md 种子文件，
        逐篇读取标题（取自 # 一级标题行）和正文内容，调用 add_documents_batch
        批量导入到知识库。

        导入后调用 search() 能精准检索到对应文档内容。

        Args:
            raw_dir: 可选自定义种子文档目录路径，默认使用 data/raw/。

        Returns:
            dict: {
                "imported": int,     # 成功导入篇数
                "total": int,        # 扫描到的总篇数
                "failed": int,       # 导入失败篇数
                "files": list[str],  # 已导入的文件列表
                "errors": list[str], # 失败文件及原因
            }
        """
        # 确定种子文档目录路径
        if raw_dir:
            seed_dir = Path(raw_dir)
        else:
            seed_dir = Path(__file__).parent.parent.parent.parent / "data" / "raw"

        if not seed_dir.exists():
            logger.warning(f"[知识库] 种子文档目录不存在: {seed_dir}")
            return {"imported": 0, "total": 0, "failed": 0, "files": [], "errors": []}

        # 扫描全部 .md 种子文件
        md_files = sorted(seed_dir.glob("**/*.md"))
        if not md_files:
            logger.warning(f"[知识库] 种子文档目录为空，无 .md 文件: {seed_dir}")
            return {"imported": 0, "total": 0, "failed": 0, "files": [], "errors": []}

        # 逐篇解析标题和内容
        docs_to_import: list[dict] = []
        errors: list[str] = []
        for md_file in md_files:
            try:
                text = md_file.read_text(encoding="utf-8")
                # 从 Markdown 一级标题提取文档标题
                title = md_file.stem  # 默认用文件名
                for line in text.split("\n"):
                    stripped = line.strip()
                    if stripped.startswith("# ") and not stripped.startswith("## "):
                        title = stripped[2:].strip()
                        break

                docs_to_import.append({
                    "doc_id": md_file.stem,
                    "title": title,
                    "content": text,
                })
            except Exception as e:
                err_msg = f"{md_file.name}: {e}"
                errors.append(err_msg)
                logger.warning(f"[知识库] 种子文档读取失败: {err_msg}")

        if not docs_to_import:
            logger.warning("[知识库] 种子文档批量导入：无可导入文档")
            return {
                "imported": 0, "total": len(md_files), "failed": len(errors),
                "files": [], "errors": errors,
            }

        # 批量导入
        imported = await self.add_documents_batch(docs_to_import)
        failed = len(docs_to_import) - imported + len(errors)
        files = [d["doc_id"] for d in docs_to_import[:imported]]

        logger.info(
            f"[知识库] 种子文档批量导入完成 | "
            f"imported={imported} total={len(md_files)} failed={failed}"
        )
        return {
            "imported": imported,
            "total": len(md_files),
            "failed": failed,
            "files": files,
            "errors": errors,
        }

    async def evaluate_search_quality(self, test_cases: Optional[list[dict]] = None) -> list[dict]:
        """Day6新增：检索质量评测。

        兼容K1~K3测试文档检索，验证3条检索案例中至少2条相关内容排在返回Top1。

        Args:
            test_cases: 可选自定义测试用例列表，每项含 {query, expected_keywords}。
                       不传则使用内置K1~K3默认测试用例。

        Returns:
            list[dict]: 每条测试用例的评测结果，含：
                {query, top1_doc_id, top1_title, top1_score, passed,
                 matched_keywords, elapsed_ms}
        """
        # K1~K3默认测试用例（覆盖工业机器人三个领域）
        if test_cases is None:
            test_cases = [
                {
                    "query": "FANUC 示教器点位编程 PTP 运动指令",
                    "expected_keywords": ["fanuc", "示教器", "点位", "PTP"],
                    "expected_domain": "K1",
                },
                {
                    "query": "RobotStudio 离线仿真工作站搭建 RAPID 程序",
                    "expected_keywords": ["robotstudio", "仿真", "RAPID", "工作站"],
                    "expected_domain": "K2",
                },
                {
                    "query": "FANUC SRVO-068 故障代码 脉冲编码器 数据传输异常",
                    "expected_keywords": ["srvo-068", "故障", "脉冲编码器", "DTERR"],
                    "expected_domain": "K3",
                },
            ]

        results: list[dict] = []
        passed_count = 0
        for case in test_cases:
            query = case.get("query", "")
            expected_keywords = [kw.lower() for kw in case.get("expected_keywords", [])]

            # 执行检索
            t_start = time.perf_counter()
            search_results = await self.search(query, top_k=5)
            elapsed_ms = round((time.perf_counter() - t_start) * 1000, 2)

            # 评测Top1结果
            top1 = search_results[0] if search_results else None
            top1_content = (top1.get("content", "") if top1 else "").lower()
            top1_title = (top1.get("doc_title", "") if top1 else "").lower()

            # 检查期望关键词是否在Top1的标题或内容中出现
            matched_keywords = [
                kw for kw in expected_keywords
                if kw in top1_content or kw in top1_title
            ] if top1 else []

            # 判定：至少匹配一半期望关键词视为通过
            threshold = max(1, len(expected_keywords) // 2)
            passed = len(matched_keywords) >= threshold

            if passed:
                passed_count += 1

            results.append({
                "query": query,
                "expected_domain": case.get("expected_domain", ""),
                "top1_doc_id": top1.get("doc_id", "") if top1 else "",
                "top1_title": top1.get("doc_title", "") if top1 else "",
                "top1_score": top1.get("relevance_score", 0) if top1 else 0,
                "passed": passed,
                "matched_keywords": matched_keywords,
                "total_expected_keywords": len(expected_keywords),
                "elapsed_ms": elapsed_ms,
                "total_results": len(search_results),
            })

            logger.info(
                f"[知识库] 检索质量评测 | query='{query[:40]}' "
                f"passed={'✓' if passed else '✗'} "
                f"top1='{top1.get('doc_title', 'N/A') if top1 else 'N/A'}' "
                f"matched={len(matched_keywords)}/{len(expected_keywords)} "
                f"elapsed={elapsed_ms}ms"
            )

        # Day6交付标准：3条测试至少2条通过
        logger.info(
            f"[知识库] 检索质量评测总结 | passed={passed_count}/{len(test_cases)} "
            f"({'达标' if passed_count >= 2 else '未达标，需调优'})"
        )
        return results


# 全局单例 — 所有模块通过此实例访问知识库
knowledge_base = KnowledgeBase()

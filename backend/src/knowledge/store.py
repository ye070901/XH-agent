"""知识库存储引擎 — ChromaDB 向量检索 + Embedding 自动切换 + 文件降级模式。

Opt‑2 KB 引擎核心模块。只做存储检索，不包含 Agent / LLM 逻辑。
"""

from __future__ import annotations

import hashlib
import math
import re
import time
from pathlib import Path
from typing import Optional

from loguru import logger

from ..config import settings
from .kb_utils import evaluate_search_quality, import_seed_documents, verify_persistence

# 文档正文「权威等级」标记正则（采集规范 3.6：A=官方一手 / B=主流二手）
# 兼容 Markdown 加粗写法「**权威等级**：A」与普通写法「权威等级：A」
_SOURCE_LEVEL_RE = re.compile(r"权威等级\**\s*[：:]\s*\**([AB])")


class KnowledgeBase:
    """领域知识库存储引擎 — ChromaDB 向量检索 / 文件降级双模式。"""

    def __init__(self) -> None:
        self._initialized: bool = False
        self._client: Optional[object] = None
        self._collection: Optional[object] = None
        self._docs: list[dict] = []
        self._fallback_dir: Optional[Path] = None
        self._persist_snapshot: Optional[dict] = None
        # BM25 索引惰性缓存（语料变化时按签名重建）
        self._bm25_index: Optional[tuple] = None
        self._bm25_sig: Optional[tuple] = None

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
            # 每次启动都增量同步 data/raw 新文档（按 doc_id 幂等去重）
            # 首次启动（空库）等价于全量导入；后续启动仅补新增
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
                source_level = self._extract_source_level(text)
                for i, chunk in enumerate(chunks):
                    self._docs.append(
                        {
                            "doc_id": md_file.stem,
                            "doc_title": md_file.stem,
                            "chunk_index": i,
                            "content": chunk,
                            "source_level": source_level,
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
        """每次启动增量同步 data/raw 下的 .md 到 ChromaDB。

        以 ``source_sha256`` 判断源文件是否变化：新增或已修改的文件写入，
        未变化的文件跳过。旧库没有该元数据时会在本次启动补写一次。
        """
        raw_dir = Path(__file__).parent.parent.parent.parent / "data" / "raw"
        if not raw_dir.exists():
            return 0
        md_files = sorted(raw_dir.glob("**/*.md"))
        if not md_files:
            return 0

        synced = 0
        skipped = 0
        for md_file in md_files:
            if self._collection is None:
                break
            doc_id = md_file.stem
            try:
                text = md_file.read_text(encoding="utf-8")
                source_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
                title = md_file.stem
                for line in text.split("\n"):
                    s = line.strip()
                    if s.startswith("# ") and not s.startswith("## "):
                        title = s[2:].strip()
                        break
                existing = self._collection.get(
                    where={"doc_id": doc_id}, include=["metadatas"]
                )
                metadatas = existing.get("metadatas") or []
                if metadatas and all(
                    metadata.get("source_sha256") == source_sha256
                    for metadata in metadatas
                ):
                    skipped += 1
                    continue

                await self.add_document(
                    doc_id=doc_id,
                    title=title,
                    content=text,
                    source_sha256=source_sha256,
                )
                synced += 1
            except Exception as e:
                logger.warning(f"[知识库] 增量向量化失败: {md_file.name} — {e}")

        logger.info(
            f"[知识库] 增量同步完成: 写入/更新 {synced} 篇，跳过未变更 {skipped} 篇，"
            f"扫描 {len(md_files)} 篇"
        )
        return synced

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

    async def add_document(
        self,
        doc_id: str,
        title: str,
        content: str,
        source_sha256: Optional[str] = None,
    ) -> list[dict]:
        """添加单篇文档 → 切分 → 向量化写入 / 文件追加 → 返回 chunk 列表。

        幂等写入：ChromaDB 模式下先删除同名 doc_id 的旧 chunks 再写入，
        重复导入不会产生重复向量。
        """
        chunks = self._chunk_text(content)
        source_level = self._extract_source_level(content)
        chunk_ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
        result = [
            {
                "doc_id": doc_id,
                "doc_title": title,
                "chunk_index": i,
                "content": c,
                "source_level": source_level,
            }
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

                metadatas = []
                for i in range(len(chunks)):
                    metadata = {
                        "doc_id": doc_id,
                        "doc_title": title,
                        "chunk_index": i,
                        "source_level": source_level,
                    }
                    if source_sha256:
                        metadata["source_sha256"] = source_sha256
                    metadatas.append(metadata)
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

    @staticmethod
    def _extract_source_level(content: str) -> str:
        """从文档正文解析权威等级标记「权威等级：A/B」，无则返回空字符串。"""
        if not content:
            return ""
        match = _SOURCE_LEVEL_RE.search(content)
        return match.group(1) if match else ""

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
        """语义检索：ChromaDB 向量 + 文件关键词匹配合并。relevance_score ∈ [0,1]。"""
        t_start = time.perf_counter()
        if not query.strip():
            return []

        # 1. 向量检索（ChromaDB 可用时）
        vector_results: list[dict] = []
        if self._collection is not None:
            try:
                collection_count = self._collection.count()
                if collection_count > 0:
                    n = min(top_k, collection_count)
                    results = self._collection.query(query_texts=[query], n_results=n)
                    vector_results = self._format_search_results(results)
            except Exception as e:
                logger.warning(f"[知识库] ChromaDB检索异常 ({e})，降级到关键词匹配")
                vector_results = []

        # 2. 关键词检索（始终计算，作为向量检索的兜底与补充）
        keyword_results = self._keyword_search(query, top_k) if self._docs else []

        # 3. 合并去重：向量 + 关键词并集按分数降序取 top_k。
        #    原逻辑只在"向量结果为空"时回退关键词，导致 ChromaDB 返回少量
        #    无关结果时中文查询仍拿不到任何有效文档，故改为始终合并。
        result = self._merge_search_results(vector_results, keyword_results, top_k)

        elapsed_ms = round((time.perf_counter() - t_start) * 1000, 2)
        logger.info(
            f"[知识库] 检索耗时 | query='{query[:50]}' top_k={top_k} "
            f"results={len(result)} elapsed={elapsed_ms}ms"
        )
        if elapsed_ms >= 200:
            logger.warning(f"[知识库] ⚠️ 检索耗时超标: {elapsed_ms}ms ≥ 200ms基线")
        return result

    @staticmethod
    def _merge_search_results(
        vector_results: list[dict], keyword_results: list[dict], top_k: int
    ) -> list[dict]:
        """合并向量与关键词结果，按 (doc_id, chunk_index) 去重，取最高分降序取 top_k。"""
        merged: dict[tuple[str, int], dict] = {}
        for result in vector_results + keyword_results:
            key = (str(result.get("doc_id") or ""), int(result.get("chunk_index") or 0))
            if key not in merged or (result.get("relevance_score") or 0.0) > (
                merged[key].get("relevance_score") or 0.0
            ):
                merged[key] = result
        ranked = sorted(
            merged.values(),
            key=lambda r: (r.get("relevance_score") or 0.0),
            reverse=True,
        )
        return ranked[:top_k]

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
                    "source_level": meta.get("source_level", ""),
                }
            )
        return formatted

    # BM25 参数（OKAPI BM25 标准取值）
    _BM25_K1 = 1.5
    _BM25_B = 0.75

    @staticmethod
    def _tokenize_for_bm25(text: str) -> list[str]:
        """BM25 分词：英文/数字 token（保留原词）+ 中文相邻双字 bigram（保留重复项）。

        中文无空格分词，纯 ``split()`` 会把整句中文当成一个词，导致
        "机器人坐标系" 这类查询几乎匹配不到文档；改用相邻双字 bigram 覆盖
        中文、``[a-z0-9]{2,}`` 覆盖英文/型号（如 SRVO-068 → srvo + 068）。
        与旧 ``_extract_keywords`` 的区别：不去重，保留词频供 BM25 计算 TF。
        """
        lowered = str(text).lower()
        tokens: list[str] = list(re.findall(r"[a-z0-9]{2,}", lowered))
        for run in re.findall(r"[一-鿿]+", lowered):
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
        return tokens

    def _get_bm25_index(self) -> tuple[list[int], float, dict[str, dict[int, int]]]:
        """惰性构建 BM25 索引，返回 (doc_len, avgdl, postings[term][doc_idx]=tf)。

        以 ``(len(_docs), id(_docs))`` 为签名缓存；语料 append（长度变）或
        整体重赋值（对象身份变）时自动失效。本模块对 _docs 只做 append 或
        整表重赋值，不存在原地改内容且长度/身份不变的情况。
        """
        sig = (len(self._docs), id(self._docs))
        if self._bm25_sig == sig and self._bm25_index is not None:
            return self._bm25_index

        doc_len: list[int] = []
        postings: dict[str, dict[int, int]] = {}
        for idx, doc in enumerate(self._docs):
            terms = self._tokenize_for_bm25(str(doc.get("content") or ""))
            doc_len.append(len(terms))
            tf: dict[str, int] = {}
            for term in terms:
                tf[term] = tf.get(term, 0) + 1
            for term, cnt in tf.items():
                postings.setdefault(term, {})[idx] = cnt
        avgdl = (sum(doc_len) / len(doc_len)) if doc_len else 0.0
        self._bm25_index = (doc_len, avgdl, postings)
        self._bm25_sig = sig
        return self._bm25_index

    def _keyword_search(self, query: str, top_k: int) -> list[dict]:
        """BM25 关键词检索（英文 token + 中文 bigram，无外部依赖）。

        相较旧 hit-count 打分：IDF 给稀有技术术语（SRVO-068/PTP/脉冲编码器）
        更高权重，词频饱和 + 文档长度归一，对「KB 存在但向量召不回」的中文
        技术事实召回更准。relevance_score 用最高分归一化到 [0,1]，便于与
        向量分数合并排序。
        """
        query_terms = self._tokenize_for_bm25(query)
        if not query_terms or not self._docs:
            return []
        doc_len, avgdl, postings = self._get_bm25_index()
        n = len(doc_len)

        q_unique = list(dict.fromkeys(query_terms))
        idf: dict[str, float] = {}
        for term in q_unique:
            df = len(postings.get(term, {}))
            idf[term] = math.log(1.0 + (n - df + 0.5) / (df + 0.5))

        scores: list[tuple[float, dict]] = []
        for idx, doc in enumerate(self._docs):
            dl = doc_len[idx]
            norm = (
                1.0 - self._BM25_B + self._BM25_B * (dl / avgdl)
                if avgdl > 0
                else 1.0
            )
            score = 0.0
            for term in q_unique:
                tf = postings.get(term, {}).get(idx, 0)
                if tf:
                    score += idf[term] * (
                        tf * (self._BM25_K1 + 1.0) / (tf + self._BM25_K1 * norm)
                    )
            if score > 0.0:
                scores.append((score, doc))

        if not scores:
            return []
        scores.sort(key=lambda x: x[0], reverse=True)
        max_score = scores[0][0]
        results: list[dict] = []
        for score, doc in scores[:top_k]:
            d = doc.copy()
            d["relevance_score"] = round(score / max_score, 4) if max_score > 0 else 0.0
            results.append(d)
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

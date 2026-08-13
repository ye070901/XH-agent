"""知识库工具函数 — 持久化校验 + 种子导入 + 检索质量评测。

从 store.py 拆分出来的大型辅助函数，保留完整业务逻辑不变。
仅依赖 KnowledgeBase 的6个公开 API，不直接操作私有属性（仅读 _persist_snapshot）。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from loguru import logger

from ..config import settings


async def verify_persistence(kb) -> dict:
    """ChromaDB 持久化校验。

    重启服务、重新执行 initialize() 后调用，对比当前数据状态与快照，
    验证文档总数、chunk 分片数量完全一致。

    Returns:
        dict: {verified, snapshot, current, total_chunks_match,
               total_documents_match, collection_name_match}
    """
    current = await kb.get_stats()
    snapshot = kb._persist_snapshot

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

    chunk_flag = "OK" if chunks_match else "MISMATCH"
    doc_flag = "OK" if docs_match else "MISMATCH"
    logger.info(
        f"[知识库] 持久化校验结果 | verified={verified} "
        f"chunks: {snapshot['total_chunks']}→{current['total_chunks']}({chunk_flag}) "
        f"docs: {snapshot['total_documents']}→{current['total_documents']}({doc_flag})"
    )
    if not verified:
        logger.warning(
            f"[知识库] WARNING 持久化校验失败！数据在重启前后不一致，请排查ChromaDB持久化路径: "
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


async def import_seed_documents(kb, raw_dir: Optional[str] = None) -> dict:
    """种子文档批量导入。

    扫描目录下全部 .md 文件，提取 # 一级标题作为文档标题，批量导入知识库。

    Returns:
        dict: {imported, total, failed, files, errors}
    """
    if raw_dir:
        seed_dir = Path(raw_dir)
    else:
        seed_dir = Path(__file__).parent.parent.parent.parent / "data" / "raw"

    if not seed_dir.exists():
        logger.warning(f"[知识库] 种子文档目录不存在: {seed_dir}")
        return {"imported": 0, "total": 0, "failed": 0, "files": [], "errors": []}

    md_files = sorted(seed_dir.glob("**/*.md"))
    if not md_files:
        logger.warning(f"[知识库] 种子文档目录为空，无 .md 文件: {seed_dir}")
        return {"imported": 0, "total": 0, "failed": 0, "files": [], "errors": []}

    docs_to_import: list[dict] = []
    errors: list[str] = []
    for md_file in md_files:
        try:
            text = md_file.read_text(encoding="utf-8")
            title = md_file.stem
            for line in text.split("\n"):
                stripped = line.strip()
                if stripped.startswith("# ") and not stripped.startswith("## "):
                    title = stripped[2:].strip()
                    break
            docs_to_import.append(
                {
                    "doc_id": md_file.stem,
                    "title": title,
                    "content": text,
                }
            )
        except Exception as e:
            err_msg = f"{md_file.name}: {e}"
            errors.append(err_msg)
            logger.warning(f"[知识库] 种子文档读取失败: {err_msg}")

    if not docs_to_import:
        logger.warning("[知识库] 种子文档批量导入：无可导入文档")
        return {
            "imported": 0,
            "total": len(md_files),
            "failed": len(errors),
            "files": [],
            "errors": errors,
        }

    imported = await kb.add_documents_batch(docs_to_import)
    failed = len(docs_to_import) - imported + len(errors)
    files = [d["doc_id"] for d in docs_to_import[:imported]]

    logger.info(
        f"[知识库] 种子文档批量导入完成 | imported={imported} total={len(md_files)} failed={failed}"
    )
    return {
        "imported": imported,
        "total": len(md_files),
        "failed": failed,
        "files": files,
        "errors": errors,
    }


async def evaluate_search_quality(kb, test_cases: Optional[list[dict]] = None) -> list[dict]:
    """检索质量评测。

    兼容 K1~K3 测试文档检索，验证3条检索案例中至少2条相关内容排在返回 Top1。

    Returns:
        list[dict]: 每条测试用例的评测结果
    """
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

        t_start = time.perf_counter()
        search_results = await kb.search(query, top_k=5)
        elapsed_ms = round((time.perf_counter() - t_start) * 1000, 2)

        top1 = search_results[0] if search_results else None
        top1_content = (top1.get("content", "") if top1 else "").lower()
        top1_title = (top1.get("doc_title", "") if top1 else "").lower()

        matched_keywords = (
            [kw for kw in expected_keywords if kw in top1_content or kw in top1_title]
            if top1
            else []
        )

        threshold = max(1, len(expected_keywords) // 2)
        passed = len(matched_keywords) >= threshold

        if passed:
            passed_count += 1

        results.append(
            {
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
            }
        )

        logger.info(
            f"[知识库] 检索质量评测 | query='{query[:40]}' "
            f"passed={'OK' if passed else 'FAIL'} "
            f"top1='{top1.get('doc_title', 'N/A') if top1 else 'N/A'}' "
            f"matched={len(matched_keywords)}/{len(expected_keywords)} "
            f"elapsed={elapsed_ms}ms"
        )

    logger.info(
        f"[知识库] 检索质量评测总结 | passed={passed_count}/{len(test_cases)} "
        f"({'达标' if passed_count >= 2 else '未达标，需调优'})"
    )
    return results

# ====================== 导入块全部置顶，连续无中断 ======================
# 1. 项目内部模块导入
# 2. Python 标准库
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# 3. 第三方依赖库
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from backend.src.config import settings
from backend.src.knowledge.store import knowledge_base
from backend.src.scheduler.pipeline import scheduler
from backend.src.api.ws import router as ws_router

# ====================== 导入全部结束后，再放文档注释与业务代码 ======================
"""FastAPI 应用入口 — 知识库 + RAG 版本。v0.2.0"""

# 定位项目根目录 XH-agent
root_path = Path(__file__).parent.parent.parent.parent
sys.path.append(str(root_path))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("领域知识个性化生成系统 v0.2.0 KB-RAG")
    logger.info(f"LLM: {settings.LLM_PROVIDER}/{settings.LLM_MODEL}")
    # 初始化知识库
    await knowledge_base.initialize()
    stats = await knowledge_base.get_stats()
    logger.info(f"知识库: {stats['mode']} 模式, {stats['total_documents']} 篇文档, "
                f"{stats['total_chunks']} chunks")
    logger.info("=" * 60)
    yield
    logger.info("系统关闭")


app = FastAPI(
    title="领域知识个性化生成系统",
    description="XH-202630 揭榜挂帅 — 多智能体协同决策 + RAG",
    version="0.2.0",
    lifespan=lifespan,
)

app.include_router(ws_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    stats = await knowledge_base.get_stats()
    return {
        "name": "领域知识个性化生成系统",
        "version": "0.2.0",
        "status": "running",
        "kb_mode": stats["mode"],
        "kb_docs": stats["total_documents"],
    }


@app.get("/health")
async def health():
    stats = await knowledge_base.get_stats()
    return {
        "status": "healthy",
        "llm": f"{settings.LLM_PROVIDER}/{settings.LLM_MODEL}",
        "demo_mode": settings.is_demo_mode,
        "kb_docs": stats["total_documents"],
        "kb_mode": stats["mode"],
    }


@app.post("/api/generate")
async def generate(request: dict):
    """主接口：用户输入工业机器人调试问题，返回生成结果。

    入参（硬性约束，不可变更）：
        {"user_input": "FANUC 机器人报 SRVO-068 怎么处理"}

    出参（硬性约束，不可变更）：
        {
            "status": "ok",
            "result": {
                "answer": "...",
                "sources": ["..."],
                "confidence": 0.85
            },
            "metrics": {
                "inputgate_ms": 12,
                "diagnosisgate_ms": 45,
                "recallgate_ms": 230,
                "rag_recall_count": 15,
                "rag_top_k": 5,
                "total_latency_ms": 2800
            }
        }
    """
    user_input = request.get("user_input", "").strip()
    if not user_input:
        raise HTTPException(status_code=422, detail="user_input 为必填字段，不能为空")

    logger.info(f"[API] /api/generate 请求: {user_input[:80]}...")

    try:
        result = await scheduler.run_pipeline(
            user_input={"learner_data": {"learning_goal": user_input}},
            task_id="",
        )

        # 提取 metrics（从 gate_results 和 elapsed_ms）
        metrics = {
            "inputgate_ms": result.get("gate_results", {}).get("input_gate", {}).get("duration_ms", 0),
            "diagnosisgate_ms": result.get("gate_results", {}).get("diagnosis_gate", {}).get("duration_ms", 0),
            "recallgate_ms": result.get("gate_results", {}).get("recall_gate", {}).get("duration_ms", 0),
            "rag_recall_count": len(result.get("retrieved_chunks", [])),
            "rag_top_k": 5,
            "total_latency_ms": result.get("elapsed_ms", 0),
        }

        # 构建 answer（从生成资源提取）
        resources = result.get("generated_resources", [])
        answer = _build_answer(resources)
        sources = _build_sources(result.get("retrieved_chunks", []))

        # 计算 confidence（基于审核结果）
        confidence = _calc_confidence(result)

        return {
            "status": "ok",
            "result": {
                "answer": answer,
                "sources": sources,
                "confidence": confidence,
            },
            "metrics": metrics,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] /api/generate 异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _build_answer(resources: list) -> str:
    """从生成资源构建 answer 文本。"""
    if not resources:
        return "未生成相关内容"
    parts = []
    for r in resources:
        title = r.get("title", "")
        content = r.get("content", "")
        if content:
            parts.append(f"## {title}\n\n{content[:500]}...")
        else:
            parts.append(f"## {title}")
    return "\n\n".join(parts)


def _build_sources(chunks: list) -> list[str]:
    """从检索 chunks 构建 sources 列表。"""
    sources = []
    seen = set()
    for chunk in chunks:
        doc_id = chunk.get("doc_id", "")
        doc_title = chunk.get("doc_title", "")
        key = f"{doc_id}"
        if key not in seen:
            seen.add(key)
            sources.append(f"{doc_title} ({doc_id[:8]})")
    return sources


def _calc_confidence(result: dict) -> float:
    """从结果计算 confidence 分数。"""
    status = result.get("status", "")
    if status == "gate_blocked":
        return 0.3
    if status == "error":
        return 0.1

    audit = result.get("audit_result", {})
    if isinstance(audit, dict):
        score = audit.get("confidence_score", 0.5)
        return round(score, 2)
    return 0.75


# ═══════════════════════════════════════════════════════════
# 知识库管理 API
# ═══════════════════════════════════════════════════════════


@app.post("/api/knowledge/upload")
async def kb_upload(request: dict):
    """上传单篇 Markdown 文档到知识库。

    请求: {"doc_id": "...", "title": "...", "content": "Markdown 正文"}
    """
    doc_id = request.get("doc_id", "")
    title = request.get("title", "")
    content = request.get("content", "")

    if not doc_id or not title or not content:
        raise HTTPException(status_code=422, detail="doc_id, title, content 均为必填")

    try:
        chunks = await knowledge_base.add_document(
            doc_id=doc_id, title=title, content=content
        )
        return {
            "status": "ok",
            "doc_id": doc_id,
            "title": title,
            "chunks_count": len(chunks),
        }
    except Exception as e:
        logger.error(f"[API] 上传文档失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/knowledge/import")
async def kb_import():
    """批量导入 data/raw/ 下所有 .md 文件到知识库。"""
    raw_dir = Path(__file__).parent.parent.parent.parent / "data" / "raw"
    if not raw_dir.exists():
        return {"status": "ok", "imported": 0, "message": "data/raw/ 目录不存在"}

    md_files = list(raw_dir.glob("**/*.md"))
    if not md_files:
        return {"status": "ok", "imported": 0, "message": "data/raw/ 下无 .md 文件"}

    docs = []
    for md_file in md_files:
        try:
            content = md_file.read_text(encoding="utf-8")
            doc_id = md_file.stem
            lines = content.strip().split("\n")
            title = lines[0].lstrip("# ").strip() if lines else doc_id
            docs.append({"doc_id": doc_id, "title": title, "content": content})
        except Exception as e:
            logger.warning(f"[API] 读取文件失败: {md_file} — {e}")

    count = await knowledge_base.add_documents_batch(docs)
    return {"status": "ok", "imported": count, "total": len(md_files)}


@app.get("/api/knowledge/search")
async def kb_search(q: str = "", top_k: int = 5):
    """检索知识库。

    参数: ?q=查询文本&top_k=5
    """
    if not q.strip():
        return {"query": "", "results": []}

    results = await knowledge_base.search(query=q, top_k=top_k)
    return {"query": q, "results": results, "count": len(results)}


@app.get("/api/knowledge/stats")
async def kb_stats():
    """知识库统计信息。"""
    return await knowledge_base.get_stats()


@app.delete("/api/knowledge/{doc_id}")
async def kb_delete(doc_id: str):
    """删除指定文档及其全部 chunks。"""
    ok = await knowledge_base.delete_document(doc_id)
    if ok:
        return {"status": "ok", "doc_id": doc_id}
    else:
        raise HTTPException(status_code=404, detail=f"文档 '{doc_id}' 未找到或删除失败")

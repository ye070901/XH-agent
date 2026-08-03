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
from backend.src.graph.orchestrator import workflow_engine
from backend.src.knowledge.store import knowledge_base

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
    """MVP 一键生成：输入学习者信息，返回诊断结果 + 学习资源。

    示例请求:
    {
        "name": "张三",
        "education_level": "bachelor",
        "major": "计算机科学",
        "work_years": 1,
        "industry": "互联网",
        "positions": ["Python开发"],
        "skills_used": ["Python", "Flask"],
        "pretest_results": [],
        "learning_goal": "学习LangGraph构建AI Agent",
        "resource_types": ["lecture", "guide", "quiz"]
    }
    """
    learner_data = {
        "education_level": request.get("education_level", "bachelor"),
        "major": request.get("major", ""),
        "school": request.get("school", ""),
        "work_years": request.get("work_years", 0),
        "industry": request.get("industry", ""),
        "positions": request.get("positions", []),
        "skills_used": request.get("skills_used", []),
        "pretest_results": request.get("pretest_results", []),
        "learning_goal": request.get("learning_goal", ""),
    }
    resource_types = request.get("resource_types", ["lecture", "guide", "quiz"])

    logger.info(f"[API] 开始生成, 目标: {learner_data.get('learning_goal', '')}")

    try:
        result = await workflow_engine.run(
            learner_data=learner_data,
            resource_types=resource_types,
        )

        return {
            "task_id": result.get("task_id", ""),
            "status": result.get("status", "completed"),
            "diagnosis": result.get("diagnosis_result", {}),
            "resources": result.get("generated_resources", []),
            "audit": result.get("audit_result", []),
            "corrected_resources": result.get("corrected_resources", []),
            "correction_stats": result.get("correction_stats", {}),
            "agent_log": result.get("agent_log", []),
        }

    except Exception as e:
        logger.error(f"[API] 生成失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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

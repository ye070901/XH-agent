"""XH-Agent FastAPI 服务入口 — 项目根目录启动文件。

接口：POST /api/generate + /api/knowledge/*
启动命令：cd XH-agent && python main.py

模式兼容：
  - 演示模式（LLM_API_KEY 为空）→ 自动降级为模拟数据
  - 真实 LLM 模式（LLM_API_KEY 已设置）→ 走 OpenAI 兼容 API

异常分层（对应 CLAUDE.md §4）：
  API 层 ── XHError 捕获 → HTTPException(500)
       └── 全局兜底 → HTTPException(500)
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from enum import Enum
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel, Field

# ── 确保 backend/ 在 sys.path 中（项目根目录入口必须）──
_PROJECT_ROOT = Path(__file__).resolve().parent
_BACKEND = _PROJECT_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from backend.src.config import settings  # noqa: E402
from backend.src.exceptions import XHError  # noqa: E402
from backend.src.graph.orchestrator import workflow_engine  # noqa: E402
from backend.src.knowledge.store import knowledge_base  # noqa: E402

# ═══════════════════════════════════════════════════════════
# 枚举（与前端表单下拉框一一对应）
# ═══════════════════════════════════════════════════════════


class EducationLevel(str, Enum):
    """学历 — 前端下拉框选项"""

    HIGH_SCHOOL = "high_school"
    JUNIOR_COLLEGE = "junior_college"
    BACHELOR = "bachelor"
    MASTER = "master"
    PHD = "phd"


class ResourceType(str, Enum):
    """资源类型 — 前端多选复选框选项"""

    LECTURE = "lecture"
    GUIDE = "guide"
    QUIZ = "quiz"
    CASE_STUDY = "case_study"
    MICRO_PROJECT = "micro_project"


# ═══════════════════════════════════════════════════════════
# 请求模型（精确匹配前端表单字段，区分必填/选填）
# ═══════════════════════════════════════════════════════════


class GenerateRequest(BaseModel):
    """POST /api/generate 入参模型。

    每个字段对应前端表单的一个控件：
      - 必填：name, education_level, learning_goal
      - 选填：major, school, work_years, industry, positions, skills_used,
              pretest_results, resource_types（均设默认值）
    """

    # ── 必填字段 ──
    name: str = Field(
        default="匿名学习者",
        description="学习者姓名（前端表单未提供，用默认值）",
        min_length=0,
        max_length=50,
        examples=["张三"],
    )
    education_level: EducationLevel = Field(
        ...,
        description="最高学历",
        examples=["bachelor"],
    )
    learning_goal: str = Field(
        ...,
        description="学习目标描述",
        min_length=1,
        max_length=500,
        examples=["学习 LangGraph 构建多 Agent 协同系统"],
    )

    # ── 选填字段（均设默认值，前端可留空）──
    major: str = Field(
        default="",
        description="专业",
        max_length=100,
        examples=["计算机科学"],
    )
    school: str = Field(
        default="",
        description="毕业院校",
        max_length=100,
        examples=["清华大学"],
    )
    work_years: float = Field(
        default=0.0,
        description="工作年限",
        ge=0,
        le=60,
        examples=[1.5],
    )
    industry: str = Field(
        default="",
        description="所在行业",
        max_length=100,
        examples=["互联网"],
    )
    positions: List[str] = Field(
        default_factory=list,
        description="历史岗位列表",
        examples=[["Python开发", "后端工程师"]],
    )
    skills_used: List[str] = Field(
        default_factory=list,
        description="使用过的技术栈或技能",
        examples=[["Python", "Flask", "Docker"]],
    )
    pretest_results: List[dict] = Field(
        default_factory=list,
        description="前置测试成绩",
        examples=[
            [
                {
                    "test_name": "Python基础",
                    "total_score": 78,
                    "max_score": 100,
                    "topic_scores": {"变量与类型": 85, "函数": 72},
                },
            ]
        ],
    )
    resource_types: List[ResourceType] = Field(
        default=[ResourceType.LECTURE, ResourceType.GUIDE, ResourceType.QUIZ],
        description="请求生成的资源类型，默认三种全部",
        examples=[["lecture", "guide", "quiz"]],
    )


# ═══════════════════════════════════════════════════════════
# 应用生命周期
# ═══════════════════════════════════════════════════════════


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动/关闭时的初始化与清理。"""
    mode_label = "[Demo 演示模式]" if settings.is_demo_mode else "[Real LLM 模式]"
    logger.info("=" * 60)
    logger.info(f"  XH-Agent 领域知识个性化生成系统 v0.2.0  {mode_label}")
    logger.info(f"  LLM: {settings.LLM_PROVIDER}/{settings.LLM_MODEL}")
    logger.info(f"  Base URL: {settings.LLM_BASE_URL}")
    logger.info(f"  Server : {settings.HOST}:{settings.PORT}")
    logger.info("=" * 60)

    # 启动自检
    warnings = settings.validate()
    for w in warnings:
        logger.warning(f"  [Config Warning] {w}")

    # 初始化知识库
    await knowledge_base.initialize()
    stats = await knowledge_base.get_stats()
    logger.info(
        f"  知识库: {stats['mode']} 模式, {stats['total_documents']} 篇文档, "
        f"{stats['total_chunks']} chunks"
    )
    logger.info("=" * 60)

    yield

    logger.info("系统关闭")


# ═══════════════════════════════════════════════════════════
# FastAPI 应用实例
# ═══════════════════════════════════════════════════════════

app = FastAPI(
    title="领域知识个性化生成系统",
    description=(
        "XH-202630 揭榜挂帅 — 多智能体协同决策系统。"
        "输入学习者画像，3 Agent 协同输出诊断报告 + 个性化学习资源 + 审核报告。"
    ),
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════
# 全局异常处理器（对应 CLAUDE.md §4：API 层全局兜底）
# ═══════════════════════════════════════════════════════════


@app.exception_handler(XHError)
async def xh_error_handler(request: Request, exc: XHError) -> JSONResponse:
    """捕获所有 XH 前缀的自定义异常，转为标准 500 响应。

    包含：XHConfigError, XHLLMError, XHAgentError, XHWorkflowError, XHAPIError 等。
    """
    status_code = getattr(exc, "status_code", 500)
    detail = getattr(exc, "detail", str(exc))
    logger.error(f"[API] XH 异常 caught: {type(exc).__name__}: {exc}")
    return JSONResponse(
        status_code=status_code,
        content={
            "error": True,
            "error_type": type(exc).__name__,
            "detail": detail,
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """全局兜底：捕获所有未预期的异常，返回标准 500。"""
    logger.error(f"[API] 未预期异常: {type(exc).__name__}: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "error_type": type(exc).__name__,
            "detail": "Internal Server Error — 请联系后端查看日志",
        },
    )


# ═══════════════════════════════════════════════════════════
# 路由
# ═══════════════════════════════════════════════════════════


@app.get("/")
async def root():
    """服务根路径 — 快速健康检查。"""
    stats = await knowledge_base.get_stats()
    return {
        "service": "XH-Agent",
        "version": "0.2.0",
        "mode": "demo" if settings.is_demo_mode else "real",
        "status": "running",
        "kb_mode": stats["mode"],
        "kb_docs": stats["total_documents"],
    }


@app.get("/health")
async def health():
    """健康检查端点。"""
    stats = await knowledge_base.get_stats()
    return {
        "status": "healthy",
        "llm": f"{settings.LLM_PROVIDER}/{settings.LLM_MODEL}",
        "demo_mode": settings.is_demo_mode,
        "kb_docs": stats["total_documents"],
        "kb_mode": stats["mode"],
    }


@app.post("/api/generate")
async def generate(request: GenerateRequest):
    """唯一业务接口：输入学习者画像，启动 3 Agent 协同流水线。

    工作流：Agent 1 学情诊断 → Agent 2 知识生成 → Agent 3 内容审核

    Args:
        request: 前端表单提交的 GenerateRequest 对象（Pydantic 自动校验）。

    Returns:
        dict: 包含 task_id, status, diagnosis, resources, agent_log 的标准响应。

    Raises:
        HTTPException(500): 工作流执行失败或 LLM 调用异常时返回。
    """
    # ── 1. 组装 learner_data（前端扁平字段 → Agent 工作流需要的嵌套 dict）──
    learner_data = {
        "education_level": request.education_level.value,
        "major": request.major,
        "school": request.school,
        "work_years": request.work_years,
        "industry": request.industry,
        "positions": request.positions,
        "skills_used": request.skills_used,
        "pretest_results": request.pretest_results,
        "learning_goal": request.learning_goal,
        "name": request.name,
    }
    resource_types = [rt.value for rt in request.resource_types]

    logger.info(
        f"[API] 收到生成请求: name={request.name}, "
        f"goal={request.learning_goal[:50]}..., "
        f"resource_types={resource_types}"
    )

    # ── 2. 启动工作流（异常由全局 handler 兜底）──
    result = await workflow_engine.run(
        learner_data=learner_data,
        resource_types=resource_types,
    )

    # ── 3. 标准化响应 ──
    response = {
        "task_id": result.get("task_id", ""),
        "status": result.get("status", "completed"),
        "diagnosis": result.get("diagnosis_result", {}),
        "resources": result.get("generated_resources", []),
        "audit": result.get("audit_result", []),
        "agent_log": result.get("agent_log", []),
        "mode": "demo" if settings.is_demo_mode else "real",
    }

    logger.info(
        f"[API] 生成完成: task_id={response['task_id']}, "
        f"status={response['status']}, "
        f"resources={len(response['resources'])}, "
        f"audit_items={len(response['audit'])}"
    )
    return response


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
        chunks = await knowledge_base.add_document(doc_id=doc_id, title=title, content=content)
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
    raw_dir = _PROJECT_ROOT / "data" / "raw"
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
    """检索知识库。参数: ?q=查询文本&top_k=5"""
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


# ═══════════════════════════════════════════════════════════
# 启动入口
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info",
    )

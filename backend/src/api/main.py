"""FastAPI 应用入口 — MVP 版本：2 Agent 工作流"""
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from ..config import settings
from ..knowledge.store import knowledge_base
from ..graph.orchestrator import workflow_engine
from ..schemas import (
    CreateProfileRequest,
    CreateProfileResponse,
    GenerateRequest,
    GenerateResponse,
    TaskStatusResponse,
    LearnerProfile,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("领域知识个性化生成与多智能体协同决策系统 v0.1.0 MVP")
    logger.info(f"LLM: {settings.LLM_PROVIDER}/{settings.LLM_MODEL}")
    logger.info("=" * 60)
    await knowledge_base.initialize()
    yield
    logger.info("系统关闭")


app = FastAPI(
    title="多智能体协同决策系统 MVP",
    description="领域知识个性化生成 — XH-202630",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_tasks: dict[str, dict] = {}


@app.get("/")
async def root():
    return {"name": "多智能体协同决策系统 MVP", "version": "0.1.0", "status": "running"}


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "llm": f"{settings.LLM_PROVIDER}/{settings.LLM_MODEL}",
        "kb_docs": len(knowledge_base._docs),
    }


# ── MVP 一键接口：诊断 + 生成一起做 ──

@app.post("/api/generate")
async def generate(request: dict):
    """
    MVP 一键生成接口。
    请求体直接传 JSON，不用 Pydantic 校验，降低门槛。

    示例请求:
    {
        "name": "张三",
        "education_level": "bachelor",
        "major": "计算机科学",
        "school": "某某大学",
        "work_years": 1,
        "industry": "互联网",
        "positions": ["Python开发"],
        "skills_used": ["Python", "Flask"],
        "pretest_results": [],
        "learning_goal": "学习LangGraph构建AI Agent",
        "resource_types": ["lecture", "guide", "quiz"]
    }
    """
    task_id = str(uuid.uuid4())
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

    logger.info(f"[API] 开始生成: task_id={task_id}, goal={learner_data.get('learning_goal', '')}")

    try:
        result = await workflow_engine.run(
            task_id=task_id,
            learner_data=learner_data,
            resource_types=resource_types,
        )

        return {
            "task_id": task_id,
            "status": result.get("status", "completed"),
            "diagnosis": result.get("diagnosis_result", {}),
            "resources": result.get("generated_resources", []),
            "agent_log": result.get("agent_log", []),
        }

    except Exception as e:
        logger.error(f"[API] 生成失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── 知识库管理 ──

@app.get("/api/knowledge")
async def list_knowledge():
    """查看知识库中有多少文档"""
    return {
        "total_docs": len(knowledge_base._docs),
        "docs": [{"doc_id": d["doc_id"], "title": d["doc_title"]} for d in knowledge_base._docs],
    }


@app.post("/api/knowledge")
async def add_knowledge(request: dict):
    """添加知识库文档"""
    doc_id = request.get("doc_id", str(uuid.uuid4()))
    title = request.get("title", "未命名文档")
    content = request.get("content", "")
    chunks = await knowledge_base.add_document(doc_id, title, content)
    return {"doc_id": doc_id, "chunks": len(chunks), "status": "ok"}

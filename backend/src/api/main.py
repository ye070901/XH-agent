"""FastAPI 应用入口 — 提供 REST API + WebSocket"""
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
    ReportResponse,
    TaskStatusResponse,
    LearnerProfile,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化知识库"""
    logger.info("=" * 60)
    logger.info("领域知识个性化生成与多智能体协同决策系统 v0.1.0")
    logger.info(f"LLM: {settings.LLM_PROVIDER}/{settings.LLM_MODEL}")
    logger.info(f"Embedding: {settings.EMBEDDING_MODEL}")
    logger.info(f"ChromaDB: {settings.CHROMA_PERSIST_DIR}")
    logger.info("=" * 60)

    await knowledge_base.initialize()
    yield
    logger.info("系统关闭")


app = FastAPI(
    title="多智能体协同决策系统",
    description="领域知识个性化生成 — XH-202630 揭榜挂帅擂台赛",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 内存任务存储（生产环境可换 Redis） ──
_tasks: dict[str, dict] = {}


@app.get("/")
async def root():
    return {
        "name": "领域知识个性化生成与多智能体协同决策系统",
        "version": "0.1.0",
        "status": "running",
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "llm": f"{settings.LLM_PROVIDER}/{settings.LLM_MODEL}",
        "chroma": knowledge_base._initialized,
    }


@app.post("/api/profile", response_model=CreateProfileResponse)
async def create_profile(req: CreateProfileRequest):
    """创建学习者画像 — 触发 Agent 1 学情诊断"""
    learner_id = str(uuid.uuid4())
    learner_data = {
        "education_level": req.education.level.value,
        "major": req.education.major,
        "school": req.education.school,
        "work_years": req.experience.years,
        "industry": req.experience.industry,
        "positions": req.experience.positions,
        "skills_used": req.experience.skills_used,
        "pretest_results": [
            {
                "test_name": t.test_name,
                "total_score": t.total_score,
                "max_score": t.max_score,
                "topic_scores": t.topic_scores,
            }
            for t in req.pretest_results
        ],
        "learning_goal": req.learning_goal,
    }

    # 运行诊断
    initial_state = {"learner_data": learner_data}
    result = await workflow_engine.diagnosis.process(initial_state)

    return CreateProfileResponse(
        learner_id=learner_id,
        profile=LearnerProfile(
            learner_id=learner_id,
            name=req.name,
            education=req.education,
            experience=req.experience,
            pretest_results=req.pretest_results,
            learning_style=result.get("diagnosis_result", {}).get("learning_style", "practice_first"),
            recommended_difficulty=result.get("diagnosis_result", {}).get("recommended_difficulty", "beginner"),
            **{
                k: v for k, v in result.get("diagnosis_result", {}).items()
                if k in ("knowledge_map", "skill_gaps")
            },
        ),
    )


@app.post("/api/generate", response_model=GenerateResponse)
async def generate_resources(req: GenerateRequest):
    """生成个性化学习资源 — 触发完整工作流"""
    task_id = str(uuid.uuid4())
    _tasks[task_id] = {
        "status": "queued",
        "progress_percent": 0,
        "current_agent": None,
        "generated_resources": [],
        "debate_records": [],
    }

    # 异步运行工作流（生产环境用 Celery/BackgroundTasks）
    try:
        result = await workflow_engine.run(
            task_id=task_id,
            learner_data={"learner_id": req.learner_id},
            resource_types=[rt.value for rt in req.resource_types],
        )
        _tasks[task_id] = {
            "status": result.get("status", "completed"),
            "progress_percent": 100,
            "current_agent": result.get("current_agent", ""),
            "generated_resources": result.get("final_resources", []),
            "debate_records": result.get("debate_records", []),
        }
    except Exception as e:
        logger.error(f"[API] 工作流失败: {e}")
        _tasks[task_id] = {
            "status": "failed",
            "progress_percent": 0,
            "current_agent": None,
            "generated_resources": [],
            "debate_records": [],
            "error_message": str(e),
        }

    return GenerateResponse(
        task_id=task_id,
        status="started",
        estimated_seconds=120,
    )


@app.get("/api/task/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """获取任务状态 — 前端轮询/WebSocket 用"""
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return TaskStatusResponse(task_id=task_id, **task)


@app.get("/api/report/{learner_id}", response_model=ReportResponse)
async def get_report(learner_id: str):
    """获取学情与资源匹配度报告 — 含三个可视化数据"""
    raise HTTPException(status_code=501, detail="报告接口待实现")


@app.post("/api/knowledge/upload")
async def upload_knowledge(doc_id: str, title: str, content: str):
    """上传知识库文档"""
    chunks = await knowledge_base.add_document(doc_id, title, content)
    return {"doc_id": doc_id, "chunks": len(chunks), "status": "ok"}

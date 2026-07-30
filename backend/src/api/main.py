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

# ====================== 导入全部结束后，再放文档注释与业务代码 ======================
"""FastAPI 应用入口 — MVP 版本：2 Agent 工作流 (不需要知识库)"""

# 定位项目根目录 XH-agent
root_path = Path(__file__).parent.parent.parent.parent
sys.path.append(str(root_path))

# 全部换成绝对导入，删掉..相对导入


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("领域知识个性化生成系统 v0.1.0 MVP")
    logger.info(f"LLM: {settings.LLM_PROVIDER}/{settings.LLM_MODEL}")
    logger.info("知识来源: LLM 自身知识（无外部知识库）")
    logger.info("=" * 60)
    yield
    logger.info("系统关闭")


app = FastAPI(
    title="领域知识个性化生成系统 MVP",
    description="XH-202630 揭榜挂帅 — 多智能体协同决策",
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


@app.get("/")
async def root():
    return {
        "name": "领域知识个性化生成系统 MVP",
        "version": "0.1.0",
        "status": "running",
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "llm": f"{settings.LLM_PROVIDER}/{settings.LLM_MODEL}",
        "demo_mode": not bool(settings.LLM_API_KEY),
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

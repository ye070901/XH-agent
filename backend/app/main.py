"""FastAPI 应用入口"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from .core.config import settings
from .api.routes import router
from .knowledge.rag import knowledge_base


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期 — 启动时初始化知识库"""
    logger.info("=" * 60)
    logger.info("领域知识个性化生成与多智能体协同决策系统 v0.1.0")
    logger.info(f"LLM: {settings.LLM_PROVIDER}/{settings.LLM_MODEL}")
    logger.info(f"Embedding: {settings.EMBEDDING_MODEL}")
    logger.info("=" * 60)

    # 初始化知识库
    await knowledge_base.initialize()

    yield

    logger.info("系统关闭")


app = FastAPI(
    title="领域知识个性化生成与多智能体协同决策系统",
    description="XH-202630 揭榜挂帅擂台赛作品",
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

app.include_router(router)


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
        "milvus": knowledge_base._initialized,
    }

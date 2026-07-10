"""系统配置 — 所有配置通过环境变量加载，一行换模型"""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # ============================================================
    # LLM（一行换模型）
    # ============================================================
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o")

    # 可选：不同 Agent 使用不同模型
    LLM_MODEL_DIAGNOSIS: str = os.getenv("LLM_MODEL_DIAGNOSIS", "")
    LLM_MODEL_GENERATION: str = os.getenv("LLM_MODEL_GENERATION", "")
    LLM_MODEL_AUDIT: str = os.getenv("LLM_MODEL_AUDIT", "")

    # ============================================================
    # Embedding
    # ============================================================
    EMBEDDING_PROVIDER: str = os.getenv("EMBEDDING_PROVIDER", "openai")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    EMBEDDING_DIM: int = int(os.getenv("EMBEDDING_DIM", "1536"))

    # ============================================================
    # ChromaDB
    # ============================================================
    CHROMA_PERSIST_DIR: str = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma")

    # ============================================================
    # Agent
    # ============================================================
    AGENT_MAX_RETRIES: int = 3
    DEBATE_MAX_ROUNDS: int = int(os.getenv("DEBATE_MAX_ROUNDS", "3"))
    HALLUCINATION_THRESHOLD: float = 0.05
    ADAPTATION_TARGET: float = 0.85
    COVERAGE_TARGET: float = 0.90

    # ============================================================
    # App
    # ============================================================
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"
    CORS_ORIGINS: list[str] = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))


settings = Settings()

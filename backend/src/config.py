"""全局配置 — 所有配置通过环境变量加载，一行换模型。

全局唯一入口：`from backend.src.config import settings`
禁止在任何模块中直接 os.getenv()，一切走 Settings 单例。

配置优先级：环境变量 > .env 文件 > 类内硬编码默认值
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from loguru import logger

load_dotenv()

# ═══════════════════════════════════════════════════════════
# 类型安全的配置读取辅助函数
# ═══════════════════════════════════════════════════════════

_ALWAYS_TRUE = ("true", "1", "yes", "on")
_ALWAYS_FALSE = ("false", "0", "no", "off")


def _bool_env(key: str, default: bool = True) -> bool:
    """统一的布尔型环境变量读取。

    兼容写法: true/false, 1/0, yes/no, on/off（大小写不敏感）。
    不符合任一格式时回退到 default 并记录 warning。
    """
    raw = os.getenv(key, str(default).lower())
    if raw.lower() in _ALWAYS_TRUE:
        return True
    if raw.lower() in _ALWAYS_FALSE:
        return False
    logger.warning(f"[Config] {key}={raw!r} 无法解析为 bool，使用默认值 {default}")
    return default


def _int_env(key: str, default: int) -> int:
    """统一的整数型环境变量读取。非法值时回退到 default。"""
    raw = os.getenv(key, str(default))
    try:
        return int(raw)
    except (ValueError, TypeError):
        logger.warning(f"[Config] {key}={raw!r} 无法解析为 int，使用默认值 {default}")
        return default


def _float_env(key: str, default: float) -> float:
    """统一的浮点型环境变量读取。非法值时回退到 default。"""
    raw = os.getenv(key, str(default))
    try:
        return float(raw)
    except (ValueError, TypeError):
        logger.warning(f"[Config] {key}={raw!r} 无法解析为 float，使用默认值 {default}")
        return default


def _list_env(key: str, default: str) -> list[str]:
    """统一的逗号分隔列表型环境变量读取。空字符串被过滤。"""
    raw = os.getenv(key, default)
    return [s.strip() for s in raw.split(",") if s.strip()]


# ═══════════════════════════════════════════════════════════
# Settings 单例
# ═══════════════════════════════════════════════════════════


class Settings:
    """全局配置单例。

    所有配置项必须在此类中定义，类型注解必须明确。
    新增配置项时同步更新 .env.example，注明默认值和用途。

    Usage:
        from backend.src.config import settings
        model = settings.get_model_for_agent("diagnosis")
    """

    # ============================================================
    # LLM 通用（一行换模型：改 LLM_PROVIDER + LLM_MODEL）
    # ============================================================
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o")

    # Agent 粒度模型覆盖（为空则回退到 LLM_MODEL）
    LLM_MODEL_DIAGNOSIS: str = os.getenv("LLM_MODEL_DIAGNOSIS", "")
    LLM_MODEL_GENERATION: str = os.getenv("LLM_MODEL_GENERATION", "")
    LLM_MODEL_AUDIT: str = os.getenv("LLM_MODEL_AUDIT", "")
    LLM_MODEL_CORRECTION: str = os.getenv("LLM_MODEL_CORRECTION", "")

    # LLM 调用参数
    LLM_TIMEOUT_SECONDS: int = _int_env("LLM_TIMEOUT_SECONDS", 120)
    LLM_MAX_RETRIES: int = _int_env("LLM_MAX_RETRIES", 2)
    LLM_MAX_INPUT_CHARS: int = _int_env("LLM_MAX_INPUT_CHARS", 32000)
    """输入文本最大字符数，超长自动截断（保留 system_prompt + 截断 user_message）"""

    # 各 Agent 推荐温度（诊断/审核/修正低温保证一致，生成中温保证多样性）
    LLM_TEMPERATURE_DIAGNOSIS: float = _float_env("LLM_TEMPERATURE_DIAGNOSIS", 0.2)
    LLM_TEMPERATURE_GENERATION: float = _float_env("LLM_TEMPERATURE_GENERATION", 0.5)
    LLM_TEMPERATURE_AUDIT: float = _float_env("LLM_TEMPERATURE_AUDIT", 0.1)
    LLM_TEMPERATURE_CORRECTION: float = _float_env("LLM_TEMPERATURE_CORRECTION", 0.2)

    # ============================================================
    # Embedding
    # ============================================================
    EMBEDDING_PROVIDER: str = os.getenv("EMBEDDING_PROVIDER", "openai")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    EMBEDDING_DIM: int = _int_env("EMBEDDING_DIM", 1536)

    # ============================================================
    # ChromaDB
    # ============================================================
    CHROMA_PERSIST_DIR: str = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma")
    CHROMA_COLLECTION_NAME: str = os.getenv("CHROMA_COLLECTION_NAME", "domain_knowledge")

    # ============================================================
    # Agent
    # ============================================================
    AGENT_MAX_RETRIES: int = _int_env("AGENT_MAX_RETRIES", 3)
    DEBATE_MAX_ROUNDS: int = _int_env("DEBATE_MAX_ROUNDS", 3)
    HALLUCINATION_THRESHOLD: float = _float_env("HALLUCINATION_THRESHOLD", 0.05)
    ADAPTATION_TARGET: float = _float_env("ADAPTATION_TARGET", 0.85)
    COVERAGE_TARGET: float = _float_env("COVERAGE_TARGET", 0.90)

    # ============================================================
    # Scheduler（调度器并发/超时）
    # ============================================================
    SCHEDULER_MAX_CONCURRENT_TASKS: int = _int_env("SCHEDULER_MAX_CONCURRENT_TASKS", 10)
    """全局任务最大并发上限，防止 LLM 资源耗尽"""
    SCHEDULER_TASK_TIMEOUT_SECONDS: int = _int_env("SCHEDULER_TASK_TIMEOUT_SECONDS", 600)
    """单 task 全局执行超时，超时主动终止链路并推送错误事件"""
    SCHEDULER_AGENT_TIMEOUT_SECONDS: int = _int_env("SCHEDULER_AGENT_TIMEOUT_SECONDS", 180)
    """单个 Agent 执行超时，超时后跳过该 Agent 继续链路（不设默认值也 OK，由 Agent 层自己控制）"""

    # ============================================================
    # Quality Gate（三道闸门全部阈值，禁止模块内硬编码）
    # ============================================================
    # -- 闸门1：特异性检测（纯规则，不调LLM）--
    GATE1_MIN_INPUT_LENGTH: int = _int_env("GATE1_MIN_INPUT_LENGTH", 10)
    """用户输入最短字符数，低于此值直接拦截"""
    GATE1_BANNED_KEYWORDS: list[str] = _list_env(
        "GATE1_BANNED_KEYWORDS",
        "违法,暴力,色情,赌博,毒品",
    )
    """领域外危险关键词，命中任一即拦截"""
    GATE1_BLOCKED_DOMAINS: list[str] = _list_env(
        "GATE1_BLOCKED_DOMAINS",
        "政治,军事,金融交易,医疗诊断",
    )
    """领域外话题，命中任一即拦截"""

    # -- 闸门2：学情诊断质量（硬规则 + 临界LLM复核）--
    GATE2_MIN_SKILL_GAPS: int = _int_env("GATE2_MIN_SKILL_GAPS", 1)
    """skill_gaps 最少条数"""
    GATE2_MIN_KNOWLEDGE_ITEMS: int = _int_env("GATE2_MIN_KNOWLEDGE_ITEMS", 1)
    """knowledge_map 最少条目数"""
    GATE2_LLM_REVIEW_LOWER: float = _float_env("GATE2_LLM_REVIEW_LOWER", 0.40)
    """诊断质量分数低于此值 → 直接驳回"""
    GATE2_LLM_REVIEW_UPPER: float = _float_env("GATE2_LLM_REVIEW_UPPER", 0.70)
    """诊断质量分数高于此值 → 直接放行；[lower, upper] 区间 → LLM复核"""

    # -- 闸门3：RAG召回质量（硬规则 + 临界LLM复核）--
    GATE3_MIN_RECALL_COUNT: int = _int_env("GATE3_MIN_RECALL_COUNT", 3)
    """最少召回文档数"""
    GATE3_MIN_SIMILARITY: float = _float_env("GATE3_MIN_SIMILARITY", 0.60)
    """单文档最低相似度阈值"""
    GATE3_LLM_REVIEW_SIM_LOWER: float = _float_env("GATE3_LLM_REVIEW_SIM_LOWER", 0.50)
    """相似度低于此值 → 直接丢弃"""
    GATE3_LLM_REVIEW_SIM_UPPER: float = _float_env("GATE3_LLM_REVIEW_SIM_UPPER", 0.70)
    """相似度高于此值 → 直接采纳；[lower, upper] 区间 → LLM复核语义相关性"""

    # -- 闸门通用 --
    GATE_LLM_MODEL: str = os.getenv("GATE_LLM_MODEL", "")
    """闸门轻量LLM复核使用的模型，为空回退到 LLM_MODEL"""

    # ============================================================
    # App
    # ============================================================
    DEBUG: bool = _bool_env("DEBUG", True)
    CORS_ORIGINS: list[str] = _list_env("CORS_ORIGINS", "http://localhost:3000")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = _int_env("PORT", 8000)

    # ═══════════════════════════════════════════════════════════
    # Agent → Model / Temperature 映射表
    # ═══════════════════════════════════════════════════════════

    _AGENT_MODEL_MAP: dict[str, str] = {
        "diagnosis": "LLM_MODEL_DIAGNOSIS",
        "agent1": "LLM_MODEL_DIAGNOSIS",
        "generation": "LLM_MODEL_GENERATION",
        "agent2": "LLM_MODEL_GENERATION",
        "audit": "LLM_MODEL_AUDIT",
        "agent3": "LLM_MODEL_AUDIT",
        "correction": "LLM_MODEL_CORRECTION",
        "agent4": "LLM_MODEL_CORRECTION",
    }

    _AGENT_TEMPERATURE_MAP: dict[str, str] = {
        "diagnosis": "LLM_TEMPERATURE_DIAGNOSIS",
        "generation": "LLM_TEMPERATURE_GENERATION",
        "audit": "LLM_TEMPERATURE_AUDIT",
        "correction": "LLM_TEMPERATURE_CORRECTION",
    }

    # ═══════════════════════════════════════════════════════════
    # 方法
    # ═══════════════════════════════════════════════════════════

    def get_model_for_agent(self, agent_name: str) -> str:
        """解析 Agent 使用的模型，支持粒度覆盖与回退。

        解析链：LLM_MODEL_<AGENT_NAME> 环境变量 → LLM_MODEL 环境变量

        agent_name 大小写不敏感。支持别名：
          diagnosis / agent1   → LLM_MODEL_DIAGNOSIS
          generation / agent2  → LLM_MODEL_GENERATION
          audit / agent3       → LLM_MODEL_AUDIT
          correction / agent4  → LLM_MODEL_CORRECTION
          未匹配的 agent_name  → 直接回退到 LLM_MODEL
        """
        attr_name = self._AGENT_MODEL_MAP.get(agent_name.lower(), "")
        if attr_name:
            override = getattr(self, attr_name, "")
            if override:
                return override
        return self.LLM_MODEL

    def get_temperature_for_agent(self, agent_name: str) -> float:
        """获取 Agent 的推荐 temperature。

        agent_name 大小写不敏感。
        未匹配的 agent_name 返回 0.3（保守默认值）。
        """
        attr_name = self._AGENT_TEMPERATURE_MAP.get(agent_name.lower(), "")
        if attr_name:
            return getattr(self, attr_name, 0.3)
        return 0.3

    @property
    def is_demo_mode(self) -> bool:
        """快捷属性：LLM_API_KEY 为空 → 演示模式。"""
        return not bool(self.LLM_API_KEY)

    def display(self) -> str:
        """启动时打印当前配置摘要（隐藏敏感信息）。"""
        lines = [
            "─" * 50,
            "  Config Summary",
            "─" * 50,
            f"  LLM Provider   : {self.LLM_PROVIDER}",
            f"  LLM Model      : {self.LLM_MODEL}",
            f"  LLM Base URL   : {self.LLM_BASE_URL}",
            f"  Demo Mode      : {self.is_demo_mode}",
            f"  Timeout        : {self.LLM_TIMEOUT_SECONDS}s",
            f"  Max Retries    : {self.LLM_MAX_RETRIES}",
            f"  Embedding      : {self.EMBEDDING_PROVIDER}/"
            f"{self.EMBEDDING_MODEL} ({self.EMBEDDING_DIM}d)",
            f"  ChromaDB       : {self.CHROMA_PERSIST_DIR}",
            f"  Debate Rounds  : {self.DEBATE_MAX_ROUNDS}",
            f"  Hallucination  : < {self.HALLUCINATION_THRESHOLD}",
            f"  Adaptation     : > {self.ADAPTATION_TARGET}",
            f"  Coverage       : > {self.COVERAGE_TARGET}",
            f"  Debug          : {self.DEBUG}",
            f"  Server         : {self.HOST}:{self.PORT}",
            "─" * 50,
        ]
        return "\n".join(lines)

    def validate(self) -> list[str]:
        """启动时自检关键配置，返回 warning 列表。

        Returns:
            list[str]: 警告信息列表。空列表表示一切就绪。
        """
        warnings: list[str] = []

        # 真实模式下必须的配置项
        if not self.is_demo_mode:
            if not self.LLM_BASE_URL:
                warnings.append("LLM_BASE_URL 为空，API 调用可能失败")
            if not self.LLM_MODEL:
                warnings.append("LLM_MODEL 为空，将使用 SDK 默认模型")

        # 数值合理性检查
        if self.LLM_TIMEOUT_SECONDS < 5:
            warnings.append(f"LLM_TIMEOUT_SECONDS={self.LLM_TIMEOUT_SECONDS} 过短，建议 ≥ 10s")
        if self.DEBATE_MAX_ROUNDS < 1:
            warnings.append(f"DEBATE_MAX_ROUNDS={self.DEBATE_MAX_ROUNDS} 无效，应 ≥ 1")
        if not (0 < self.HALLUCINATION_THRESHOLD < 1):
            warnings.append(
                f"HALLUCINATION_THRESHOLD={self.HALLUCINATION_THRESHOLD} 应在 (0, 1) 区间"
            )

        return warnings


# ── 全局单例（唯一入口）──
settings = Settings()

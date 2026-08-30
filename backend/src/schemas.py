"""
接口Schema定义 — 全员统一引用此文件。修改需全员周知。
═══════════════════════════════════════════════════════════
这是 8 个人的契约文件。修改此文件的任何字段，必须：
1. 在团队群通知
2. 更新 docs/INTERFACE_CONTRACT.md
3. 确保所有 Agent 的输入/输出仍然匹配
"""

import re
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# ═══════════════════════════════════════════════════════════
# 枚举
# ═══════════════════════════════════════════════════════════


class EducationLevel(str, Enum):
    HIGH_SCHOOL = "high_school"
    JUNIOR_COLLEGE = "junior_college"
    BACHELOR = "bachelor"
    MASTER = "master"
    PHD = "phd"


class Difficulty(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class RiskLevel(str, Enum):
    """工业实操风险分级（与 Difficulty 正交：危险 ≠ 难度）。

    theory    纯理论内容，无操作风险
    low_risk  软件操作、参数查看、程序编辑
    high_risk 示教、点动、运行程序、IO调试等涉及机器人运动的操作
    """

    THEORY = "theory"
    LOW_RISK = "low_risk"
    HIGH_RISK = "high_risk"


class ResourceType(str, Enum):
    LECTURE = "lecture"
    GUIDE = "guide"
    QUIZ = "quiz"
    CASE_STUDY = "case_study"
    MICRO_PROJECT = "micro_project"
    PROJECT = "project"
    PITFALL_GUIDE = "pitfall_guide"


class LearningStyle(str, Enum):
    THEORY_FIRST = "theory_first"
    PRACTICE_FIRST = "practice_first"
    VISUAL = "visual"
    PROJECT_BASED = "project_based"


class AuditVerdict(str, Enum):
    APPROVED = "approved"
    NEEDS_REVISION = "needs_revision"
    REJECTED = "rejected"
    UNCERTAIN = "uncertain"


class FeedbackAction(str, Enum):
    SIMPLIFY = "simplify"
    ADVANCE = "advance"
    REGENERATE = "regenerate"
    CONTINUE = "continue"


class AgentState(str, Enum):
    IDLE = "idle"
    THINKING = "thinking"
    ACTING = "acting"
    DONE = "done"
    ERROR = "error"


class PipelineState(str, Enum):
    """流水线调度器全局状态 — 用于 Scheduler v0.1 状态机。

    IDLE           → 初始状态，等待用户输入
    RUNNING        → 流水线执行中
    WAITING_RETRY  → 闸门返回 RETRY，等待回跳重试
    FALLBACK       → 闸门返回 FALLBACK，执行降级兜底路径
    DONE           → 流水线执行完成（含正常、降级、失败三种终态）
    """

    IDLE = "idle"
    RUNNING = "running"
    WAITING_RETRY = "waiting_retry"
    FALLBACK = "fallback"
    DONE = "done"


class GateVerdict(str, Enum):
    """闸门三路裁决 — v0.1 PASS/RETRY/FALLBACK 模型。"""

    PASS = "PASS"
    RETRY = "RETRY"
    FALLBACK = "FALLBACK"


# ═══════════════════════════════════════════════════════════
# 学习者画像（Agent 1: 学情诊断 的输入/输出）
# ═══════════════════════════════════════════════════════════


class Education(BaseModel):
    level: EducationLevel
    major: str = Field(description="专业")
    school: Optional[str] = None
    graduation_year: Optional[int] = None


class WorkExperience(BaseModel):
    years: float = Field(default=0, ge=0)
    industry: Optional[str] = None
    positions: list[str] = Field(default_factory=list)
    skills_used: list[str] = Field(default_factory=list)


class PretestResult(BaseModel):
    test_name: str
    total_score: float
    max_score: float
    topic_scores: dict[str, float] = Field(default_factory=dict)
    completed_at: datetime = Field(default_factory=datetime.now)


class KnowledgeItem(BaseModel):
    """单个知识点的掌握评估"""

    topic: str = Field(description="知识点名称")
    level: float = Field(ge=0, le=1, description="掌握度 0-1")
    confidence: float = Field(ge=0, le=1, description="评估置信度 0-1")
    evidence: Optional[str] = Field(default=None, description="评估依据")


class SkillGap(BaseModel):
    """知识盲区 — Agent 1 核心输出"""

    topic: str
    current_level: float = Field(ge=0, le=1)
    target_level: float = Field(ge=0, le=1)
    priority: str = Field(description="critical | high | medium | low")
    reason: str


class LearnerProfile(BaseModel):
    """学情画像 — Agent 1 的完整输出，也是 Agent 2 的输入"""

    learner_id: str
    name: str
    education: Education
    experience: WorkExperience
    pretest_results: list[PretestResult] = Field(default_factory=list)
    knowledge_map: dict[str, KnowledgeItem] = Field(default_factory=dict)
    skill_gaps: list[SkillGap] = Field(default_factory=list)
    learning_style: LearningStyle
    recommended_difficulty: Difficulty
    additional_notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


# ═══════════════════════════════════════════════════════════
# 知识溯源
# ═══════════════════════════════════════════════════════════


class Citation(BaseModel):
    """知识溯源 — 每条生成的断言必须关联此记录"""

    doc_id: str
    chunk_index: int
    original_text: str = Field(description="知识库原文片段 — 必须是逐字引用")
    relevance_score: float = Field(ge=0, le=1)


# ═══════════════════════════════════════════════════════════
# 生成资源（Agent 2: 知识生成 的输出）
# ═══════════════════════════════════════════════════════════


class RobotMetadata(BaseModel):
    """实操类资源的适配元数据 — 仅由知识库 doc_id/doc_title 确定性派生，LLM 不产出。

    任一字段在知识库无权威来源时，运行时代码标注「未标注」，禁止编造具体型号。
    """

    brand: Optional[str] = None
    controller_version: Optional[str] = None
    applicable_model: Optional[str] = None


class InstructionLink(BaseModel):
    """正文命中的指令速查跳转链接 — 由生成管线消费 instruction_index.json 确定性派生。"""

    brand: str
    name: str = Field(description="指令名，如 MoveJ")
    doc_id: str
    doc_title: str


class AlarmLink(BaseModel):
    """正文命中的报警排查跳转链接 — 由生成管线消费 alarm_index.json 确定性派生。"""

    brand: str
    code: str = Field(description="报警代码，如 SRVO-068")
    doc_id: str
    doc_title: str
    fault_name: str = ""


class GeneratedResource(BaseModel):
    """个性化学习资源 — Agent 2 输出，Agent 3 审核"""

    resource_id: str
    learner_id: str
    resource_type: ResourceType
    title: str
    content: str = Field(description="Markdown 格式的完整内容")
    citations: list[Citation] = Field(
        default_factory=list,
        description="专业断言溯源。空数组 = 疑似未约束生成，Agent 3 将标记为 critical",
    )
    difficulty_level: Difficulty
    target_skill_gaps: list[str] = Field(default_factory=list)
    estimated_duration_minutes: int = 30
    prerequisites: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.THEORY
    safety_warnings: list[str] = Field(
        default_factory=list,
        description="逐步安全提示，从正文 `> ⚠️ 安全提示：…` 引用块确定性提取，不与普通步骤文本合并",
    )
    robot_metadata: Optional[RobotMetadata] = None
    instruction_links: list[InstructionLink] = Field(
        default_factory=list,
        description="正文命中的指令速查跳转链接（三品牌），供前端渲染可点击速查条",
    )
    alarm_links: list[AlarmLink] = Field(
        default_factory=list,
        description="正文命中的报警排查跳转链接（三品牌），供前端渲染可点击速查条",
    )


# ═══════════════════════════════════════════════════════════
# 审核与辩论（Agent 3: 审核裁判 的输入/输出）
# ═══════════════════════════════════════════════════════════


class FactCheckItem(BaseModel):
    claim: str = Field(description="从生成内容中提取的断言")
    citation_ref: Optional[str] = Field(default=None, description="对应的 Citation.doc_id")
    verdict: Literal["accurate", "hallucination", "unverifiable", "partially_supported", "skip"] = (
        Field(description="四态事实核验结果；非事实性表述使用 skip")
    )
    is_accurate: Optional[bool] = Field(
        default=None,
        description="兼容字段：accurate=True，hallucination=False，partially_supported/其余为 None",
    )
    evidence_from_kb: Optional[str] = Field(default=None, description="知识库中支撑/反驳的原句")
    explanation: str = ""

    @model_validator(mode="before")
    @classmethod
    def populate_compatibility_fields(cls, value: Any) -> Any:
        """兼容旧版仅含 is_accurate 的 Agent3 输出。"""

        if not isinstance(value, dict):
            return value
        item = dict(value)
        verdict = item.get("verdict")
        if not verdict:
            accurate = item.get("is_accurate")
            if accurate is True:
                item["verdict"] = "accurate"
            elif accurate is False:
                item["verdict"] = "hallucination"
            else:
                item["verdict"] = "unverifiable"
        if "is_accurate" not in item:
            item["is_accurate"] = {
                "accurate": True,
                "hallucination": False,
                "partially_supported": None,  # 核心事实成立但细节缺失 → 非完全准确，亦非错误
            }.get(item["verdict"])
        return item


class FactCheckResult(BaseModel):
    overall_accuracy: float = Field(ge=0, le=1)
    items: list[FactCheckItem] = Field(default_factory=list)
    hallucination_count: int = 0
    unverifiable_count: int = 0
    partially_supported_count: int = 0


class ComplianceResult(BaseModel):
    is_compliant: bool
    issues: list[str] = Field(default_factory=list)
    industry_standards_referenced: list[str] = Field(default_factory=list)


class DifficultyMatchResult(BaseModel):
    is_match: bool
    learner_level: Difficulty
    resource_level: Difficulty
    mismatch_reason: Optional[str] = None
    score: float = Field(ge=0, le=1)


class HallucinationFlag(BaseModel):
    location: str = Field(description="内容中的具体位置")
    description: str
    severity: str = Field(description="critical | major | minor")
    suggested_correction: Optional[str] = None


class AuditReport(BaseModel):
    """审核报告 — Agent 3 的核心输出"""

    resource_id: str
    is_approved: bool
    verdict: AuditVerdict
    fact_check: FactCheckResult
    compliance_check: ComplianceResult
    difficulty_match: DifficultyMatchResult
    knowledge_coverage: float = Field(ge=0, le=1, description="知识点覆盖率")
    hallucination_flags: list[HallucinationFlag] = Field(default_factory=list)
    hallucination_rate: float = Field(ge=0, le=1, description="幻觉率 = 错误断言数 / 总断言数")
    confidence_score: float = Field(ge=0, le=1)
    correction_suggestions: list[str] = Field(default_factory=list)
    reviewed_at: datetime = Field(default_factory=datetime.now)


# ═══════════════════════════════════════════════════════════
# 辩论协议（Agent 2⇄Agent 3 博弈记录）
# ═══════════════════════════════════════════════════════════


class AuditChallenge(BaseModel):
    """Agent 3 向 Agent 2 发起的质询"""

    round_number: int
    claim: str = Field(description="被质疑的断言")
    challenge: str = Field(description="审核方的质疑理由")
    evidence_from_kb: Optional[str] = Field(default=None, description="KB中反驳该断言的原文")
    severity: str = Field(description="critical | major | minor")


class AgentDefense(BaseModel):
    """Agent 2 对质询的回应"""

    round_number: int
    original_claim: str
    defense: str = Field(description="辩护理由")
    evidence_from_kb: Optional[str] = Field(default=None, description="KB中支撑该断言的原文")
    action: str = Field(description="accept_challenge(修正) | rebut(反驳) | concede(承认错误)")


class DebateRound(BaseModel):
    """单轮辩论记录"""

    round_number: int
    challenge: AuditChallenge
    defense: AgentDefense
    resolution: Optional[str] = None
    consensus_reached: bool = False


class DebateRecord(BaseModel):
    """完整辩论记录"""

    debate_id: str
    resource_id: str
    rounds: list[DebateRound] = Field(default_factory=list)
    final_verdict: AuditVerdict
    final_resource: Optional[GeneratedResource] = None
    unresolved_claims: list[str] = Field(
        default_factory=list,
        description="3轮后仍未共识的断言，标记为待人工审核",
    )
    started_at: datetime = Field(default_factory=datetime.now)
    ended_at: Optional[datetime] = None


# ═══════════════════════════════════════════════════════════
# 交互反馈与动态决策
# ═══════════════════════════════════════════════════════════


class QuizSubmission(BaseModel):
    learner_id: str
    resource_id: str
    answers: list[dict] = Field(default_factory=list)
    submitted_at: datetime = Field(default_factory=datetime.now)


class QuizResult(BaseModel):
    submission_id: str
    total_score: float
    max_score: float
    correct_rate: float = Field(ge=0, le=1)
    topic_breakdown: dict[str, float] = Field(default_factory=dict)
    time_spent_total: int


class FeedbackDecision(BaseModel):
    """答题反馈后的多Agent协同决策结果"""

    learner_id: str
    resource_id: str
    quiz_result: QuizResult
    action: FeedbackAction
    reason: str = Field(description="多Agent协同做出此决策的推理过程")
    contributing_agents: list[str] = Field(
        default_factory=list,
        description="参与此决策的Agent列表",
    )
    suggested_next_resource: Optional[str] = None
    decided_at: datetime = Field(default_factory=datetime.now)


# ═══════════════════════════════════════════════════════════
# 学习路径与可视化
# ═══════════════════════════════════════════════════════════


class LearningPathNode(BaseModel):
    node_id: str
    title: str
    resource_id: Optional[str] = None
    resource_type: Optional[ResourceType] = None
    difficulty: Difficulty
    estimated_duration_minutes: int
    depends_on: list[str] = Field(default_factory=list)
    is_completed: bool = False


class LearningPath(BaseModel):
    learner_id: str
    nodes: list[LearningPathNode]
    total_estimated_hours: float
    created_at: datetime = Field(default_factory=datetime.now)


# ═══════════════════════════════════════════════════════════
# 报告（含可视化数据）
# ═══════════════════════════════════════════════════════════


class ReportResponse(BaseModel):
    """学情与资源匹配度报告 — 评分标准要求的三个可视化"""

    learner_id: str
    profile: LearnerProfile
    knowledge_radar: dict[str, float] = Field(
        default_factory=dict,
        description="知识雷达图数据：topic→score",
    )
    skill_gap_analysis: list[SkillGap]
    resource_match_curve: list[dict] = Field(
        default_factory=list,
        description="资源难度匹配曲线数据",
    )
    learning_path: Optional[LearningPath] = None
    agent_decision_log: list[dict] = Field(
        default_factory=list,
        description="多Agent决策过程日志，用于可视化Agent协同过程",
    )
    debate_summary: Optional[DebateRecord] = None
    metrics_summary: dict = Field(
        default_factory=dict,
        description="三项硬指标：幻觉率、适配率、覆盖率",
    )
    generated_at: datetime = Field(default_factory=datetime.now)


# ═══════════════════════════════════════════════════════════
# API 请求/响应
# ═══════════════════════════════════════════════════════════


class CreateProfileRequest(BaseModel):
    name: str
    education: Education
    experience: WorkExperience
    pretest_results: list[PretestResult] = Field(default_factory=list)
    learning_goal: Optional[str] = None


class CreateProfileResponse(BaseModel):
    learner_id: str
    profile: LearnerProfile


# ═══════════════════════════════════════════════════════════
# Phase 3：认可画像快照持久化
# ═══════════════════════════════════════════════════════════


class ProfileSnapshotCreate(BaseModel):
    """K3 点击“认可，保存画像”时提交的完整快照。"""

    learner_id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    profile: dict[str, Any] = Field(description="完整学情画像，含 knowledge_map/skill_gaps")
    source_task_id: Optional[str] = Field(default=None, max_length=128)
    label: Optional[str] = Field(default=None, max_length=100)


class ProfileSnapshotResponse(BaseModel):
    profile_id: str
    learner_id: str
    name: Optional[str] = None
    profile: dict[str, Any]
    source_task_id: Optional[str] = None
    label: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ProfileListResponse(BaseModel):
    items: list[ProfileSnapshotResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class ProfileCleanupSettings(BaseModel):
    max_profiles: int = Field(ge=1, le=10000)
    cleanup_time: str = Field(description="服务器本地时间，HH:MM")
    enabled: bool = True
    updated_at: datetime

    @field_validator("cleanup_time")
    @classmethod
    def validate_cleanup_time(cls, value: str) -> str:
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("cleanup_time must use 24-hour HH:MM format")
        return value


class ProfileCleanupSettingsUpdate(BaseModel):
    max_profiles: Optional[int] = Field(default=None, ge=1, le=10000)
    cleanup_time: Optional[str] = None
    enabled: Optional[bool] = None

    @field_validator("cleanup_time")
    @classmethod
    def validate_cleanup_time(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("cleanup_time must use 24-hour HH:MM format")
        return value


# ═══════════════════════════════════════════════════════════
# Phase 3：前置测试采集
# ═══════════════════════════════════════════════════════════


class PretestAnswer(BaseModel):
    question_id: str = Field(min_length=1, max_length=64)
    answer: str = Field(max_length=500)


class PretestSubmission(BaseModel):
    learner_id: str = Field(min_length=1, max_length=128)
    answers: list[PretestAnswer] = Field(min_length=1)

    @field_validator("answers")
    @classmethod
    def validate_unique_answers(
        cls,
        answers: list[PretestAnswer],
    ) -> list[PretestAnswer]:
        question_ids = [answer.question_id for answer in answers]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("each question_id may be submitted only once")
        return answers


class PretestScoreResponse(BaseModel):
    learner_id: str
    total_score: float
    max_score: float
    percentage: float = Field(ge=0, le=100)
    topic_scores: dict[str, float]
    pretest_results: list[PretestResult]
    details: list[dict[str, Any]]


class GenerateRequest(BaseModel):
    learner_id: str
    resource_types: list[ResourceType] = Field(
        default=[ResourceType.LECTURE, ResourceType.GUIDE, ResourceType.QUIZ],
    )
    difficulty_override: Optional[Difficulty] = None


class GenerateResponse(BaseModel):
    task_id: str
    status: str
    estimated_seconds: int


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    progress_percent: float = Field(ge=0, le=100)
    current_agent: Optional[str] = None
    current_agent_state: AgentState = AgentState.IDLE
    generated_resources: list[GeneratedResource] = Field(default_factory=list)
    debate_records: list[DebateRecord] = Field(default_factory=list)
    agent_interaction_log: list[dict] = Field(
        default_factory=list,
        description="Agent间交互日志，用于可视化",
    )
    error_message: Optional[str] = None


# ═══════════════════════════════════════════════════════════
# WebSocket 消息（Agent 协同可视化）
# ═══════════════════════════════════════════════════════════


class WSMessage(BaseModel):
    task_id: str
    timestamp: datetime = Field(default_factory=datetime.now)
    agent_name: str
    agent_state: AgentState
    message: str
    message_type: str = Field(
        default="info",
        description="info | challenge | defense | decision | error",
    )
    data: Optional[dict] = None
    to_agent: Optional[str] = Field(
        default=None,
        description="消息目标Agent，用于绘制Agent间通信拓扑",
    )

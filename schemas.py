"""
接口Schema定义 — 全员统一引用此文件。
修改需全员周知。
"""
from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime
from enum import Enum


# ============================================================
# 枚举
# ============================================================

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

class ResourceType(str, Enum):
    LECTURE = "lecture"
    GUIDE = "guide"
    QUIZ = "quiz"
    CASE_STUDY = "case_study"
    MICRO_PROJECT = "micro_project"

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


# ============================================================
# 学习者相关
# ============================================================

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

class KnowledgeItem(BaseModel):
    topic: str = Field(description="知识点名称")
    level: float = Field(ge=0, le=1, description="掌握度")
    confidence: float = Field(ge=0, le=1, description="评估置信度")
    evidence: Optional[str] = None

class SkillGap(BaseModel):
    topic: str
    current_level: float = Field(ge=0, le=1)
    target_level: float = Field(ge=0, le=1)
    priority: Literal["critical", "high", "medium", "low"]
    reason: str

class PretestResult(BaseModel):
    test_name: str
    total_score: float
    max_score: float
    topic_scores: dict[str, float] = Field(default_factory=dict)
    completed_at: datetime = Field(default_factory=datetime.now)

class LearnerProfile(BaseModel):
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


# ============================================================
# 知识溯源
# ============================================================

class Citation(BaseModel):
    doc_id: str
    chunk_index: int
    original_text: str = Field(description="知识库原文片段")
    relevance_score: float = Field(ge=0, le=1)


# ============================================================
# 生成资源
# ============================================================

class GeneratedResource(BaseModel):
    resource_id: str
    learner_id: str
    resource_type: ResourceType
    title: str
    content: str = Field(description="Markdown格式")
    citations: list[Citation] = Field(default_factory=list)
    difficulty_level: Difficulty
    target_skill_gaps: list[str] = Field(default_factory=list)
    estimated_duration_minutes: int = 30
    prerequisites: list[str] = Field(default_factory=list)


# ============================================================
# 审核
# ============================================================

class FactCheckItem(BaseModel):
    claim: str
    citation_ref: Optional[str] = None
    is_accurate: bool
    explanation: str

class FactCheckResult(BaseModel):
    overall_accuracy: float = Field(ge=0, le=1)
    items: list[FactCheckItem] = Field(default_factory=list)
    hallucination_count: int = 0

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
    location: str
    description: str
    severity: Literal["critical", "major", "minor"]
    suggested_correction: Optional[str] = None

class AuditReport(BaseModel):
    resource_id: str
    is_approved: bool
    verdict: AuditVerdict
    fact_check: FactCheckResult
    compliance_check: ComplianceResult
    difficulty_match: DifficultyMatchResult
    knowledge_coverage: float = Field(ge=0, le=1)
    hallucination_flags: list[HallucinationFlag] = Field(default_factory=list)
    confidence_score: float = Field(ge=0, le=1)
    correction_suggestions: list[str] = Field(default_factory=list)
    reviewed_at: datetime = Field(default_factory=datetime.now)


# ============================================================
# 辩论
# ============================================================

class DebateRound(BaseModel):
    round_number: int
    generation_agent_response: str
    review_agent_response: str
    arbitration_result: Optional[str] = None
    consensus_reached: bool = False

class DebateRecord(BaseModel):
    debate_id: str
    resource_id: str
    rounds: list[DebateRound] = Field(default_factory=list)
    final_verdict: AuditVerdict
    final_resource: Optional[GeneratedResource] = None
    started_at: datetime = Field(default_factory=datetime.now)
    ended_at: Optional[datetime] = None


# ============================================================
# 学习路径
# ============================================================

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


# ============================================================
# 答题反馈
# ============================================================

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
    learner_id: str
    resource_id: str
    quiz_result: QuizResult
    action: FeedbackAction
    reason: str
    suggested_next_resource: Optional[str] = None
    decided_at: datetime = Field(default_factory=datetime.now)


# ============================================================
# API请求/响应
# ============================================================

class CreateProfileRequest(BaseModel):
    name: str
    education: Education
    experience: WorkExperience
    pretest_results: list[PretestResult] = Field(default_factory=list)

class CreateProfileResponse(BaseModel):
    learner_id: str
    profile: LearnerProfile

class GenerateRequest(BaseModel):
    learner_id: str
    resource_types: list[ResourceType] = Field(
        default=[ResourceType.LECTURE, ResourceType.GUIDE, ResourceType.QUIZ]
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
    generated_resources: list[GeneratedResource] = Field(default_factory=list)
    debate_records: list[DebateRecord] = Field(default_factory=list)
    error_message: Optional[str] = None

class ReportResponse(BaseModel):
    learner_id: str
    profile: LearnerProfile
    knowledge_radar: dict[str, float] = Field(default_factory=dict)
    skill_gap_analysis: list[SkillGap]
    resource_match_curve: list[dict] = Field(default_factory=list)
    learning_path: Optional[LearningPath] = None
    generated_at: datetime = Field(default_factory=datetime.now)


# ============================================================
# WebSocket消息
# ============================================================

class WSMessage(BaseModel):
    task_id: str
    timestamp: datetime = Field(default_factory=datetime.now)
    agent_name: str
    agent_state: str  # idle / thinking / acting / done / error
    message: str
    data: Optional[dict] = None

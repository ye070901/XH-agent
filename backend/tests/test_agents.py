"""多Agent协同逻辑单元测试"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


# ═══════════════════════════════════════════
# Agent Prompt测试（不需要真实LLM调用）
# ═══════════════════════════════════════════

class TestDiagnosisAgent:
    """学情诊断Agent"""

    def test_prompt_format(self):
        """验证Prompt构建包含必要字段"""
        from app.agents.diagnosis import DiagnosisAgent
        agent = DiagnosisAgent()
        data = {
            "education_level": "本科",
            "major": "机械工程",
            "school": "XX大学",
            "work_years": 2,
            "industry": "智能制造",
            "positions": ["PLC工程师"],
            "skills_used": ["PLC编程", "CAD"],
            "pretest_results": [],
            "learning_goal": "学习工业视觉",
        }
        prompt = agent._build_prompt(data)
        assert "本科" in prompt
        assert "机械工程" in prompt
        assert "智能制造" in prompt
        assert "PLC编程" in prompt
        assert "工业视觉" in prompt

    def test_format_pretests_empty(self):
        from app.agents.diagnosis import DiagnosisAgent
        agent = DiagnosisAgent()
        result = agent._format_pretests([])
        assert "无前置测试" in result


class TestGeneratorAgent:
    """领域知识生成Agent"""

    def test_prompt_includes_chunks(self):
        from app.agents.generator import GeneratorAgent
        agent = GeneratorAgent()
        diagnosis = {"skill_gaps": [], "recommended_difficulty": "beginner"}
        chunks = [{"doc_title": "PLC手册", "content": "PLC安全操作规程..."}]
        prompt = agent._build_prompt(diagnosis, chunks, "lecture")
        assert "PLC手册" in prompt
        assert "lecture" in prompt
        assert "beginner" in prompt

    def test_prompt_no_chunks(self):
        from app.agents.generator import GeneratorAgent
        agent = GeneratorAgent()
        prompt = agent._build_prompt({}, [], "guide")
        assert "无检索结果" in prompt


class TestReviewerAgent:
    """审核裁判Agent"""

    def test_prompt_structure(self):
        from app.agents.reviewer import ReviewerAgent
        agent = ReviewerAgent()
        resource = {"title": "测试", "content": "测试内容"}
        chunks = []
        diagnosis = {}
        prompt = agent._build_prompt(resource, chunks, diagnosis)
        assert "fact_check" in prompt
        assert "compliance_check" in prompt
        assert "hallucination_flags" in prompt
        assert "verdict" in prompt


# ═══════════════════════════════════════════
# 辩论引擎测试
# ═══════════════════════════════════════════

class TestDebateEngine:
    """辩论与交叉验证引擎"""

    def test_approved_skips_debate(self):
        """审核通过时跳过辩论"""
        from app.debate.engine import DebateEngine
        engine = DebateEngine()
        result = engine.run_debate(
            resource={"title": "测试"},
            audit_report={"verdict": "approved"},
            knowledge_chunks=[],
        )
        assert result["debate_needed"] is False
        assert result["final_verdict"] == "approved"
        assert len(result["rounds"]) == 0

    def test_rejected_triggers_debate(self):
        """审核不通过时触发辩论"""
        from app.debate.engine import DebateEngine
        engine = DebateEngine()
        result = engine.run_debate(
            resource={"title": "测试"},
            audit_report={"verdict": "needs_revision", "hallucination_flags": []},
            knowledge_chunks=[],
        )
        assert result["debate_needed"] is True
        assert len(result["rounds"]) > 0


# ═══════════════════════════════════════════
# 工作流测试
# ═══════════════════════════════════════════

class TestWorkflow:
    """LangGraph工作流"""

    def test_sequential_run(self):
        """无LangGraph时顺序执行也能完成"""
        from app.workflow.graph import AgentWorkflow
        workflow = AgentWorkflow()
        result = workflow.run(
            task_id="test-001",
            learner_data={
                "education_level": "本科",
                "major": "计算机科学",
                "work_years": 0,
                "pretest_results": [],
                "learning_goal": "学习Python",
            },
        )
        assert result["status"] == "completed"
        assert "final_resources" in result

    def test_should_debate_approved(self):
        from app.workflow.graph import AgentWorkflow
        workflow = AgentWorkflow()
        state = {"audit_reports": [{"verdict": "approved"}]}
        assert workflow._should_debate(state) == "plan"

    def test_should_debate_rejected(self):
        from app.workflow.graph import AgentWorkflow
        workflow = AgentWorkflow()
        state = {"audit_reports": [{"verdict": "needs_revision"}]}
        assert workflow._should_debate(state) == "debate"


# ═══════════════════════════════════════════
# 知识库测试
# ═══════════════════════════════════════════

class TestKnowledgeBase:
    """RAG知识库"""

    @pytest.mark.asyncio
    async def test_chunk_text(self):
        from app.knowledge.rag import KnowledgeBase
        kb = KnowledgeBase()
        text = "第一段内容。\n\n第二段内容。\n\n第三段很长的内容" + "测试" * 100
        chunks = kb._chunk_text(text)
        assert len(chunks) > 0
        for chunk in chunks:
            assert isinstance(chunk, str)

    @pytest.mark.asyncio
    async def test_add_document(self):
        from app.knowledge.rag import KnowledgeBase
        kb = KnowledgeBase()
        chunks = await kb.add_document(
            doc_id="test-001",
            title="测试文档",
            content="这是一段测试内容，用于验证知识库的文档添加功能。",
        )
        assert len(chunks) > 0


# ═══════════════════════════════════════════
# Schema测试
# ═══════════════════════════════════════════

class TestSchemas:
    """Pydantic Schema校验"""

    def test_learner_profile_schema(self):
        # 导入项目根目录的schemas.py
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from schemas import LearnerProfile, Education, WorkExperience, EducationLevel, LearningStyle, Difficulty

        profile = LearnerProfile(
            learner_id="L001",
            name="测试用户",
            education=Education(level=EducationLevel.BACHELOR, major="计算机科学"),
            experience=WorkExperience(years=0),
            learning_style=LearningStyle.PRACTICE_FIRST,
            recommended_difficulty=Difficulty.BEGINNER,
        )
        assert profile.learner_id == "L001"
        assert profile.education.level == EducationLevel.BACHELOR
        assert profile.experience.years == 0

    def test_audit_report_schema(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from schemas import AuditReport, FactCheckResult, ComplianceResult, DifficultyMatchResult, AuditVerdict, Difficulty

        report = AuditReport(
            resource_id="R001",
            is_approved=True,
            verdict=AuditVerdict.APPROVED,
            fact_check=FactCheckResult(overall_accuracy=0.95),
            compliance_check=ComplianceResult(is_compliant=True),
            difficulty_match=DifficultyMatchResult(
                is_match=True,
                learner_level=Difficulty.BEGINNER,
                resource_level=Difficulty.BEGINNER,
                score=1.0,
            ),
            knowledge_coverage=0.9,
            confidence_score=0.95,
        )
        assert report.verdict == AuditVerdict.APPROVED
        assert report.fact_check.overall_accuracy == 0.95

    def test_feedback_decision_schema(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from schemas import FeedbackDecision, QuizResult, FeedbackAction

        decision = FeedbackDecision(
            learner_id="L001",
            resource_id="R001",
            quiz_result=QuizResult(
                submission_id="S001",
                total_score=70,
                max_score=100,
                correct_rate=0.7,
                time_spent_total=600,
            ),
            action=FeedbackAction.CONTINUE,
            reason="学习效果良好",
        )
        assert decision.action == FeedbackAction.CONTINUE
        assert decision.quiz_result.correct_rate == 0.7

"""接口契约单元测试 — 每人写完代码后跑这个，确认自己的 Agent 没问题"""
import pytest


class TestAgentDiagnosis:
    """角色4 的测试"""

    async def test_process_returns_diagnosis(self):
        from src.agents.diagnosis import DiagnosisAgent
        agent = DiagnosisAgent()
        state = {
            "learner_data": {
                "education_level": "bachelor",
                "major": "计算机科学",
                "school": "测试大学",
                "work_years": 0,
                "industry": "IT",
                "positions": [],
                "skills_used": [],
                "pretest_results": [],
                "learning_goal": "学习 LangGraph",
            }
        }
        result = await agent.process(state)
        assert "diagnosis_result" in result
        assert "diagnosis_completed" in result
        assert result["diagnosis_completed"] is True


class TestAgentGeneration:
    """角色5 的测试"""

    async def test_process_returns_resources(self):
        from src.agents.generation import GenerationAgent
        agent = GenerationAgent()
        state = {
            "diagnosis_result": {
                "skill_gaps": [
                    {"topic": "LangGraph", "priority": "critical",
                     "current_level": 0.2, "target_level": 0.8, "reason": "未学过"}
                ],
                "recommended_difficulty": "beginner",
                "learning_style": "practice_first",
            },
            "retrieved_chunks": [
                {"doc_id": "test", "doc_title": "Test Doc",
                 "chunk_index": 0, "content": "LangGraph is a library for building stateful agents."}
            ],
            "resource_types": ["lecture"],
        }
        result = await agent.process(state)
        assert "generated_resources" in result
        assert len(result["generated_resources"]) > 0


class TestAgentAudit:
    """角色6+7 的测试"""

    async def test_process_returns_audit(self):
        from src.agents.audit import AuditAgent
        agent = AuditAgent()
        state = {
            "generated_resources": [{
                "resource_id": "test-1",
                "resource_type": "lecture",
                "title": "测试资源",
                "content": "# Test\n\nLangGraph uses StateGraph to define workflows. [ref:1]",
                "citations": [{"ref_index": 1, "original_text": "StateGraph is the core abstraction.", "usage": "正文第一段"}],
                "difficulty_level": "beginner",
                "target_skill_gaps": ["LangGraph"],
            }],
            "retrieved_chunks": [
                {"doc_id": "test", "doc_title": "Test Doc",
                 "chunk_index": 0, "content": "StateGraph is the core abstraction in LangGraph."}
            ],
            "diagnosis_result": {
                "recommended_difficulty": "beginner",
                "learning_style": "practice_first",
                "skill_gaps": [{"topic": "LangGraph", "current_level": 0.2, "target_level": 0.8, "priority": "critical", "reason": "未学过"}],
            },
        }
        result = await agent.process(state)
        assert "audit_reports" in result
        assert len(result["audit_reports"]) > 0


class TestSchemas:
    """数据模型测试"""

    def test_learner_profile_creation(self):
        from src.schemas import LearnerProfile, Education, WorkExperience, LearningStyle, Difficulty
        edu = Education(level="bachelor", major="CS")
        exp = WorkExperience(years=2, industry="IT", positions=["Developer"])
        profile = LearnerProfile(
            learner_id="test-1",
            name="测试用户",
            education=edu,
            experience=exp,
            learning_style=LearningStyle.PRACTICE_FIRST,
            recommended_difficulty=Difficulty.BEGINNER,
        )
        assert profile.learner_id == "test-1"

    def test_generated_resource_citations_required(self):
        from src.schemas import GeneratedResource, ResourceType, Difficulty
        # citations 为空数组应被允许创建，但 Agent 2 不应这样做
        resource = GeneratedResource(
            resource_id="r-1",
            learner_id="l-1",
            resource_type=ResourceType.LECTURE,
            title="test",
            content="test",
            citations=[],
            difficulty_level=Difficulty.BEGINNER,
            target_skill_gaps=["topic1"],
        )
        assert resource.citations == []
        # Agent 3 应标记此情况为 critical flag（由 Agent 3 的测试覆盖）

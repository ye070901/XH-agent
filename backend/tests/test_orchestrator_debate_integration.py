"""编排器接入博弈引擎 + 追问重生成 的集成测试。

对应 PHASE3_PLAN.md §4.1（Arch-L 交付标准）：
  1. 博弈引擎接入流水线：Agent3 三态断言 → 争议断言进 debate → 裁决结果回写资源
  2. 追问流程接入：反馈 → 触发资源重生成（regenerate 调度入口）

覆盖三处接入点：
  - AgentWorkflow.debate 属性 → 真实 debate_engine 单例
  - AgentWorkflow._generate_and_refine → 产出 state["debate_result"]
  - AgentWorkflow.regenerate → 反馈（答错降维/答对进阶）后重跑生成链
  - PipelineScheduler._run_debate → 占位替换为真实引擎调用，回写 state

运行方式（在仓库根目录）:
    .venv/Scripts/python.exe -m pytest backend/tests/test_orchestrator_debate_integration.py -v
"""

from __future__ import annotations

import backend.src.scheduler.pipeline as pipeline_module
from backend.src.graph.orchestrator import AgentWorkflow, debate_engine
from backend.src.scheduler.pipeline import PipelineScheduler


class _FakeAgent:
    """最小化 Agent 替身：run() 把固定结果合并回 state 并返回。"""

    def __init__(self, result: dict):
        self._result = result

    async def run(self, state: dict) -> dict:
        state.update(self._result)
        return self._result


def _resource(resource_id: str = "res-1") -> dict:
    return {
        "resource_id": resource_id,
        "resource_type": "lecture",
        "title": "测试资源",
        "content": "错误的断言内容。",
        "difficulty_level": "beginner",
    }


def _audit_report(items: list[dict]) -> dict:
    """构造单资源审核报告（对齐 audit.py 的 _build_report 输出形状）。"""
    return {
        "resource_index": 0,
        "resource_type": "lecture",
        "title": "测试资源",
        "fact_check": {"items": items},
    }


def test_workflow_debate_property_is_engine():
    """debate 属性暴露真实博弈引擎单例（Opt-2 交付物）。"""
    workflow = AgentWorkflow()
    assert workflow.debate is debate_engine


async def test_generate_and_refine_writes_debate_result():
    """生成 → 审核 → 博弈 → 修正：三态断言裁决结果回写 state["debate_result"]。"""
    workflow = AgentWorkflow()
    res = _resource()
    workflow._generation = _FakeAgent({"generated_resources": [res], "status": "done"})
    workflow._audit = _FakeAgent(
        {
            "audit_result": [
                _audit_report(
                    [
                        {
                            "claim": "正确的断言",
                            "verdict": "accurate",
                            "evidence_from_kb": "原文A",
                            "authority_level": "A",
                        },
                        {
                            "claim": "错误的断言",
                            "verdict": "hallucination",
                            "evidence_from_kb": "KB原文",
                            "authority_level": "A",
                        },
                        {"claim": "无法验证的断言", "verdict": "unverifiable"},
                    ]
                )
            ],
            "status": "done",
        }
    )
    workflow._correction = _FakeAgent(
        {
            "corrected_resources": [res],
            "correction_log": [],
            "correction_stats": {},
            "status": "done",
        }
    )

    state = {
        "diagnosis_result": {"recommended_difficulty": "beginner", "skill_gaps": []},
        "resource_types": ["lecture"],
        "agent_log": [],
    }
    await workflow._generate_and_refine(state)

    debate_result = state["debate_result"]
    by_claim = {a["claim"]: a["decision"] for a in debate_result["adjudications"]}
    assert by_claim["正确的断言"] == "keep"
    assert by_claim["错误的断言"] == "replace"
    assert by_claim["无法验证的断言"] == "delete"  # 未覆盖 → 删除（D1）
    # resource_id 从 generated_resources 映射回写，供 correction 落地裁决
    assert debate_result["adjudications"][0]["resource_id"] == "res-1"
    # agent_log 记录 debate 环节
    assert any(e.get("agent") == "debate" for e in state["agent_log"])


async def test_regenerate_applies_feedback_and_reruns():
    """追问流程接入：反馈（答对→进阶 + 收窄 hint）后重跑生成链。"""
    workflow = AgentWorkflow()
    captured: dict = {}

    class _RecordingGeneration:
        async def run(self, state: dict) -> dict:
            captured["difficulty"] = state["diagnosis_result"].get("recommended_difficulty")
            captured["summary"] = state["diagnosis_result"].get("summary", "")
            result = {"generated_resources": [_resource()], "status": "done"}
            state.update(result)
            return result

    workflow._generation = _RecordingGeneration()
    workflow._audit = _FakeAgent({"audit_result": [_audit_report([])], "status": "done"})
    workflow._correction = _FakeAgent(
        {
            "corrected_resources": [_resource()],
            "correction_log": [],
            "correction_stats": {},
            "status": "done",
        }
    )

    state = {
        "diagnosis_result": {
            "recommended_difficulty": "intermediate",
            "summary": "学习 FANUC 示教器编程",
        },
        "resource_types": ["lecture"],
        "retrieved_chunks": [],
        "agent_log": [],
    }
    await workflow.regenerate(state, {"action": "advance", "hint": "点位示教"})

    assert captured["difficulty"] == "advanced"
    assert "点位示教" in captured["summary"]
    assert state["status"] == "completed"
    assert "debate_result" in state


async def test_regenerate_simplify_lowers_difficulty():
    """答错 → 降维解释（D8）：simplify 反馈把推荐难度降为 beginner。"""
    workflow = AgentWorkflow()
    captured: dict = {}

    class _RecordingGeneration:
        async def run(self, state: dict) -> dict:
            captured["difficulty"] = state["diagnosis_result"].get("recommended_difficulty")
            result = {"generated_resources": [_resource()], "status": "done"}
            state.update(result)
            return result

    workflow._generation = _RecordingGeneration()
    workflow._audit = _FakeAgent({"audit_result": [_audit_report([])], "status": "done"})
    workflow._correction = _FakeAgent(
        {"corrected_resources": [_resource()], "correction_log": [], "correction_stats": {}}
    )

    state = {
        "diagnosis_result": {"recommended_difficulty": "advanced"},
        "resource_types": ["lecture"],
        "retrieved_chunks": [],
        "agent_log": [],
    }
    await workflow.regenerate(state, {"action": "simplify"})

    assert captured["difficulty"] == "beginner"


async def test_run_full_chain_includes_debate(monkeypatch):
    """run() 全链路：诊断 → 检索 → 生成 → 审核 → 博弈 → 修正，产出 debate_result。"""
    workflow = AgentWorkflow()
    res = _resource()

    class _RecordingDiagnosis:
        async def run(self, state: dict) -> dict:
            result = {
                "diagnosis_result": {
                    "summary": "学习示教器",
                    "recommended_difficulty": "beginner",
                    "learning_style": "practice_first",
                    "skill_gaps": [{"priority": "critical", "topic": "点位示教"}],
                },
                "status": "done",
            }
            state.update(result)
            return result

    async def _no_retrieve(learner_data, diagnosis, resource_types=None):
        return []

    workflow._diagnosis = _RecordingDiagnosis()
    workflow._generation = _FakeAgent({"generated_resources": [res], "status": "done"})
    workflow._audit = _FakeAgent(
        {
            "audit_result": [
                _audit_report(
                    [
                        {
                            "claim": "错误断言",
                            "verdict": "hallucination",
                            "evidence_from_kb": "KB原文",
                            "authority_level": "A",
                        }
                    ]
                )
            ],
            "status": "done",
        }
    )
    workflow._correction = _FakeAgent(
        {
            "corrected_resources": [res],
            "correction_log": [],
            "correction_stats": {},
            "status": "done",
        }
    )
    monkeypatch.setattr(workflow, "_retrieve_knowledge", _no_retrieve)

    result = await workflow.run(
        learner_data={"learning_goal": "学机器人"},
        resource_types=["lecture"],
    )

    assert result["status"] == "completed"
    assert "debate_result" in result
    assert result["debate_result"]["adjudications"][0]["decision"] == "replace"


async def test_pipeline_run_debate_sets_state(monkeypatch):
    """Scheduler._run_debate：占位替换为真实引擎调用，回写 state 且返回原对象。"""

    class _FakeBus:
        async def broadcast(self, task_id, event_type, data):
            return None

    monkeypatch.setattr(pipeline_module, "event_bus", _FakeBus())

    scheduler = PipelineScheduler()
    state = {
        "audit_result": [
            _audit_report(
                [
                    {
                        "claim": "错误断言",
                        "verdict": "hallucination",
                        "evidence_from_kb": "KB原文",
                        "authority_level": "A",
                    }
                ]
            )
        ],
        "generated_resources": [_resource("res-9")],
    }
    returned = await scheduler._run_debate(state, "task-test-1")

    assert returned is state  # 必须返回原 state 对象（引用语义，避免修正结果丢失）
    assert "debate_result" in state
    assert state["debate_result"]["adjudications"][0]["decision"] == "replace"
    assert state["debate_result"]["adjudications"][0]["resource_id"] == "res-9"

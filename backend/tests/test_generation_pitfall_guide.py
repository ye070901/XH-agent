"""三期-1 新手避坑指南（pitfall_guide）回归测试。

覆盖 generation_v2 新增的 pitfall_guide 确定性规则（不调 LLM）：
  1. _classify_risk_level：pitfall_guide 恒为 theory（即便正文含运动词「示教」）。
  2. _structure_validation_failure：
     - 缺「常见误区」→ fail；缺「规避/正确做法」→ fail；齐 → pass。
     - 品牌锚定：pitfall_guide 也须声明品牌或「通用原理」。
     - 品牌混淆：声明 FANUC + 使用 KRL → 仍判定混淆（复用二期-1 词表）。
  3. 端到端 process()：合格 pitfall_guide → 保留且 risk_level == "theory"；
     缺规避 → 丢弃并记录 structure_validation 错误。

关键约束：全部确定性规则，不调真实 LLM。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from src.agents.generation_v2 import GenerationAgent

ROBOT_TOPIC = "学习工业机器人示教器操作与安全"


def _agent_with(mock_result: dict) -> GenerationAgent:
    agent = GenerationAgent()
    agent.call_llm_json = AsyncMock(side_effect=lambda *a, **k: dict(mock_result))
    return agent


def _run_state(agent: GenerationAgent, resource_types: list[str]) -> dict:
    return asyncio.run(
        agent.run(
            {
                "learner_data": {"learning_goal": ROBOT_TOPIC},
                "diagnosis_result": {
                    "recommended_difficulty": "intermediate",
                    "learning_style": "project_based",
                },
                "retrieved_chunks": [],
                "resource_types": resource_types,
            }
        )
    )


def _structure(result: dict) -> list[str]:
    return GenerationAgent._structure_validation_failure(result, "pitfall_guide", "intermediate")


# ═══════════════════════════════════════════════════════════
# _classify_risk_level：避坑指南恒 theory
# ═══════════════════════════════════════════════════════════


def test_classify_risk_level_pitfall_guide_theory() -> None:
    # 「示教」是运动类高危标记，但避坑指南属「查/警示」类，应恒为 theory
    assert GenerationAgent._classify_risk_level("pitfall_guide", "跳过示教前的安全确认") == "theory"


# ═══════════════════════════════════════════════════════════
# _structure_validation_failure：避坑三要素 + 品牌锚定/混淆
# ═══════════════════════════════════════════════════════════


def test_structure_validation_pitfall_missing_pitfall() -> None:
    result = {
        "title": "FANUC 新手避坑指南",
        "content": "# FANUC 新手避坑指南\n\n## 规避方法\n- 操作前确认安全\n",
    }
    failures = _structure(result)
    assert any("常见误区" in f for f in failures)


def test_structure_validation_pitfall_missing_avoidance() -> None:
    result = {
        "title": "FANUC 新手避坑指南",
        "content": "# FANUC 新手避坑指南\n\n## 常见误区\n- 跳过安全确认\n",
    }
    failures = _structure(result)
    assert any("规避" in f for f in failures)


def test_structure_validation_pitfall_complete_passes() -> None:
    result = {
        "title": "FANUC 新手避坑指南",
        "content": (
            "# FANUC 新手避坑指南\n\n"
            "## 常见误区\n- 跳过安全确认直接示教\n\n"
            "## 原因\n- 忽视急停流程，安全意识不足\n\n"
            "## 后果\n- 误触机械臂造成伤害\n\n"
            "## 规避方法\n- 操作前完成安全确认清单\n"
        ),
    }
    assert _structure(result) == []


def test_structure_validation_pitfall_missing_cause() -> None:
    result = {
        "title": "FANUC 新手避坑指南",
        "content": (
            "# FANUC 新手避坑指南\n\n"
            "## 常见误区\n- 跳过安全确认直接示教\n\n"
            "## 后果\n- 误触机械臂造成伤害\n\n"
            "## 规避方法\n- 操作前完成安全确认清单\n"
        ),
    }
    failures = _structure(result)
    assert any("原因" in f for f in failures)


def test_structure_validation_pitfall_brand_anchor() -> None:
    # 缺品牌声明且无「通用原理」→ 品牌锚定失败
    result = {
        "title": "新手避坑指南",
        "content": "# 新手避坑指南\n\n## 常见误区\n- 跳过安全确认\n\n## 规避方法\n- 操作前确认\n",
    }
    failures = _structure(result)
    assert any("品牌" in f for f in failures)


def test_structure_validation_pitfall_brand_confusion() -> None:
    # 声明 FANUC 但使用 KUKA 专属术语 KRL → 品牌混淆仍生效
    result = {
        "title": "FANUC 新手避坑指南",
        "content": (
            "# FANUC 新手避坑指南\n\n"
            "## 常见误区\n- 误用 KRL 编写 FANUC 程序\n\n"
            "## 规避方法\n- 按对应品牌手册编程\n"
        ),
    }
    failures = _structure(result)
    assert any("品牌混淆" in f for f in failures)


# ═══════════════════════════════════════════════════════════
# 端到端：process() 保留合格避坑指南 / 丢弃缺规避的
# ═══════════════════════════════════════════════════════════


def test_process_keeps_complete_pitfall_guide() -> None:
    ok = {
        "title": "FANUC 新手避坑指南",
        "content": (
            "# FANUC 新手避坑指南\n\n"
            "## 常见误区\n- 跳过安全确认直接示教\n\n"
            "## 原因\n- 忽视急停流程，安全意识不足\n\n"
            "## 后果\n- 误触机械臂造成伤害\n\n"
            "## 规避方法\n- 操作前完成安全确认清单\n"
        ),
        "citations": [],
        "difficulty_level": "intermediate",
        "estimated_duration_minutes": 20,
        "key_takeaways": ["掌握避坑要点"],
    }
    state = _run_state(_agent_with(ok), ["pitfall_guide"])
    assert state["generated_resources"]
    resource = state["generated_resources"][0]
    assert resource["resource_type"] == "pitfall_guide"
    assert resource["risk_level"] == "theory"


def test_process_drops_pitfall_guide_missing_avoidance() -> None:
    no_avoid = {
        "title": "FANUC 新手避坑指南",
        "content": ("# FANUC 新手避坑指南\n\n## 常见误区\n- 跳过安全确认直接示教\n"),
        "citations": [],
        "difficulty_level": "intermediate",
        "estimated_duration_minutes": 20,
        "key_takeaways": ["掌握避坑要点"],
    }
    state = _run_state(_agent_with(no_avoid), ["pitfall_guide"])
    assert state["generated_resources"] == []
    assert any(e.get("error") == "structure_validation" for e in state.get("generation_errors", []))

"""修正 Agent 补全 guide 缺失结构章节的回归测试。

覆盖两层行为：
  1. correction._fill_structure_sections（方法级）：基于知识库素材调用 LLM 补全缺失章节，
     成功移除 structure_missing_sections 并打 _structure_sections_filled 标记；
     失败原样返回（保留 structure_missing_sections，供 process() 判定）。
  2. correction.process（流程级）：补全失败 → guide 从 corrected_resources 丢弃，
     generation_errors 由 structure_sections_missing 回退为 structure_validation；
     补全成功 → guide 保留并移除该告警。
全部 mock call_llm_json，不调真实 LLM。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from src.agents.correction import CorrectionAgent


def _agent_with(filled_content: str | None) -> CorrectionAgent:
    agent = CorrectionAgent()
    if filled_content is None:
        agent.call_llm_json = AsyncMock(return_value={"_parse_error": "parse failed"})
    else:
        agent.call_llm_json = AsyncMock(return_value={"content": filled_content})
    return agent


def _incomplete_guide() -> dict:
    return {
        "resource_id": "r1",
        "resource_type": "guide",
        "title": "FANUC 示教器操作指南",
        "content": "# FANUC 示教器操作指南\n\n## 操作步骤\n1. 进入手动模式\n",
        "structure_missing_sections": ["guide 缺少独立「安全」标题章节"],
    }


def test_fill_structure_sections_success() -> None:
    agent = _agent_with("# FANUC 示教器操作指南\n\n## 安全\n\n## 操作步骤\n1. 进入手动模式\n")
    resource = _incomplete_guide()
    filled = asyncio.run(
        agent._fill_structure_sections(resource, resource["structure_missing_sections"], {}, [])
    )
    assert filled["content"].startswith("# FANUC 示教器操作指南")
    assert "structure_missing_sections" not in filled
    assert filled.get("_structure_sections_filled") is True


def test_fill_structure_sections_fallback_keeps_original() -> None:
    # 补全失败（LLM 解析失败）→ 原样返回，保留 structure_missing_sections 供 process() 判定
    agent = _agent_with(None)
    resource = _incomplete_guide()
    filled = asyncio.run(
        agent._fill_structure_sections(resource, resource["structure_missing_sections"], {}, [])
    )
    assert filled is resource
    assert filled.get("structure_missing_sections")


# ═══════════════════════════════════════════════════════════
# 流程级 process()：补全失败丢弃 / 补全成功移除告警
# ═══════════════════════════════════════════════════════════

_STRUCTURE_MISSING_ERR = {
    "resource_type": "guide",
    "error": "structure_sections_missing",
    "detail": "guide 缺少独立「安全」标题章节",
}


def _state_with(
    guide: dict, generation_errors: list[dict], *, downgrade_mode: bool = False
) -> dict:
    return {
        "generated_resources": [guide],
        "audit_result": [],
        "retrieved_chunks": [],
        "diagnosis_result": {},
        "learner_data": {},
        "generation_errors": generation_errors,
        "downgrade_mode": downgrade_mode,
    }


def test_process_fill_failure_drops_guide_and_upgrades_error() -> None:
    # 补全失败 → guide 从 corrected_resources 丢弃，generation_errors 回退为 structure_validation
    agent = _agent_with(None)
    state = _state_with(_incomplete_guide(), [_STRUCTURE_MISSING_ERR])
    result = asyncio.run(agent.process(state))
    assert result["corrected_resources"] == []
    assert result["generation_errors"] == [
        {
            "resource_type": "guide",
            "error": "structure_validation",
            "detail": "guide 缺少独立「安全」标题章节",
        }
    ]


def test_process_fill_success_keeps_guide_and_removes_warning() -> None:
    # 补全成功 → guide 保留，structure_sections_missing 告警被移除
    agent = _agent_with("# FANUC 示教器操作指南\n\n## 安全\n\n## 操作步骤\n1. 进入手动模式\n")
    state = _state_with(_incomplete_guide(), [_STRUCTURE_MISSING_ERR], downgrade_mode=True)
    result = asyncio.run(agent.process(state))
    assert len(result["corrected_resources"]) == 1
    assert "structure_missing_sections" not in result["corrected_resources"][0]
    assert result["generation_errors"] == []

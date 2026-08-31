"""修正 Agent 补全 guide 缺失结构章节的回归测试。

覆盖 correction._fill_structure_sections：基于知识库素材调用 LLM 补全缺失章节，
补全成功移除 structure_missing_sections 并打 _structure_sections_filled 标记；
补全失败原样返回（保留原始输出，不因补全失败丢资源）。全部 mock call_llm_json，不调真实 LLM。
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
    # 补全失败（LLM 解析失败）→ 原样返回，保留 structure_missing_sections 供前端感知
    agent = _agent_with(None)
    resource = _incomplete_guide()
    filled = asyncio.run(
        agent._fill_structure_sections(resource, resource["structure_missing_sections"], {}, [])
    )
    assert filled is resource
    assert filled.get("structure_missing_sections")

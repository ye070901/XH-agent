"""生成链「空知识库」降级行为测试（方案 1：检索层注入人工预置兜底块）。

验证 `AgentWorkflow._retrieve_knowledge` 的双分支：
- 演示模式（is_demo_mode=True）：空 query / 检索空库 → 注入预置演示知识块，
  生成 Agent 据此照常生成，护栏不绕过、不凭空生成。
- 正式模式（is_demo_mode=False）：空 query → 返回空列表，保留生成 Agent 的
  `no_knowledge_base_chunks` 硬拦截，知识库无素材绝不生成。
"""

from __future__ import annotations

import pytest

from backend.src.graph import orchestrator as orchestrator_module
from backend.src.graph.orchestrator import AgentWorkflow


def _set_demo_mode(monkeypatch: pytest.MonkeyPatch, on: bool) -> None:
    """切换演示模式：LLM_API_KEY 为空 → is_demo_mode=True。"""
    monkeypatch.setattr(orchestrator_module.settings, "LLM_API_KEY", "" if on else "sk-test-123")


async def test_demo_mode_empty_query_injects_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_demo_mode(monkeypatch, on=True)
    workflow = AgentWorkflow()

    chunks = await workflow._retrieve_knowledge({}, {})

    assert chunks
    assert all(chunk["content"].strip() for chunk in chunks)
    # 兜底块来自真实文档：doc_id 指向原文件，source_level 记录权威等级 A
    assert chunks[0]["doc_id"]
    assert chunks[0]["source_level"] == "A"


async def test_demo_mode_empty_search_injects_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_demo_mode(monkeypatch, on=True)

    async def _empty_search(query: str, top_k: int = 10) -> list[dict]:
        return []

    monkeypatch.setattr(orchestrator_module.knowledge_base, "search", _empty_search)
    workflow = AgentWorkflow()

    chunks = await workflow._retrieve_knowledge(
        {"learning_goal": "安全操作"}, {"skill_gaps": [{"topic": "急停"}]}
    )

    assert chunks
    assert all(chunk["content"].strip() for chunk in chunks)


async def test_prod_mode_empty_query_stays_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_demo_mode(monkeypatch, on=False)
    workflow = AgentWorkflow()

    chunks = await workflow._retrieve_knowledge({}, {})

    assert chunks == []

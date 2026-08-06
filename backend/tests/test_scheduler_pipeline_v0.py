"""Scheduler v0.1 全链路测试 — Day 5。

两条路径：
  路径 1：正常结束（全 PASS，终态 DONE）
  路径 2：RecallGate FALLBACK（RAG 无召回 → 3次 RETRY → FALLBACK → DONE）

Run:
    cd backend && python -m pytest tests/test_scheduler_pipeline_v0.py -v -s
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 插入项目根目录 (XH-agent)，使 backend.src.* 导入可解析
_project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_project_root))

import pytest
from backend.src.scheduler.pipeline_v0 import (
    PipelineSchedulerV0,
    _build_default_steps,
    make_initial_state,
)
from backend.src.schemas import PipelineState


# ═══════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════


async def _mock_rag_search_empty(state: dict) -> dict:
    """覆盖 RAG 检索：始终返回空列表（用于测试 FALLBACK 路径）。"""
    state["retrieved_chunks"] = []
    state["rag_query"] = state.get("rag_query", "test query")
    return {"verdict": "PASS"}


async def _mock_rag_search_with_results(state: dict) -> dict:
    """覆盖 RAG 检索：始终返回 3 条模拟文档（用于测试正常路径）。"""
    query = state.get("rag_query", "test query")
    # 如果 RecallGate 返回了改写 query，用它
    recall_results = state.get("gate_results", {}).get("RAG召回质量检测 v0.1", {})
    new_query = recall_results.get("details", {}).get("new_query", "")
    if new_query:
        query = new_query
        state["_pending_query"] = new_query

    state["retrieved_chunks"] = [
        {
            "doc_id": "mock_001",
            "doc_title": "FANUC SRVO-068 故障处理指南",
            "chunk_index": 0,
            "content": f"SRVO-068 是伺服放大器报警...查询词: {query[:30]}",
            "relevance_score": 0.92,
        },
        {
            "doc_id": "mock_002",
            "doc_title": "FANUC 常见故障排查",
            "chunk_index": 0,
            "content": "机器人故障排查步骤...",
            "relevance_score": 0.85,
        },
        {
            "doc_id": "mock_003",
            "doc_title": "工业机器人安全操作",
            "chunk_index": 1,
            "content": "安全门、急停装置...",
            "relevance_score": 0.78,
        },
    ]
    return {"verdict": "PASS"}


# ═══════════════════════════════════════════════════════════
# 测试
# ═══════════════════════════════════════════════════════════


class TestPipelineNormal:
    """路径 1：正常全 PASS。"""

    async def test_normal_completion(self):
        """所有步骤 PASS → 终态 DONE + final_output 含 diagnosis。"""
        state = make_initial_state(
            learning_goal="FANUC 机器人 SRVO-068 故障处理",
            major="自动化",
        )
        scheduler = PipelineSchedulerV0()
        steps = _build_default_steps()
        # 替换 RAG_search 为返回模拟结果的版本
        steps[4] = ("RAG_search(mock_results)", _mock_rag_search_with_results, -1)

        result = await scheduler.run(state, steps=steps)

        assert result["pipeline_state"] == PipelineState.DONE.value, (
            f"Expected DONE, got {result['pipeline_state']}"
        )
        fo = result.get("final_output", {})
        assert fo.get("status") == "ok", f"Expected ok, got {fo}"
        assert "diagnosis" in fo
        assert fo["diagnosis"]["confidence"] > 0.6
        print(f"\n  [OK] Normal pipeline: {fo}")


class TestPipelineFallback:
    """路径 2：RAG 无召回 → RecallGate FALLBACK。"""

    async def test_recall_fallback_path(self):
        """RAG 始终空 → 3 次 RETRY 后 FALLBACK → DONE。"""
        state = make_initial_state(
            learning_goal="FANUC 机器人 SRVO-068 故障处理",
            major="自动化",
        )
        scheduler = PipelineSchedulerV0()

        # 构建自定义 steps：将 RAG_search 替换为始终返回空的 mock
        steps = _build_default_steps()
        # 替换 index 4: RAG_search
        steps[4] = ("RAG_search(mock_empty)", _mock_rag_search_empty, -1)

        result = await scheduler.run(state, steps=steps)

        assert result["pipeline_state"] == PipelineState.DONE.value, (
            f"Expected DONE, got {result['pipeline_state']}"
        )
        # 应走 FALLBACK 路径
        assert result.get("_is_fallback") is True, "Expected _is_fallback=True"
        fo = result.get("final_output", {})
        assert fo.get("status") == "fallback", f"Expected fallback status, got {fo}"
        print(f"\n  [OK] Fallback pipeline: {fo}")


# ═══════════════════════════════════════════════════════════
# 手动运行入口
# ═══════════════════════════════════════════════════════════


async def _run_standalone():
    """直接 python 运行时的测试入口。"""
    print("=" * 60)
    print("  Day 5: Scheduler v0.1 Pipeline Tests")
    print("=" * 60)

    test_normal = TestPipelineNormal()
    test_fallback = TestPipelineFallback()

    try:
        print("\n--- Test 1: Normal Completion ---")
        await test_normal.test_normal_completion()
        print("  [PASS] Normal path")
    except Exception as e:
        print(f"  [FAIL] {e}")

    try:
        print("\n--- Test 2: RecallGate FALLBACK ---")
        await test_fallback.test_recall_fallback_path()
        print("  [PASS] Fallback path")
    except Exception as e:
        print(f"  [FAIL] {e}")

    print("\n" + "=" * 60)
    print("  Day 5 Pipeline Tests Complete")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(_run_standalone())

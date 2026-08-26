"""RecallGate 单元测试 — 闸门3 v0.1（三路裁决）。

覆盖场景：
  - 3 PASS：1 篇 / 3 篇 / 10 篇
  - 2 RETRY：0 篇且 retry_count < 3 → 改写 Query 并附带 new_query
  - 1 FALLBACK：0 篇且 retry_count >= 3 → 知识库暂无数据

Run:
    cd backend && pytest tests/test_recall_gate_v0.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.quality_gate.gates.recall_gate import RecallGate
from src.schemas import GateVerdict

# ═══════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════


def _make_state(chunks: list[dict], retry_count: int = 0) -> dict:
    """构建含 retrieved_chunks 和 recall_retry_count 的最小 state。"""
    return {
        "retrieved_chunks": chunks,
        "recall_retry_count": retry_count,
        "learner_data": {
            "learning_goal": "FANUC 机器人 SRVO-068 故障处理",
        },
    }


def _make_chunk(
    doc_id: str = "doc_001",
    title: str = "测试文档",
    content: str = "测试内容",
) -> dict:
    return {
        "doc_id": doc_id,
        "doc_title": title,
        "chunk_index": 0,
        "content": content,
        "relevance_score": 0.85,
    }


# ═══════════════════════════════════════════════════════════
# 测试类
# ═══════════════════════════════════════════════════════════


class TestRecallGatePass:
    """有召回结果 → PASS。"""

    async def test_one_doc_passes(self):
        """1 篇文档 → PASS。"""
        gate = RecallGate()
        state = _make_state([_make_chunk()])
        result = await gate.check(state)

        assert result["verdict"] == GateVerdict.PASS.value, (
            f"Expected PASS, got verdict={result['verdict']}"
        )
        assert result["passed"] is True

    async def test_three_docs_pass(self):
        """3 篇文档 → PASS。"""
        gate = RecallGate()
        state = _make_state(
            [
                _make_chunk("d1", "FANUC 基础"),
                _make_chunk("d2", "SRVO 错误码"),
                _make_chunk("d3", "故障排查"),
            ]
        )
        result = await gate.check(state)

        assert result["verdict"] == GateVerdict.PASS.value
        assert result["details"].get("total_chunks") == 3

    async def test_ten_docs_pass(self):
        """10 篇文档 → PASS。"""
        gate = RecallGate()
        state = _make_state([_make_chunk(f"d{i}", f"文档{i}") for i in range(10)])
        result = await gate.check(state)

        assert result["verdict"] == GateVerdict.PASS.value
        assert result["details"].get("total_chunks") == 10


class TestRecallGateRetry:
    """无召回、未达重试上限 → RETRY + 改写 Query。"""

    async def test_zero_docs_first_retry(self):
        """0 篇 + retry_count=0 → RETRY + 附带 new_query。"""
        gate = RecallGate()
        state = _make_state([], retry_count=0)
        result = await gate.check(state)

        assert result["verdict"] == GateVerdict.RETRY.value, (
            f"Expected RETRY, got verdict={result['verdict']}"
        )
        assert result["passed"] is False
        # 应附带改写后的 Query
        assert "new_query" in result["details"], (
            f"RETRY should include new_query in details, got keys={list(result['details'].keys())}"
        )
        new_q = result["details"]["new_query"]
        assert len(new_q) >= 2, f"new_query 过短: '{new_q}'"

    async def test_zero_docs_second_retry(self):
        """0 篇 + retry_count=1 → RETRY（距上限还有）"""
        gate = RecallGate()
        state = _make_state([], retry_count=1)
        result = await gate.check(state)

        assert result["verdict"] == GateVerdict.RETRY.value
        assert result["details"].get("retry_count") == 2


class TestRecallGateFallback:
    """无召回、重试已达上限 → FALLBACK。"""

    async def test_zero_docs_after_max_retries(self):
        """0 篇 + retry_count=3（=RECALL_MAX_RETRIES）→ FALLBACK。"""
        gate = RecallGate()
        state = _make_state([], retry_count=3)
        result = await gate.check(state)

        assert result["verdict"] == GateVerdict.FALLBACK.value, (
            f"Expected FALLBACK, got verdict={result['verdict']}"
        )
        assert result["passed"] is False
        assert any("知识库暂无" in v for v in result["violations"]), (
            f"Expected '知识库暂无' in violations, got {result['violations']}"
        )


class TestRecallGateDoubleThreshold:
    """双层相似度阈值防误判：high_pass / low_pass / fallback_external。"""

    def _chunk(self, score: float, doc_id: str = "d") -> dict:
        return {
            "doc_id": doc_id,
            "doc_title": "FANUC 故障排查",
            "chunk_index": 0,
            "content": "SRVO-068 检查通信链路",
            "relevance_score": score,
        }

    async def test_high_confidence_pass(self):
        """最高分 0.85 > 0.70 → high_pass，PASS 且无 low_confidence 标记。"""
        gate = RecallGate()
        state = _make_state([self._chunk(0.85)])
        result = await gate.check(state)

        assert result["verdict"] == GateVerdict.PASS.value
        assert result["details"].get("recall_type") == "high_pass"
        assert result["details"].get("low_confidence") is not True
        assert state["gate_results"]["recall"]["final_type"] == "high_pass"

    async def test_low_confidence_pass(self):
        """最高分 0.50 落入 (0.30, 0.70] → low_pass，PASS 且打 low_confidence 标记。"""
        gate = RecallGate()
        state = _make_state([self._chunk(0.50)])
        result = await gate.check(state)

        assert result["verdict"] == GateVerdict.PASS.value, "低置信区间应放行，而非 FALLBACK"
        assert result["details"].get("recall_type") == "low_pass"
        assert result["details"].get("low_confidence") is True
        assert state.get("_low_confidence") is True
        assert state["gate_results"]["recall"]["final_type"] == "low_pass"

    async def test_low_band_mid_retry_terminates(self):
        """重试中途召回落入低置信区间 → 立刻放行，不再继续重试至兜底。"""
        gate = RecallGate()
        # retry_count=1 表示已重试过一轮，此时召回 0.50 落入低置信区间
        state = _make_state([self._chunk(0.50)], retry_count=1)
        result = await gate.check(state)

        assert result["verdict"] == GateVerdict.PASS.value, (
            "落入低置信区间应立即放行，而不是继续 RETRY/FALLBACK"
        )
        assert result["details"].get("recall_type") == "low_pass"

    async def test_all_below_low_retry(self):
        """全部 ≤ 0.30（含 0.20 召回）且未达上限 → RETRY。"""
        gate = RecallGate()
        state = _make_state([self._chunk(0.20)], retry_count=0)
        result = await gate.check(state)

        assert result["verdict"] == GateVerdict.RETRY.value
        assert "new_query" in result["details"]

    async def test_all_below_low_fallback_external(self):
        """全部 ≤ 0.30 且达上限 → FALLBACK，recall final_type=fallback_external。"""
        gate = RecallGate()
        state = _make_state([self._chunk(0.10)], retry_count=3)
        result = await gate.check(state)

        assert result["verdict"] == GateVerdict.FALLBACK.value
        assert result["details"].get("recall_type") == "fallback_external"
        assert state["gate_results"]["recall"]["final_type"] == "fallback_external"

    async def test_recall_round_log(self):
        """recall 日志记录每一轮 query 与相似度分数。"""
        gate = RecallGate()
        state = _make_state([self._chunk(0.85), self._chunk(0.5)])
        await gate.check(state)

        recall = state["gate_results"]["recall"]
        assert len(recall["rounds"]) == 1
        round0 = recall["rounds"][0]
        assert round0["query"] == "FANUC 机器人 SRVO-068 故障处理"
        assert round0["scores"] == [0.85, 0.5]
        assert round0["max_score"] == 0.85
        assert round0["type"] == "high_pass"

"""DiagnosisGate 单元测试 — 闸门2 v0.1（三路裁决）。

覆盖场景：
  - 1 PASS：overall_confidence ≥ 0.3 + recommended_difficulty 存在 + skill_gaps 非空
  - 2 RETRY：confidence < 0.3（低置信度触发 RETRY）
  - 3 RETRY：recommended_difficulty 缺失
  - 4 RETRY：skill_gaps 为空
  - 5 FALLBACK：diagnosis_result 为空 dict（不可解析）

Run:
    cd backend && pytest tests/test_diagnosis_gate_v0.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.quality_gate.gates.diagnosis_gate import DiagnosisGate
from src.schemas import GateVerdict

# ═══════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════


def _make_state(diagnosis_result: dict) -> dict:
    """构建含 diagnosis_result 的最小 state。"""
    return {
        "diagnosis_result": diagnosis_result,
        "learner_data": {
            "learning_goal": "学习 FANUC 机器人编程",
        },
    }


def _valid_diagnosis(**overrides) -> dict:
    """返回一个合法的 diagnosis_result，支持部分字段覆盖。"""
    base = {
        "knowledge_map": {
            "FANUC 基础操作": {"level": 0.8, "confidence": 0.9},
            "示教器编程": {"level": 0.6, "confidence": 0.7},
            "安全规范": {"level": 0.9, "confidence": 0.95},
            "IO 配置": {"level": 0.4, "confidence": 0.6},
            "运动指令": {"level": 0.5, "confidence": 0.65},
        },
        "skill_gaps": [
            {
                "topic": "工具坐标系标定",
                "current_level": 0.2,
                "target_level": 0.8,
                "priority": "high",
                "reason": "缺少实操经验",
            }
        ],
        "learning_style": "practice_first",
        "recommended_difficulty": "intermediate",
        "overall_confidence": 0.85,
        "summary": "该学习者有基础操作经验，但缺少坐标系标定实操。",
    }
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════
# 测试类
# ═══════════════════════════════════════════════════════════


class TestDiagnosisGatePass:
    """正常诊断结果 → PASS。"""

    async def test_valid_diagnosis_passes(self):
        """所有字段齐全、高置信度 → PASS。"""
        gate = DiagnosisGate()
        state = _make_state(_valid_diagnosis())
        result = await gate.check(state)

        assert result["verdict"] == GateVerdict.PASS.value, (
            f"Expected PASS, got verdict={result['verdict']}, violations={result['violations']}"
        )
        assert result["passed"] is True
        assert result["score"] == 1.0
        assert len(result["violations"]) == 0


class TestDiagnosisGateRetry:
    """部分不满足 → RETRY。"""

    async def test_low_confidence_triggers_retry(self):
        """overall_confidence < 0.3（且 learner_data 丰富，不走稀疏模式）→ RETRY。"""
        gate = DiagnosisGate()
        state = _make_state(_valid_diagnosis(overall_confidence=0.2))
        # 必须提供丰富的 learner_data，否则 _get_effective_threshold 会降为 0.05 稀疏模式
        state["learner_data"] = {
            "learning_goal": "学习 FANUC 机器人编程",
            "major": "自动化",
            "education_level": "本科",
        }
        result = await gate.check(state)

        assert result["verdict"] == GateVerdict.RETRY.value, (
            f"Expected RETRY, got verdict={result['verdict']}"
        )
        assert result["passed"] is False
        assert "置信度" in result.get("retry_hint", "")

    async def test_missing_difficulty_triggers_retry(self):
        """recommended_difficulty 为空 → RETRY。"""
        gate = DiagnosisGate()
        state = _make_state(_valid_diagnosis(recommended_difficulty=""))
        result = await gate.check(state)

        assert result["verdict"] == GateVerdict.RETRY.value, (
            f"Expected RETRY, got verdict={result['verdict']}"
        )
        assert any("recommended_difficulty" in v for v in result["violations"])

    async def test_empty_skill_gaps_triggers_retry(self):
        """skill_gaps 为空列表 → RETRY。"""
        gate = DiagnosisGate()
        state = _make_state(
            _valid_diagnosis(
                skill_gaps=[],
                overall_confidence=0.80,
            )
        )
        result = await gate.check(state)

        assert result["verdict"] == GateVerdict.RETRY.value, (
            f"Expected RETRY, got verdict={result['verdict']}"
        )
        assert any("skill_gaps" in v for v in result["violations"])


class TestDiagnosisGateFallback:
    """不可解析的输入 → FALLBACK。"""

    async def test_empty_dict_triggers_fallback(self):
        """diagnosis_result 为空 dict → FALLBACK + fallback_data 含默认诊断。"""
        gate = DiagnosisGate()
        state = _make_state({})
        result = await gate.check(state)

        assert result["verdict"] == GateVerdict.FALLBACK.value, (
            f"Expected FALLBACK, got verdict={result['verdict']}"
        )
        assert result["passed"] is False

        fb = result.get("fallback_data", {})
        assert fb.get("recommended_difficulty") == "beginner"
        assert len(fb.get("skill_gaps", [])) >= 1
        assert "[FALLBACK]" in fb.get("summary", "")


# ═══════════════════════════════════════════════════════════
# 兼容性测试：旧版 Agent1 无 overall_confidence → 自动推算
# ═══════════════════════════════════════════════════════════


class TestDiagnosisGateBackwardCompat:
    """旧版诊断结果（无 overall_confidence）→ 从 knowledge_map 自动推算。"""

    async def test_missing_overall_confidence_infers_from_knowledge_map(self):
        """knowledge_map 有各条目 confidence → 自动计算平均值为 overall_confidence。"""
        gate = DiagnosisGate()
        diag = _valid_diagnosis()
        del diag["overall_confidence"]  # 模拟旧版 Agent1 输出
        state = _make_state(diag)
        result = await gate.check(state)

        # knowledge_map 5 条 confidence: 0.9, 0.7, 0.95, 0.6, 0.65 → avg = 0.76（≥ 稀疏阈值 0.05）→ PASS
        assert result["verdict"] == GateVerdict.PASS.value, (
            f"Expected PASS via inferred confidence, "
            f"got verdict={result['verdict']}, violations={result['violations']}"
        )

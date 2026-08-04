"""InputGate 单元测试 — 闸门1（输入特异性检测）。

覆盖场景：
  - 3 个正常工业机器人领域输入 → PASS + 意图标签
  - 2 个敏感词输入 → FALLBACK（passed=False）
  - 2 个空/过短输入 → FALLBACK（passed=False）

Run:
    cd backend && pytest tests/test_input_gate.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

# 确保 repo 根目录在 sys.path 中，使 gate 模块自身的 backend.src.* 导入能解析
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.quality_gate.gates import InputGate  # noqa: E402


class TestInputGateNormalCases:
    """正常工业机器人领域输入 — 预期 PASS + 正确意图标签。"""

    @staticmethod
    def _make_state(learning_goal: str) -> dict:
        """构建含 learner_data 的最小 state。"""
        return {
            "learner_data": {
                "education_level": "bachelor",
                "major": "自动化",
                "school": "测试职业技术学院",
                "work_years": 0,
                "industry": "汽车制造",
                "positions": ["机器人调试员"],
                "skills_used": ["FANUC示教器"],
                "pretest_results": [],
                "learning_goal": learning_goal,
            }
        }

    async def test_normal_fault_diagnosis(self):
        """完整工业机器人故障问题 → PASS + intent='故障排查'。"""
        gate = InputGate()
        state = self._make_state("FANUC机器人SRVO-068报警怎么解决")
        result = await gate.check(state)

        assert result["passed"] is True, f"Expected PASS, got violations={result['violations']}"
        assert result["score"] == 1.0
        assert result["details"].get("intent") == "故障排查"
        assert result["details"].get("intent_confidence") == "high"

    async def test_normal_programming_teach(self):
        """示教编程问题 → PASS + intent='编程操作'。"""
        gate = InputGate()
        state = self._make_state("如何使用KUKA示教器编写轨迹程序")
        result = await gate.check(state)

        assert result["passed"] is True
        assert result["details"].get("intent") == "编程操作"
        assert result["details"].get("intent_confidence") == "high"

    async def test_normal_safety_standard(self):
        """安全规范问题 → PASS + intent='安全规范'。"""
        gate = InputGate()
        state = self._make_state("工业机器人急停装置的安全配置要求")
        result = await gate.check(state)

        assert result["passed"] is True
        assert result["details"].get("intent") == "安全规范"
        assert result["details"].get("intent_confidence") == "high"


class TestInputGateSensitiveCases:
    """敏感词输入 — 预期 FALLBACK（passed=False）。"""

    @staticmethod
    def _make_state(text: str) -> dict:
        return {
            "learner_data": {
                "education_level": "bachelor",
                "major": "测试",
                "industry": "测试",
                "learning_goal": text,
            }
        }

    async def test_sensitive_gambling(self):
        """包含"赌博"关键词 → FALLBACK。"""
        gate = InputGate()
        state = self._make_state("如何在赌博网站上下注")
        result = await gate.check(state)

        assert result["passed"] is False
        assert any("赌博" in v for v in result["violations"]), (
            f"Expected '赌博' in violations, got {result['violations']}"
        )

    async def test_sensitive_violence(self):
        """包含"暴力"关键词 → FALLBACK。"""
        gate = InputGate()
        state = self._make_state("暴力机器的操作方法")
        result = await gate.check(state)

        assert result["passed"] is False
        assert any("暴力" in v for v in result["violations"]), (
            f"Expected '暴力' in violations, got {result['violations']}"
        )


class TestInputGateEmptyCases:
    """空/过短输入 — 预期 FALLBACK（passed=False）。"""

    async def test_empty_input(self):
        """learner_data 中无任何文本字段 → FALLBACK。"""
        gate = InputGate()
        state = {
            "learner_data": {
                "education_level": "bachelor",
                "major": "",
                "industry": "",
                "school": "",
                "positions": [],
                "skills_used": [],
                "learning_goal": "",
            }
        }
        result = await gate.check(state)

        assert result["passed"] is False
        assert any("输入为空" in v for v in result["violations"]), (
            f"Expected '输入为空' in violations, got {result['violations']}"
        )
        assert result["details"].get("intent") == "未识别"
        assert result["details"].get("intent_confidence") == "low"

    async def test_too_short_input(self):
        """仅有一个极短文本字段且未达最小长度 → FALLBACK。"""
        gate = InputGate()
        state = {
            "learner_data": {
                "education_level": "bachelor",
                "major": "",
                "industry": "",
                "school": "",
                "positions": [],
                "skills_used": [],
                "learning_goal": "你好",
            }
        }
        result = await gate.check(state)

        assert result["passed"] is False
        assert any("输入过短" in v for v in result["violations"]), (
            f"Expected '输入过短' in violations, got {result['violations']}"
        )

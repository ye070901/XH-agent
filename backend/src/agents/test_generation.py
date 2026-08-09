"""test_generation.py — Agent2 知识生成 Agent 单元测试。

- mock 模拟 diagnosis_result 输入，**不调用真实大模型**
- 断言 ``state["generated_resources"]`` 长度 >= 1 且 <= 3
- 通过 mock 掉 ``call_llm_json`` 避免任何真实 LLM 调用

运行方式（在项目根目录）::

    python test_generation.py            # 直接运行（unittest）
    python -m unittest test_generation   # unittest 发现
    pytest test_generation.py            # 安装 pytest 后也可
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

# ── 让 agents 包可被导入：把 agents 包所在目录的父目录加入 sys.path ──
_PKG_PARENT = Path(__file__).resolve().parent.parent
if str(_PKG_PARENT) not in sys.path:
    sys.path.insert(0, str(_PKG_PARENT))

from agents.generation import GenerationAgent

# ═══════════════════════════════════════════════════════════
# 测试数据（mock，不经真实 LLM）
# ═══════════════════════════════════════════════════════════

#: 单份资源的 mock 返回（call_llm_json 的返回值）
MOCK_RESOURCE = {
    "title": "LangGraph 入门讲义（mock）",
    "content": "# LangGraph 入门讲义\n\n这是 mock 返回的 Markdown 内容。",
    "difficulty_level": "beginner",
    "key_takeaways": ["理解 StateGraph", "掌握节点与边"],
}

#: 模拟的 diagnosis_result 输入
MOCK_DIAGNOSIS = {
    "knowledge_map": {
        "LangGraph框架": {"level": 0.1, "confidence": 0.8, "evidence": "学习目标提及"},
    },
    "skill_gaps": [
        {
            "topic": "LangGraph状态图",
            "current_level": 0.1,
            "target_level": 0.8,
            "priority": "critical",
            "reason": "LangGraph 是核心基础",
        },
    ],
    "learning_style": "practice_first",
    "recommended_difficulty": "beginner",
    "summary": "学习 LangGraph 开发 AI Agent",
}

#: 每条资源必须包含的字段（与 schemas.GeneratedResource 对齐）
REQUIRED_FIELDS = (
    "resource_id",
    "learner_id",
    "resource_type",
    "title",
    "content",
    "citations",
    "difficulty_level",
    "target_skill_gaps",
    "estimated_duration_minutes",
    "prerequisites",
    "key_takeaways",
)


class GenerationAgentTest(unittest.TestCase):
    """生成 Agent 单元测试：只跑 run(state)，LLM 全部 mock。"""

    def _mock_agent(self) -> GenerationAgent:
        """创建 GenerationAgent 并 mock 掉 call_llm_json（不调用真实大模型）。"""
        agent = GenerationAgent()
        patcher = patch.object(
            agent,
            "call_llm_json",
            new=AsyncMock(return_value=dict(MOCK_RESOURCE)),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return agent

    def _run(self, state: dict) -> dict:
        """同步包装：asyncio.run 执行 agent.run(state)。"""
        agent = self._mock_agent()
        return asyncio.run(agent.run(state))

    # ── 断言辅助 ──
    def _assert_resource_count(self, state: dict) -> None:
        resources = state["generated_resources"]
        # 核心断言：数量 >= 1 且 <= 3
        self.assertTrue(
            1 <= len(resources) <= 3,
            f"generated_resources 数量应为 1~3，实际为 {len(resources)}",
        )

    def _assert_resource_fields(self, state: dict) -> None:
        for res in state["generated_resources"]:
            for key in REQUIRED_FIELDS:
                self.assertIn(key, res, f"资源缺少字段: {key}")

    # ── 测试用例 ──
    def test_default_resource_types_generates_3(self) -> None:
        """未传 resource_types → 默认 3 种类型，产出 3 条资源。"""
        state = self._run({"diagnosis_result": MOCK_DIAGNOSIS})
        self._assert_resource_count(state)
        self.assertEqual(len(state["generated_resources"]), 3)
        self._assert_resource_fields(state)

    def test_single_resource_type_generates_1(self) -> None:
        """只请求一种类型 → 产出 1 条资源。"""
        state = self._run(
            {
                "diagnosis_result": MOCK_DIAGNOSIS,
                "resource_types": ["lecture"],
            }
        )
        self._assert_resource_count(state)
        self.assertEqual(len(state["generated_resources"]), 1)
        self.assertEqual(state["generated_resources"][0]["resource_type"], "lecture")

    def test_resource_count_capped_at_3(self) -> None:
        """请求超过 3 种类型 → 上限截断为 3 条。"""
        state = self._run(
            {
                "diagnosis_result": MOCK_DIAGNOSIS,
                "resource_types": ["lecture", "guide", "quiz", "project"],
            }
        )
        self._assert_resource_count(state)
        self.assertEqual(len(state["generated_resources"]), 3)

    def test_empty_diagnosis_still_generates(self) -> None:
        """诊断结果为空时仍可生成（缺省值兜底），数量仍在 1~3。"""
        state = self._run({"diagnosis_result": {}, "resource_types": ["lecture"]})
        self._assert_resource_count(state)
        self.assertEqual(len(state["generated_resources"]), 1)

    def test_generated_resources_in_state(self) -> None:
        """输出必须写入 state["generated_resources"]。"""
        state = self._run({"diagnosis_result": MOCK_DIAGNOSIS})
        self.assertIn("generated_resources", state)


if __name__ == "__main__":
    unittest.main(verbosity=2)

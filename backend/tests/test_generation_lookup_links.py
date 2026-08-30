"""二期-2 速查链接接线（指令速查手册 + 报警排查库）回归测试。

覆盖 generation_v2 新增的确定性速查链接注入（不调 LLM，纯关键词规则）：
  1. 索引 loader 只保留三品牌（FANUC/KUKA/ABB），排除 UR/Yaskawa。
  2. _strip_code_blocks 剔除 ``` 围栏代码块，保留行内反引号。
  3. 指令链接：正文命中 → 注入 ABB MoveJ 等；代码块内 / 词粘连 / UR 指令不命中。
  4. 报警链接：正文命中 → 注入 FANUC SRVO-068 等；代码块内 / Yaskawa 报警不命中。
  5. 端到端 process()：机器人讲义/指南注入 instruction_links / alarm_links。

关键约束：消费 data/instruction_index.json、data/alarm_index.json（只读，fail-open）。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from src.agents.generation_v2 import (
    GenerationAgent,
    _load_alarm_index,
    _load_instruction_index,
)

ROBOT_TOPIC = "学习工业机器人示教器操作与安全"


def _agent_with(mock_result: dict) -> GenerationAgent:
    agent = GenerationAgent()
    agent.call_llm_json = AsyncMock(side_effect=lambda *a, **k: dict(mock_result))
    return agent


# ═══════════════════════════════════════════════════════════
# 索引加载（三品牌过滤，防静默降级）
# ═══════════════════════════════════════════════════════════


def test_load_instruction_index_three_brands_only() -> None:
    idx = _load_instruction_index()
    assert idx, "instruction_index.json 应含三品牌条目（ABB 7 条）"
    assert {e["brand"] for e in idx} <= {"FANUC", "KUKA", "ABB"}


def test_load_alarm_index_three_brands_only() -> None:
    idx = _load_alarm_index()
    assert idx, "alarm_index.json 应含三品牌条目（ABB + FANUC）"
    assert {e["brand"] for e in idx} <= {"FANUC", "KUKA", "ABB"}


# ═══════════════════════════════════════════════════════════
# _strip_code_blocks：代码块剔除、行内反引号保留
# ═══════════════════════════════════════════════════════════


def test_strip_code_blocks_removes_fence_keeps_inline() -> None:
    content = "正文提到 `MoveJ` 指令\n\n```python\nMoveJ p1, v100\n```\n\n结尾"
    stripped = GenerationAgent._strip_code_blocks(content)
    assert "MoveJ p1" not in stripped  # 代码块内代码被整体剔除
    assert "`MoveJ`" in stripped  # 行内反引号（讲解速查点）保留


# ═══════════════════════════════════════════════════════════
# _extract_instruction_links：指令速查链接
# ═══════════════════════════════════════════════════════════


def test_extract_instruction_links_body() -> None:
    links = GenerationAgent._extract_instruction_links("使用 MoveJ 指令进行关节运动")
    assert any(link["name"] == "MoveJ" and link["brand"] == "ABB" for link in links)


def test_extract_instruction_links_code_block_skipped() -> None:
    links = GenerationAgent._extract_instruction_links("```\nMoveJ p1, v100\n```")
    assert links == []


def test_extract_instruction_links_word_boundary() -> None:
    # MoveJoint 不应命中 MoveJ（词边界）
    links = GenerationAgent._extract_instruction_links("使用 MoveJoint 运动")
    assert links == []


def test_extract_instruction_links_ur_excluded() -> None:
    # Freedrive 是 UR 指令，三品牌过滤后不应命中
    links = GenerationAgent._extract_instruction_links("使用 Freedrive 安全示教")
    assert links == []


# ═══════════════════════════════════════════════════════════
# _extract_alarm_links：报警排查链接
# ═══════════════════════════════════════════════════════════


def test_extract_alarm_links_srvo() -> None:
    links = GenerationAgent._extract_alarm_links("处理 SRVO-068 报警")
    assert any(link["code"] == "SRVO-068" and link["brand"] == "FANUC" for link in links)


def test_extract_alarm_links_code_block_skipped() -> None:
    links = GenerationAgent._extract_alarm_links("```\nSRVO-068\n```")
    assert links == []


def test_extract_alarm_links_yaskawa_excluded() -> None:
    # ALARM 0060 是 Yaskawa 报警，三品牌过滤后不应命中
    links = GenerationAgent._extract_alarm_links("出现 ALARM 0060 报警")
    assert links == []


# ═══════════════════════════════════════════════════════════
# 端到端：process() 注入链接字段
# ═══════════════════════════════════════════════════════════


def test_process_injects_instruction_links() -> None:
    abb_guide = {
        "title": "ABB 示教器操作指南",
        "content": (
            "# ABB 示教器操作指南\n\n"
            "## 安全操作确认清单\n"
            "- 安全门状态确认\n- 急停按钮位置确认\n- 使能键使用规范\n"
            "- 工作区间无人员确认\n- 减速模式开启要求\n\n"
            "## 操作步骤\n"
            "> ⚠️ 安全提示：示教前确认工作区间无人员。\n1. 使用 MoveJ 指令示教点位\n\n"
            "## 常见异常与排错\n- 报警：检查安全门。\n"
        ),
        "citations": [],
        "difficulty_level": "intermediate",
        "estimated_duration_minutes": 30,
        "key_takeaways": ["掌握示教器操作"],
    }
    agent = _agent_with(abb_guide)
    state = asyncio.run(
        agent.run(
            {
                "learner_data": {"learning_goal": ROBOT_TOPIC},
                "diagnosis_result": {
                    "recommended_difficulty": "intermediate",
                    "learning_style": "project_based",
                },
                "retrieved_chunks": [],
                "resource_types": ["guide"],
            }
        )
    )
    assert state["generated_resources"]
    resource = state["generated_resources"][0]
    assert any(
        link["name"] == "MoveJ" and link["brand"] == "ABB" for link in resource["instruction_links"]
    )


def test_process_injects_alarm_links() -> None:
    fanuc_guide = {
        "title": "FANUC 报警排查指南",
        "content": (
            "# FANUC 报警排查指南\n\n"
            "## 安全操作确认清单\n"
            "- 安全门状态确认\n- 急停按钮位置确认\n- 使能键使用规范\n"
            "- 工作区间无人员确认\n- 减速模式开启要求\n\n"
            "## 排查步骤\n"
            "> ⚠️ 安全提示：处理报警前先停机。\n1. 处理 SRVO-068 报警\n\n"
            "## 常见异常与排错\n- 报警：检查急停。\n"
        ),
        "citations": [],
        "difficulty_level": "intermediate",
        "estimated_duration_minutes": 30,
        "key_takeaways": ["掌握报警排查"],
    }
    agent = _agent_with(fanuc_guide)
    state = asyncio.run(
        agent.run(
            {
                "learner_data": {"learning_goal": ROBOT_TOPIC},
                "diagnosis_result": {
                    "recommended_difficulty": "intermediate",
                    "learning_style": "project_based",
                },
                "retrieved_chunks": [],
                "resource_types": ["guide"],
            }
        )
    )
    assert state["generated_resources"]
    resource = state["generated_resources"][0]
    assert any(
        link["code"] == "SRVO-068" and link["brand"] == "FANUC" for link in resource["alarm_links"]
    )

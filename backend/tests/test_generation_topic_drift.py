"""主题漂移幻觉回归测试。

复现案例：用户学习目标「掌握数控机床的编程与加工」，Agent 却输出
《入门机器人坐标系与姿态》整套课件（课题被替换成工业机器人）。

覆盖两层防线：
  1. 片段过滤（_filter_relevant_chunks）：非机器人课题丢弃机器人领域检索片段；
     片段全被丢弃后进入「无素材自生成」（打免责标记），仍受主题锁定约束，绝不生成机器人内容。
  2. 生成后自检（_topic_drift_failure + 重试）：检索片段不携带机器人标记、
     但模型仍漂移到机器人领域时，丢弃本次结果并重试；重试仍漂移则整体丢弃。

全部 mock call_llm_json，不调用真实大模型。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from src.agents.generation_v2 import GenerationAgent

# ═══════════════════════════════════════════════════════════
# 测试数据（mock，不经真实 LLM）
# ═══════════════════════════════════════════════════════════

CNC_LEARNING_GOAL = "掌握数控机床的编程与加工；重点学习基础原理；目标是知道并大致了解其流程"

#: 模型跑偏到机器人领域的 mock 返回（标题 + 核心知识点均含机器人标记）
ROBOT_DRIFTED_RESOURCE = {
    "title": "入门机器人坐标系与姿态",
    "content": "# 入门机器人坐标系\n\n机器人坐标系与姿态表示……",
    "citations": [],
    "difficulty_level": "beginner",
    "estimated_duration_minutes": 30,
    "key_takeaways": ["理解机器人坐标系", "掌握姿态表示"],
}

#: 未跑偏的数控机床 mock 返回
CNC_RESOURCE = {
    "title": "数控机床编程基础",
    "content": "# 数控机床编程基础\n\nG 代码与加工流程……",
    "citations": [],
    "difficulty_level": "beginner",
    "estimated_duration_minutes": 30,
    "key_takeaways": ["掌握 G 代码", "了解加工流程"],
}

#: 机器人领域检索片段（用于片段过滤路径）
ROBOT_CHUNKS = [
    {
        "doc_id": "K1_robot_001",
        "doc_title": "工业机器人基础安全常识",
        "chunk_index": 0,
        "content": "进入机器人工作区域前必须按下急停按钮，示教器操作时……",
        "relevance_score": 0.9,
    },
]

#: 数控机床领域检索片段（不含机器人标记，用于自检路径）
CNC_CHUNKS = [
    {
        "doc_id": "cnc_001",
        "doc_title": "数控机床编程基础",
        "chunk_index": 0,
        "content": "数控机床采用 G 代码编程，常见指令包括 G00 快速定位、G01 直线插补……",
        "relevance_score": 0.9,
    },
]

_CNC_DIAGNOSIS = {
    "skill_gaps": [
        {
            "topic": "数控编程",
            "current_level": 0.1,
            "target_level": 0.6,
            "priority": "critical",
            "reason": "核心基础",
        }
    ],
    "learning_style": "theory_first",
    "recommended_difficulty": "beginner",
    "summary": "学习数控机床编程",
}


def _agent_with(mock_result: dict) -> GenerationAgent:
    """创建 GenerationAgent 并把 call_llm_json 替换为固定返回的 AsyncMock。"""
    agent = GenerationAgent()
    agent.call_llm_json = AsyncMock(side_effect=lambda *a, **k: dict(mock_result))
    return agent


# ═══════════════════════════════════════════════════════════
# 单测：主题漂移判定 + 片段过滤（不经过 process）
# ═══════════════════════════════════════════════════════════


def test_robot_title_on_cnc_topic_is_drift() -> None:
    reason = GenerationAgent._topic_drift_failure(ROBOT_DRIFTED_RESOURCE, CNC_LEARNING_GOAL)
    assert reason is not None
    assert "机器人" in reason


def test_cnc_title_on_cnc_topic_is_not_drift() -> None:
    reason = GenerationAgent._topic_drift_failure(CNC_RESOURCE, CNC_LEARNING_GOAL)
    assert reason is None


def test_robot_title_on_robot_topic_is_not_drift() -> None:
    reason = GenerationAgent._topic_drift_failure(
        ROBOT_DRIFTED_RESOURCE, "学习工业机器人示教器操作"
    )
    assert reason is None


def test_empty_topic_does_not_flag_drift() -> None:
    reason = GenerationAgent._topic_drift_failure(ROBOT_DRIFTED_RESOURCE, "")
    assert reason is None


def test_filter_drops_robot_chunks_for_cnc_topic() -> None:
    kept = GenerationAgent._filter_relevant_chunks(ROBOT_CHUNKS, CNC_LEARNING_GOAL)
    assert kept == []


def test_filter_keeps_chunks_for_robot_topic() -> None:
    kept = GenerationAgent._filter_relevant_chunks(ROBOT_CHUNKS, "学习工业机器人安全操作")
    assert kept == ROBOT_CHUNKS


def test_filter_keeps_all_when_topic_empty() -> None:
    kept = GenerationAgent._filter_relevant_chunks(ROBOT_CHUNKS, "")
    assert kept == ROBOT_CHUNKS


# ═══════════════════════════════════════════════════════════
# 端到端 process()：跑偏结果不进入 generated_resources
# ═══════════════════════════════════════════════════════════


def test_drifted_result_discarded_and_retried() -> None:
    """检索片段不带机器人标记，但模型仍输出机器人内容 → 丢弃 + 重试，最终不返回。"""
    agent = _agent_with(ROBOT_DRIFTED_RESOURCE)
    state = asyncio.run(
        agent.run(
            {
                "learner_data": {"learning_goal": CNC_LEARNING_GOAL},
                "diagnosis_result": _CNC_DIAGNOSIS,
                "retrieved_chunks": CNC_CHUNKS,
                "resource_types": ["lecture"],
            }
        )
    )

    assert state["generated_resources"] == []
    errors = state.get("generation_errors", [])
    assert any(e.get("error") == "topic_drift" for e in errors)
    # 首次 + MAX_TOPIC_RETRIES 次重试都被调用
    assert agent.call_llm_json.call_count == 1 + GenerationAgent.MAX_TOPIC_RETRIES


def test_on_topic_result_is_kept() -> None:
    """未跑偏的结果正常通过，不误伤；有 KB 素材时保持权威生成，不打免责标记。"""
    agent = _agent_with(CNC_RESOURCE)
    state = asyncio.run(
        agent.run(
            {
                "learner_data": {"learning_goal": CNC_LEARNING_GOAL},
                "diagnosis_result": _CNC_DIAGNOSIS,
                "retrieved_chunks": CNC_CHUNKS,
                "resource_types": ["lecture"],
            }
        )
    )

    assert len(state["generated_resources"]) == 1
    assert "generation_errors" not in state
    # 有 KB 素材 → 权威生成：不打免责标记、不进入降级模式
    resource = state["generated_resources"][0]
    assert not resource["content"].startswith("【提示：以下内容由模型基于通用知识生成")
    assert state.get("downgrade_mode") is not True


def test_robot_chunks_filtered_then_self_generate_for_cnc_topic() -> None:
    """非机器人课题 + 机器人检索片段 → 片段被过滤 → 无素材自生成（CNC 内容）+ 免责标记。"""
    agent = _agent_with(CNC_RESOURCE)
    state = asyncio.run(
        agent.run(
            {
                "learner_data": {"learning_goal": CNC_LEARNING_GOAL},
                "diagnosis_result": {},
                "retrieved_chunks": ROBOT_CHUNKS,
                "resource_types": ["lecture"],
            }
        )
    )

    resources = state["generated_resources"]
    assert len(resources) == 1
    assert resources[0]["citations"] == []
    assert resources[0]["content"].startswith("【提示：以下内容由模型基于通用知识生成")
    assert "不保证其真实性" in resources[0]["content"]
    assert state.get("downgrade_mode") is True

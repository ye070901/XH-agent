"""工业实操安全体系（风险分级 + 安全提示抽取 + 元数据派生）回归测试。

覆盖 generation_v2 新增的确定性安全机制（全部不调 LLM，纯规则判定）：
  1. _classify_risk_level：风险分级（theory / low_risk / high_risk），危险 ≠ 难度。
  2. _extract_safety_warnings：从扁平 content 抽取 `> ⚠️ 安全提示：…` 文本。
  3. _derive_robot_metadata：从 retrieved_chunks 派生品牌/控制器/机型，无则「未标注」。
  4. _structure_validation_failure：high_risk 实操须含清单 + 安全提示。
  5. process() 端到端打标：high_risk guide 与 theory lecture 的字段落地。

全部 mock call_llm_json，不调真实 LLM。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from src.agents.generation_v2 import GenerationAgent

ROBOT_TOPIC = "学习工业机器人示教器操作与安全"

# ── mock 资源（不经真实 LLM）──────────────────────────────────────────

#: 完整合规的 high_risk guide（品牌 + 清单 + 逐步安全提示 + 排错模块齐全）
HIGH_RISK_GUIDE = {
    "title": "FANUC 工业机器人示教器安全操作指南",
    "content": (
        "# FANUC 示教器安全操作指南\n\n"
        "## 安全操作确认清单\n"
        "- 安全门状态确认\n- 急停按钮位置确认\n- 使能键使用规范\n"
        "- 工作区间无人员确认\n- 减速模式开启要求\n\n"
        "## 操作步骤\n"
        "> ⚠️ 安全提示：进入手动模式前确认安全门关闭。\n1. 进入手动模式\n"
        "> ⚠️ 安全提示：示教点位前确认工作区间无人员。\n2. 示教点位\n\n"
        "## 常见异常与排错\n- 报警 SRVO-xxx：检查安全门。\n"
    ),
    "citations": [],
    "difficulty_level": "intermediate",
    "estimated_duration_minutes": 30,
    "key_takeaways": ["掌握示教器安全操作"],
}

#: 含 FANUC/YRC1000/CRX 标识的知识库 chunk（用于元数据派生）
FANUC_CHUNKS = [
    {
        "doc_id": "fanuc-yrc1000-crx-setup",
        "doc_title": "FANUC YRC1000 CRX 系列机器人参数设置",
        "content": "……",
    }
]


def _agent_with(mock_result: dict) -> GenerationAgent:
    agent = GenerationAgent()
    agent.call_llm_json = AsyncMock(side_effect=lambda *a, **k: dict(mock_result))
    return agent


# ═══════════════════════════════════════════════════════════
# _classify_risk_level：风险分级
# ═══════════════════════════════════════════════════════════


def test_classify_theory_types_always_theory() -> None:
    # lecture/quiz 恒为 theory，即使正文出现运动类词（讲义/测试属理论内容）
    assert GenerationAgent._classify_risk_level("lecture", "## 示教\n示教点位操作") == "theory"
    assert GenerationAgent._classify_risk_level("quiz", "## 题\n示教前确认安全门") == "theory"


def test_classify_guide_motion_high_risk() -> None:
    assert (
        GenerationAgent._classify_risk_level("guide", "## 操作\n示教点位并运行程序") == "high_risk"
    )


def test_classify_guide_software_low_risk() -> None:
    assert (
        GenerationAgent._classify_risk_level("guide", "## 参数查看\n进入参数查看界面") == "low_risk"
    )


def test_classify_guide_plain_theory() -> None:
    assert (
        GenerationAgent._classify_risk_level("guide", "## 概述\n机器人坐标系基本概念") == "theory"
    )


# ═══════════════════════════════════════════════════════════
# _extract_safety_warnings：逐步安全提示抽取
# ═══════════════════════════════════════════════════════════


def test_extract_safety_warnings_in_order() -> None:
    content = (
        "# 指南\n\n"
        "> ⚠️ 安全提示：进入手动模式前确认安全门关闭。\n"
        "1. 进入手动模式\n"
        "> 安全提示：示教点位前确认工作区间无人员。\n"
        "2. 示教点位\n"
        "> 这是一段普通引用，不是安全提示。\n"
    )
    warnings = GenerationAgent._extract_safety_warnings(content)
    assert warnings == [
        "进入手动模式前确认安全门关闭。",
        "示教点位前确认工作区间无人员。",
    ]


def test_extract_safety_warnings_empty() -> None:
    assert GenerationAgent._extract_safety_warnings("# 指南\n无任何安全提示") == []


# ═══════════════════════════════════════════════════════════
# _derive_robot_metadata：元数据派生
# ═══════════════════════════════════════════════════════════


def test_derive_metadata_found() -> None:
    meta = GenerationAgent._derive_robot_metadata(FANUC_CHUNKS)
    assert meta == {
        "brand": "FANUC",
        "controller_version": "YRC1000",
        "applicable_model": "CRX",
    }


def test_derive_metadata_unlabeled() -> None:
    meta = GenerationAgent._derive_robot_metadata(
        [{"doc_id": "doc-001", "doc_title": "工业机器人基础坐标系", "content": "……"}]
    )
    assert meta == {
        "brand": "未标注",
        "controller_version": "未标注",
        "applicable_model": "未标注",
    }


def test_derive_metadata_empty_chunks_unlabeled() -> None:
    assert GenerationAgent._derive_robot_metadata([]) == {
        "brand": "未标注",
        "controller_version": "未标注",
        "applicable_model": "未标注",
    }


# ═══════════════════════════════════════════════════════════
# _structure_validation_failure：high_risk 清单/安全提示硬校验
# ═══════════════════════════════════════════════════════════


def _high_risk_body(motion: str) -> str:
    """构造含运动标记、品牌、安全标题、排错模块的最小 high_risk guide 正文。"""
    return (
        "# FANUC 示教器操作指南\n\n"
        "## 安全操作\n操作前按下急停按钮。\n\n"
        f"## 操作步骤\n1. {motion}\n\n"
        "## 常见异常与排错\n- 报警：检查安全门。\n"
    )


def test_high_risk_missing_checklist_fails() -> None:
    # 有运动标记 + 逐步安全提示，但缺「安全操作确认清单」标题
    content = (
        "# FANUC 示教器操作指南\n\n"
        "## 安全操作确认\n操作前按下急停按钮。\n\n"
        "## 操作步骤\n"
        "> ⚠️ 安全提示：示教前确认工作区间无人员。\n1. 示教点位\n\n"
        "## 常见异常与排错\n- 报警：检查安全门。\n"
    )
    failures = GenerationAgent._structure_validation_failure(
        {"title": "FANUC 示教器操作指南", "content": content}, "guide", "intermediate"
    )
    assert any("安全操作确认清单" in f for f in failures)


def test_high_risk_missing_safety_warning_fails() -> None:
    # 有运动标记 + 清单，但缺 `> ⚠️ 安全提示` 引用块
    content = (
        "# FANUC 示教器操作指南\n\n"
        "## 安全操作确认清单\n"
        "- 安全门状态确认\n- 急停按钮位置确认\n- 使能键使用规范\n"
        "- 工作区间无人员确认\n- 减速模式开启要求\n\n"
        "## 操作步骤\n1. 示教点位\n\n"
        "## 常见异常与排错\n- 报警：检查安全门。\n"
    )
    failures = GenerationAgent._structure_validation_failure(
        {"title": "FANUC 示教器操作指南", "content": content}, "guide", "intermediate"
    )
    assert any("安全提示" in f for f in failures)


def test_high_risk_complete_passes() -> None:
    failures = GenerationAgent._structure_validation_failure(
        HIGH_RISK_GUIDE, "guide", "intermediate"
    )
    assert failures == []


# ═══════════════════════════════════════════════════════════
# process() 端到端打标
# ═══════════════════════════════════════════════════════════


def _run(agent: GenerationAgent, resource_types: list[str], chunks: list) -> dict:
    return asyncio.run(
        agent.run(
            {
                "learner_data": {"learning_goal": ROBOT_TOPIC},
                "diagnosis_result": {
                    "recommended_difficulty": "intermediate",
                    "learning_style": "project_based",
                },
                "retrieved_chunks": chunks,
                "resource_types": resource_types,
            }
        )
    )


def test_process_stamps_high_risk_guide() -> None:
    state = _run(_agent_with(HIGH_RISK_GUIDE), ["guide"], FANUC_CHUNKS)
    assert len(state["generated_resources"]) == 1
    res = state["generated_resources"][0]
    assert res["risk_level"] == "high_risk"
    assert len(res["safety_warnings"]) == 2
    assert res["robot_metadata"] == {
        "brand": "FANUC",
        "controller_version": "YRC1000",
        "applicable_model": "CRX",
    }


def test_process_stamps_theory_lecture() -> None:
    lecture = {
        "title": "工业机器人坐标系与运动原理",
        "content": "# 坐标系\n机器人关节与笛卡尔坐标系的映射关系（通用原理）。",
        "citations": [],
        "difficulty_level": "intermediate",
        "estimated_duration_minutes": 30,
        "key_takeaways": ["理解坐标系"],
    }
    state = _run(_agent_with(lecture), ["lecture"], [])
    assert len(state["generated_resources"]) == 1
    res = state["generated_resources"][0]
    assert res["risk_level"] == "theory"
    assert res["safety_warnings"] == []
    # 机器人领域 lecture 同样派生元数据，但空 chunk 只能「未标注」
    assert res["robot_metadata"]["brand"] == "未标注"

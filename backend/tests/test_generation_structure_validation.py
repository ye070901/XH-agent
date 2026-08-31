"""工业机器人领域结构后置校验（A档）回归测试。

覆盖 generation_v2 新增的确定性结构校验（不调 LLM，仅结构性/存在性判定）：
  1. 品牌锚定：讲义/指南须声明 FANUC/KUKA/ABB 之一，或标注「通用原理」。
  2. 安全红线：guide 须前置独立「安全」标题章节。
  3. 实操真实性：guide 须含「常见异常与排错」对照模块。
  4. 难度层级：入门级内容不得出现视觉集成/离线编程等超纲主题。
  5. quiz 安全规范类题目占比 ≥20%。

关键约束：结构校验仅在课题属于机器人领域时生效；非机器人课题（如数控机床）
跳过结构校验，保持主题锁定的既有行为。全部 mock call_llm_json，不调真实 LLM。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from src.agents.generation_v2 import GenerationAgent

ROBOT_TOPIC = "学习工业机器人示教器操作与安全"

# ── mock 资源（不经真实 LLM）──────────────────────────────────────────

#: 完整合规的 guide（品牌 + 安全章节 + 排错模块齐全）
GOOD_GUIDE = {
    "title": "FANUC 工业机器人示教器操作指南",
    "content": (
        "# FANUC 示教器操作指南\n\n"
        "## 安全操作确认清单\n"
        "- 安全门状态确认\n- 急停按钮位置确认\n- 使能键使用规范\n"
        "- 工作区间无人员确认\n- 减速模式开启要求\n\n"
        "## 安全规范\n操作前必须按下急停按钮，手动模式下限速运行。\n\n"
        "## 操作步骤\n"
        "> ⚠️ 安全提示：进入手动模式前确认安全门关闭。\n1. 进入手动模式\n"
        "> ⚠️ 安全提示：示教点位前确认工作区间无人员。\n2. 示教点位\n\n"
        "## 常见异常与排错\n- 报警 SRVO-xxx：检查安全门。\n"
    ),
    "citations": [],
    "difficulty_level": "beginner",
    "estimated_duration_minutes": 30,
    "key_takeaways": ["掌握示教器安全操作"],
}

#: 缺安全章节、缺排错模块、未声明品牌的 guide
BAD_GUIDE = {
    "title": "示教器操作",
    "content": "# 示教器操作\n\n第一步……第二步……",
    "citations": [],
    "difficulty_level": "beginner",
    "estimated_duration_minutes": 30,
    "key_takeaways": ["操作示教器"],
}

#: 未声明品牌、未标注「通用原理」的讲义
BAD_LECTURE = {
    "title": "工业机器人基础",
    "content": "# 工业机器人基础\n\n机器人由机械臂、控制器、示教器组成……",
    "citations": [],
    "difficulty_level": "beginner",
    "estimated_duration_minutes": 30,
    "key_takeaways": ["了解机器人组成"],
}

#: 入门级内容命中超纲主题（视觉集成）
BAD_BEGINNER_ADVANCED = {
    "title": "FANUC 视觉集成入门",
    "content": "# 视觉集成\n\n本讲介绍视觉集成与离线编程……",
    "citations": [],
    "difficulty_level": "beginner",
    "estimated_duration_minutes": 30,
    "key_takeaways": ["了解视觉集成"],
}

#: 仅标注「通用原理」、不写具体品牌的讲义（品牌锚定兜底路径）
GENERIC_LECTURE = {
    "title": "工业机器人坐标系讲解",
    "content": "# 坐标系\n\n通用原理，具体以对应品牌官方手册为准……",
    "citations": [],
    "difficulty_level": "beginner",
    "estimated_duration_minutes": 30,
    "key_takeaways": ["理解坐标系"],
}

#: 声明了品牌但缺安全章节/安全清单/排错模块的 guide（品牌锚定通过，仅缺结构章节 → 应保留并标记）
INCOMPLETE_GUIDE = {
    "title": "FANUC 示教器操作指南",
    "content": "# FANUC 示教器操作指南\n\n## 操作步骤\n1. 进入手动模式\n2. 示教点位\n",
    "citations": [],
    "difficulty_level": "beginner",
    "estimated_duration_minutes": 30,
    "key_takeaways": ["掌握示教器基础操作"],
}

#: 数控机床讲义（无品牌声明，也不含机器人标记）——用于验证非机器人课题跳过结构校验
CNC_LECTURE = {
    "title": "数控机床编程基础",
    "content": "# 数控机床编程基础\n\nG 代码与加工流程……",
    "citations": [],
    "difficulty_level": "beginner",
    "estimated_duration_minutes": 30,
    "key_takeaways": ["掌握 G 代码", "了解加工流程"],
}


def _agent_with(mock_result: dict) -> GenerationAgent:
    agent = GenerationAgent()
    agent.call_llm_json = AsyncMock(side_effect=lambda *a, **k: dict(mock_result))
    return agent


# ═══════════════════════════════════════════════════════════
# 单测：_structure_validation_failure（确定性，逐项判定）
# ═══════════════════════════════════════════════════════════


def test_complete_guide_passes_structure() -> None:
    failures = GenerationAgent._structure_validation_failure(GOOD_GUIDE, "guide", "beginner")
    assert failures == []


def test_guide_missing_safety_section_fails() -> None:
    # 有品牌、有排错，唯独缺安全章节
    result = {
        "title": "FANUC 示教器操作",
        "content": "# FANUC 示教器操作\n\n## 常见异常与排错\n- 报警：……",
    }
    failures = GenerationAgent._structure_validation_failure(result, "guide", "beginner")
    assert any("安全" in f for f in failures)


def test_guide_missing_troubleshoot_fails() -> None:
    # 有品牌、有安全章节，唯独缺排错模块
    result = {
        "title": "KUKA 示教器操作",
        "content": "# KUKA 示教器操作\n\n## 安全规范\n操作前急停……",
    }
    failures = GenerationAgent._structure_validation_failure(result, "guide", "beginner")
    assert any("排错" in f for f in failures)


def test_lecture_missing_brand_fails() -> None:
    failures = GenerationAgent._structure_validation_failure(BAD_LECTURE, "lecture", "beginner")
    assert any("品牌" in f or "通用原理" in f for f in failures)


def test_lecture_generic_brand_passes() -> None:
    failures = GenerationAgent._structure_validation_failure(GENERIC_LECTURE, "lecture", "beginner")
    assert failures == []


def test_beginner_advanced_marker_fails() -> None:
    failures = GenerationAgent._structure_validation_failure(
        BAD_BEGINNER_ADVANCED, "lecture", "beginner"
    )
    assert any("超纲" in f for f in failures)


def test_advanced_marker_ok_for_non_beginner() -> None:
    # 同一份含「视觉集成」的内容，难度为 advanced 时不算超纲
    failures = GenerationAgent._structure_validation_failure(
        BAD_BEGINNER_ADVANCED, "lecture", "advanced"
    )
    assert all("超纲" not in f for f in failures)


def test_beginner_light_mention_passes() -> None:
    # 入门级仅轻度提及（1 次）高级主题「离线编程」→ 允许保留，不判超纲
    result = {
        "title": "FANUC 示教器基础操作",
        "content": "# 示教器基础\n\n本文介绍示教器基础操作。离线编程属于后续进阶内容，本文不展开。",
    }
    failures = GenerationAgent._structure_validation_failure(result, "lecture", "beginner")
    assert all("超纲" not in f for f in failures)


# ═══════════════════════════════════════════════════════════
# 单测：_quiz_safety_ratio_failure（安全题占比 ≥20%）
# ═══════════════════════════════════════════════════════════

SAFE_QUIZ = (
    "第1题：进入机器人工作区前必须先做什么？\n"
    "A. 按下急停\nB. 直接进入\nC. 关闭电源\nD. 大声喊叫\n"
    "答案：A\n解析：急停是进入工作区前的基本安全操作。\n\n"
    "第2题：FANUC 控制器的常见型号是？\n"
    "A. R-30iB\nB. PLC\nC. 单片机\nD. 变频器\n"
    "答案：A\n解析：R-30iB 是 FANUC 机器人控制器型号。\n\n"
    "第3题：KUKA 的编程语言是？\n"
    "A. KRL\nB. Python\nC. Java\nD. C++\n"
    "答案：A\n解析：KRL 是 KUKA 机器人编程语言。\n\n"
    "第4题：ABB 的编程语言是？\n"
    "A. RAPID\nB. Go\nC. Rust\nD. Swift\n"
    "答案：A\n解析：RAPID 是 ABB 机器人编程语言。\n\n"
    "第5题：工业机器人常见的轴数是？\n"
    "A. 六轴\nB. 一轴\nC. 二轴\nD. 三轴\n"
    "答案：A\n解析：常见工业机器人为六轴结构。"
)

NO_SAFETY_QUIZ = (
    "第1题：FANUC 控制器的常见型号是？\n"
    "A. R-30iB\nB. PLC\nC. 单片机\nD. 变频器\n"
    "答案：A\n解析：R-30iB 是 FANUC 机器人控制器型号。\n\n"
    "第2题：KUKA 的编程语言是？\n"
    "A. KRL\nB. Python\nC. Java\nD. C++\n"
    "答案：A\n解析：KRL 是 KUKA 机器人编程语言。\n\n"
    "第3题：ABB 的编程语言是？\n"
    "A. RAPID\nB. Go\nC. Rust\nD. Swift\n"
    "答案：A\n解析：RAPID 是 ABB 机器人编程语言。\n\n"
    "第4题：工业机器人常见的轴数是？\n"
    "A. 六轴\nB. 一轴\nC. 二轴\nD. 三轴\n"
    "答案：A\n解析：常见工业机器人为六轴结构。\n\n"
    "第5题：示教器的英文缩写是？\n"
    "A. TP\nB. PC\nC. CPU\nD. GPU\n"
    "答案：A\n解析：TP 是 Teach Pendant 的缩写。"
)


def test_quiz_safety_ratio_meets_threshold() -> None:
    assert GenerationAgent._quiz_safety_ratio_failure(SAFE_QUIZ) is None


def test_quiz_safety_ratio_below_threshold() -> None:
    failure = GenerationAgent._quiz_safety_ratio_failure(NO_SAFETY_QUIZ)
    assert failure is not None
    assert "安全" in failure


# ═══════════════════════════════════════════════════════════
# 端到端 process()：结构校验的丢弃/保留/跳过
# ═══════════════════════════════════════════════════════════


def test_robot_guide_missing_safety_dropped() -> None:
    agent = _agent_with(BAD_GUIDE)
    state = asyncio.run(
        agent.run(
            {
                "learner_data": {"learning_goal": ROBOT_TOPIC},
                "diagnosis_result": {
                    "recommended_difficulty": "beginner",
                    "learning_style": "practice_first",
                },
                "retrieved_chunks": [],
                "resource_types": ["guide"],
            }
        )
    )
    assert state["generated_resources"] == []
    errors = state.get("generation_errors", [])
    assert any(e.get("error") == "structure_validation" for e in errors)


def test_robot_guide_complete_kept() -> None:
    agent = _agent_with(GOOD_GUIDE)
    state = asyncio.run(
        agent.run(
            {
                "learner_data": {"learning_goal": ROBOT_TOPIC},
                "diagnosis_result": {
                    "recommended_difficulty": "beginner",
                    "learning_style": "practice_first",
                },
                "retrieved_chunks": [],
                "resource_types": ["guide"],
            }
        )
    )
    assert len(state["generated_resources"]) == 1
    assert "generation_errors" not in state


def test_robot_guide_missing_sections_kept_and_flagged() -> None:
    # 声明了品牌但缺安全章节/排错模块的 guide → 不再整篇丢弃，保留并标记缺失项
    agent = _agent_with(INCOMPLETE_GUIDE)
    state = asyncio.run(
        agent.run(
            {
                "learner_data": {"learning_goal": ROBOT_TOPIC},
                "diagnosis_result": {
                    "recommended_difficulty": "beginner",
                    "learning_style": "practice_first",
                },
                "retrieved_chunks": [],
                "resource_types": ["guide"],
            }
        )
    )
    assert len(state["generated_resources"]) == 1
    res = state["generated_resources"][0]
    assert res.get("structure_missing_sections")
    errors = state.get("generation_errors", [])
    assert any(e.get("error") == "structure_sections_missing" for e in errors)


def test_non_robot_topic_skips_structure_validation() -> None:
    """非机器人课题（数控机床）不注入机器人领域结构校验，保持主题锁定行为。"""
    agent = _agent_with(CNC_LECTURE)
    state = asyncio.run(
        agent.run(
            {
                "learner_data": {"learning_goal": "掌握数控机床的编程与加工"},
                "diagnosis_result": {
                    "recommended_difficulty": "beginner",
                    "learning_style": "theory_first",
                },
                "retrieved_chunks": [],
                "resource_types": ["lecture"],
            }
        )
    )
    assert len(state["generated_resources"]) == 1
    assert "generation_errors" not in state


# ═══════════════════════════════════════════════════════════
# project 类型：品牌锚定 + 端到端丢弃/保留
# ═══════════════════════════════════════════════════════════

#: 完整合规的项目实战（声明品牌 FANUC）
GOOD_PROJECT = {
    "title": "FANUC 搬运工作站上下料项目实战",
    "content": (
        "# FANUC 搬运工作站上下料项目\n\n"
        "## 项目背景与目标\n本工作站采用 FANUC 机器人完成工件上下料。\n\n"
        "## 工作站拆解\n机器人 + 输送线 + 夹爪。\n\n"
        "## 全流程方案\nFANUC 控制柜 + 示教器编程。\n\n"
        "## 安全操作确认清单\n"
        "- 安全门状态确认\n- 急停按钮位置确认\n- 使能键使用规范\n"
        "- 工作区间无人员确认\n- 减速模式开启要求\n\n"
        "## 分步调试步骤\n"
        "> ⚠️ 安全提示：校点前确认工作区间无人员。\n1. 校点\n"
        "> ⚠️ 安全提示：试运行前开启减速模式。\n2. 试运行。\n\n"
        "## 验收标准与风险点\n节拍达标、安全联锁有效。"
    ),
    "citations": [],
    "difficulty_level": "intermediate",
    "estimated_duration_minutes": 60,
    "key_takeaways": ["掌握搬运工作站完整调试流程"],
}

#: 未声明品牌的 project（应被品牌锚定校验丢弃）
BAD_PROJECT = {
    "title": "搬运工作站上下料项目",
    "content": "# 搬运工作站上下料项目\n\n## 项目背景\n完成工件上下料。",
    "citations": [],
    "difficulty_level": "intermediate",
    "estimated_duration_minutes": 60,
    "key_takeaways": ["了解项目流程"],
}


def test_project_missing_brand_fails() -> None:
    failures = GenerationAgent._structure_validation_failure(BAD_PROJECT, "project", "intermediate")
    assert any("品牌" in f or "通用原理" in f for f in failures)


def test_project_with_brand_passes() -> None:
    failures = GenerationAgent._structure_validation_failure(
        GOOD_PROJECT, "project", "intermediate"
    )
    assert failures == []


def test_robot_project_missing_brand_dropped() -> None:
    agent = _agent_with(BAD_PROJECT)
    state = asyncio.run(
        agent.run(
            {
                "learner_data": {"learning_goal": ROBOT_TOPIC},
                "diagnosis_result": {
                    "recommended_difficulty": "intermediate",
                    "learning_style": "project_based",
                },
                "retrieved_chunks": [],
                "resource_types": ["project"],
            }
        )
    )
    assert state["generated_resources"] == []
    errors = state.get("generation_errors", [])
    assert any(e.get("error") == "structure_validation" for e in errors)


def test_robot_project_complete_kept() -> None:
    agent = _agent_with(GOOD_PROJECT)
    state = asyncio.run(
        agent.run(
            {
                "learner_data": {"learning_goal": ROBOT_TOPIC},
                "diagnosis_result": {
                    "recommended_difficulty": "intermediate",
                    "learning_style": "project_based",
                },
                "retrieved_chunks": [],
                "resource_types": ["project"],
            }
        )
    )
    assert len(state["generated_resources"]) == 1
    assert "generation_errors" not in state
    assert state["generated_resources"][0]["resource_type"] == "project"


def test_five_resource_types_not_truncated() -> None:
    """回归：勾选 5 种资源类型时不应被 MAX_RESOURCES 截断为前 3 种。

    mock _generate_one 直接返回合规资源，绕过逐类型结构校验，仅验证数量/顺序不被截断。
    """

    def _fake_generate(diagnosis, rtype, chunks, learner_data):
        return {"title": f"{rtype} 标题", "content": f"# {rtype}\n正文内容"}

    agent = GenerationAgent()
    agent._generate_one = AsyncMock(side_effect=_fake_generate)
    state = asyncio.run(
        agent.run(
            {
                "learner_data": {"learning_goal": "掌握数控机床编程与加工"},
                "diagnosis_result": {
                    "recommended_difficulty": "beginner",
                    "learning_style": "theory_first",
                },
                "retrieved_chunks": [],
                "resource_types": ["lecture", "guide", "quiz", "project", "pitfall_guide"],
            }
        )
    )
    assert [r["resource_type"] for r in state["generated_resources"]] == [
        "lecture",
        "guide",
        "quiz",
        "project",
        "pitfall_guide",
    ]
    assert "generation_errors" not in state

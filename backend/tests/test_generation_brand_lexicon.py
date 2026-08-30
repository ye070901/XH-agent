"""二期-1 品牌术语双向词表校验（品牌混淆判定）回归测试。

覆盖 generation_v2 新增的确定性品牌混淆校验（不调 LLM，纯关键词规则）：
  1. 单一品牌声明 + 其他品牌专属术语 → 判定品牌混淆。
  2. 单一品牌声明 + 自身品牌术语 → 不判定混淆。
  3. 多品牌对比（len>1）→ 不判定混淆。
  4. 零品牌声明 → 不判定混淆（由品牌锚定校验兜底）。
  5. 「通用原理」→ 豁免，不判定混淆。
  6. 词表 data/brand-lexicon.json 必须能加载出三品牌非空术语（防文件删除/损坏静默降级）。

关键约束：全部确定性规则，不调真实 LLM；词表消费 data/brand-lexicon.json。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from src.agents.generation_v2 import GenerationAgent, _load_brand_lexicon

ROBOT_TOPIC = "学习工业机器人示教器操作与安全"


def _agent_with(mock_result: dict) -> GenerationAgent:
    agent = GenerationAgent()
    agent.call_llm_json = AsyncMock(side_effect=lambda *a, **k: dict(mock_result))
    return agent


# ═══════════════════════════════════════════════════════════
# 词表加载（防静默降级）
# ═══════════════════════════════════════════════════════════


def test_brand_lexicon_is_populated() -> None:
    lex = _load_brand_lexicon()
    assert set(lex) >= {"FANUC", "KUKA", "ABB"}
    assert any(lex["FANUC"])
    assert any(lex["KUKA"])
    assert any(lex["ABB"])


# ═══════════════════════════════════════════════════════════
# _brand_confusion_failures：品牌混淆判定
# ═══════════════════════════════════════════════════════════


def test_confusion_fanuc_uses_kuka_krl() -> None:
    head = "FANUC 示教器操作指南\n使用 KRL 编写程序"
    failures = GenerationAgent._brand_confusion_failures(head)
    assert any("FANUC" in f and "KUKA" in f and "KRL" in f for f in failures)


def test_confusion_fanuc_uses_abb_rapid() -> None:
    head = "FANUC 机器人编程\n使用 RAPID 语言的 IF 语句"
    failures = GenerationAgent._brand_confusion_failures(head)
    assert any("FANUC" in f and "ABB" in f and "RAPID" in f for f in failures)


def test_confusion_kuka_uses_fanuc_srvo() -> None:
    head = "KUKA 编程指南\n处理 SRVO-068 报警"
    failures = GenerationAgent._brand_confusion_failures(head)
    assert any("KUKA" in f and "FANUC" in f and "SRVO" in f for f in failures)


def test_no_confusion_own_brand_term() -> None:
    # 声明 FANUC + 使用 FANUC 自身术语 SRVO → 不混淆
    head = "FANUC 示教器操作指南\n处理 SRVO-068 报警"
    assert GenerationAgent._brand_confusion_failures(head) == []


def test_no_confusion_multi_brand_comparison() -> None:
    # 多品牌对比（FANUC + ABB 都声明）→ 不混淆
    head = "FANUC 与 ABB 对比\nFANUC 用 TP，ABB 用 RAPID 与 IRC5"
    assert GenerationAgent._brand_confusion_failures(head) == []


def test_no_confusion_zero_brand() -> None:
    # 零品牌声明（无品牌名）→ 不判定混淆，交品牌锚定兜底
    head = "示教器基本操作\n使用 TP 界面"
    assert GenerationAgent._brand_confusion_failures(head) == []


# ═══════════════════════════════════════════════════════════
# _structure_validation_failure 集成：豁免 + 触发重生成
# ═══════════════════════════════════════════════════════════


def test_structure_validation_confusion_flagged() -> None:
    # 声明 FANUC 但写 KRL → 品牌混淆，触发重生成
    result = {
        "title": "FANUC 编程讲义",
        "content": "# FANUC 编程讲义\n\n使用 KRL 指令编写程序。",
    }
    failures = GenerationAgent._structure_validation_failure(result, "lecture", "beginner")
    assert any("品牌混淆" in f for f in failures)


def test_structure_validation_generic_exempts_confusion() -> None:
    # 「通用原理」标注 → 即便命中其他品牌术语也不判定混淆
    result = {
        "title": "机器人编程通用原理",
        "content": "# 机器人编程\n\n通用原理，FANUC 与 RAPID 语法对比说明。",
    }
    failures = GenerationAgent._structure_validation_failure(result, "lecture", "beginner")
    assert not any("品牌混淆" in f for f in failures)


def test_process_drops_confused_guide() -> None:
    # 端到端：FANUC guide 使用 KRL → 结构校验丢弃
    confused_guide = {
        "title": "FANUC 示教器操作指南",
        "content": (
            "# FANUC 示教器操作指南\n\n"
            "## 安全操作确认清单\n"
            "- 安全门状态确认\n- 急停按钮位置确认\n- 使能键使用规范\n"
            "- 工作区间无人员确认\n- 减速模式开启要求\n\n"
            "## 操作步骤\n"
            "> ⚠️ 安全提示：示教前确认工作区间无人员。\n1. 使用 KRL 指令示教点位\n\n"
            "## 常见异常与排错\n- 报警：检查安全门。\n"
        ),
        "citations": [],
        "difficulty_level": "intermediate",
        "estimated_duration_minutes": 30,
        "key_takeaways": ["掌握示教器操作"],
    }
    agent = _agent_with(confused_guide)
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
    assert state["generated_resources"] == []
    assert any(e.get("error") == "structure_validation" for e in state.get("generation_errors", []))

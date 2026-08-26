"""画像参数对齐测试：demo 模式 + 真实 LLM 模式（两套用例）。

覆盖本次修改的两个核心目标：
  1. demo 与真实 LLM 读同一份「结构化画像参数」
     （difficulty / learning_style / profile_tag），消除双源冲突
  2. 消除「难度失效 / 风格漂移 / 输出旧标准」

两套用例：
  - demo 模式：纯规则、确定性、可离线运行（LLM_API_KEY 为空时）
  - 真实 LLM 模式：mock 捕获 prompt，断言「结构化画像参数 + 画像锁定」注入到位，
    以及难度不匹配时 correction 的「注入 error → 修正 → 重试 → 兜底」链路

用法:
    cd backend
    python tests/test_profile_prompt_alignment.py
    或
    pytest tests/test_profile_prompt_alignment.py -v
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents.correction import CorrectionAgent
from src.agents.generation_v2 import GenerationAgent, derive_profile_tag
from src.llm.client import LLMClient, _lazy_load_openai_exceptions

_PASS = 0
_FAIL = 0


def check(condition: bool, label: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  [PASS] {label}")
    else:
        _FAIL += 1
        print(f"  [FAIL] {label}")


def _make_demo_client() -> LLMClient:
    """构造 demo 模式的 LLMClient（不读 settings.LLM_API_KEY）。"""
    client = LLMClient.__new__(LLMClient)
    client._clients = {}
    client._is_demo = True
    _lazy_load_openai_exceptions()
    return client


# ═══════════════════════════════════════════════════════════
# 一、demo 模式用例
# ═══════════════════════════════════════════════════════════


def test_derive_profile_tag_7_profiles() -> None:
    """纯规则 profile_tag 推导：7 画像全部命中，无 LLM 脑补。"""
    print("\n── demo：profile_tag 纯规则推导（7 画像）──")

    cases = [
        ({}, "beginner", "visual", "zero_basis"),  # D
        ({}, "beginner", "theory_first", "heard_only"),  # E
        (
            {"work_years": 0, "positions": ["自动化实习生"]},
            "intermediate",
            "theory_first",
            "theory_student",
        ),  # F
        ({}, "intermediate", "practice_first", "hands_on_operator"),  # G
        (
            {"work_years": 2, "positions": ["设备维护员"]},
            "intermediate",
            "theory_first",
            "balanced_junior",
        ),  # H
        ({}, "advanced", "practice_first", "skilled_engineer"),  # I
        ({}, "advanced", "project_based", "authority_expert"),  # J
    ]
    for learner, diff, style, expected in cases:
        got = derive_profile_tag(learner, diff, style)
        check(got == expected, f"({diff},{style}) → {expected}，实际 {got}")


def test_demo_generation_reads_structured_params() -> None:
    """demo 生成端读同一份结构化画像参数，difficulty 透传 + 画像区分 + 机器人领域。"""
    print("\n── demo：生成端读结构化参数 ──")

    client = _make_demo_client()
    user_msg = (
        "## 结构化画像参数（权威，禁止改写）\n"
        '{"difficulty": "advanced", "learning_style": "project_based", '
        '"profile_tag": "authority_expert"}\n\n'
        "## 生成任务\n"
        "请生成一份 lecture 类型的个性化学习资源。\n"
    )
    data = json.loads(client._demo_generation("你是一个知识专家", user_msg))
    check(data["difficulty_level"] == "advanced", "difficulty=advanced 透传")
    check("多品牌" in data["content"], "authority_expert 画像前缀注入")
    check(
        "FANUC" in data["content"] and "KUKA" in data["content"] and "ABB" in data["content"],
        "机器人领域三品牌（FANUC/KUKA/ABB）",
    )
    check(
        "LangGraph" not in data["content"] and "Google" not in data["content"],
        "无旧标准（LangGraph/Google）",
    )


def test_demo_correction_preserves_difficulty_and_robot_domain() -> None:
    """demo 修正端：difficulty 透传（非硬编码 beginner）+ 机器人领域 + 无旧标准。"""
    print("\n── demo：修正端读结构化参数 ──")

    client = _make_demo_client()
    user_msg = (
        "## 结构化画像参数（权威，禁止改写）\n"
        '{"difficulty": "intermediate", "learning_style": "practice_first", '
        '"profile_tag": "hands_on_operator"}\n\n'
        "## 原始资源\n- 类型：guide\n- 标题：SRVO-068 排查\n\n"
        "### 原始内容\n# SRVO-068 排查\n\n检查示教器与主机间的通信链路。\n\n"
        "## 审核发现的问题\n### 🔴 必须修正（error）\n无\n"
    )
    data = json.loads(client._demo_correction("你是一个内容修正专家", user_msg))
    check(data["difficulty_level"] == "intermediate", "difficulty=intermediate 透传")
    check("SRVO-068" in data["content"], "修正内容保留机器人故障领域")
    check("SRVO-068" in data["citations"][0]["original_text"], "引用为机器人领域 KB 原文")
    check(
        "LangGraph" not in data["content"] and "Google" not in data["content"],
        "无旧标准（LangGraph/Google）",
    )


def test_validate_profile_match() -> None:
    """画像匹配软校验：难度硬判 + 风格软判。"""
    print("\n── demo：画像匹配校验 ──")

    agent = CorrectionAgent()
    ok = agent._validate_profile_match(
        {"difficulty_level": "beginner", "content": "用示意图拆解步骤"},
        "beginner",
        "visual",
    )
    check(ok["difficulty_ok"] and ok["style_ok"], "难度+风格均匹配")

    diff_bad = agent._validate_profile_match(
        {"difficulty_level": "advanced", "content": "用示意图拆解步骤"},
        "beginner",
        "visual",
    )
    check(not diff_bad["difficulty_ok"], "难度不匹配 → difficulty_ok=False")

    style_bad = agent._validate_profile_match(
        {"difficulty_level": "beginner", "content": "这是一个纯文字的理论讲解"},
        "beginner",
        "visual",
    )
    check(style_bad["difficulty_ok"] and not style_bad["style_ok"], "风格特征缺失 → style_ok=False")


# ═══════════════════════════════════════════════════════════
# 二、真实 LLM 模式用例（mock 捕获 prompt）
# ═══════════════════════════════════════════════════════════


def test_system_prompts_no_old_standard() -> None:
    """system prompt 已删除旧标准（LangGraph/Google/LangChain），仅保留新难度矩阵 + 4 风格。"""
    print("\n── 真实模式：system prompt 旧标准清理 ──")

    from src.agents.correction import SYSTEM_PROMPT as C4
    from src.agents.generation_v2 import SYSTEM_PROMPT as G2

    for name, sp in [("generation_v2", G2), ("correction", C4)]:
        check("LangGraph" not in sp, f"{name} 无 LangGraph")
        check("Google" not in sp, f"{name} 无 Google")
        check("LangChain" not in sp, f"{name} 无 LangChain")
    check("难度矩阵" in G2, "generation_v2 含唯一难度矩阵")
    check("学习风格" in G2 and "4 种" in G2, "generation_v2 含 4 种学习风格")
    check("画像匹配" in C4, "correction 含画像匹配规则")


def test_build_correction_prompt_has_structured_params() -> None:
    """修正 prompt 注入结构化画像参数 + 画像锁定硬规则。"""
    print("\n── 真实模式：修正 prompt 结构化参数 ──")

    agent = CorrectionAgent()
    prompt = agent._build_correction_prompt(
        resource={
            "resource_type": "guide",
            "title": "T",
            "difficulty_level": "beginner",
            "content": "C",
        },
        errors=[{"severity": "error", "detail": "E", "kb_evidence": ""}],
        warnings=[],
        infos=[],
        diagnosis={"recommended_difficulty": "advanced", "learning_style": "practice_first"},
        chunks=[],
        profile_tag="skilled_engineer",
    )
    check('"difficulty": "advanced"' in prompt, "结构化参数含 difficulty")
    check('"learning_style": "practice_first"' in prompt, "结构化参数含 learning_style")
    check('"profile_tag": "skilled_engineer"' in prompt, "结构化参数含 profile_tag")
    check("画像锁定" in prompt, "含画像锁定硬规则")
    check("禁止自行调整难度" in prompt, "含「禁止自行调整难度」约束")


async def test_generate_one_prompt_has_structured_params() -> None:
    """生成 prompt 注入结构化画像参数 + 难度/风格锁定。"""
    print("\n── 真实模式：生成 prompt 结构化参数 ──")

    agent = GenerationAgent()
    captured: list[str] = []

    async def fake_json(prompt, *, temperature=None):
        captured.append(prompt)
        return {}

    agent.call_llm_json = fake_json  # type: ignore[method-assign]

    diagnosis = {
        "recommended_difficulty": "beginner",
        "learning_style": "visual",
        "summary": "入门",
        "skill_gaps": [],
    }
    await agent._generate_one(diagnosis, "lecture", [], learner_data={})
    prompt = captured[0]
    check("## 结构化画像参数（权威，禁止改写）" in prompt, "生成 prompt 含结构化参数块")
    check('"difficulty": "beginner"' in prompt, "含 difficulty")
    check('"learning_style": "visual"' in prompt, "含 learning_style")
    check('"profile_tag": "zero_basis"' in prompt, "profile_tag 纯规则推导 zero_basis")
    check("难度锁定" in prompt, "含难度锁定规则")
    check("风格锁定" in prompt, "含风格锁定规则")


async def test_correct_one_injects_difficulty_mismatch() -> None:
    """难度不一致时，correction 注入 error issue 触发修正并对齐难度。"""
    print("\n── 真实模式：难度不一致注入 error ──")

    agent = CorrectionAgent()
    captured: list[str] = []

    async def fake_json(prompt, *, temperature=None):
        captured.append(prompt)
        return {
            "content": "已对齐高级内容",
            "title": "T",
            "difficulty_level": "advanced",
            "citations": [],
            "key_takeaways": [],
            "correction_summary": "对齐难度",
        }

    agent.call_llm_json = fake_json  # type: ignore[method-assign]

    resource = {
        "resource_id": "r1",
        "resource_type": "guide",
        "title": "T",
        "difficulty_level": "beginner",
        "content": "入门内容",
        "citations": [],
        "key_takeaways": [],
    }
    audit_report = {"issues": [], "fact_check": {"items": []}}
    diagnosis = {"recommended_difficulty": "advanced", "learning_style": "practice_first"}

    result = await agent._correct_one(resource, audit_report, diagnosis, [], learner_data={})
    check(len(captured) == 1, "难度不一致触发一次修正（未早退）")
    check("难度标注不一致" in captured[0], "注入「难度标注不一致」error issue")
    check(result["corrected_resource"]["difficulty_level"] == "advanced", "修正后难度对齐 advanced")


async def test_enforce_profile_match_retry_success() -> None:
    """画像重试对齐成功：难度不匹配 → 重试 → 成功。"""
    print("\n── 真实模式：画像重试成功 ──")

    agent = CorrectionAgent()
    calls: list[str] = []

    async def fake_json(prompt, *, temperature=None):
        calls.append(prompt)
        return {"content": "对齐后内容", "difficulty_level": "beginner"}

    agent.call_llm_json = fake_json  # type: ignore[method-assign]

    resource = {
        "resource_id": "r1",
        "resource_type": "lecture",
        "difficulty_level": "advanced",
        "content": "旧内容",
    }
    out, logs = await agent._enforce_profile_match(resource, "beginner", "visual", "zero_basis")
    check(out["difficulty_level"] == "beginner", "重试后难度对齐 beginner")
    check(out.get("_profile_retried") is True, "标记 _profile_retried")
    check(logs and logs[0]["action"] == "retry_success", "记录 retry_success")
    check(len(calls) == 1, "重试仅调用一次 LLM")


async def test_enforce_profile_match_fallback() -> None:
    """画像重试失败 → 降级兜底强制难度。"""
    print("\n── 真实模式：画像重试失败降级兜底 ──")

    agent = CorrectionAgent()

    async def fake_json(prompt, *, temperature=None):
        return {"content": "仍是高级内容", "difficulty_level": "advanced"}

    agent.call_llm_json = fake_json  # type: ignore[method-assign]

    resource = {
        "resource_id": "r1",
        "resource_type": "lecture",
        "difficulty_level": "advanced",
        "content": "旧内容",
    }
    out, logs = await agent._enforce_profile_match(resource, "beginner", "visual", "zero_basis")
    check(out["difficulty_level"] == "beginner", "兜底强制难度 beginner")
    check(out.get("_profile_fallback") is True, "标记 _profile_fallback")
    check(logs and logs[0]["action"] == "fallback_forced", "记录 fallback_forced")


async def test_enforce_profile_match_fallback_on_parse_error() -> None:
    """画像重试 LLM 解析失败 → 降级兜底强制难度。"""
    print("\n── 真实模式：画像重试解析失败兜底 ──")

    agent = CorrectionAgent()

    async def fake_json(prompt, *, temperature=None):
        return {"_parse_error": True}

    agent.call_llm_json = fake_json  # type: ignore[method-assign]

    resource = {
        "resource_id": "r1",
        "resource_type": "lecture",
        "difficulty_level": "advanced",
        "content": "旧内容",
    }
    out, logs = await agent._enforce_profile_match(resource, "beginner", "visual", "zero_basis")
    check(out["difficulty_level"] == "beginner", "解析失败 → 兜底强制 beginner")
    check(out.get("_profile_fallback") is True, "标记 _profile_fallback")


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════


async def main() -> None:
    global _PASS, _FAIL

    print("=" * 60)
    print("  画像参数对齐测试（demo + 真实 LLM 两套）")
    print("=" * 60)

    # ── 同步测试 ──
    test_derive_profile_tag_7_profiles()
    test_demo_generation_reads_structured_params()
    test_demo_correction_preserves_difficulty_and_robot_domain()
    test_validate_profile_match()
    test_system_prompts_no_old_standard()
    test_build_correction_prompt_has_structured_params()

    # ── 异步测试 ──
    await test_generate_one_prompt_has_structured_params()
    await test_correct_one_injects_difficulty_mismatch()
    await test_enforce_profile_match_retry_success()
    await test_enforce_profile_match_fallback()
    await test_enforce_profile_match_fallback_on_parse_error()

    # ── 汇总 ──
    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    if _FAIL == 0:
        print(f"  [PASS] 全部 {total} 项测试通过")
    else:
        print(f"  [DONE] {_PASS}/{total} 通过, {_FAIL} 失败")
    print("=" * 60)

    if _FAIL > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

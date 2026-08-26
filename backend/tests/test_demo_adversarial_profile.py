"""demo 模式对抗画像测试：K/L/M 三个对抗画像 + 修正重试/兜底链路。

覆盖本次修改的两个核心目标：
  1. demo 模式对「对抗画像输入」（K 过度自信 / L 知识空白 / M 自相矛盾）
     仍按结构化规则判定难度/风格，不被自述经历带偏，且 profile_tag 复用
     真实链路的 derive_profile_tag（而非另写一套映射）。
  2. demo 修正端在难度不匹配时模拟「主修正保留原难度 → 触发重试 → 对齐」，
     而非无脑返回正确结果；真实 CorrectionAgent._correct_one 接入 demo mock
     后端到端触发重试成功。

用法:
    cd backend
    python tests/test_demo_adversarial_profile.py
    或
    pytest tests/test_demo_adversarial_profile.py -v
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents.correction import CorrectionAgent
from src.agents.diagnosis import DiagnosisAgent
from src.agents.generation_v2 import GenerationAgent, derive_profile_tag
from src.config import settings
from src.llm.client import LLMClient, _lazy_load_openai_exceptions
from src.quality_gate.gates.recall_gate import (
    OFFLINE_FALLBACK_MESSAGE,
    ONLINE_FALLBACK_DISCLAIMER,
    RecallGate,
)
from src.schemas import GateVerdict

_PROFILES_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "data"
    / "evaluation"
    / "learner_profiles.json"
)


def _make_demo_client() -> LLMClient:
    """构造 demo 模式的 LLMClient（不读 settings.LLM_API_KEY）。"""
    client = LLMClient.__new__(LLMClient)
    client._clients = {}
    client._is_demo = True
    _lazy_load_openai_exceptions()
    return client


def _load_profile(profile_id: str) -> dict:
    data = json.loads(_PROFILES_PATH.read_text(encoding="utf-8"))
    for p in data["profiles"]:
        if p["id"] == profile_id:
            return p
    raise KeyError(f"未找到画像 {profile_id}")


def test_demo_diagnosis_adversarial_profiles() -> None:
    """demo 学情诊断：K/L/M 三个对抗画像的难度/风格判定 + profile_tag 复用。"""
    print("\n── demo：对抗画像（K/L/M）难度/风格判定 ──")

    # (画像 id, 期望难度, 期望风格, 期望 profile_tag)
    expected = {
        "profile-k-over-confident": ("beginner", "practice_first", "custom"),
        "profile-l-knowledge-void": ("intermediate", "theory_first", "balanced_junior"),
        "profile-m-self-contradictory": ("beginner", "practice_first", "custom"),
    }

    client = _make_demo_client()
    agent = DiagnosisAgent()

    for pid, (diff, style, tag) in expected.items():
        profile = _load_profile(pid)
        learner = profile["input"]

        # 复用真实 DiagnosisAgent._build_prompt 构造诊断输入，demo 只替换 LLM 层
        prompt = agent._build_prompt(learner)
        result = json.loads(client._demo_diagnosis(agent.system_prompt, prompt))

        assert result["recommended_difficulty"] == diff, (
            f"{pid}: 期望难度 {diff}，实际 {result['recommended_difficulty']}"
        )
        assert result["learning_style"] == style, (
            f"{pid}: 期望风格 {style}，实际 {result['learning_style']}"
        )
        assert result["profile_tag"] == tag, (
            f"{pid}: 期望画像 {tag}，实际 {result['profile_tag']}"
        )
        # demo 层的 profile_tag 必须与真实 derive_profile_tag 完全一致（复用而非另写）
        assert result["profile_tag"] == derive_profile_tag(learner, diff, style), (
            f"{pid}: demo 的 profile_tag 与 derive_profile_tag 不一致"
        )

        print(f"  [PASS] {profile['label']}: {diff}/{style}/{tag}")


def test_demo_correction_simulates_retry_path() -> None:
    """demo 修正端：主修正保留原难度（触发重试），重写调用才对齐期望难度。"""
    print("\n── demo：修正端模拟重试路径 ──")
    client = _make_demo_client()

    # 主修正调用：结构化难度=beginner，但原资源难度标注=advanced → 保留 advanced
    main_msg = (
        "## 结构化画像参数（权威，禁止改写）\n"
        '{"difficulty": "beginner", "learning_style": "practice_first", '
        '"profile_tag": "custom"}\n\n'
        "## 原始资源\n- 类型：guide\n- 标题：SRVO-068 排查\n- 难度标注：advanced\n\n"
        "### 原始内容\n# SRVO-068 排查\n\n检查示教器与主机间的通信链路。\n\n"
        "## 审核发现的问题\n### 🔴 必须修正（error）\n1. [error] 难度标注不一致\n\n"
        "## 修正任务\n请修正。\n"
    )
    main_data = json.loads(client._demo_correction("你是一个内容修正专家", main_msg))
    assert main_data["difficulty_level"] == "advanced", (
        f"主修正应保留原难度 advanced，实际 {main_data['difficulty_level']}"
    )

    # 重写调用：同一画像参数 + 「重写任务」→ 对齐为期望难度 beginner
    retry_msg = (
        "## 结构化画像参数（权威，禁止改写）\n"
        '{"difficulty": "beginner", "learning_style": "practice_first", '
        '"profile_tag": "custom"}\n\n'
        "## 重写任务\n上一轮修正未通过画像匹配校验，请对齐难度。\n\n"
        "## 原始资源（待对齐）\n- 当前难度标注：advanced\n- 内容：\n"
        "# SRVO-068 排查\n\n检查示教器与主机间的通信链路。\n\n"
        "## 输出 JSON\n"
    )
    retry_data = json.loads(client._demo_correction("你是一个内容修正专家", retry_msg))
    assert retry_data["difficulty_level"] == "beginner", (
        f"重写调用应对齐期望难度 beginner，实际 {retry_data['difficulty_level']}"
    )

    print("  [PASS] 主修正保留原难度、重写调用对齐期望难度")


async def test_correct_one_retry_via_demo_mock() -> None:
    """真实 CorrectionAgent._correct_one 接入 demo mock：难度不匹配端到端触发重试成功。"""
    print("\n── demo：真实 correction 接入 demo mock 触发重试 ──")
    client = _make_demo_client()
    agent = CorrectionAgent()

    async def demo_json(prompt, *, temperature=None):
        return await client.call_json(agent.system_prompt, prompt, temperature=temperature)

    agent.call_llm_json = demo_json  # type: ignore[method-assign]

    resource = {
        "resource_id": "r-adv",
        "resource_type": "guide",
        "title": "SRVO-068 排查",
        "difficulty_level": "advanced",  # 与诊断 beginner 不符，应被画像校验纠正
        "content": "# SRVO-068 排查\n\n检查示教器与主机间的通信链路。\n",
        "citations": [],
        "key_takeaways": [],
    }
    audit_report = {"issues": [], "fact_check": {"items": []}}
    diagnosis = {"recommended_difficulty": "beginner", "learning_style": "practice_first"}

    result = await agent._correct_one(resource, audit_report, diagnosis, [], learner_data={})

    corrected = result["corrected_resource"]
    assert corrected["difficulty_level"] == "beginner", (
        f"修正后难度应对齐 beginner，实际 {corrected['difficulty_level']}"
    )
    assert corrected.get("_profile_retried") is True, (
        "应标记 _profile_retried（主修正保留原难度 → 触发重试）"
    )
    actions = [log.get("action") for log in result["logs"]]
    assert "retry_success" in actions, f"日志应记录 retry_success，实际 {actions}"

    print("  [PASS] 难度不匹配 → 主修正保留 → 重试 → 对齐 beginner")


async def test_positive_case_no_conflict_direct_match() -> None:
    """正例：信息完整、自评与能力匹配的画像 → 直接匹配正确难度，不触发重试流程。"""
    print("\n── demo：正例 — 无冲突画像直接匹配难度、不触发重试 ──")
    client = _make_demo_client()
    diag_agent = DiagnosisAgent()

    # 真实「均衡初级 H」画像：学历/岗位/技能/前置测试齐全且自洽（65/120 → intermediate）
    profile = _load_profile("profile-h-balanced-junior")
    learner = profile["input"]
    prompt = diag_agent._build_prompt(learner)
    diag = json.loads(client._demo_diagnosis(diag_agent.system_prompt, prompt))

    # ① 诊断直接匹配正确难度/风格/画像，无冲突
    assert diag["recommended_difficulty"] == "intermediate", (
        f"期望难度 intermediate，实际 {diag['recommended_difficulty']}"
    )
    assert diag["learning_style"] == "theory_first", (
        f"期望风格 theory_first，实际 {diag['learning_style']}"
    )
    assert diag["profile_tag"] == "balanced_junior", (
        f"期望画像 balanced_junior，实际 {diag['profile_tag']}"
    )

    # ② 修正端：资源难度与诊断一致 → 即使有 error 也只在修正阶段处理，不触发画像重试
    agent = CorrectionAgent()

    async def demo_json(prompt_, *, temperature=None):
        return await client.call_json(agent.system_prompt, prompt_, temperature=temperature)

    agent.call_llm_json = demo_json  # type: ignore[method-assign]

    resource = {
        "resource_id": "r-h",
        "resource_type": "lecture",
        "title": "SRVO-068 排查",
        "difficulty_level": "intermediate",  # 与诊断一致，无冲突
        "content": "# SRVO-068 排查\n\n从通信链路原理出发排查示教器与主机间故障。\n",
        "citations": [],
        "key_takeaways": [],
    }
    audit_report = {
        "verdict": "needs_revision",
        "issues": [{"severity": "error", "detail": "某事实表述需修正", "kb_evidence": ""}],
        "fact_check": {"items": []},
    }
    diagnosis = {
        "recommended_difficulty": diag["recommended_difficulty"],
        "learning_style": diag["learning_style"],
    }

    result = await agent._correct_one(resource, audit_report, diagnosis, [], learner_data=learner)

    corrected = result["corrected_resource"]
    assert corrected["difficulty_level"] == "intermediate", (
        f"难度应保持 intermediate，实际 {corrected['difficulty_level']}"
    )
    assert corrected.get("_profile_retried") is None, "难度一致不应触发画像重试"
    assert corrected.get("_profile_fallback") is None, "难度一致不应触发降级兜底"
    actions = [log.get("action") for log in result["logs"]]
    assert "retry_success" not in actions, f"不应记录 retry_success，实际 {actions}"
    assert "fallback_forced" not in actions, f"不应记录 fallback_forced，实际 {actions}"

    print("  [PASS] 正例：诊断 intermediate/theory_first/balanced_junior，修正不触发重试")


async def test_negative_case_conflict_triggers_retry() -> None:
    """反例：自述与能力矛盾的画像 → 首次难度判定出错，完整触发 demo 重试链路后对齐。"""
    print("\n── demo：反例 — 冲突画像首次判定出错、完整触发重试链路 ──")
    client = _make_demo_client()
    diag_agent = DiagnosisAgent()

    # 真实「自相矛盾 M」画像：自述 10 年经验，但技能实习生级 + 前置测试 25/120
    profile = _load_profile("profile-m-self-contradictory")
    learner = profile["input"]
    prompt = diag_agent._build_prompt(learner)
    diag = json.loads(client._demo_diagnosis(diag_agent.system_prompt, prompt))

    # ① 诊断不被自述经历带偏，按前置测试证据判为 beginner
    assert diag["recommended_difficulty"] == "beginner", (
        f"期望难度 beginner，实际 {diag['recommended_difficulty']}"
    )
    assert diag["learning_style"] == "practice_first", (
        f"期望风格 practice_first，实际 {diag['learning_style']}"
    )

    # ② 模拟「首次难度判定出错」：资源被错标 advanced（自述专家水平）→ 触发重试 → 对齐 beginner
    agent = CorrectionAgent()

    async def demo_json(prompt_, *, temperature=None):
        return await client.call_json(agent.system_prompt, prompt_, temperature=temperature)

    agent.call_llm_json = demo_json  # type: ignore[method-assign]

    resource = {
        "resource_id": "r-m",
        "resource_type": "guide",
        "title": "SRVO-068 排查",
        "difficulty_level": "advanced",  # 首次判定出错（自述专家水平）
        "content": "# SRVO-068 排查\n\n检查示教器与主机间的通信链路。\n",
        "citations": [],
        "key_takeaways": [],
    }
    audit_report = {"issues": [], "fact_check": {"items": []}}
    diagnosis = {
        "recommended_difficulty": diag["recommended_difficulty"],
        "learning_style": diag["learning_style"],
    }

    result = await agent._correct_one(resource, audit_report, diagnosis, [], learner_data=learner)

    corrected = result["corrected_resource"]
    assert corrected["difficulty_level"] == "beginner", (
        f"重试后应输出正确难度 beginner，实际 {corrected['difficulty_level']}"
    )
    assert corrected.get("_profile_retried") is True, (
        "应完整触发 demo 重试链路（标记 _profile_retried）"
    )
    actions = [log.get("action") for log in result["logs"]]
    assert "retry_success" in actions, f"日志应记录 retry_success，实际 {actions}"

    print("  [PASS] 反例：诊断 beginner，首次 advanced(错) → 重试 → 对齐 beginner")


def test_case_info_short_falls_back_to_beginner() -> None:
    """信息极少：缺学习背景与答题数据 → 兜底降级到安全默认（beginner/visual/zero_basis）。"""
    print("\n── demo：信息不足兜底降级（无背景、无答题数据）──")
    client = _make_demo_client()
    diag_agent = DiagnosisAgent()

    # 用户只给了学习目标，无学历/经历/岗位/技能/前置测试
    learner = {"learning_goal": "想了解工业机器人故障排查，但还没想好具体方向"}
    prompt = diag_agent._build_prompt(learner)
    diag = json.loads(client._demo_diagnosis(diag_agent.system_prompt, prompt))

    # 无前置测试（max_score=0）→ 工作年限兜底（work_years=0）→ 安全默认 beginner
    assert diag["recommended_difficulty"] == "beginner", (
        f"信息不足应兜底降级为 beginner，实际 {diag['recommended_difficulty']}"
    )
    assert diag["learning_style"] == "visual", (
        f"无技能信号应默认 visual，实际 {diag['learning_style']}"
    )
    assert diag["profile_tag"] == "zero_basis", (
        f"应落为 zero_basis 画像，实际 {diag['profile_tag']}"
    )

    # 降级不抛异常、不返回空：仍产出结构化盲区与知识图谱
    assert diag.get("skill_gaps"), "降级后仍应给出结构化盲区"
    assert diag.get("knowledge_map"), "降级后仍应给出知识图谱"

    print("  [PASS] 信息不足 → 无前置测试/无经历 → 兜底降级 beginner/visual/zero_basis")


async def test_case_topic_mismatch_retrieval_retry() -> None:
    """画像准确但知识库缺少感兴趣主题 → 检索重试（0 召回 → RETRY，达上限 → FALLBACK）。"""
    print("\n── demo：画像准确、知识库缺主题 → 检索重试 ──")
    client = _make_demo_client()
    diag_agent = DiagnosisAgent()

    # 画像 I「熟练工程师」：自评客观、信息准确（88/120 → advanced/practice_first）
    profile = _load_profile("profile-i-skilled-engineer")
    learner = profile["input"]
    prompt = diag_agent._build_prompt(learner)
    diag = json.loads(client._demo_diagnosis(diag_agent.system_prompt, prompt))

    # ① 画像诊断准确（问题不在画像，而在知识库缺主题）
    assert diag["recommended_difficulty"] == "advanced", (
        f"画像 I 应判 advanced，实际 {diag['recommended_difficulty']}"
    )
    assert diag["learning_style"] == "practice_first", (
        f"画像 I 应判 practice_first，实际 {diag['learning_style']}"
    )

    # ② 知识库缺少该学习目标主题 → retrieved_chunks 为空 → 召回闸门三路裁决
    print("【当前为mock模拟，未调用真实知识库API】")
    gate = RecallGate()
    query = learner.get("learning_goal", "多品牌离线仿真与复杂故障定位")

    # 首次：0 召回且未达上限 → RETRY + 改写 Query
    retry_result = await gate.check(
        {
            "retrieved_chunks": [],
            "recall_retry_count": 0,
            "learner_data": {"learning_goal": query},
            "diagnosis_result": diag,
        }
    )
    assert retry_result["verdict"] == GateVerdict.RETRY.value, (
        f"0 召回应判 RETRY，实际 {retry_result['verdict']}"
    )
    assert "new_query" in retry_result.get("details", {}), (
        f"RETRY 应附带改写后的 new_query，实际 keys={list(retry_result.get('details', {}))}"
    )
    print(
        "  [检索重试] recall_retry_count=0 召回0 → verdict=RETRY，"
        f"本次重试计数 retry_count={retry_result.get('details', {}).get('retry_count')}"
    )

    # 达上限（recall_retry_count == RECALL_MAX_RETRIES）→ FALLBACK
    fallback_result = await gate.check(
        {
            "retrieved_chunks": [],
            "recall_retry_count": settings.RECALL_MAX_RETRIES,
            "learner_data": {"learning_goal": query},
            "diagnosis_result": diag,
        }
    )
    assert fallback_result["verdict"] == GateVerdict.FALLBACK.value, (
        f"达上限应判 FALLBACK，实际 {fallback_result['verdict']}"
    )
    assert any("知识库暂无" in v for v in fallback_result.get("violations", [])), (
        f"FALLBACK 应说明知识库暂无数据，实际 {fallback_result.get('violations')}"
    )
    hit_fallback = fallback_result["verdict"] == GateVerdict.FALLBACK.value
    print(
        f"  [检索重试] recall_retry_count={settings.RECALL_MAX_RETRIES}（达上限）召回0 → "
        f"verdict=FALLBACK，命中FALLBACK兜底标记={hit_fallback}"
    )

    print("  [PASS] 画像 accurate + 知识库缺主题 → RETRY → FALLBACK（检索重试）")


async def test_case_real_beginner_direct_match_no_retry() -> None:
    """真实新手：自评客观、能力描述统一 → 直接匹配 beginner，不触发重试。"""
    print("\n── demo：真实新手直接匹配初级难度、无重试 ──")
    client = _make_demo_client()
    diag_agent = DiagnosisAgent()

    # 画像 D「纯零基础·行业外转行」：自评客观（5/120，目标「从零了解」），无夸大
    profile = _load_profile("profile-d-zero-basis")
    learner = profile["input"]
    prompt = diag_agent._build_prompt(learner)
    diag = json.loads(client._demo_diagnosis(diag_agent.system_prompt, prompt))

    # ① 诊断直接匹配正确难度/风格/画像
    assert diag["recommended_difficulty"] == "beginner", (
        f"真实新手应直接判 beginner，实际 {diag['recommended_difficulty']}"
    )
    assert diag["learning_style"] == "visual", (
        f"零基础应判 visual，实际 {diag['learning_style']}"
    )
    assert diag["profile_tag"] == "zero_basis", (
        f"应落为 zero_basis，实际 {diag['profile_tag']}"
    )

    # ② 修正端：资源难度与诊断一致（beginner）→ 即便有 error 也只修正内容，不触发重试
    agent = CorrectionAgent()

    async def demo_json(prompt_, *, temperature=None):
        return await client.call_json(agent.system_prompt, prompt_, temperature=temperature)

    agent.call_llm_json = demo_json  # type: ignore[method-assign]

    resource = {
        "resource_id": "r-d",
        "resource_type": "lecture",
        "title": "工业机器人是什么",
        "difficulty_level": "beginner",  # 与诊断一致
        "content": "# 工业机器人是什么\n\n工业机器人是可编程的机械臂，用于搬运、焊接等场景。\n",
        "citations": [],
        "key_takeaways": [],
    }
    audit_report = {
        "verdict": "needs_revision",
        "issues": [{"severity": "error", "detail": "某事实表述需修正", "kb_evidence": ""}],
        "fact_check": {"items": []},
    }
    diagnosis = {
        "recommended_difficulty": diag["recommended_difficulty"],
        "learning_style": diag["learning_style"],
    }

    result = await agent._correct_one(resource, audit_report, diagnosis, [], learner_data=learner)

    corrected = result["corrected_resource"]
    assert corrected["difficulty_level"] == "beginner", (
        f"难度应保持 beginner，实际 {corrected['difficulty_level']}"
    )
    assert corrected.get("_profile_retried") is None, "真实新手难度一致不应触发重试"
    assert corrected.get("_profile_fallback") is None, "真实新手难度一致不应触发降级兜底"
    actions = [log.get("action") for log in result["logs"]]
    assert "retry_success" not in actions, f"不应记录 retry_success，实际 {actions}"
    assert "fallback_forced" not in actions, f"不应记录 fallback_forced，实际 {actions}"

    print("  [PASS] 真实新手：诊断 beginner/visual/zero_basis，修正不触发重试")


def test_case_uneven_skill_local_ability_validation() -> None:
    """技能强弱分化（部分很强、部分零基础，描述如实）→ 局部能力校验。"""
    print("\n── demo：技能强弱分化 → 局部能力校验 ──")
    client = _make_demo_client()
    diag_agent = DiagnosisAgent()

    # 如实描述：编程调试很强，但离线仿真几乎没接触过（topic 分数如实分化）
    learner = {
        "education_level": "junior_college",
        "major": "机电一体化",
        "school": "职业技术学院",
        "work_years": 3,
        "industry": "汽车零部件制造",
        "positions": ["机器人调试工程师"],
        "skills_used": ["FANUC编程", "示教调试"],
        "learning_goal": "编程调试较熟，但离线仿真几乎没接触过，想补齐仿真与复杂故障定位",
        "pretest_results": [
            {
                "test_name": "工业机器人编程调试前置测试",
                "total_score": 60,
                "max_score": 120,
                "topic_scores": {
                    "机器人坐标系": 90,
                    "运动指令": 85,
                    "RobotStudio仿真": 10,
                    "ROS2/Gazebo仿真": 5,
                    "SRVO-068数据传输故障": 15,
                    "安全急停链路": 60,
                },
            }
        ],
    }
    prompt = diag_agent._build_prompt(learner)
    diag = json.loads(client._demo_diagnosis(diag_agent.system_prompt, prompt))

    # ① 整体难度按总分率 60/120=0.5 判 intermediate，既不因强项拔高、也不因弱项贬低
    assert diag["recommended_difficulty"] == "intermediate", (
        f"强弱分化应判 intermediate，实际 {diag['recommended_difficulty']}"
    )
    assert diag["learning_style"] == "practice_first", (
        f"调试岗应判 practice_first，实际 {diag['learning_style']}"
    )

    # ② 局部能力校验：即便整体 intermediate，仍定位到「弱项」作为高优先级盲区
    gaps = diag.get("skill_gaps", [])
    assert gaps, "应产出结构化知识盲区"
    critical_topics = [g.get("topic", "") for g in gaps if g.get("priority") == "critical"]
    assert critical_topics, "应识别出 critical 级盲区"
    all_topics = critical_topics + [g.get("topic", "") for g in gaps]
    assert any("仿真" in t for t in all_topics), (
        f"弱项「离线仿真」应被纳入盲区，实际 {[g.get('topic') for g in gaps]}"
    )

    # ③ 知识图谱呈现分化掌握度（局部能力：并非所有知识点同一水平）
    levels = [
        v.get("level")
        for v in diag.get("knowledge_map", {}).values()
        if isinstance(v, dict)
    ]
    assert len(set(levels)) >= 2, f"知识图谱应体现分化掌握度，实际 {levels}"

    print("  [PASS] 强弱分化 → intermediate + 离线仿真 critical + 知识图谱分化")


async def test_offline_mode_fallback_no_external_api() -> None:
    """离线模式兜底：知识库空 + is_offline=True → FALLBACK 返回固定提示，不调用外部 LLM。"""
    print("\n── demo：离线模式兜底 — 禁止调用外部 API ──")
    print("【离线模式触发兜底，禁止调用外部API】")

    gate = RecallGate(is_offline=True)

    # 守护外部 LLM：_rewrite_query 是召回闸门调用外部大模型的唯一入口（内部 llm.call）。
    # 离线模式命中 FALLBACK 时必须跳过联网兜底，因此该入口绝不能被调用。
    llm_called = {"count": 0}

    async def _forbid_external_llm(*args, **kwargs):
        llm_called["count"] += 1
        raise AssertionError("离线模式 FALLBACK 不应调用外部大模型接口")

    gate._rewrite_query = _forbid_external_llm  # type: ignore[method-assign]

    result = await gate.check(
        {
            "retrieved_chunks": [],  # mock 知识库返回空结果
            "recall_retry_count": settings.RECALL_MAX_RETRIES,  # 已达重试上限 → FALLBACK
            "learner_data": {"learning_goal": "某知识库缺主题的提问"},
            "diagnosis_result": {"summary": "某知识库缺主题的提问"},
        }
    )

    # ① 命中 FALLBACK
    assert result["verdict"] == GateVerdict.FALLBACK.value, (
        f"达上限应判 FALLBACK，实际 {result['verdict']}"
    )
    # ② 输出为离线固定提示文本
    fb = result.get("fallback_data", {})
    assert fb.get("offline_message") == OFFLINE_FALLBACK_MESSAGE, (
        f"离线 FALLBACK 应返回固定提示，实际 {fb.get('offline_message')}"
    )
    # ③ 断言不会调用外部大模型接口
    assert llm_called["count"] == 0, (
        f"离线模式 FALLBACK 不应调用外部大模型接口，实际调用 {llm_called['count']} 次"
    )

    print("  [PASS] 离线 FALLBACK 返回固定提示，未调用外部 API")


async def test_online_mode_fallback_external_retrieval_no_llm() -> None:
    """在线模式兜底：调用外部检索工具返回原始摘要，禁止调用 LLM 生成/改写。"""
    print("\n── demo：在线模式兜底 — 外部检索原始摘要，不调用 LLM ──")

    gate = RecallGate(is_offline=False)

    fixed_summary = (
        "[1] FANUC SRVO-068 数据传输故障概述\n"
        "SRVO-068 表示示教器与主机间数据传输故障，需检查通信链路与线缆连接。\n"
        "来源：https://example.com/srvo068"
    )
    fixed_sources = ["FANUC SRVO-068 数据传输故障概述（https://example.com/srvo068）"]

    async def _mock_external_retrieve(query: str):
        # 模拟「外部检索工具」：仅返回原始摘要 + 来源，不做任何 LLM 生成
        return fixed_summary, fixed_sources

    gate._external_retrieve = _mock_external_retrieve  # type: ignore[method-assign]

    # 守护：在线兜底绝不能再调用外部大模型（改写/生成均禁止）
    import backend.src.llm.client as _client

    llm_called = {"count": 0}
    _original_call = _client.llm.call

    async def _forbid_llm(*args, **kwargs):
        llm_called["count"] += 1
        raise AssertionError("在线兜底不应调用 LLM")

    _client.llm.call = _forbid_llm  # type: ignore[method-assign]
    try:
        result = await gate.check(
            {
                "retrieved_chunks": [],  # mock 知识库返回空结果
                "recall_retry_count": settings.RECALL_MAX_RETRIES,  # 已达上限 → FALLBACK
                "learner_data": {"learning_goal": "想了解多品牌离线仿真与复杂故障定位"},
                "diagnosis_result": {"summary": "想了解多品牌离线仿真与复杂故障定位"},
            }
        )
    finally:
        _client.llm.call = _original_call

    # ① 命中 FALLBACK
    assert result["verdict"] == GateVerdict.FALLBACK.value, (
        f"达上限应判 FALLBACK，实际 {result['verdict']}"
    )
    # ② 返回外部检索原始摘要 + 来源信息（gate_results 保存来源）
    fb = result.get("fallback_data", {})
    assert fb.get("online_fallback_raw") == fixed_summary, (
        f"应返回外部检索原始摘要，实际 {fb.get('online_fallback_raw')}"
    )
    assert fb.get("sources") == fixed_sources, (
        f"应保存检索来源信息，实际 {fb.get('sources')}"
    )
    # ③ 未调用 LLM（改写/生成均被禁止）
    assert llm_called["count"] == 0, (
        f"在线兜底不应调用 LLM，实际调用 {llm_called['count']} 次"
    )
    # ④ 免责声明为代码层面硬拼接的固定文本
    assert ONLINE_FALLBACK_DISCLAIMER.startswith("【提示：以下内容来自外部网络检索")

    print("  [PASS] 在线 FALLBACK 返回外部检索原始摘要，未调用 LLM")


async def test_no_kb_generation_blocked_no_llm() -> None:
    """Agent2 空 KB 生成关闭：无有效 chunk 时直接返回空资源，不调用 LLM。"""
    print("\n── demo：Agent2 空 KB 禁止凭空生成 ──")

    agent = GenerationAgent()
    llm_called = {"n": 0}

    async def _forbid_llm_json(prompt, *, temperature=None):
        llm_called["n"] += 1
        raise AssertionError("空 KB 时 Agent2 不应调用 LLM")

    agent.call_llm_json = _forbid_llm_json  # type: ignore[method-assign]

    result = await agent.process(
        {
            "diagnosis_result": {
                "recommended_difficulty": "beginner",
                "learning_style": "visual",
                "skill_gaps": [],
            },
            "retrieved_chunks": [],  # 无任何知识库 chunk
            "resource_types": ["lecture", "guide", "quiz"],
        }
    )

    assert result.get("generated_resources") == [], (
        f"空 KB 应返回空资源列表，实际 {result.get('generated_resources')}"
    )
    assert llm_called["n"] == 0, f"空 KB 不应调用 LLM，实际调用 {llm_called['n']} 次"

    print("  [PASS] 空 KB → Agent2 返回空资源，未调用 LLM")


async def test_agent2_all_parse_fail_returns_empty() -> None:
    """有 KB chunk 但 Agent2 全部解析失败 → generated_resources 为空列表。"""
    print("\n── demo：有 KB 但 Agent2 全部解析失败 → 空资源列表 ──")

    agent = GenerationAgent()

    async def _return_unparseable(prompt, *, temperature=None):
        return {}  # 模拟 LLM 返回无法解析的 JSON → _generate_one 返回 {}

    agent.call_llm_json = _return_unparseable  # type: ignore[method-assign]

    chunks = [
        {
            "doc_id": "doc_001",
            "doc_title": "FANUC SRVO-068 故障处理",
            "chunk_index": 0,
            "content": "SRVO-068 表示数据传输故障，需检查示教器与主机间通信链路。",
            "relevance_score": 0.9,
        }
    ]
    result = await agent.process(
        {
            "diagnosis_result": {
                "recommended_difficulty": "intermediate",
                "learning_style": "practice_first",
                "skill_gaps": [
                    {"topic": "SRVO-068", "priority": "critical", "reason": "r"}
                ],
            },
            "retrieved_chunks": chunks,  # 有 chunk → 进入生成，但解析失败
            "resource_types": ["lecture", "guide", "quiz"],
        }
    )

    assert result.get("generated_resources") == [], (
        f"有 KB 但全部解析失败应返回空列表，实际 {result.get('generated_resources')}"
    )

    print("  [PASS] 有 KB 但解析失败 → generated_resources=[]")


async def main() -> None:
    test_demo_diagnosis_adversarial_profiles()
    test_demo_correction_simulates_retry_path()
    await test_correct_one_retry_via_demo_mock()
    await test_positive_case_no_conflict_direct_match()
    await test_negative_case_conflict_triggers_retry()
    test_case_info_short_falls_back_to_beginner()
    await test_case_topic_mismatch_retrieval_retry()
    await test_case_real_beginner_direct_match_no_retry()
    test_case_uneven_skill_local_ability_validation()
    await test_offline_mode_fallback_no_external_api()
    await test_online_mode_fallback_external_retrieval_no_llm()
    await test_no_kb_generation_blocked_no_llm()
    await test_agent2_all_parse_fail_returns_empty()
    print("\n[PASS] 对抗画像 demo 测试全部通过")


if __name__ == "__main__":
    asyncio.run(main())

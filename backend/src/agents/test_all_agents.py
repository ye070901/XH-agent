"""test_all_agents.py — 三大 Agent 的 pytest 单元测试。

被测 Agent（仅统计这四个模块的业务代码覆盖率，不含测试脚本）:
  - DiagnosisAgent    diagnosis.py      学情诊断
  - GenerationAgent   generation_v2.py 领域知识生成（融合版 v2）
  - AuditAgent        audit.py         内容审核（只审不修）
  - CorrectionAgent   correction.py    保真修正

覆盖要求:
  - 每个 Agent 不少于 3 个 case：正常输入 / 边界输入 / 异常输入
  - 覆盖 process 流程、JSON 解析分支、错误返回分支
  - 使用 mock 模拟 3 种 LLM 异常：调用超时 / 返回非法 JSON / 返回空内容
  - 异常时代理不崩溃；由 BaseAgent.run() 统一兜底的场景返回
    {"error": "错误描述", "status": "error"}
  - 覆盖率统计不把测试脚本计入业务代码（仅 --cov 三个业务模块）

运行方式（在仓库根目录 XH-agent-main）::

    python -m pytest backend/src/agents/test_all_agents.py -q

注意（现有业务源码的既有行为，测试如实断言，不修改源码）:
  - DiagnosisAgent / CorrectionAgent 的 run() 包装了 BaseAgent.run()，
    BaseAgent.run() 内置 try/except，LLM 抛出的异常会被捕获，
    以 state["status"]="error" / state["error"]="..." 形式返回。
  - GenerationAgent 使用 generation_v2 版本，同样走 BaseAgent.run() 的
    try/except 异常隔离：LLM 抛出 TimeoutError 不会向上传播，而是被
    process() 的单资源 try/except 记录到 generation_errors（不崩溃）。
  - CorrectionAgent.process() 对"单个资源"的修正有 try/except，
    LLM 异常会被降级为"保留原内容 + 记录 failed 日志"，不崩溃。
"""

from __future__ import annotations

import asyncio
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# ── 让 backend 包可被导入：把仓库根目录加入 sys.path，使
#    `backend.src.agents.*` 全限定导入可用（agents 内部依赖相对导入
#    `from ..config import settings`，必须以子包身份导入）──
_PKG_PARENT = Path(__file__).resolve().parent.parent.parent.parent
if str(_PKG_PARENT) not in sys.path:
    sys.path.insert(0, str(_PKG_PARENT))

from backend.src.agents.audit import AuditAgent  # noqa: E402
from backend.src.agents.base import BaseAgent  # noqa: E402
from backend.src.agents.correction import CorrectionAgent  # noqa: E402
from backend.src.agents.diagnosis import DiagnosisAgent  # noqa: E402
from backend.src.agents.event_bus import SimpleEventBus  # noqa: E402
from backend.src.agents.generation_v2 import GenerationAgent  # noqa: E402

# ═══════════════════════════════════════════════════════════
# 测试数据（全部 mock，不调用真实大模型）
# ═══════════════════════════════════════════════════════════

#: 学习者学情数据（含前置测试，覆盖 _format_pretests 非空分支）
LEARNER_DATA = {
    "education_level": "本科",
    "major": "计算机科学",
    "school": "示例大学",
    "work_years": 1,
    "industry": "软件",
    "positions": ["初级后端工程师"],
    "skills_used": ["Python", "SQL"],
    "pretest_results": [
        {
            "test_name": "Python基础",
            "total_score": 80,
            "max_score": 100,
            "topic_scores": {"语法": 90, "高级特性": 70},
        },
    ],
    "learning_goal": "掌握 LangGraph 开发 AI Agent",
}

#: 学情诊断的正常 mock 返回
VALID_DIAGNOSIS = {
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

#: 知识生成单份资源的正常 mock 返回
#: 字段与 schemas.GeneratedResource 对齐；generation_v2 只补 resource_type /
#: resource_id / learner_id / target_skill_gaps，其余字段按 LLM 原样透传，
#: 因此 mock 需要给全字段才能断言结构完整。
VALID_RESOURCE = {
    "title": "LangGraph 入门讲义（mock）",
    "content": "# LangGraph 入门讲义\n\n这是 mock 返回的 Markdown 内容。",
    "citations": [],
    "difficulty_level": "beginner",
    "estimated_duration_minutes": 30,
    "prerequisites": [],
    "target_skill_gaps": ["LangGraph状态图"],
    "key_takeaways": ["理解 StateGraph", "掌握节点与边"],
}

#: 通过 quiz 契约校验的有效题库内容（5 题，含 A-D 选项 / 答案 / 解析）
VALID_QUIZ_CONTENT = "\n\n".join(
    "\n".join(
        [
            f"Question {n}: Before task {n}, which operating setting keeps the equipment safe?",
            "A. Run at full speed",
            "B. Use the approved safe setting",
            "C. Disable the protection",
            "D. Ignore the warning",
            "Answer: B",
            "Explanation: The approved setting keeps the operation within the "
            "documented safety limits.",
        ]
    )
    for n in range(1, 6)
)

#: 知识生成所需的 KB 素材（空 KB 生成关闭守卫要求至少 1 条有效 chunk 才进入生成）
GEN_KB_CHUNKS = [
    {
        "doc_id": "langgraph_intro.md",
        "doc_title": "LangGraph 入门",
        "chunk_index": 0,
        "content": "LangGraph is a library built by the LangChain team for stateful agents.",
        "relevance_score": 0.95,
    },
]

#: 保真修正的正常 mock 返回（含 _infos_applied 控制 info 采纳数量）
CORRECTED_OK = {
    "title": "LangGraph 入门讲义（修正）",
    "content": "# LangGraph 入门讲义\n\nLangGraph 是 LangChain 团队开发的库。",
    "difficulty_level": "beginner",
    "citations": [
        {
            "doc_id": "langgraph_intro.md",
            "chunk_index": 2,
            "original_text": "LangGraph is a library built by the LangChain team",
            "relevance_score": 0.95,
        },
    ],
    "key_takeaways": ["理解 StateGraph", "掌握节点与边"],
    "correction_summary": "修正了 LangGraph 归属错误",
    "_infos_applied": 1,  # 2 条 info 只采纳 1 条 → 同时覆盖 accepted / skipped 分支
}

#: 保真修正的完整输入 state
CORRECTION_STATE = {
    "diagnosis_result": VALID_DIAGNOSIS,
    "generated_resources": [
        {
            "resource_id": "res-001",
            "resource_type": "lecture",
            "title": "LangGraph 入门讲义",
            "content": "# LangGraph 入门讲义\n\nLangGraph 是 Google 开发的框架。",
            "difficulty_level": "beginner",
            "citations": [],
            "key_takeaways": ["理解 StateGraph"],
        },
    ],
    "audit_result": [
        {
            "verdict": "needs_revision",
            "issues": [
                {
                    "severity": "error",
                    "detail": "LangGraph 是 LangChain 团队开发的，不是 Google",
                    "kb_evidence": "LangGraph is a library built by the LangChain team",
                },
                {"severity": "warning", "detail": "缺少对 StateGraph 三要素的说明"},
                {"severity": "info", "detail": "建议加入生活类比"},
                {"severity": "info", "detail": "建议补充进阶阅读"},
            ],
        },
    ],
    "retrieved_chunks": [
        {
            "doc_id": "langgraph_intro.md",
            "chunk_index": 2,
            "content": (
                "LangGraph is a library built by the LangChain team "
                "for building stateful, multi-actor applications with LLMs."
            ),
            "relevance_score": 0.95,
        },
    ],
}

#: 生成资源必需的字段（与 schemas.GeneratedResource 对齐）
GENERATION_FIELDS = (
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


# ═══════════════════════════════════════════════════════════
# 通用运行辅助
# ═══════════════════════════════════════════════════════════


def _patch_call_llm_json(agent, behavior: dict):
    """把 agent.call_llm_json 替换为 AsyncMock（LLM 全部 mock，不发真实请求）。

    生成 / 修正 Agent 会改写 call_llm_json 返回的 dict（补 resource_id 等字段），
    因此把 return_value 转换为每次调用返回全新 deepcopy 的 side_effect，
    避免多份资源共享同一 dict 对象导致字段相互污染。
    """
    if "return_value" in behavior:
        payload = behavior.pop("return_value")
        behavior["side_effect"] = lambda *a, **k: deepcopy(payload)
    patcher = patch.object(agent, "call_llm_json", AsyncMock(**behavior))
    patcher.start()
    return patcher


def _no_crash(result: dict) -> None:
    """异常场景通用断言：代理必须正常返回 dict，不得崩溃/抛出。"""
    assert isinstance(result, dict)


# ═══════════════════════════════════════════════════════════
# DiagnosisAgent — 学情诊断 Agent
# ═══════════════════════════════════════════════════════════


class TestDiagnosisAgent:
    """学情诊断 Agent：正常 / 边界 / 异常（3 种 LLM 异常 + 校验错误分支）。"""

    def _run(self, state: dict, behavior: dict) -> tuple[dict, AsyncMock]:
        agent = DiagnosisAgent()
        patcher = _patch_call_llm_json(agent, behavior)
        try:
            return asyncio.run(agent.run(state)), patcher.new
        finally:
            patcher.stop()

    # ── 正常输入 ──
    def test_normal_process(self):
        """正常输入：完整 learner_data → 输出 diagnosis_result + diagnosis_completed=True。"""
        m = AsyncMock(return_value=dict(VALID_DIAGNOSIS))
        state = {"learner_data": dict(LEARNER_DATA), "task_id": "t1"}
        agent = DiagnosisAgent()
        patcher = patch.object(agent, "call_llm_json", m)
        patcher.start()
        try:
            result = asyncio.run(agent.run(state))
        finally:
            patcher.stop()

        # process 流程：输出已写入 state
        assert result["diagnosis_completed"] is True
        # 确定性兜底以客观前置测试为准：80/100=80% → advanced；岗位「初级后端工程师」
        # 非专家/非直接操作岗 → theory_first（覆盖 mock 的 "beginner"/"practice_first"）
        assert result["diagnosis_result"]["recommended_difficulty"] == "advanced"
        assert result["diagnosis_result"]["learning_style"] == "theory_first"
        # 生命周期日志以 complete 结尾
        assert result["agent_log"][-1]["stage"] == "complete"
        # 未进入错误分支
        assert result.get("status") != "error"
        # LLM 收到完整 prompt（覆盖 _build_prompt / _format_pretests 非空分支）
        prompt = m.await_args.args[0]
        assert "本科" in prompt
        assert "初级后端工程师" in prompt
        assert "Python基础" in prompt and "80/100" in prompt

    # ── 边界输入 ──
    def test_empty_learner_data(self):
        """边界：learner_data 为空 dict → 仍能构建 prompt 并完成诊断，不崩溃。"""
        m = AsyncMock(return_value=dict(VALID_DIAGNOSIS))
        state = {"learner_data": {}}
        agent = DiagnosisAgent()
        patcher = patch.object(agent, "call_llm_json", m)
        patcher.start()
        try:
            result = asyncio.run(agent.run(state))
        finally:
            patcher.stop()

        assert result["diagnosis_completed"] is True
        assert result["diagnosis_result"]["recommended_difficulty"] == "beginner"
        # 空前置测试 → "无前置测试数据" 分支
        prompt = m.await_args.args[0]
        assert "无前置测试数据" in prompt

    def test_missing_learner_data_validation_error(self):
        """边界/错误输入：缺少必需字段 learner_data → 走校验错误分支，返回 status=error。"""
        m = AsyncMock(return_value=dict(VALID_DIAGNOSIS))
        agent = DiagnosisAgent()
        patcher = patch.object(agent, "call_llm_json", m)
        patcher.start()
        try:
            result = asyncio.run(agent.run({"task_id": "t1"}))
        finally:
            patcher.stop()

        # 校验失败 → 统一错误返回分支
        assert result["status"] == "error"
        assert result["agent_log"][-1]["stage"] == "validation"
        assert "learner_data" in result["agent_log"][-1]["message"]
        # 校验短路：未调用 LLM
        m.assert_not_awaited()

    # ── 异常输入：3 种 LLM 异常 ──
    def test_llm_timeout_returns_error_dict(self):
        """异常①调用超时：BaseAgent.run() 捕获 → 统一返回 {"error", "status":"error"}，不崩溃。"""
        m = AsyncMock(side_effect=asyncio.TimeoutError("LLM 调用超时"))
        state = {"learner_data": dict(LEARNER_DATA)}
        agent = DiagnosisAgent()
        patcher = patch.object(agent, "call_llm_json", m)
        patcher.start()
        try:
            result = asyncio.run(agent.run(state))
        finally:
            patcher.stop()

        _no_crash(result)
        assert result["status"] == "error"
        assert "error" in result and "超时" in result["error"]
        assert result["error_type"] == "TimeoutError"

    def test_llm_invalid_json_graceful(self):
        """异常②返回非法 JSON：解析失败返回 {} 风格的错误标记 → 不崩溃，诊断结果照常回写。"""
        m = AsyncMock(return_value={"_parse_error": True, "raw": "这不是合法 JSON"})
        state = {"learner_data": dict(LEARNER_DATA)}
        agent = DiagnosisAgent()
        patcher = patch.object(agent, "call_llm_json", m)
        patcher.start()
        try:
            result = asyncio.run(agent.run(state))
        finally:
            patcher.stop()

        _no_crash(result)
        assert result["diagnosis_completed"] is True
        assert result["diagnosis_result"] == {"_parse_error": True, "raw": "这不是合法 JSON"}
        assert result.get("status") != "error"

    def test_llm_empty_content_graceful(self):
        """异常③返回空内容：call_llm_json 返回 {} → 不崩溃，诊断结果为空 dict。"""
        m = AsyncMock(return_value={})
        state = {"learner_data": dict(LEARNER_DATA)}
        agent = DiagnosisAgent()
        patcher = patch.object(agent, "call_llm_json", m)
        patcher.start()
        try:
            result = asyncio.run(agent.run(state))
        finally:
            patcher.stop()

        _no_crash(result)
        assert result["diagnosis_completed"] is True
        assert result["diagnosis_result"] == {}
        assert result.get("status") != "error"

    # ── 置信度规整（避免真实 LLM 保守打分误触发闸门降级）──
    def test_normalization_adds_overall_confidence(self):
        """诊断结构完整 → 自动补全 overall_confidence（>= 0.6，不触发闸门降级）。"""
        m = AsyncMock(return_value=dict(VALID_DIAGNOSIS))
        agent = DiagnosisAgent()
        patcher = patch.object(agent, "call_llm_json", m)
        patcher.start()
        try:
            result = asyncio.run(agent.run({"learner_data": dict(LEARNER_DATA)}))
        finally:
            patcher.stop()

        conf = result["diagnosis_result"]["overall_confidence"]
        assert 0.6 <= conf <= 1.0

    def test_normalization_keeps_existing_confidence(self):
        """LLM 已给出合法 overall_confidence → 原样保留，不覆盖。"""
        diag = dict(VALID_DIAGNOSIS)
        diag["overall_confidence"] = 0.6
        m = AsyncMock(return_value=diag)
        agent = DiagnosisAgent()
        patcher = patch.object(agent, "call_llm_json", m)
        patcher.start()
        try:
            result = asyncio.run(agent.run({"learner_data": dict(LEARNER_DATA)}))
        finally:
            patcher.stop()

        assert result["diagnosis_result"]["overall_confidence"] == 0.6

    def test_normalization_passthrough_on_parse_error(self):
        """JSON 解析失败 / 空结果 → 原样透传，不补 overall_confidence（交由闸门 FALLBACK）。"""
        agent = DiagnosisAgent()
        assert agent._normalize_diagnosis({}, {}) == {}
        parsed = {"_parse_error": True, "raw": "not json"}
        assert agent._normalize_diagnosis(parsed, {}) == parsed
        assert agent._normalize_diagnosis(None, {}) is None

    def test_calc_confidence_score_breaks(self):
        """_calc_overall_confidence 分段打分：knowledge_map 5+/3+/1+ 三档与下限 0.05。"""
        agent = DiagnosisAgent()
        base = {
            "learning_style": "practice_first",
            "recommended_difficulty": "beginner",
            "summary": "画像总结",
            "skill_gaps": [{"topic": "x"}],
        }
        map5 = {f"k{i}": {"level": 0.1} for i in range(5)}
        map3 = {f"k{i}": {"level": 0.1} for i in range(3)}
        map1 = {"k0": {"level": 0.1}}

        with5 = agent._calc_overall_confidence({**base, "knowledge_map": map5}, {})
        with3 = agent._calc_overall_confidence({**base, "knowledge_map": map3}, {})
        with1 = agent._calc_overall_confidence({**base, "knowledge_map": map1}, {})
        # 0.30 / 0.20 / 0.10 三档差异
        assert with5 == with3 + 0.10 == with1 + 0.20
        # 无任何证据 → 下限 0.05（对齐闸门稀疏模式阈值）
        assert agent._calc_overall_confidence({}, {}) == 0.05
        # 非 dict 的 knowledge_map 条目不计入
        assert agent._calc_overall_confidence({"knowledge_map": {"k": 0.5}}, {}) == 0.05


# ═══════════════════════════════════════════════════════════
# GenerationAgent — 领域知识生成 Agent
# ═══════════════════════════════════════════════════════════


class TestGenerationAgent:
    """知识生成 Agent：正常 / 边界 / 异常（3 种 LLM 异常）。"""

    def _run(self, state: dict, behavior: dict) -> tuple[dict, AsyncMock]:
        agent = GenerationAgent()
        patcher = _patch_call_llm_json(agent, behavior)
        try:
            return asyncio.run(agent.run(state)), patcher.new
        finally:
            patcher.stop()

    # ── 正常输入 ──
    def test_normal_generates_3(self):
        """正常输入：默认 3 种资源类型 → 产出 3 条资源，字段齐全。"""
        result, _ = self._run(
            {"diagnosis_result": dict(VALID_DIAGNOSIS), "retrieved_chunks": GEN_KB_CHUNKS},
            {"return_value": dict(VALID_RESOURCE)},
        )
        resources = result["generated_resources"]
        assert 1 <= len(resources) <= 3
        assert len(resources) == 3
        for res in resources:
            for key in GENERATION_FIELDS:
                assert key in res, f"资源缺少字段: {key}"
        assert [r["resource_type"] for r in resources] == ["lecture", "guide", "quiz"]
        # v2 走 BaseAgent.run()：正常流程以 complete 阶段日志收尾
        assert result["agent_log"][-1]["stage"] == "complete"

    # ── 边界输入 ──
    def test_single_resource_type(self):
        """边界：只请求 1 种类型 → 产出 1 条 lecture 资源。"""
        result, _ = self._run(
            {
                "diagnosis_result": dict(VALID_DIAGNOSIS),
                "resource_types": ["lecture"],
                "retrieved_chunks": GEN_KB_CHUNKS,
            },
            {"return_value": dict(VALID_RESOURCE)},
        )
        assert len(result["generated_resources"]) == 1
        assert result["generated_resources"][0]["resource_type"] == "lecture"

    def test_resource_count_capped_at_3(self):
        """边界：请求超过 3 种类型 → 按 MAX_RESOURCES 截断为 3 条。"""
        result, _ = self._run(
            {
                "diagnosis_result": dict(VALID_DIAGNOSIS),
                "resource_types": ["lecture", "guide", "quiz", "project"],
                "retrieved_chunks": GEN_KB_CHUNKS,
            },
            {"return_value": dict(VALID_RESOURCE)},
        )
        assert len(result["generated_resources"]) == 3

    def test_empty_diagnosis_still_generates(self):
        """边界：诊断结果为空 dict → 缺省值兜底，仍能生成 1 条资源。"""
        result, _ = self._run(
            {
                "diagnosis_result": {},
                "resource_types": ["guide"],
                "retrieved_chunks": GEN_KB_CHUNKS,
            },
            {"return_value": dict(VALID_RESOURCE)},
        )
        assert len(result["generated_resources"]) == 1
        assert result["generated_resources"][0]["resource_type"] == "guide"

    def test_fmt_gaps_float_type_protection(self):
        """边界：skill_gaps 的数值是非法字符串 → float() 类型保护回退 0.0/1.0，不崩溃。"""
        diagnosis = {
            "skill_gaps": [
                {
                    "topic": "A",
                    "current_level": "abc",
                    "target_level": "xyz",
                    "priority": "critical",
                    "reason": "原因A",
                },
                {
                    "topic": "B",
                    "current_level": 0.5,
                    "target_level": 1.0,
                    "priority": "high",
                    "reason": "原因B",
                },
            ],
            "recommended_difficulty": "beginner",
            "learning_style": "theory_first",
            "summary": "学习目标",
        }
        result, m = self._run(
            {
                "diagnosis_result": diagnosis,
                "resource_types": ["lecture"],
                "retrieved_chunks": GEN_KB_CHUNKS,
            },
            {"return_value": dict(VALID_RESOURCE)},
        )
        assert len(result["generated_resources"]) == 1
        prompt = m.await_args.args[0]
        # 非法字符串被回退为 0.0 / 1.0
        assert "当前 0.0 → 目标 1.0" in prompt
        assert "当前 0.5 → 目标 1.0" in prompt

    # ── 异常输入：3 种 LLM 异常 ──
    def test_llm_invalid_json_skipped(self):
        """异常②返回非法 JSON：解析失败 → 该类型资源跳过，记录 json_parse_failed，不崩溃。"""
        result, _ = self._run(
            {
                "diagnosis_result": dict(VALID_DIAGNOSIS),
                "resource_types": ["lecture"],
                "retrieved_chunks": GEN_KB_CHUNKS,
            },
            {"return_value": {"_parse_error": True, "raw": "not json"}},
        )
        _no_crash(result)
        assert result["generated_resources"] == []
        assert len(result["generation_errors"]) == 1
        assert result["generation_errors"][0]["error"] == "json_parse_failed"

    def test_llm_empty_content_skipped(self):
        """异常③返回空内容：call_llm_json 返回 {} → 该类型资源跳过，不崩溃。"""
        result, _ = self._run(
            {
                "diagnosis_result": dict(VALID_DIAGNOSIS),
                "resource_types": ["lecture"],
                "retrieved_chunks": GEN_KB_CHUNKS,
            },
            {"return_value": {}},
        )
        _no_crash(result)
        assert result["generated_resources"] == []
        assert len(result["generation_errors"]) == 1

    def test_llm_timeout_recorded_as_error(self):
        """异常①调用超时：v2 走 BaseAgent.run() 的异常隔离。

        超时不向上传播，而是被 process() 的单资源 try/except 捕获，
        记录到 generation_errors；单资源失败不置 status="error"。
        """
        result, _ = self._run(
            {
                "diagnosis_result": dict(VALID_DIAGNOSIS),
                "resource_types": ["lecture"],
                "retrieved_chunks": GEN_KB_CHUNKS,
            },
            {"side_effect": asyncio.TimeoutError("LLM 调用超时")},
        )
        _no_crash(result)
        assert result["generated_resources"] == []
        assert len(result["generation_errors"]) == 1
        assert "超时" in result["generation_errors"][0]["error"]
        assert result.get("status") != "error"

    def test_partial_success_records_errors(self):
        """异常/边界：3 种类型中 1 个失败 → 部分成功，其余照常产出，errors 只记失败项。"""
        payloads = [
            dict(VALID_RESOURCE),
            {"_parse_error": True, "raw": "not json"},
            {"content": VALID_QUIZ_CONTENT},
        ]
        result, _ = self._run(
            {"diagnosis_result": dict(VALID_DIAGNOSIS), "retrieved_chunks": GEN_KB_CHUNKS},
            {"side_effect": payloads},
        )
        assert len(result["generated_resources"]) == 2
        assert [r["resource_type"] for r in result["generated_resources"]] == [
            "lecture",
            "quiz",
        ]
        assert len(result["generation_errors"]) == 1
        assert result["generation_errors"][0]["resource_type"] == "guide"

    def test_fmt_knowledge_base_private_helper(self):
        """私有 _fmt_knowledge_base：空 / 去重 / 截断 / 上限 6 条四个分支。"""
        agent = GenerationAgent()

        # 空 chunk → 无资料提示文案
        assert "无可用知识库素材" in agent._fmt_knowledge_base([])

        # 同 doc_title 去重（保留第一个）+ 上限 6 条
        chunks = [{"doc_title": f"doc-{i % 3}", "content": "c" * 50} for i in range(10)]
        text = agent._fmt_knowledge_base(chunks)
        # doc-0 / doc-1 / doc-2 各去重后只出现一次
        assert text.count("### 资料") == 3
        assert "doc-0" in text and "doc-1" in text and "doc-2" in text

        # >500 字符内容被截断并加省略号
        long_chunk = [{"doc_title": "long", "content": "x" * 600}]
        assert agent._fmt_knowledge_base(long_chunk).endswith("…")

        # ≥6 个不同 doc_title → 触发上限 6 条截断分支
        six_plus = [{"doc_title": f"doc-{i}", "content": "c" * 10} for i in range(10)]
        assert agent._fmt_knowledge_base(six_plus).count("### 资料") == 6

        # 缺 doc_title / content 字段 → 缺省值兜底
        ragged = [{"content": "内容但无标题"}]
        assert "未知文档" in agent._fmt_knowledge_base(ragged)


# ═══════════════════════════════════════════════════════════
# CorrectionAgent — 保真修正 Agent
# ═══════════════════════════════════════════════════════════


class TestCorrectionAgent:
    """保真修正 Agent：正常 / 边界 / 异常（3 种 LLM 异常）。"""

    def _run(self, state: dict, behavior: dict | None = None) -> tuple[dict, AsyncMock]:
        agent = CorrectionAgent()
        if behavior is None:
            return asyncio.run(agent.run(state)), AsyncMock()  # 无 mock 时第二返回值不使用
        patcher = _patch_call_llm_json(agent, behavior)
        try:
            return asyncio.run(agent.run(state)), patcher.new
        finally:
            patcher.stop()

    # ── 正常输入 ──
    def test_normal_corrects_issues(self):
        """正常输入：error/warning/info 逐条修正，统计与日志正确。"""
        result, m = self._run(deepcopy(CORRECTION_STATE), {"return_value": dict(CORRECTED_OK)})

        # 修正资源已写入且带 _was_corrected 标记
        cr = result["corrected_resources"]
        assert len(cr) == 1
        assert cr[0]["_was_corrected"] is True
        assert "LangChain 团队开发" in cr[0]["content"]

        # 修正统计
        stats = result["correction_stats"]
        assert stats["total_resources"] == 1
        assert stats["resources_corrected"] == 1
        assert stats["errors_fixed"] == 1
        assert stats["warnings_addressed"] == 1
        assert stats["infos_applied"] == 2  # 2 条 info
        assert stats["total_issues"] == 4

        # 修正日志覆盖 replaced / adjusted / accepted / skipped 四种 action
        actions = {log["action"] for log in result["correction_log"]}
        assert {"replaced", "adjusted", "accepted", "skipped"} <= actions
        error_logs = [entry for entry in result["correction_log"] if entry["severity"] == "error"]
        assert error_logs[0]["correction_basis"] == "knowledge_base"  # kb_evidence 存在

    def test_llm_calls_prompt_contains_context(self):
        """正常输入：prompt 携带学习者难度 / 学习风格 / KB 素材与 issue 明细。"""
        result, m = self._run(deepcopy(CORRECTION_STATE), {"return_value": dict(CORRECTED_OK)})
        prompt = m.await_args.args[0]
        # 结构化画像参数块（取代旧的「推荐难度/学习风格」自然语言行）
        assert '"difficulty": "beginner"' in prompt
        assert '"learning_style": "practice_first"' in prompt
        assert '"profile_tag": "custom"' in prompt
        assert "LangGraph is a library built by the LangChain team" in prompt
        assert "必须修正（error）" in prompt
        assert "尽量修正（warning）" in prompt
        assert "可选修正（info）" in prompt

    # ── 边界输入 ──
    def test_no_issues_skips_correction(self):
        """边界：审核无问题 → 原样返回资源，不调用 LLM。"""
        state = deepcopy(CORRECTION_STATE)
        state["audit_result"] = [{"verdict": "approved", "issues": [], "fact_check": {"items": []}}]
        m = AsyncMock(return_value={})
        agent = CorrectionAgent()
        patcher = patch.object(agent, "call_llm_json", m)
        patcher.start()
        try:
            result = asyncio.run(agent.run(state))
        finally:
            patcher.stop()

        assert result["corrected_resources"][0].get("_was_corrected") is None  # 原样
        assert result["correction_log"] == []
        m.assert_not_awaited()

    def test_empty_generated_resources(self):
        """边界：generated_resources 为空 → 空修正结果 + 空统计，不崩溃。"""
        state = {
            "diagnosis_result": dict(VALID_DIAGNOSIS),
            "generated_resources": [],
            "audit_result": [],
        }
        result, _ = self._run(state)
        assert result["corrected_resources"] == []
        assert result["correction_log"] == []
        stats = result["correction_stats"]
        assert stats == {
            "total_resources": 0,
            "resources_corrected": 0,
            "total_issues": 0,
            "errors_fixed": 0,
            "warnings_addressed": 0,
            "infos_applied": 0,
            "correction_time_ms": 0,
        }

    def test_audit_result_count_mismatch(self):
        """边界：audit_result 数量与资源不一致 → 记录 warning，仍能修正（无 issues 则原样）。"""
        state = deepcopy(CORRECTION_STATE)
        state["audit_result"] = []  # 0 份审核 vs 1 份资源
        result, m = self._run(state, {"return_value": dict(CORRECTED_OK)})
        # audit_report 为空 → 无 issues → _correct_one 原样返回，不调用 LLM
        assert len(result["corrected_resources"]) == 1
        assert result["corrected_resources"][0].get("_was_corrected") is None
        m.assert_not_awaited()

    def test_fact_check_failure_promoted_to_error(self):
        """边界：fact_check 不准确项被提升为 error 并进入修正与统计。"""
        state = deepcopy(CORRECTION_STATE)
        state["audit_result"] = [
            {
                "verdict": "needs_revision",
                "issues": [],
                "fact_check": {
                    "items": [
                        {
                            "claim": "LangGraph 是 Google 开发",
                            "is_accurate": False,
                            "explanation": "应为 LangChain 团队",
                            "evidence_from_kb": "LangGraph is built by LangChain",
                        },
                    ]
                },
            }
        ]
        result, m = self._run(state, {"return_value": dict(CORRECTED_OK)})
        assert result["correction_stats"]["errors_fixed"] == 1
        error_logs = [entry for entry in result["correction_log"] if entry["severity"] == "error"]
        assert error_logs and error_logs[0]["correction_basis"] == "knowledge_base"
        # 提升后的 error 出现在修正 prompt 中
        prompt = m.await_args.args[0]
        assert "事实校验不通过" in prompt

    def test_downgrade_mode_consistency_check(self):
        """边界：downgrade_mode=True → 无 KB，纯规则一致性检查，不调用 LLM。

        Phase 3 起降级模式走 _downgrade_check（只检查不自动改内容），
        覆盖四项规则：前后矛盾 / 术语不一致 / 缺失 import / 步骤跳跃。
        """
        state = deepcopy(CORRECTION_STATE)
        state["downgrade_mode"] = True
        state["diagnosis_result"] = {
            **VALID_DIAGNOSIS,
            "skill_gaps": [
                {
                    "topic": "LangGraph",
                    "priority": "critical",
                    "current_level": 0.1,
                    "target_level": 0.9,
                    "reason": "r",
                }
            ],
        }
        state["generated_resources"][0]["content"] = (
            "LangGraph 支持状态机。langgraph 不支持状态机。\n\n"
            "1. 第一步\n2. 第二步\n4. 第四步\n\n"
            "```python\nimport pandas as pd\ndf = pd.DataFrame()\nplt.figure()\n```\n"
        )
        m = AsyncMock(return_value={})
        agent = CorrectionAgent()
        patcher = patch.object(agent, "call_llm_json", m)
        patcher.start()
        try:
            result = asyncio.run(agent.run(state))
        finally:
            patcher.stop()

        # 降级模式不调用 LLM
        m.assert_not_awaited()
        cr = result["corrected_resources"][0]
        assert cr["_consistency_checked"] is True
        assert cr["_downgrade_mode"] is True
        # 只检查不自动改内容（不做事实判断）
        assert "不支持状态机" in cr["content"] and "第四步" in cr["content"]
        # consistency_report 覆盖四项规则
        report = result["consistency_report"]
        types = {issue["check_type"] for issue in report}
        assert {"missing_import", "step_jump", "term_inconsistency", "contradiction"} <= types
        assert result["correction_stats"]["consistency_findings"] == len(report)
        # 日志 action=detected，correction_basis=consistency_check
        assert all(log["action"] == "detected" for log in result["correction_log"])
        assert all(
            log["correction_basis"] == "consistency_check" for log in result["correction_log"]
        )

    def test_no_kb_chunks(self):
        """边界：retrieved_chunks 为空 → prompt 提示无知识库素材。"""
        state = deepcopy(CORRECTION_STATE)
        state["retrieved_chunks"] = []
        result, m = self._run(state, {"return_value": dict(CORRECTED_OK)})
        assert "无知识库参考素材" in m.await_args.args[0]

    def test_multiple_resources_and_structure_guides(self):
        """边界：多类型资源 → 每种资源结构模板正确、>8 个 KB chunk 截断提示。"""
        state = deepcopy(CORRECTION_STATE)
        state["generated_resources"] = [
            {
                "resource_id": "res-lecture",
                "resource_type": "lecture",
                "title": "讲义",
                "content": "内容",
                "difficulty_level": "beginner",
                "citations": [],
                "key_takeaways": [],
            },
            {
                "resource_id": "res-guide",
                "resource_type": "guide",
                "title": "实操",
                "content": "内容",
                "difficulty_level": "beginner",
                "citations": [],
                "key_takeaways": [],
            },
            {
                "resource_id": "res-quiz",
                "resource_type": "quiz",
                "title": "测试",
                "content": "内容",
                "difficulty_level": "beginner",
                "citations": [],
                "key_takeaways": [],
            },
            {
                "resource_id": "res-custom",
                "resource_type": "custom",
                "title": "自定义",
                "content": "内容",
                "difficulty_level": "beginner",
                "citations": [],
                "key_takeaways": [],
            },
        ]
        # 每份审核报告带 1 个 issue → 每份资源都会调用 LLM（触发 4 次 prompt 构建）
        state["audit_result"] = [
            {"issues": [{"severity": "error", "detail": f"问题{i}", "kb_evidence": "kb"}]}
            for i in range(4)
        ]
        # 10 个 KB chunk → 覆盖 >8 截断分支
        state["retrieved_chunks"] = [
            {
                "doc_id": f"kb-{i}",
                "chunk_index": i,
                "content": f"chunk content {i}",
                "relevance_score": 0.9 - i * 0.01,
            }
            for i in range(10)
        ]
        result, m = self._run(state, {"return_value": dict(CORRECTED_OK)})

        assert len(result["corrected_resources"]) == 4
        prompts = [call.args[0] for call in m.await_args_list]
        assert any("保持 lecture 结构" in p for p in prompts)
        assert any("保持 guide 结构" in p for p in prompts)
        assert any("保持 quiz 结构" in p for p in prompts)
        assert any("保持原内容结构不变" in p for p in prompts)
        assert any("还有" in p and "chunks 未列出" in p for p in prompts)

    # ── 异常输入：3 种 LLM 异常 ──
    def test_llm_timeout_keeps_original(self):
        """异常①调用超时：单资源 try/except 兜底 → 保留原内容 + failed 日志，不崩溃。"""
        result, _ = self._run(
            deepcopy(CORRECTION_STATE),
            {"side_effect": asyncio.TimeoutError("LLM 调用超时")},
        )

        _no_crash(result)
        # 保留原内容，未被替换
        cr = result["corrected_resources"]
        assert cr[0]["content"] == "# LangGraph 入门讲义\n\nLangGraph 是 Google 开发的框架。"
        assert cr[0].get("_was_corrected") is None
        # 记录失败日志（severity=error / action=failed / 原因含超时）
        failed_log = result["correction_log"][0]
        assert failed_log["action"] == "failed"
        assert failed_log["severity"] == "error"
        assert "超时" in failed_log["error_detail"]
        # 说明：业务源码对"异常捕获"的失败只写日志、不累加 errors_fixed 统计
        # （errors_fixed 仅统计成功修正路径的 error 日志），这里如实断言为 0。
        assert result["correction_stats"]["errors_fixed"] == 0
        # process 整体正常返回（status 不置 error），不向上抛异常
        assert result.get("status") != "error"

    def test_llm_invalid_json_fallback(self):
        """异常②返回非法 JSON：_parse_error → 保留原内容 + json_parse_failed 兜底日志。"""
        result, _ = self._run(
            deepcopy(CORRECTION_STATE),
            {"return_value": {"_parse_error": True, "raw": "not json"}},
        )
        _no_crash(result)
        cr = result["corrected_resources"]
        assert cr[0]["content"] == "# LangGraph 入门讲义\n\nLangGraph 是 Google 开发的框架。"
        logs = result["correction_log"]
        assert any(
            entry["error_detail"] == "json_parse_failed" and entry["correction_basis"] == "failed"
            for entry in logs
        )

    def test_llm_empty_content_fallback(self):
        """异常③返回空内容：call_llm_json 返回 {} → 保留原内容 + 兜底日志，不崩溃。"""
        result, _ = self._run(deepcopy(CORRECTION_STATE), {"return_value": {}})
        _no_crash(result)
        cr = result["corrected_resources"]
        assert cr[0]["content"] == "# LangGraph 入门讲义\n\nLangGraph 是 Google 开发的框架。"
        assert any(
            entry["error_detail"] == "json_parse_failed" for entry in result["correction_log"]
        )

    def test_partial_corrected_result_falls_back(self):
        """异常/边界：LLM 返回缺字段的修正结果 → 缺失字段回退到原资源，不崩溃。"""
        result, _ = self._run(
            deepcopy(CORRECTION_STATE),
            {"return_value": {"title": "只改了标题"}},
        )
        _no_crash(result)
        cr = result["corrected_resources"][0]
        assert cr["_was_corrected"] is True
        assert cr["title"] == "只改了标题"
        original_content = "# LangGraph 入门讲义\n\nLangGraph 是 Google 开发的框架。"
        assert cr["content"] == original_content  # 回退原文
        assert cr["difficulty_level"] == "beginner"  # 回退原资源难度
        assert cr["key_takeaways"] == ["理解 StateGraph"]  # 回退原资源要点
        assert "_correction_summary" in cr  # 无 summary 时使用默认文案

    def test_private_format_helpers(self):
        """私有格式化工具直接单测：覆盖业务路径中因三元表达式短路而不到达的分支。

        业务路径用 ``self._fmt_issues(x) if x else "无"`` 短路，空列表从不进入
        _fmt_issues 的空分支；此处直接调用私有方法以覆盖该分支与 .get 缺省值。
        """
        agent = CorrectionAgent()

        # 空列表分支
        assert agent._fmt_issues([]) == "无"
        # 非空列表：kb_evidence 有无、detail 有无、severity 缺省回退
        text = agent._fmt_issues(
            [
                {"severity": "error", "detail": "d1", "kb_evidence": "kb1"},
                {"severity": "warning", "detail": "d2"},
                {"detail": "无 severity"},
            ]
        )
        assert text == ("1. [error] d1\n   KB 原文: kb1\n2. [warning] d2\n3. [unknown] 无 severity")
        # detail 缺省回退为 str(iss)
        assert "[error] {'severity': 'error'}" in agent._fmt_issues([{"severity": "error"}])
        # KB 空 / 结构模板缺省
        assert agent._fmt_kb_chunks([]).startswith("⚠️ 无知识库参考素材")
        assert agent._fmt_structure_guide("unknown") == "保持原内容结构不变"

    # ── Phase 3：辩论裁决落地 + 资源溯源绑定（纯数据处理，不调用 LLM）──
    def test_arbitration_replace_lands_kb_text(self):
        """裁决 replace：用 KB 原文替换错误断言并标注来源，追加事实溯源块。"""
        state = deepcopy(CORRECTION_STATE)
        state["debate_result"] = {
            "adjudications": [
                {
                    "resource_id": "res-001",
                    "claim": "LangGraph 是 Google 开发的框架。",
                    "decision": "replace",
                    "replacement_text": "LangGraph is a library built by the LangChain team",
                    "doc_id": "langgraph_intro.md",
                    "chunk_index": 2,
                    "evidence": "LangGraph is a library built by the LangChain team",
                }
            ]
        }
        result, m = self._run(state, {"return_value": {}})
        # 纯数据处理：不调用 LLM
        m.assert_not_awaited()
        cr = result["corrected_resources"][0]
        assert cr["_was_corrected"] is True
        assert cr["_arbitration_applied"] is True
        # KB 原文替换 + 来源标注
        assert "LangGraph is a library built by the LangChain team" in cr["content"]
        assert "[来源: langgraph_intro.md, 段落 2]" in cr["content"]
        assert "是 Google 开发" not in cr["content"]
        # 溯源绑定（lecture）：【生成陈述】【KB原文出处】【来源】
        assert "## 事实溯源" in cr["content"]
        assert "【生成陈述】LangGraph is a library built by the LangChain team" in cr["content"]
        assert "【来源】langgraph_intro.md#chunk_2" in cr["content"]
        # 统计与日志
        assert result["correction_stats"]["replacements_applied"] == 1
        assert any(log["action"] == "replaced" for log in result["correction_log"])
        assert result["correction_log"][0]["correction_basis"] == "arbitration"

    def test_arbitration_delete_removes_sentence(self):
        """裁决 delete：删除无权威参考支撑的整句（D1 规则）。"""
        state = deepcopy(CORRECTION_STATE)
        state["generated_resources"][0]["content"] = (
            "# LangGraph 入门讲义\n\nLangGraph 是 Google 开发的框架。这是第二句保留内容。\n"
        )
        state["debate_result"] = {
            "adjudications": [
                {
                    "resource_id": "res-001",
                    "claim": "LangGraph 是 Google 开发的框架。",
                    "decision": "delete",
                    "doc_id": "unverified.md",
                    "chunk_index": 0,
                }
            ]
        }
        result, m = self._run(state, {"return_value": {}})
        m.assert_not_awaited()
        cr = result["corrected_resources"][0]
        assert cr["_was_corrected"] is True
        assert cr["_arbitration_applied"] is True
        # 被裁决语句整句删除，其余内容保留
        assert "LangGraph 是 Google 开发" not in cr["content"]
        assert "这是第二句保留内容" in cr["content"]
        assert result["correction_stats"]["deletions_applied"] == 1
        assert result["correction_log"][0]["action"] == "deleted"

    def test_arbitration_keep_marks_source(self):
        """裁决 keep：保留原文并在断言后追加来源标注。"""
        state = deepcopy(CORRECTION_STATE)
        state["generated_resources"][0]["content"] = (
            "# LangGraph 入门讲义\n\nLangGraph 是 LangChain 团队开发的框架。\n"
        )
        state["debate_result"] = {
            "adjudications": [
                {
                    "resource_id": "res-001",
                    "claim": "LangGraph 是 LangChain 团队开发的框架。",
                    "decision": "keep",
                    "doc_id": "langgraph_intro.md",
                    "chunk_index": 2,
                    "evidence": "LangGraph is a library built by the LangChain team",
                }
            ]
        }
        result, m = self._run(state, {"return_value": {}})
        m.assert_not_awaited()
        cr = result["corrected_resources"][0]
        assert "（来源：langgraph_intro.md，段落 2）" in cr["content"]
        # 溯源绑定：keep 断言也作为事实点
        assert "## 事实溯源" in cr["content"]
        assert result["correction_stats"]["keeps_sourced"] == 1
        assert any(log["action"] == "kept" for log in result["correction_log"])

    def test_arbitration_replace_claim_not_found_appends_correction(self):
        """裁决 replace 但断言未定位 → 追加更正声明（不静默丢弃）。"""
        state = deepcopy(CORRECTION_STATE)
        state["generated_resources"][0]["content"] = (
            "# LangGraph 入门讲义\n\nLangGraph 是 Google 开发的框架。\n"
        )
        state["debate_result"] = {
            "adjudications": [
                {
                    "resource_id": "res-001",
                    "claim": "完全不存在于内容中的断言。",
                    "decision": "replace",
                    "replacement_text": "LangGraph is built by LangChain",
                    "doc_id": "kb.md",
                    "chunk_index": 1,
                }
            ]
        }
        result, m = self._run(state, {"return_value": {}})
        m.assert_not_awaited()
        cr = result["corrected_resources"][0]
        assert "更正声明" in cr["content"]
        assert "LangGraph is built by LangChain" in cr["content"]
        assert result["correction_stats"]["replacements_applied"] == 1
        assert any(log["action"] == "replaced_appended" for log in result["correction_log"])

    def test_quiz_skips_traceability_binding(self):
        """quiz 资源：只落实 keep 来源标注，不追加事实溯源块。"""
        state = deepcopy(CORRECTION_STATE)
        state["generated_resources"][0]["resource_type"] = "quiz"
        state["generated_resources"][0]["content"] = "问题：LangGraph 是谁开发的？\n"
        state["debate_result"] = {
            "adjudications": [
                {
                    "resource_id": "res-001",
                    "claim": "问题：LangGraph 是谁开发的？",
                    "decision": "keep",
                    "doc_id": "kb.md",
                    "chunk_index": 0,
                }
            ]
        }
        result, m = self._run(state, {"return_value": {}})
        m.assert_not_awaited()
        cr = result["corrected_resources"][0]
        assert "（来源：kb.md，段落 0）" in cr["content"]  # keep 标注生效
        assert "## 事实溯源" not in cr["content"]  # 非讲义/指南不绑定溯源块

    def test_normalize_adjudications_variants(self):
        """裁决规范化：dict / 扁平 list / DebateRecord rounds 三种形态 → 统一三态。"""
        agent = CorrectionAgent()

        # dict 形态（adjudications），decision 别名映射
        r1 = agent._normalize_adjudications(
            {
                "adjudications": [
                    {"resource_id": "r1", "claim": "A", "decision": "support_agent2"},
                    {
                        "resource_id": "r1",
                        "claim": "B",
                        "decision": "support_agent3",
                        "kb_text": "KB-B",
                    },
                    {"resource_id": "r1", "claim": "C", "decision": "uncovered"},
                    {"resource_id": "r1", "claim": "D", "decision": "weird-unknown"},
                ]
            }
        )
        decisions = {a["claim"]: a["decision"] for a in r1}
        assert decisions == {"A": "keep", "B": "replace", "C": "delete", "D": "keep"}

        # DebateRecord rounds 形态（concede→delete / accept_challenge→replace / rebut→keep）
        r2 = agent._normalize_adjudications(
            {
                "resource_id": "r2",
                "rounds": [
                    {"challenge": {"claim": "X"}, "defense": {"action": "concede"}},
                    {
                        "challenge": {"claim": "Y", "evidence_from_kb": "KB-Y"},
                        "defense": {"action": "accept_challenge"},
                    },
                    {"challenge": {"claim": "Z"}, "defense": {"action": "rebut"}},
                ],
            }
        )
        decisions2 = {a["claim"]: a["decision"] for a in r2}
        assert decisions2 == {"X": "delete", "Y": "replace", "Z": "keep"}
        # replace 且无 KB 原文 → 按 D1 降为 delete
        r3 = agent._normalize_adjudications(
            {
                "resource_id": "r3",
                "rounds": [
                    {"challenge": {"claim": "W"}, "defense": {"action": "accept_challenge"}}
                ],
            }
        )
        assert r3[0]["decision"] == "delete"
        # 空 / 缺字段 → 空列表
        assert agent._normalize_adjudications(None) == []
        assert agent._normalize_adjudications({}) == []
        assert agent._normalize_adjudications([{"decision": "keep"}]) == []  # 缺 claim

    def test_traceability_format_and_bind(self):
        """溯源格式化：【生成陈述】【KB原文出处】【来源】三要素 + 防重复追加。"""
        agent = CorrectionAgent()
        point = {
            "statement": "LangGraph 由 LangChain 团队开发",
            "source_text": "LangGraph is a library built by the LangChain team",
            "doc_id": "langgraph_intro.md",
            "chunk_index": 2,
        }
        line = agent._format_fact_point(point)
        assert "【生成陈述】LangGraph 由 LangChain 团队开发" in line
        assert "【KB原文出处】LangGraph is a library built by the LangChain team" in line
        assert "【来源】langgraph_intro.md#chunk_2" in line

        content, lines = agent._bind_traceability("正文内容", [point])
        assert "## 事实溯源" in content
        assert content.endswith("【来源】langgraph_intro.md#chunk_2")
        assert lines == [line]

        # 已有溯源块 → 不重复追加
        _, lines2 = agent._bind_traceability(content, [point])
        assert lines2 == []
        # 无事实点 → 原样返回
        content3, lines3 = agent._bind_traceability("x", [])
        assert content3 == "x" and lines3 == []

    # ── Phase 3：降级模式一致性检查（纯规则）──
    def test_consistency_rules_private(self):
        """四项一致性规则：前后矛盾 / 术语不一致 / 缺失 import / 步骤跳跃。"""
        agent = CorrectionAgent()
        content = (
            "LangGraph 支持状态机。langgraph 不支持状态机。\n\n"
            "1. 第一步\n2. 第二步\n4. 第四步\n\n"
            "```python\nimport pandas as pd\ndf = pd.DataFrame()\nplt.figure()\n```\n"
        )
        issues = agent._consistency_check(content, ["LangGraph"])
        types = {i["check_type"] for i in issues}
        assert {"missing_import", "step_jump", "term_inconsistency", "contradiction"} <= types
        # 缺失 import：用了 plt. 但全文无 matplotlib import
        missing = [i for i in issues if i["check_type"] == "missing_import"]
        assert missing and "matplotlib" in missing[0]["detail"]
        # 干净内容 → 无 finding
        assert agent._consistency_check("LangGraph 是 LangChain 开发的。", ["LangGraph"]) == []


# ═══════════════════════════════════════════════════════════
# AuditAgent — 内容审核 Agent（只审不修）
# ═══════════════════════════════════════════════════════════

#: 内容审核的正常 mock 返回（LLM 生成的审核报告，仅透传不解析）
AUDIT_OK = {
    "resource_index": 0,
    "resource_type": "lecture",
    "verdict": "needs_revision",
    "issues": [
        {"severity": "error", "detail": "LangGraph 归属错误"},
        {"severity": "info", "detail": "可加生活类比"},
    ],
}

#: 内容审核的完整输入 state
AUDIT_STATE = {
    "diagnosis_result": dict(VALID_DIAGNOSIS),
    "generated_resources": [
        {
            "resource_id": "res-001",
            "resource_type": "lecture",
            "title": "LangGraph 入门讲义",
            "content": "# LangGraph 入门讲义\n\nLangGraph 是 Google 开发的框架。",
            "difficulty_level": "beginner",
            "citations": [],
            "key_takeaways": ["理解 StateGraph"],
        },
    ],
}


class TestAuditAgent:
    """内容审核 Agent：正常 / 边界 / 异常（只审不修，逐资源产出审核报告）。"""

    def _run(self, state: dict, behavior: dict | None = None) -> tuple[dict, AsyncMock]:
        agent = AuditAgent()
        if behavior is None:
            return asyncio.run(agent.run(state)), AsyncMock()  # 无 mock 时第二返回值不使用
        patcher = _patch_call_llm_json(agent, behavior)
        try:
            return asyncio.run(agent.run(state)), patcher.new
        finally:
            patcher.stop()

    def _run_no_kb(self, state: dict, behavior: dict | None = None) -> tuple[dict, AsyncMock]:
        """运行 AuditAgent，同时 mock 掉 ChromaDB 检索（KB 证据池为空）。

        Phase 3 audit.py 会逐条检索真实 knowledge_base.search；测试不依赖
        真实 ChromaDB，统一 mock 为空证据池，使三态裁决可预测。
        """
        agent = AuditAgent()
        m = AsyncMock()
        if behavior is not None:
            if "return_value" in behavior:
                payload = behavior.pop("return_value")
                behavior["side_effect"] = lambda *a, **k: deepcopy(payload)
            m = AsyncMock(**behavior)
        patch_llm = patch.object(agent, "call_llm_json", m)
        patch_kb = patch(
            "backend.src.agents.audit.knowledge_base.search", new=AsyncMock(return_value=[])
        )
        patch_llm.start()
        patch_kb.start()
        try:
            return asyncio.run(agent.run(state)), m
        finally:
            patch_kb.stop()
            patch_llm.stop()

    # ── 正常输入 ──
    def test_normal_audits_each_resource(self):
        """正常输入：每份资源产出 1 份审核报告（KB 逐条比对 → 三态裁决）。"""
        state = deepcopy(AUDIT_STATE)
        state["generated_resources"].append(deepcopy(state["generated_resources"][0]))
        state["generated_resources"][1]["resource_id"] = "res-002"
        result, m = self._run_no_kb(
            state, {"return_value": {"claims": ["LangGraph 是 Google 开发的框架。"]}}
        )

        assert len(result["audit_result"]) == 2
        report = result["audit_result"][0]
        assert report["resource_index"] == 0
        assert report["title"] == "LangGraph 入门讲义"
        # verdict 由代码规则裁决：无 KB 证据 → 全部 unverifiable → 无 error → approved
        assert report["verdict"] == "approved"
        assert report["fact_check"]["items"][0]["verdict"] == "unverifiable"
        assert report["fact_check"]["unverifiable_count"] == 1
        # 每份资源 1 次断言提取 LLM 调用（逐条比对在空证据池下走规则兜底）
        assert m.await_count == 2

    def test_llm_claim_extraction_prompt_contains_resource(self):
        """正常输入：断言提取 prompt 携带资源标题与内容。"""
        result, m = self._run_no_kb(deepcopy(AUDIT_STATE), {"return_value": {"claims": []}})
        prompt = m.await_args.args[0]
        assert "LangGraph 入门讲义" in prompt  # 标题
        assert "LangGraph 是 Google 开发的框架" in prompt  # 内容

    # ── 边界输入 ──
    def test_empty_resources_skips_llm(self):
        """边界：generated_resources 为空 → 空审核结果，不调用 LLM。"""
        state = {"diagnosis_result": dict(VALID_DIAGNOSIS), "generated_resources": []}
        m = AsyncMock(return_value={})
        agent = AuditAgent()
        patcher = patch.object(agent, "call_llm_json", m)
        patcher.start()
        try:
            result = asyncio.run(agent.run(state))
        finally:
            patcher.stop()

        assert result["audit_result"] == []
        m.assert_not_awaited()

    def test_missing_required_keys_validation_error(self):
        """边界：缺必需字段 generated_resources → 校验错误分支，返回 status=error。"""
        result, _ = self._run({"diagnosis_result": dict(VALID_DIAGNOSIS)})
        assert result["status"] == "error"
        assert result["agent_log"][-1]["stage"] == "validation"

    def test_fallback_extract_claims_rules(self):
        """私有 _fallback_extract_claims：剥离 markdown 标题/代码块/链接，过滤短句，上限截断。"""
        agent = AuditAgent()
        content = (
            "# 标题\n\n"
            "LangGraph 是 Google 开发的框架，这是一个足够长的句子。\n"
            "短句。\n"
            "```python\nx = 1\n```\n"
            "[链接文字](https://example.com) 这又是一个很长的断言内容。\n"
        )
        claims = agent._fallback_extract_claims(content)
        # 标题 / 代码块 / 链接均被剥离，短句被过滤
        assert not any("标题" in c for c in claims)
        assert not any("x = 1" in c for c in claims)
        assert not any("链接文字" in c for c in claims)
        assert "LangGraph 是 Google 开发的框架" in claims[0]
        # 上限 MAX_CLAIMS_PER_RESOURCE=8
        long_content = "。".join([f"第{i}条足够长的事实断言内容用于测试" for i in range(20)])
        assert len(agent._fallback_extract_claims(long_content)) == 8

    def test_resolve_verdict_authority_weighting(self):
        """权威裁决 A>B：A 反驳 > A 支持 > B 反驳 > B 支持 > 无覆盖。"""
        agent = AuditAgent()
        assert agent._resolve_verdict({"contradict_a": "A反驳"}) == "hallucination"
        assert agent._resolve_verdict({"support_a": "A支持"}) == "accurate"
        assert agent._resolve_verdict({"contradict_b": "B反驳"}) == "hallucination"
        assert agent._resolve_verdict({"support_b": "B支持"}) == "accurate"
        assert agent._resolve_verdict({}) == "unverifiable"

    # ── 异常输入 ──
    def test_llm_timeout_degrades_to_rule_fallback(self):
        """异常①调用超时：断言提取降级为规则兜底，报告照常产出，不崩溃。"""
        result, _ = self._run_no_kb(
            deepcopy(AUDIT_STATE),
            {"side_effect": asyncio.TimeoutError("LLM 调用超时")},
        )
        _no_crash(result)
        # 未置 status=error：单资源 try/except 兜底而非向上传播
        assert result.get("status") != "error"
        assert len(result["audit_result"]) == 1
        # 规则兜底提取的断言被逐条比对（无 KB 证据 → unverifiable）
        assert result["audit_result"][0]["fact_check"]["items"]
        assert result["audit_result"][0]["fact_check"]["items"][0]["verdict"] == "unverifiable"

    def test_llm_invalid_json_degrades_to_rule_fallback(self):
        """异常②返回非法 JSON：断言提取降级为规则兜底，报告照常产出。"""
        result, _ = self._run_no_kb(
            deepcopy(AUDIT_STATE),
            {"return_value": {"_parse_error": True, "raw": "not json"}},
        )
        _no_crash(result)
        report = result["audit_result"][0]
        # 三态裁决仍由代码产出（非 LLM 透传）
        assert report["verdict"] == "approved"
        assert report["fact_check"]["items"][0]["verdict"] == "unverifiable"

    # ── 降级模式（无 KB）──
    def test_downgrade_mode_consistency_no_kb(self):
        """downgrade_mode=True：不做 KB 比对，输出 no_kb_mode 一致性报告，不调 LLM。"""
        state = deepcopy(AUDIT_STATE)
        state["downgrade_mode"] = True
        state["generated_resources"][0]["content"] = "步骤 1 完成。步骤 3 完成。"
        result, m = self._run_no_kb(state, {"return_value": {}})
        report = result["audit_result"][0]
        assert report["no_kb_mode"] is True
        assert report["verdict"] == "approved"
        # 步骤跳跃：缺少第 2 步
        assert any("步骤 2" in i["detail"] or "2" in i["detail"] for i in report["issues"])
        # 一致性检查为纯规则，不调用 LLM
        m.assert_not_awaited()


# ═══════════════════════════════════════════════════════════
# BaseAgent / EventBus — 基础设施（run() 兜底 + 事件总线）
# ═══════════════════════════════════════════════════════════


class _DummyProcessAgent(BaseAgent):
    """process() 返回非 dict 的最小测试子类。"""

    REQUIRED_STATE_KEYS = set()

    def __init__(self):
        super().__init__(name="测试Agent", system_prompt="test", temperature=0.2)

    async def process(self, state):
        return "not-a-dict"


class _PassThroughAgent(BaseAgent):
    """最小子类：process() 原样回显输入。"""

    REQUIRED_STATE_KEYS = {"learner_data"}

    def __init__(self):
        super().__init__(name="测试Agent", system_prompt="test", temperature=0.2)

    async def process(self, state):
        return {"echo": state.get("learner_data")}


class _EmptyNameAgent(BaseAgent):
    """用于触发空 name 校验的子类。"""

    REQUIRED_STATE_KEYS = set()

    def __init__(self, **kwargs):
        super().__init__(system_prompt="test", temperature=0.2, **kwargs)

    async def process(self, state):
        return {}


class TestBaseAgent:
    """BaseAgent 基类：run() 兜底 / call_llm* / 校验的通用行为。"""

    def test_empty_name_raises(self):
        """空 name → __init__ 抛 ValueError。"""
        with pytest.raises(ValueError):
            _EmptyNameAgent(name="")

    def test_non_dict_process_wrapped(self):
        """process() 返回非 dict → run() 包装为 {"result": ...}，不崩溃。"""
        agent = _DummyProcessAgent()
        result = asyncio.run(agent.run({}))
        assert result["result"] == "not-a-dict"
        assert result["agent_log"][-1]["stage"] == "complete"

    def test_call_llm_uses_temperature_and_passthrough(self):
        """call_llm：patch 掉底层 llm.call，默认温度 + 显式温度覆盖都被采用。"""
        agent = _PassThroughAgent()
        captured = {}

        async def fake_call(**kwargs):
            captured.update(kwargs)
            return "mock reply"

        with patch("backend.src.agents.base.llm.call", new=fake_call):
            text = asyncio.run(agent.call_llm("hello"))
        assert text == "mock reply"
        assert captured["user_message"] == "hello"
        assert captured["temperature"] == agent.temperature

        with patch("backend.src.agents.base.llm.call", new=fake_call):
            asyncio.run(agent.call_llm("hello", temperature=0.9))
        assert captured["temperature"] == 0.9

    def test_call_llm_json_real_body_with_temp(self):
        """call_llm_json：patch 底层 llm.call_json，覆盖未 mock 的实方法体。"""
        agent = _PassThroughAgent()

        async def fake_call_json(**kwargs):
            return {"ok": True, "temperature": kwargs.get("temperature")}

        with patch("backend.src.agents.base.llm.call_json", new=fake_call_json):
            result = asyncio.run(agent.call_llm_json("hello", temperature=0.1))
        assert result == {"ok": True, "temperature": 0.1}

    def test_unknown_state_key_warns(self):
        """校验：state 含未声明键 → 记录 warning 但校验通过、不置 error。"""
        agent = _PassThroughAgent()
        result = asyncio.run(agent.run({"learner_data": {}, "mystery_key": 1}))
        assert result.get("status") != "error"
        assert result["echo"] == {}
        assert result["agent_log"][-1]["stage"] == "complete"


class TestEventBus:
    """SimpleEventBus：精确匹配 / 通配 / 异常隔离。"""

    def test_publish_exact_and_wildcard(self):
        """精确匹配订阅 + 通配订阅都收到事件，载荷透传。"""
        bus = SimpleEventBus()
        calls = []
        bus.subscribe("agent.start", lambda et, **kw: calls.append(("exact", kw)))
        bus.subscribe("*", lambda et, **kw: calls.append(("wild", et)))
        bus.publish("agent.start", agent_name="A")
        assert ("exact", {"agent_name": "A"}) in calls
        assert ("wild", "agent.start") in calls

    def test_unmatched_event_only_wildcard(self):
        """未精确订阅的事件 → 只有通配订阅者收到。"""
        bus = SimpleEventBus()
        calls = []
        bus.subscribe("other", lambda et, **kw: calls.append("other"))
        bus.subscribe("*", lambda et, **kw: calls.append("wild"))
        bus.publish("unmatched", x=1)
        assert calls == ["wild"]

    def test_subscriber_exception_isolated(self):
        """订阅者抛异常 → 被捕获记录，不影响其余订阅者与发布者。"""
        bus = SimpleEventBus()
        calls = []

        def bad(et, **kw):
            raise RuntimeError("boom")

        bus.subscribe("t", bad)
        bus.subscribe("t", lambda et, **kw: calls.append("ok"))
        bus.subscribe("*", lambda et, **kw: calls.append("wild"))
        bus.publish("t")  # 不抛出
        assert calls == ["ok", "wild"]

"""test_all_agents.py — 三大 Agent 的 pytest 单元测试。

被测 Agent（仅统计这三个模块的业务代码覆盖率，不含测试脚本）:
  - DiagnosisAgent    diagnosis.py   学情诊断
  - GenerationAgent   generation.py  领域知识生成
  - CorrectionAgent   correction.py  保真修正

覆盖要求:
  - 每个 Agent 不少于 3 个 case：正常输入 / 边界输入 / 异常输入
  - 覆盖 process 流程、JSON 解析分支、错误返回分支
  - 使用 mock 模拟 3 种 LLM 异常：调用超时 / 返回非法 JSON / 返回空内容
  - 异常时代理不崩溃；由 BaseAgent.run() 统一兜底的场景返回
    {"error": "错误描述", "status": "error"}
  - 覆盖率统计不把测试脚本计入业务代码（仅 --cov 三个业务模块）

运行方式（在项目根目录 C:/Users/CAT/Desktop）::

    python -m pytest agents/test_all_agents.py --cov=agents.diagnosis \
        --cov=agents.generation --cov=agents.correction --cov-report=term-missing

注意（现有业务源码的既有行为，测试如实断言，不修改源码）:
  - DiagnosisAgent / CorrectionAgent 的 run() 包装了 BaseAgent.run()，
    BaseAgent.run() 内置 try/except，LLM 抛出的异常会被捕获，
    以 state["status"]="error" / state["error"]="..." 形式返回。
  - GenerationAgent.run() 自行覆写、直接调用 self.process()，
    没有 BaseAgent.run() 的异常隔离：LLM 抛出 TimeoutError 会向上传播
    （见 test_timeout_raises_under_current_code 的文档化断言）。
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

# ── 让 agents 包可被导入：把 agents 包所在目录的父目录加入 sys.path ──
_PKG_PARENT = Path(__file__).resolve().parent.parent
if str(_PKG_PARENT) not in sys.path:
    sys.path.insert(0, str(_PKG_PARENT))

from agents.correction import CorrectionAgent
from agents.diagnosis import DiagnosisAgent
from agents.generation import GenerationAgent

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
VALID_RESOURCE = {
    "title": "LangGraph 入门讲义（mock）",
    "content": "# LangGraph 入门讲义\n\n这是 mock 返回的 Markdown 内容。",
    "difficulty": "beginner",
    "key_takeaways": ["理解 StateGraph", "掌握节点与边"],
}

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
    """把 agent.call_llm_json 替换为 AsyncMock（LLM 全部 mock，不发真实请求）。"""
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
        assert result["diagnosis_result"]["recommended_difficulty"] == "beginner"
        assert result["diagnosis_result"]["learning_style"] == "practice_first"
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
            {"diagnosis_result": dict(VALID_DIAGNOSIS)},
            {"return_value": dict(VALID_RESOURCE)},
        )
        resources = result["generated_resources"]
        assert 1 <= len(resources) <= 3
        assert len(resources) == 3
        for res in resources:
            for key in GENERATION_FIELDS:
                assert key in res, f"资源缺少字段: {key}"
        assert [r["resource_type"] for r in resources] == ["lecture", "guide", "quiz"]
        assert result["agent_log"][-1]["message"].startswith("生成完成")

    # ── 边界输入 ──
    def test_single_resource_type(self):
        """边界：只请求 1 种类型 → 产出 1 条 lecture 资源。"""
        result, _ = self._run(
            {"diagnosis_result": dict(VALID_DIAGNOSIS), "resource_types": ["lecture"]},
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
            },
            {"return_value": dict(VALID_RESOURCE)},
        )
        assert len(result["generated_resources"]) == 3

    def test_empty_diagnosis_still_generates(self):
        """边界：诊断结果为空 dict → 缺省值兜底，仍能生成 1 条资源。"""
        result, _ = self._run(
            {"diagnosis_result": {}, "resource_types": ["guide"]},
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
            {"diagnosis_result": diagnosis, "resource_types": ["quiz"]},
            {"return_value": dict(VALID_RESOURCE)},
        )
        assert len(result["generated_resources"]) == 1
        prompt = m.await_args.args[0]
        # 非法字符串被回退为 0.0 / 1.0
        assert "当前 0.0 → 目标 1.0" in prompt
        assert "当前 0.5 → 目标 1.0" in prompt

    # ── 异常输入：3 种 LLM 异常 ──
    def test_llm_invalid_json_skipped(self):
        """异常②返回非法 JSON：解析失败 → 该类型资源跳过，不崩溃。"""
        result, _ = self._run(
            {"diagnosis_result": dict(VALID_DIAGNOSIS), "resource_types": ["lecture"]},
            {"return_value": {"_parse_error": True, "raw": "not json"}},
        )
        _no_crash(result)
        assert result["generated_resources"] == []

    def test_llm_empty_content_skipped(self):
        """异常③返回空内容：call_llm_json 返回 {} → 该类型资源跳过，不崩溃。"""
        result, _ = self._run(
            {"diagnosis_result": dict(VALID_DIAGNOSIS), "resource_types": ["lecture"]},
            {"return_value": {}},
        )
        _no_crash(result)
        assert result["generated_resources"] == []

    def test_timeout_raises_under_current_code(self):
        """异常①调用超时（当前行为文档化）。

        GenerationAgent.run() 覆写了 BaseAgent.run() 并直接调用 self.process()，
        没有 BaseAgent.run() 的 try/except 异常隔离，因此 LLM 抛出的 TimeoutError
        目前会向上传播（未返回错误 dict）。这是现有业务源码的既有行为，
        本测试如实记录之；按需求不允许修改业务源码，故不强制断言错误 dict。
        """
        m = AsyncMock(side_effect=asyncio.TimeoutError("LLM 调用超时"))
        agent = GenerationAgent()
        patcher = patch.object(agent, "call_llm_json", m)
        patcher.start()
        try:
            with pytest.raises(asyncio.TimeoutError):
                asyncio.run(
                    agent.run(
                        {
                            "diagnosis_result": dict(VALID_DIAGNOSIS),
                            "resource_types": ["lecture"],
                        }
                    )
                )
        finally:
            patcher.stop()


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
        error_logs = [l for l in result["correction_log"] if l["severity"] == "error"]
        assert error_logs[0]["correction_basis"] == "knowledge_base"  # kb_evidence 存在

    def test_llm_calls_prompt_contains_context(self):
        """正常输入：prompt 携带学习者难度 / 学习风格 / KB 素材与 issue 明细。"""
        result, m = self._run(deepcopy(CORRECTION_STATE), {"return_value": dict(CORRECTED_OK)})
        prompt = m.await_args.args[0]
        assert "推荐难度：beginner" in prompt
        assert "学习风格：practice_first" in prompt
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
        error_logs = [l for l in result["correction_log"] if l["severity"] == "error"]
        assert error_logs and error_logs[0]["correction_basis"] == "knowledge_base"
        # 提升后的 error 出现在修正 prompt 中
        prompt = m.await_args.args[0]
        assert "事实校验不通过" in prompt

    def test_downgrade_mode_adds_note(self):
        """边界：downgrade_mode=True → prompt 追加降级模式说明。"""
        state = deepcopy(CORRECTION_STATE)
        state["downgrade_mode"] = True
        result, m = self._run(state, {"return_value": dict(CORRECTED_OK)})
        assert "降级模式" in m.await_args.args[0]

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
            l["error_detail"] == "json_parse_failed" and l["correction_basis"] == "failed"
            for l in logs
        )

    def test_llm_empty_content_fallback(self):
        """异常③返回空内容：call_llm_json 返回 {} → 保留原内容 + 兜底日志，不崩溃。"""
        result, _ = self._run(deepcopy(CORRECTION_STATE), {"return_value": {}})
        _no_crash(result)
        cr = result["corrected_resources"]
        assert cr[0]["content"] == "# LangGraph 入门讲义\n\nLangGraph 是 Google 开发的框架。"
        assert any(
            l["error_detail"] == "json_parse_failed" for l in result["correction_log"]
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
        assert cr["content"] == "# LangGraph 入门讲义\n\nLangGraph 是 Google 开发的框架。"  # 回退原文
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
        assert text == (
            "1. [error] d1\n   KB 原文: kb1\n"
            "2. [warning] d2\n"
            "3. [unknown] 无 severity"
        )
        # detail 缺省回退为 str(iss)
        assert "[error] {'severity': 'error'}" in agent._fmt_issues([{"severity": "error"}])
        # KB 空 / 结构模板缺省
        assert agent._fmt_kb_chunks([]).startswith("⚠️ 无知识库参考素材")
        assert agent._fmt_structure_guide("unknown") == "保持原内容结构不变"

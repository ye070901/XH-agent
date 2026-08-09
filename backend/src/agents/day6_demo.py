"""day6_demo.py — 演示 3 种 LLM 异常场景下三大 Agent 的 error 格式输出。

只做演示，不改动任何业务源码；LLM 全部 mock（unittest.mock.AsyncMock），不发真实请求。

演示的 3 种 LLM 异常:
  1. 调用超时      —— call_llm_json 抛出 asyncio.TimeoutError
  2. 返回非法 JSON —— call_llm_json 返回 {"_parse_error": True, "raw": "..."}
  3. 返回空内容    —— call_llm_json 返回 {}

观察点（异常时代理不崩溃，统一返回 {"error": "错误描述", "status": "error"}）:
  - DiagnosisAgent / CorrectionAgent 的 run() 包装了 BaseAgent.run()，
    内置 try/except：LLM 抛出的异常被捕获，以 state 中的
    error / error_type / status="error" 返回（下称"error 格式"）。
  - CorrectionAgent 还额外对"单资源修正"做 try/except：
    LLM 异常会降级为"保留原内容 + 记录 failed 日志"，process 整体正常返回。
  - GenerationAgent.run() 自行覆写、直接调用 process()，没有 BaseAgent.run()
    的异常隔离：调用超时会向上抛出（下文中如实打印，属既有行为，演示不做修改）。

运行方式（在项目根目录）::

    python day6_demo.py
"""

from __future__ import annotations

import asyncio
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, patch

# ── 让 agents 包可被导入：把 agents 包所在目录的父目录加入 sys.path ──
_PKG_PARENT = Path(__file__).resolve().parent.parent
if str(_PKG_PARENT) not in sys.path:
    sys.path.insert(0, str(_PKG_PARENT))

# ── Windows 控制台 UTF-8 输出，避免中文乱码 ──
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agents.correction import CorrectionAgent
from agents.diagnosis import DiagnosisAgent
from agents.generation import GenerationAgent

# ═══════════════════════════════════════════════════════════
# 演示输入数据（与 test_all_agents.py 对齐，保证各 Agent 的必需字段齐全）
# ═══════════════════════════════════════════════════════════

LEARNER_DATA = {
    "education_level": "本科",
    "major": "计算机科学",
    "school": "示例大学",
    "work_years": 1,
    "industry": "软件",
    "positions": ["初级后端工程师"],
    "skills_used": ["Python", "SQL"],
    "pretest_results": [],
    "learning_goal": "掌握 LangGraph 开发 AI Agent",
}

DIAGNOSIS_RESULT = {
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

DIAGNOSIS_STATE = {
    "task_id": "day6-demo",
    "learner_data": LEARNER_DATA,
}

GENERATION_STATE = {
    "task_id": "day6-demo",
    "diagnosis_result": DIAGNOSIS_RESULT,
    "resource_types": ["lecture", "guide", "quiz"],
}

CORRECTION_STATE = {
    "task_id": "day6-demo",
    "diagnosis_result": DIAGNOSIS_RESULT,
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
            ],
        },
    ],
    "retrieved_chunks": [
        {
            "doc_id": "langgraph_intro.md",
            "chunk_index": 2,
            "content": "LangGraph is a library built by the LangChain team.",
            "relevance_score": 0.95,
        },
    ],
}

# ═══════════════════════════════════════════════════════════
# 3 种 LLM 异常工厂
# ═══════════════════════════════════════════════════════════

FAILURES: dict[str, str] = {
    "timeout": "调用超时",
    "invalid_json": "返回非法JSON",
    "empty": "返回空内容",
}


def _failure_mock(failure: str) -> AsyncMock:
    """按异常类型构造 call_llm_json 的 AsyncMock。"""
    if failure == "timeout":
        return AsyncMock(side_effect=asyncio.TimeoutError("LLM 调用超时（模拟）"))
    if failure == "invalid_json":
        return AsyncMock(return_value={"_parse_error": True, "raw": "这不是合法 JSON"})
    return AsyncMock(return_value={})  # empty


async def _run_with_failure(agent, state: dict, failure: str) -> dict:
    """在指定 LLM 异常下执行 agent.run(state)。

    LLM 异常若被代理捕获 → 返回正常 dict（可能含 status="error" / error 字段）；
    若未被捕获向上抛出（GenerationAgent 超时场景）→ 记录为 {"_raised": ...}。
    """
    with patch.object(agent, "call_llm_json", _failure_mock(failure)):
        try:
            return await agent.run(deepcopy(state))
        except Exception as e:  # noqa: BLE001 — 演示需要捕获任何上抛异常
            return {"_raised": f"{type(e).__name__}: {e}"}


# ═══════════════════════════════════════════════════════════
# 输出辅助
# ═══════════════════════════════════════════════════════════

def _error_format(result: dict) -> dict:
    """抽取统一错误格式 {"error", "status", "error_type"}。"""
    err: dict = {
        "error": result.get("error"),
        "status": result.get("status"),
    }
    if result.get("error_type"):
        err["error_type"] = result["error_type"]
    return err


def _show(agent, failure: str, result: dict) -> None:
    print(f"  ├─ 场景: LLM {FAILURES[failure]}")
    if "_raised" in result:
        print(
            f"  │   → !! 异常向上抛出（该 Agent 的 run() 未做异常隔离，"
            f"属既有行为）: {result['_raised']}"
        )
        return

    fmt = _error_format(result)
    # 只打印 error 相关字段：统一 error 格式
    print(f"  │   → error 格式: {fmt}")
    _show_output(agent, result)
    print(f"  │   → 未崩溃，正常返回 dict ✓")


def _show_output(agent, result: dict) -> None:
    """按 Agent 打印关键输出，展示异常降级后的实际结果。"""
    name = type(agent).__name__
    if name == "DiagnosisAgent":
        dx = result.get("diagnosis_result", {})
        gaps = len(dx.get("skill_gaps", [])) if isinstance(dx, dict) else 0
        print(f"  │      diagnosis_completed={result.get('diagnosis_completed')}, "
              f"skill_gaps 数量={gaps}, diagnosis_result={dx}")
    elif name == "GenerationAgent":
        res = result.get("generated_resources", [])
        print(f"  │      generated_resources 数量={len(res)}, 类型={[r['resource_type'] for r in res]}")
    elif name == "CorrectionAgent":
        stats = result.get("correction_stats", {})
        logs = result.get("correction_log", [])
        failed = [l for l in logs if l["action"] == "failed"]
        print(f"  │      修正统计={stats}")
        print(f"  │      corrected_resources 数量={len(result.get('corrected_resources', []))}, "
              f"failed 日志条数={len(failed)}")
        if failed:
            print(f"  │      failed 日志示例: {{'action': 'failed', "
                  f"'error_detail': {failed[0].get('error_detail')!r}}}")


# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════

async def main() -> None:
    print("=" * 72)
    print("day6_demo: 3 种 LLM 异常（调用超时 / 非法JSON / 空内容）× 3 大 Agent")
    print("目标: 观察异常时代理不崩溃，统一返回 {\"error\": ..., \"status\": \"error\"}")
    print("=" * 72)

    scenarios = [
        (DiagnosisAgent(), DIAGNOSIS_STATE, "学情诊断 Agent"),
        (GenerationAgent(), GENERATION_STATE, "知识生成 Agent"),
        (CorrectionAgent(), CORRECTION_STATE, "保真修正 Agent"),
    ]

    for agent, state, label in scenarios:
        print(f"\n────── {label} ({type(agent).__name__}) ──────")
        for failure in ("timeout", "invalid_json", "empty"):
            result = await _run_with_failure(agent, state, failure)
            _show(agent, failure, result)

    print("\n" + "=" * 72)
    print("结论:")
    print("  1. Diagnosis/Correction 的 run() 走 BaseAgent.run() try/except:")
    print("     LLM 超时 → 不崩溃，state 返回 {\"error\": \"LLM 调用超时（模拟）\", \"status\": \"error\"}")
    print("  2. Correction 对单资源修正额外兜底: 超时/解析失败 → 保留原内容 + failed 日志")
    print("  3. GenerationAgent.run() 无异常隔离（既有行为）: 超时会向上抛出，非法JSON/空内容则跳过该资源")
    print("  4. 非法 JSON / 空内容在三个 Agent 中均被降级处理，不会导致崩溃")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())

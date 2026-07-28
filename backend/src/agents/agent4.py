"""
Agent 4: 保真修正 Agent（入口文件）
══════════════════════════════════
负责: 人员3 实现（与 Agent 2 同一开发者，prompt 风格统一）

输入: state["generated_resources"] + state["audit_result"]
      + state["diagnosis_result"] + state["retrieved_chunks"]
输出: state["corrected_resources"] + state["correction_log"] + state["correction_stats"]

修正策略:
  - error   → 必须修正（查 KB 原文替换错误断言）
  - warning → 尽量修正（调整解释深度、难度匹配、遗漏覆盖）
  - info    → 可选修正（改进建议酌情采纳）

关键约束:
  1. 只改有问题的部分，不重写整个资源
  2. 修改后重新标注来源 [来源: {doc_id}]
  3. KB 冲突内容并列展示，不自动选边
  4. 修正后不引入新的事实断言（无 KB 支撑标注 [暂无权威参考]）
  5. downgrade_mode=True 时只做一致性修正，不做事实判断

与 Agent 2 的统一风格:
  - SYSTEM_PROMPT 模块顶层常量
  - 中文 Agent name
  - 通过 self.call_llm() / self.call_llm_json() 调用 LLM
  - Temperature 0.2（修正类操作低温保证准确）
  - Prompt 排版格式对齐 generation_v2.py

主实现位于 correction.py，本文件作为 Agent 4 的标准入口。
"""

from .correction import CorrectionAgent, SYSTEM_PROMPT

__all__ = ["CorrectionAgent", "SYSTEM_PROMPT"]


# ═══════════════════════════════════════════════════════════
# 使用示例（开发调试用）
# ═══════════════════════════════════════════════════════════
"""
import asyncio
from backend.src.agents.agent4 import CorrectionAgent


async def demo():
    agent = CorrectionAgent()
    state = {
        "diagnosis_result": {
            "summary": "学习 LangGraph 开发 AI Agent",
            "recommended_difficulty": "beginner",
            "learning_style": "theory_first",
            "skill_gaps": [
                {
                    "priority": "critical",
                    "topic": "LangGraph 状态管理",
                    "current_level": 0.1,
                    "target_level": 0.9,
                    "reason": "不清楚图状态流转机制",
                },
            ],
        },
        "generated_resources": [
            {
                "resource_id": "res-001",
                "resource_type": "lecture",
                "title": "LangGraph 入门讲义",
                "content": (
                    "# LangGraph 入门讲义\\n\\n"
                    "LangGraph 是 Google 开发的图状态管理框架。\\n\\n"
                    "## 核心概念\\n"
                    "StateGraph 让你用状态字典在节点间传递数据。\\n"
                ),
                "difficulty_level": "beginner",
                "citations": [],
                "key_takeaways": ["理解 LangGraph", "掌握 StateGraph"],
            },
        ],
        "audit_result": [
            {
                "verdict": "needs_revision",
                "issues": [
                    {
                        "severity": "error",
                        "detail": "LangGraph 不是 Google 开发的，是 LangChain 团队开发的",
                        "kb_evidence": "LangGraph is a library built by the LangChain team",
                    },
                    {
                        "severity": "warning",
                        "detail": "缺少对 StateGraph 三个要素的逐一说明",
                    },
                    {
                        "severity": "info",
                        "detail": "建议在引言中加入一个生活类比",
                    },
                ],
            },
        ],
        "retrieved_chunks": [
            {
                "doc_id": "langgraph_intro.md",
                "chunk_index": 2,
                "content": "LangGraph is a library built by the LangChain team for building stateful, multi-actor applications with LLMs.",
                "relevance_score": 0.95,
            },
        ],
    }
    result = await agent.run(state)
    print(f"修正完成: {len(result.get('corrected_resources', []))} 个资源")
    print(f"修正统计: {result.get('correction_stats', {})}")
    if result.get("correction_log"):
        for log in result["correction_log"]:
            print(f"  [{log['severity']}] {log['action']}: {log['original_text'][:50]}...")


if __name__ == "__main__":
    asyncio.run(demo())
"""

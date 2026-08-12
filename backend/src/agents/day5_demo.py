"""day5_demo.py — 串联完整链路：学情诊断 Agent → 知识生成 Agent。

运行后控制台打印 EventBus 事件日志，能看到 agent.start / agent.done。

本 demo 使用本地演示 LLM（llm_demo，离线）驱动，无需 API Key；
若配置了 LLM_API_KEY 并在完整项目（backend/src）中运行，则走真实调用。

运行方式（在项目根目录）::

    python day5_demo.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# ── 让 agents 包可被导入：把 agents 包所在目录的父目录加入 sys.path ──
_PKG_PARENT = Path(__file__).resolve().parent.parent
if str(_PKG_PARENT) not in sys.path:
    sys.path.insert(0, str(_PKG_PARENT))

# ── Windows 控制台 UTF-8 输出，避免中文乱码 ──
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agents.diagnosis import DiagnosisAgent  # noqa: E402
from agents.event_bus import event_bus  # noqa: E402
from agents.generation_v2 import GenerationAgent  # noqa: E402


def _on_event(event_type: str, *args, **kwargs) -> None:
    """EventBus 订阅回调：把每个事件打印到控制台。"""
    # 埋点使用 event_bus.publish("agent.start", {"agent_name": ...})，
    # 载荷 dict 作为位置参数传入（args），也可能作为关键字参数（kwargs）。
    payload = kwargs if kwargs else (args[0] if args else {})
    print(f"[EventBus] {event_type}  payload={payload}")


async def main() -> None:
    # 订阅全部事件，观察 agent.start / agent.done
    event_bus.subscribe("*", _on_event)

    diagnosis = DiagnosisAgent()
    generation = GenerationAgent()

    state = {
        "task_id": "day5-demo-001",
        "learner_data": {
            "education_level": "本科",
            "major": "计算机科学",
            "school": "示例大学",
            "work_years": 1,
            "industry": "软件",
            "positions": ["初级后端工程师"],
            "skills_used": ["Python", "SQL"],
            "pretest_results": [],
            "learning_goal": "掌握 LangGraph 开发 AI Agent",
        },
        "resource_types": ["lecture", "guide"],
    }

    print("=== Step 1: 学情诊断 Agent ===")
    state = await diagnosis.run(state)

    print("\n=== Step 2: 知识生成 Agent ===")
    state = await generation.run(state)

    print("\n=== 生成结果 ===")
    for i, res in enumerate(state.get("generated_resources", []), 1):
        print(
            f"{i}. [{res['resource_type']}] {res['title']} "
            f"(difficulty={res['difficulty_level']})"
        )
        print(f"   key_takeaways: {res.get('key_takeaways', [])}")

    print("\n=== 链路完成 ===")


if __name__ == "__main__":
    asyncio.run(main())

"""Day8 接入联调 — 全链路验证脚本。

运行完整 pipeline_v0 链路（真实 Agent1/2/3 + 真实 RAG + EventBus 广播），
并校验 logs/eventbus.log 中：
  1. 存在 gate → agent → gate 的完整事件链（以 workflow_complete 结尾）
  2. 时间戳单调连续、无断层

Run:
    python scripts/run_day8_chain.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.src.knowledge.store import knowledge_base
from backend.src.scheduler.pipeline_v0 import (
    PipelineSchedulerV0,
    make_initial_state,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVENT_LOG = PROJECT_ROOT / "logs" / "eventbus.log"

# 时间断层阈值（秒）：demo 模式各步骤毫秒级完成，间隔超过该值视为断档
_GAP_THRESHOLD_SECONDS = 5.0


async def run_chain(learning_goal: str = "FANUC 机器人 SRVO-068 故障处理") -> dict:
    """运行完整默认链路（真实 Agent + 真实 RAG）。"""
    await knowledge_base.initialize()
    state = make_initial_state(learning_goal=learning_goal, major="自动化")
    scheduler = PipelineSchedulerV0()
    return await scheduler.run(state)


def verify_event_log(events: list[dict], task_id: str) -> list[str]:
    """校验事件链完整性与时间戳连续性，返回异常列表（空 = 通过）。"""
    anomalies: list[str] = []

    run_events = [e for e in events if e.get("task_id") == task_id]
    if not run_events:
        return [f"日志中未找到当前运行 task_id={task_id[:8]}… 的事件"]

    types = [e.get("event_type", "?") for e in run_events]
    timestamps = [float(e.get("timestamp", 0)) for e in run_events]

    print(f"\n  EventBus 事件类型序列 ({len(run_events)}):")
    print("    " + " -> ".join(types))

    # ── 1. 链完整性：gate 开头 → agent 执行 → gate → ... → workflow_complete ──
    if types[0] not in ("gate_pass", "gate_fail"):
        anomalies.append(f"事件链未以 gate 事件开头: {types[0]}")
    if types[-1] != "workflow_complete":
        anomalies.append(f"事件链未以 workflow_complete 结尾: {types[-1]}")

    gate_events = {"gate_pass", "gate_fail"}
    agent_events = {"agent_start", "agent_error"}
    found_chain = False
    for i, t_i in enumerate(types):
        if t_i not in gate_events:
            continue
        for j in range(i + 1, len(types)):
            if types[j] not in agent_events:
                continue
            for k in range(j + 1, len(types)):
                if types[k] in gate_events:
                    found_chain = True
                    break
            if found_chain:
                break
        if found_chain:
            break
    if not found_chain:
        anomalies.append("日志中不存在 gate → agent → gate 完整事件链")

    # 每个 agent_start 之后必须有 agent_done
    for i, t_i in enumerate(types):
        if t_i == "agent_start" and "agent_done" not in types[i + 1 :]:
            anomalies.append(f"agent_start(idx={i}) 后缺少 agent_done")

    # ── 2. 时间戳单调连续、无断层 ──
    diffs: list[float] = []
    for a, b in zip(timestamps, timestamps[1:]):
        if b < a:
            anomalies.append(f"时间戳回退: {a} -> {b}")
        else:
            diffs.append(b - a)

    if diffs:
        max_gap = max(diffs)
        print(
            f"\n  时间戳: 首 {timestamps[0]:.3f} → 末 {timestamps[-1]:.3f}，"
            f"共 {len(timestamps)} 个事件，最大间隔 {max_gap:.3f}s"
        )
        large_gaps = [(i, round(d, 3)) for i, d in enumerate(diffs) if d > _GAP_THRESHOLD_SECONDS]
        if large_gaps:
            anomalies.append(f"存在时间断层 (>{_GAP_THRESHOLD_SECONDS}s): {large_gaps}")
    else:
        print("\n  时间戳: 仅 1 个事件，无间隔可校验")

    return anomalies


async def main() -> None:
    print("=" * 64)
    print("  Day8 接入联调 — 全链路验证")
    print("=" * 64)

    result = await run_chain()

    print("\n  ── 运行结果 ──")
    print(f"  task_id          = {result.get('task_id')}")
    print(f"  pipeline_state   = {result.get('pipeline_state')}")
    print(f"  elapsed_ms       = {result.get('elapsed_ms')}")
    fo = result.get("final_output", {})
    print(f"  final_output     = {json.dumps(fo, ensure_ascii=False)}")
    print(f"  _is_fallback     = {result.get('_is_fallback', False)}")

    gate_trace = []
    for gate_name, gate_result in result.get("gate_results", {}).items():
        gate_trace.append(f"{gate_name}:{gate_result.get('verdict', '?')}")
    print(f"  gate_trace       = {gate_trace}")

    # ── EventBus 日志校验 ──
    print("\n" + "=" * 64)
    print("  EventBus 日志校验 (logs/eventbus.log)")
    print("=" * 64)

    if not EVENT_LOG.exists():
        print(f"  [FAIL] 日志文件不存在: {EVENT_LOG}")
        return

    events: list[dict] = []
    with EVENT_LOG.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"  [WARN] 解析失败的行已跳过: {exc}")

    print(f"  {EVENT_LOG} 共 {len(events)} 条事件")
    anomalies = verify_event_log(events, result["task_id"])

    print("\n  ── 结论 ──")
    if anomalies:
        for a in anomalies:
            print(f"  [FAIL] {a}")
        print("  >>> EventBus 事件链校验未通过")
    else:
        print("  [OK] gate → agent → gate 完整事件链存在，时间戳连续无断层")
        print("  [OK] 校验通过")

    # 摘要：异常总数（供命令行直接判断）
    print(f"\n  anomaly_count={len(anomalies)}")


if __name__ == "__main__":
    asyncio.run(main())

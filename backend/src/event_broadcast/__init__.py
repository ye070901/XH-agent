"""事件广播模块 — Scheduler 层专用，底层模块不依赖此包。

对外导出：
  - EventType  事件类型枚举（7 种固定事件）
  - EventBus   内存事件总线单例
  - event_bus  全局唯一实例

使用方式：
  from backend.src.event_broadcast import event_bus, EventType

  # 广播
  await event_bus.broadcast(task_id, EventType.AGENT_START, {"agent": "诊断Agent"})

  # 订阅
  async for event in event_bus.subscribe(task_id):
      await websocket.send_json(event)
"""

from backend.src.event_broadcast.bus import EventBus, EventType, event_bus

__all__ = ["EventBus", "EventType", "event_bus"]

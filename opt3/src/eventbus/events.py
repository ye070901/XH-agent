"""事件类型常量，供事件总线及各模块直接导入使用。

这些字符串就是 SimpleEventBus 的事件键。需要引用某个事件时，
直接从本模块导入常量，避免散落的魔法字符串::

    from src.eventbus.events import AGENT_START

    bus.publish(AGENT_START)
"""

#: 门控检查通过，放行当前请求/回合。
GATE_PASS = "gate.pass"

#: 门控检查失败，但允许重试。
GATE_RETRY = "gate.retry"

#: 门控检查失败，走回退路径。
GATE_FALLBACK = "gate.fallback"

#: Agent 开始处理。
AGENT_START = "agent.start"

#: Agent 处理结束。
AGENT_DONE = "agent.done"

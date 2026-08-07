"""极简进程内事件总线 — 供 Agent 埋点与演示/测试使用。

对齐团队 opt3/src/eventbus 的设计（SimpleEventBus）：
  - ``publish(event_type, *args, **kwargs)`` 同步分发，先精确匹配再通配 ``"*"``
  - 单个订阅者回调抛异常被捕获记录，不影响其余订阅者与发布者
  - 事件类型常量与 opt3/src/eventbus/events.py 一致：
      AGENT_START = "agent.start"
      AGENT_DONE  = "agent.done"

用法::

    from .event_bus import event_bus, AGENT_START, AGENT_DONE

    event_bus.subscribe("*", lambda et, **kw: print(et, kw))
    event_bus.publish(AGENT_START, agent_name="DiagnosisAgent")
    event_bus.publish(AGENT_DONE, agent_name="DiagnosisAgent")
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 事件类型常量（与 opt3/src/eventbus/events.py 对齐）
# ──────────────────────────────────────────────

#: Agent 开始处理。
AGENT_START = "agent.start"

#: Agent 处理结束。
AGENT_DONE = "agent.done"

#: 通配符事件键：订阅 ``"*"`` 的回调收到所有已发布事件。
WILDCARD = "*"


#: 订阅者回调类型。回调签名：``callback(event_type, *args, **kwargs)``。
Callback = Callable[..., None]


class SimpleEventBus:
    """订阅 / 发布模式的同步事件总线。

    订阅者通过 :meth:`subscribe` 把回调注册到某个事件键上；
    :meth:`publish` 时按订阅顺序同步调用匹配的回调（先精确匹配，再通配）。
    单个回调抛出的异常会被捕获记录，不会中断或阻塞其余回调。
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callback]] = defaultdict(list)

    def subscribe(self, event_type: str, callback: Callback) -> None:
        """注册一个订阅者。

        Args:
            event_type: 要监听的事件键；传 ``"*"`` 接收所有事件。
            callback: 以 ``callback(event_type, *args, **kwargs)`` 形式被调用。
        """
        self._subscribers[event_type].append(callback)

    def publish(self, event_type: str, *args: Any, **kwargs: Any) -> None:
        """同步分发事件给所有匹配的回调。

        Args:
            event_type: 要分发的事件键。
            *args / **kwargs: 原样透传给每个回调。
        """
        for callback in list(self._subscribers.get(event_type, ())):
            self._dispatch(callback, event_type, *args, **kwargs)
        for callback in list(self._subscribers.get(WILDCARD, ())):
            self._dispatch(callback, event_type, *args, **kwargs)

    @staticmethod
    def _dispatch(callback: Callback, event_type: str, *args: Any, **kwargs: Any) -> None:
        """调用单个回调并隔离其异常。"""
        try:
            callback(event_type, *args, **kwargs)
        except Exception:
            logger.exception(
                "订阅者回调处理事件 %s 时抛出异常，已跳过: %r",
                event_type,
                callback,
            )


# ──────────────────────────────────────────────
# 全局单例（唯一入口，各 Agent 共用同一个总线）
# ──────────────────────────────────────────────
event_bus = SimpleEventBus()

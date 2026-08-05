"""一个极简的、进程内同步事件总线，支持通配符订阅。

用法::

    from src.eventbus.bus import SimpleEventBus
    from src.eventbus.events import AGENT_DONE

    bus = SimpleEventBus()
    bus.subscribe(AGENT_DONE, lambda event_type: print("done"))
    bus.publish(AGENT_DONE)
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

#: 订阅者回调类型。回调的第一个位置参数是事件类型字符串，
#: 其后依次是 publish 时传入的 ``*args`` / ``**kwargs``。
Callback = Callable[..., None]

#: 通配符事件键。订阅 ``"*"`` 的回调会收到所有已发布事件。
WILDCARD = "*"

#: 事件持久化日志文件的默认路径（相对于当前工作目录）。
DEFAULT_LOG_PATH = "logs/eventbus.log"

#: 模块级日志器，用于记录订阅者异常与持久化失败。
logger = logging.getLogger(__name__)


class SimpleEventBus:
    """订阅 / 发布模式的同步事件总线。

    订阅者通过 :meth:`subscribe` 把回调注册到某个事件键（字符串）上；
    调用 :meth:`publish` 时，会按订阅顺序同步地逐个调用匹配的回调。
    订阅 ``"*"`` 的回调能收到全部事件。

    每次 :meth:`publish` 会把事件序列化为一行 JSON 追加写入日志文件
    （默认 ``logs/eventbus.log``，目录不存在时自动创建）；某个订阅者
    回调抛出的异常会被捕获并记录，不会中断或阻塞其余订阅者。

    Example
    -------
    >>> bus = SimpleEventBus()
    >>> bus.subscribe("agent.done", lambda event_type: print(event_type))
    >>> bus.publish("agent.done")
    agent.done
    """

    def __init__(self, log_path: str = DEFAULT_LOG_PATH) -> None:
        """创建一个没有任何订阅者的空总线。

        Args:
            log_path: 事件持久化日志文件的路径。所在目录不存在时会自动创建。
        """
        self._subscribers: Dict[str, List[Callback]] = defaultdict(list)
        self._log_path: str = log_path

    def subscribe(self, event_type: str, callback: Callback) -> None:
        """为 ``event_type`` 注册一个 ``callback`` 订阅者。

        Args:
            event_type: 要监听的事件键。传 ``"*"`` 可接收所有事件。
            callback: 匹配事件被发布时调用的函数，
                以 ``callback(event_type, *args, **kwargs)`` 形式被调用。

        Notes:
            - 同一个回调重复 subscribe 会注册两次（触发两次）。
            - 同一事件键的多个订阅者按注册顺序先后调用。
        """
        self._subscribers[event_type].append(callback)

    def publish(self, event_type: str, *args: Any, **kwargs: Any) -> None:
        """同步地把 ``event_type`` 分发给所有匹配的回调。

        每次发布都会把事件序列化为一行 JSON 追加写入日志文件
        （默认 :data:`DEFAULT_LOG_PATH`，可经 ``log_path`` 覆盖）。
        先调用与事件键精确匹配的订阅者，再调用 ``"*"`` 通配符订阅者；
        单个订阅者抛出的异常会被记录，不会中断或阻塞其余订阅者。

        Args:
            event_type: 要分发的事件键。
            *args: 透传给每个回调的位置参数。
            **kwargs: 透传给每个回调的关键字参数。
        """
        self._persist(event_type, args, kwargs)
        for callback in list(self._subscribers.get(event_type, ())):
            self._dispatch(callback, event_type, *args, **kwargs)
        for callback in list(self._subscribers.get(WILDCARD, ())):
            self._dispatch(callback, event_type, *args, **kwargs)

    def _persist(self, event_type: str, args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> None:
        """把事件序列化为一行 JSON，追加写入日志文件。

        日志目录不存在时自动创建。写入失败只记录错误日志，
        不会影响事件的分发。
        """
        record = {"event_type": event_type, "args": args, "kwargs": kwargs}
        try:
            path = Path(self._log_path)
            os.makedirs(path.parent, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception:
            logger.exception("事件持久化写入日志失败: %s", self._log_path)

    def _dispatch(self, callback: Callback, event_type: str, *args: Any, **kwargs: Any) -> None:
        """调用单个订阅者回调并隔离其异常。

        回调抛出的异常被捕获并记录后吞掉，让 publish 继续执行其余订阅者。
        """
        try:
            callback(event_type, *args, **kwargs)
        except Exception:
            logger.exception(
                "订阅者回调处理事件 %s 时抛出异常，已跳过: %r",
                event_type,
                callback,
            )

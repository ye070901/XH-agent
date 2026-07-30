"""内存事件总线 — WebSocket 配套，Scheduler 层专用。

架构约束（不可擅自改动）：
  - 基于 task_id 定向广播，禁止全局广播，隔离多任务消息
  - data 只允许基础序列化类型（dict/list/str/int/float/bool/None），禁止传递对象实例
  - 闸门模块、Agent 内部不直接依赖 EventBus；统一由 Scheduler 调用
  - 单例模式，参考 config.Settings 风格

使用方式：
  from backend.src.event_broadcast import event_bus, EventType

  # 生产者（Scheduler）
  await event_bus.broadcast(task_id, EventType.AGENT_START, {"agent": "诊断Agent"})

  # 消费者（WebSocket 端点）
  async for event in event_bus.subscribe(task_id):
      await websocket.send_json(event)
"""

from __future__ import annotations

import asyncio
import json
import time
from enum import Enum
from typing import Any, AsyncIterator

from loguru import logger

from backend.src.config import settings

# ═══════════════════════════════════════════════════════════
# 事件类型枚举
# ═══════════════════════════════════════════════════════════


class EventType(str, Enum):
    """事件类型枚举 — 前端订阅事件集合。

    agent_start:        Agent 开始执行
    agent_done:         Agent 执行完成
    agent_error:        Agent 执行异常
    gate_pass:          闸门通过
    gate_fail:          闸门未通过
    debate_round:       单轮辩论结束
    workflow_complete:  工作流全部完成
    """

    AGENT_START = "agent_start"
    AGENT_DONE = "agent_done"
    AGENT_ERROR = "agent_error"
    GATE_PASS = "gate_pass"
    GATE_FAIL = "gate_fail"
    DEBATE_ROUND = "debate_round"
    WORKFLOW_COMPLETE = "workflow_complete"


# ═══════════════════════════════════════════════════════════
# EventBus 单例
# ═══════════════════════════════════════════════════════════

# 单通道最大队列长度（防止消费者过慢撑爆内存）
_MAX_QUEUE_SIZE = 2048


class _Subscriber:
    """单个订阅者内部状态。"""

    __slots__ = ("queue", "last_read_ts")

    def __init__(self) -> None:
        self.queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=_MAX_QUEUE_SIZE)
        self.last_read_ts: float = time.monotonic()


class EventBus:
    """内存事件总线 — 全局单例。

    职责：
      - 定向广播：将事件推送到匹配 task_id 的所有订阅者队列
      - 数据校验：拒绝非基础序列化类型
      - 订阅管理：提供 async iterator 接口，自动注册/注销
      - 僵尸回收：超时未消费的订阅通道自动清理

    Attributes:
        无公开属性。全部通过 broadcast() / subscribe() 操作。
    """

    def __init__(self) -> None:
        # task_id → list[_Subscriber]，一个 task_id 可被多个消费者订阅
        self._subscriptions: dict[str, list[_Subscriber]] = {}

    # ═══════════════════════════════════════════════════════════
    # 公开 API
    # ═══════════════════════════════════════════════════════════

    async def broadcast(
        self,
        task_id: str,
        event_type: EventType | str,
        data: dict[str, Any],
    ) -> int:
        """向指定 task_id 的所有订阅者广播事件。

        Args:
            task_id:    任务唯一标识。
            event_type: 事件类型（EventType 枚举值或等价字符串）。
            data:       事件载荷，仅允许基础序列化类型。

        Returns:
            int: 实际送达的订阅者数量。

        Raises:
            TypeError: data 包含非序列化类型时抛出。
        """
        if not task_id:
            logger.warning("[EventBus] task_id 为空，跳过广播")
            return 0

        # ── 数据校验 ──
        self._validate_data(data)

        # ── 僵尸回收 ──
        self._reap_stale_subscribers(task_id)

        # ── 组装事件体 ──
        if isinstance(event_type, EventType):
            et = event_type.value
        else:
            et = str(event_type)

        event: dict[str, Any] = {
            "task_id": task_id,
            "event_type": et,
            "data": data,
            "timestamp": time.time(),
        }

        # ── 推送 ──
        subscribers = self._subscriptions.get(task_id, [])
        delivered = 0
        for sub in subscribers:
            try:
                sub.queue.put_nowait(event)
                delivered += 1
            except asyncio.QueueFull:
                logger.warning(
                    f"[EventBus] task_id={task_id} 订阅者队列已满 (max={_MAX_QUEUE_SIZE})，事件丢弃"
                )

        if delivered > 0:
            logger.debug(f"[EventBus] 广播 {et} → task_id={task_id[:8]}… ({delivered} 订阅者)")
        return delivered

    async def subscribe(self, task_id: str) -> AsyncIterator[dict[str, Any]]:
        """订阅指定 task_id 的事件流，返回异步迭代器。

        消费者通过 ``async for`` 迭代获取事件。
        迭代器退出时（break/return/异常）自动注销订阅。

        用法::

            async for event in event_bus.subscribe(task_id):
                await websocket.send_json(event)

        Args:
            task_id: 要订阅的任务 ID。

        Yields:
            dict: 事件体，包含 task_id/event_type/data/timestamp 字段。
        """
        if not task_id:
            logger.warning("[EventBus] task_id 为空，拒绝订阅")
            return

        sub = _Subscriber()
        self._subscriptions.setdefault(task_id, []).append(sub)
        logger.debug(f"[EventBus] 新增订阅 task_id={task_id[:8]}…")

        try:
            while True:
                # 读取队列，超时用作心跳触发僵尸回收
                try:
                    event = await asyncio.wait_for(sub.queue.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    # 心跳：检查自身是否已过期
                    if self._is_subscriber_stale(sub):
                        logger.debug(
                            f"[EventBus] 订阅者超时未消费，自动注销 task_id={task_id[:8]}…"
                        )
                        return
                    continue

                # None 是停止信号
                if event is None:
                    return

                sub.last_read_ts = time.monotonic()
                yield event

        finally:
            # 注销：从订阅列表中移除
            subs = self._subscriptions.get(task_id, [])
            if sub in subs:
                subs.remove(sub)
                logger.debug(f"[EventBus] 注销订阅 task_id={task_id[:8]}…")
            # 清理空列表
            if task_id in self._subscriptions and not self._subscriptions[task_id]:
                del self._subscriptions[task_id]

    # ═══════════════════════════════════════════════════════════
    # 数据校验
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _validate_data(data: dict[str, Any]) -> None:
        """校验 data 只包含基础序列化类型。

        通过 json.dumps 探测：能序列化 → 仅基础类型；抛 TypeError → 含非标类型。
        对象实例、自定义类的序列化失败会触发拒绝。

        Raises:
            TypeError: data 不可 JSON 序列化时抛出。
        """
        try:
            json.dumps(data, ensure_ascii=False, default=None)
        except TypeError as e:
            raise TypeError(
                f"[EventBus] data 包含非基础序列化类型，"
                f"仅允许 dict/list/str/int/float/bool/None: {e}"
            ) from e

    # ═══════════════════════════════════════════════════════════
    # 僵尸回收
    # ═══════════════════════════════════════════════════════════

    def _is_subscriber_stale(self, sub: _Subscriber) -> bool:
        """判断订阅者是否已超过 TTL 未消费。"""
        ttl = settings.EVENTBUS_SUBSCRIBER_TTL_SECONDS
        elapsed = time.monotonic() - sub.last_read_ts
        return elapsed > ttl

    def _reap_stale_subscribers(self, task_id: str) -> None:
        """回收指定 task_id 下所有过期未消费的订阅通道。

        在每次 broadcast() 时触发，零额外后台开销。
        """
        subs = self._subscriptions.get(task_id)
        if not subs:
            return

        stale = [s for s in subs if self._is_subscriber_stale(s)]
        for s in stale:
            # 向过期队列发送 None 信号以触发 finally 清理
            try:
                s.queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
            subs.remove(s)

        if stale:
            logger.info(f"[EventBus] 回收 {len(stale)} 个僵尸订阅者 task_id={task_id[:8]}…")

        # 清理空列表
        if not subs and task_id in self._subscriptions:
            del self._subscriptions[task_id]


# ──────────────────────────────────────────────
# 全局单例（唯一入口）
# ──────────────────────────────────────────────

event_bus = EventBus()

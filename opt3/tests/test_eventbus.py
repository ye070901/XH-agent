"""SimpleEventBus 与事件类型常量的单元测试。

运行方式（在项目根目录）::

    pytest tests/test_eventbus.py
"""

import json

from src.eventbus.bus import SimpleEventBus, WILDCARD
from src.eventbus.events import (
    AGENT_DONE,
    AGENT_START,
    GATE_FALLBACK,
    GATE_PASS,
    GATE_RETRY,
)

#: 总线可能发布的所有事件键，便于在断言中引用。
ALL_EVENTS: tuple[str, ...] = (GATE_PASS, GATE_RETRY, GATE_FALLBACK, AGENT_START, AGENT_DONE)


def test_specific_subscriber_only_receives_matching_event() -> None:
    """普通订阅者只收到与自身事件键精确匹配的事件。"""
    bus = SimpleEventBus()
    seen: list[str] = []

    bus.subscribe(GATE_PASS, lambda event_type: seen.append(event_type))

    for event_type in ALL_EVENTS:
        bus.publish(event_type)

    assert seen == [GATE_PASS]


def test_wildcard_subscriber_receives_every_event() -> None:
    """订阅 ``"*"`` 的回调能收到全部已发布事件。"""
    bus = SimpleEventBus()
    seen: list[str] = []

    bus.subscribe(WILDCARD, lambda event_type: seen.append(event_type))

    for event_type in ALL_EVENTS:
        bus.publish(event_type)

    assert seen == list(ALL_EVENTS)


def test_three_subscribers_get_only_their_events() -> None:
    """三个订阅者：两个精确匹配 + 一个通配符，各收各的事件。"""
    bus = SimpleEventBus()
    gate_pass_seen: list[str] = []
    agent_done_seen: list[str] = []
    wildcard_seen: list[str] = []

    # 三个订阅者。
    bus.subscribe(GATE_PASS, lambda event_type: gate_pass_seen.append(event_type))
    bus.subscribe(AGENT_DONE, lambda event_type: agent_done_seen.append(event_type))
    bus.subscribe(WILDCARD, lambda event_type: wildcard_seen.append(event_type))

    for event_type in ALL_EVENTS:
        bus.publish(event_type)

    # 普通订阅者只收对应事件。
    assert gate_pass_seen == [GATE_PASS]
    assert agent_done_seen == [AGENT_DONE]
    # 通配符订阅者收到全部事件。
    assert wildcard_seen == list(ALL_EVENTS)


def test_multiple_subscribers_for_same_event_all_fire() -> None:
    """同一事件键的多个订阅者按注册顺序全部触发。"""
    bus = SimpleEventBus()
    calls: list[str] = []

    bus.subscribe(GATE_RETRY, lambda event_type: calls.append(f"first:{event_type}"))
    bus.subscribe(GATE_RETRY, lambda event_type: calls.append(f"second:{event_type}"))

    bus.publish(GATE_RETRY)

    assert calls == [f"first:{GATE_RETRY}", f"second:{GATE_RETRY}"]


def test_publish_with_no_subscribers_is_a_noop() -> None:
    """没有任何订阅者时，publish 不应报错。"""
    bus = SimpleEventBus()
    bus.publish(AGENT_START)
    bus.publish("unknown.event")


def test_publish_forwards_args_and_kwargs_to_callbacks() -> None:
    """publish 携带的参数会原样透传给回调。"""
    bus = SimpleEventBus()
    received: list[tuple[str, int, str]] = []

    def on_pass(event_type: str, attempts: int, reason: str = "") -> None:
        received.append((event_type, attempts, reason))

    bus.subscribe(GATE_PASS, on_pass)

    bus.publish(GATE_PASS, attempts=2, reason="ok")
    bus.publish(GATE_PASS, 3, "again")

    assert received == [
        (GATE_PASS, 2, "ok"),
        (GATE_PASS, 3, "again"),
    ]


def test_exception_in_one_subscriber_does_not_affect_others() -> None:
    """其中一个订阅者抛出异常时，其余订阅者仍正常收到消息，publish 不崩溃。"""
    bus = SimpleEventBus()
    received: list[str] = []

    def exploding_callback(event_type: str) -> None:
        raise RuntimeError(f"boom: {event_type}")

    bus.subscribe(GATE_PASS, exploding_callback)
    bus.subscribe(GATE_PASS, lambda event_type: received.append(event_type))

    # 第一个订阅者抛异常，第二个订阅者仍应收到事件。
    bus.publish(GATE_PASS)

    assert received == [GATE_PASS]


def test_exact_subscriber_exception_does_not_block_wildcard_subscriber() -> None:
    """精确订阅者抛异常后，通配符订阅者仍收到同一事件。"""
    bus = SimpleEventBus()
    received: list[str] = []

    def explode(event_type: str) -> None:
        raise ValueError("boom")

    bus.subscribe(GATE_PASS, explode)
    bus.subscribe(WILDCARD, lambda event_type: received.append(event_type))

    bus.publish(GATE_PASS)

    assert received == [GATE_PASS]


def test_multiple_failing_subscribers_do_not_stop_others() -> None:
    """多个订阅者连续抛异常，其余订阅者（含通配符）仍全部收到消息。"""
    bus = SimpleEventBus()
    received: list[str] = []

    def explode(event_type: str) -> None:
        raise RuntimeError("boom")

    bus.subscribe(GATE_PASS, explode)
    bus.subscribe(GATE_PASS, lambda event_type: received.append(f"exact:{event_type}"))
    bus.subscribe(GATE_RETRY, explode)
    bus.subscribe(WILDCARD, lambda event_type: received.append(f"wild:{event_type}"))

    bus.publish(GATE_PASS)
    bus.publish(GATE_RETRY)

    assert received == [
        f"exact:{GATE_PASS}",
        f"wild:{GATE_PASS}",
        f"wild:{GATE_RETRY}",
    ]


def test_publish_appends_one_json_line_per_event(tmp_path) -> None:
    """每个已发布事件被序列化为一行 JSON 追加写入日志文件。"""
    log_path = tmp_path / "logs" / "eventbus.log"
    bus = SimpleEventBus(log_path=str(log_path))

    bus.publish(GATE_PASS)
    bus.publish(AGENT_DONE)

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["event_type"] == GATE_PASS
    assert json.loads(lines[1])["event_type"] == AGENT_DONE


def test_publish_auto_creates_log_directory(tmp_path) -> None:
    """日志目录不存在时，publish 会自动创建。"""
    log_path = tmp_path / "nonexistent" / "deep" / "eventbus.log"
    bus = SimpleEventBus(log_path=str(log_path))

    bus.publish(AGENT_START)

    assert log_path.exists()
    record = json.loads(log_path.read_text(encoding="utf-8"))
    assert record["event_type"] == AGENT_START


def test_publish_logs_args_and_kwargs(tmp_path) -> None:
    """日志记录包含 publish 透传的 args 与 kwargs。"""
    log_path = tmp_path / "eventbus.log"
    bus = SimpleEventBus(log_path=str(log_path))

    bus.publish(GATE_PASS, attempts=2, reason="ok")

    record = json.loads(log_path.read_text(encoding="utf-8"))
    assert record["event_type"] == GATE_PASS
    assert record["args"] == []
    assert record["kwargs"] == {"attempts": 2, "reason": "ok"}

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from neos.coding.domain.events import CodingEvent, make_event
from neos.coding.transport.redis_events import (
    CodingEventSubscriptionClosed,
    CodingEventSubscriptionOverloaded,
    RedisCodingEventTransport,
)


class FakeRedisPubSubBus:
    def __init__(self) -> None:
        self.channels: dict[str, set[FakePubSub]] = {}
        self.subscribe_calls = 0
        self.unsubscribe_calls = 0
        self.publish_error: Exception | None = None

    def client(self) -> "FakeRedisClient":
        return FakeRedisClient(self)

    async def publish(self, channel: str, data: str) -> int:
        if self.publish_error is not None:
            raise self.publish_error
        subscribers = tuple(self.channels.get(channel, ()))
        for subscriber in subscribers:
            subscriber.messages.put_nowait(
                {"type": "message", "channel": channel, "data": data}
            )
        return len(subscribers)


class FakeRedisClient:
    def __init__(self, bus: FakeRedisPubSubBus) -> None:
        self.bus = bus

    def pubsub(self) -> "FakePubSub":
        return FakePubSub(self.bus)

    async def publish(self, channel: str, data: str) -> int:
        return await self.bus.publish(channel, data)


class FakePubSub:
    def __init__(self, bus: FakeRedisPubSubBus) -> None:
        self.bus = bus
        self.messages: asyncio.Queue[Any] = asyncio.Queue()
        self.channels: set[str] = set()
        self.closed = False

    async def subscribe(self, channel: str) -> None:
        self.bus.subscribe_calls += 1
        self.channels.add(channel)
        self.bus.channels.setdefault(channel, set()).add(self)

    async def unsubscribe(self, channel: str) -> None:
        self.bus.unsubscribe_calls += 1
        self.channels.discard(channel)
        subscribers = self.bus.channels.get(channel)
        if subscribers is not None:
            subscribers.discard(self)

    async def get_message(self, **_: Any) -> dict[str, Any] | None:
        value = await self.messages.get()
        if isinstance(value, Exception):
            raise value
        return value

    async def aclose(self) -> None:
        self.closed = True


def event(seq: int = 1) -> CodingEvent:
    return make_event(
        task_id="ct_1",
        seq=seq,
        event_type="text.delta",
        payload={"delta": "hi"},
        now=datetime(2026, 7, 18, tzinfo=UTC),
        run_id="run_1",
        checkpoint_id="cc_1",
    )


async def test_publish_reaches_subscription_owned_by_another_transport() -> None:
    bus = FakeRedisPubSubBus()
    worker_a = RedisCodingEventTransport(bus.client())
    worker_b = RedisCodingEventTransport(bus.client())
    subscription = await worker_b.subscribe("ct_1")
    expected = event()

    await worker_a.publish(expected)

    assert await asyncio.wait_for(subscription.get(), timeout=0.1) == expected
    await worker_a.close()
    await worker_b.close()


async def test_local_subscriptions_share_listener_until_last_close() -> None:
    bus = FakeRedisPubSubBus()
    transport = RedisCodingEventTransport(bus.client())
    first = await transport.subscribe("ct_1")
    second = await transport.subscribe("ct_1")

    assert bus.subscribe_calls == 1
    await first.close()
    assert bus.unsubscribe_calls == 0
    await second.close()
    assert bus.unsubscribe_calls == 1
    await transport.close()


async def test_publish_errors_propagate() -> None:
    bus = FakeRedisPubSubBus()
    bus.publish_error = ConnectionError("redis unavailable")
    transport = RedisCodingEventTransport(bus.client())

    with pytest.raises(ConnectionError, match="redis unavailable"):
        await transport.publish(event())


async def test_listener_failure_closes_local_subscriptions() -> None:
    bus = FakeRedisPubSubBus()
    transport = RedisCodingEventTransport(bus.client())
    subscription = await transport.subscribe("ct_1")
    pubsub = next(iter(bus.channels["neos:coding:events:ct_1"]))

    pubsub.messages.put_nowait(ConnectionError("listener failed"))

    with pytest.raises(CodingEventSubscriptionClosed):
        await asyncio.wait_for(subscription.get(), timeout=0.1)
    await transport.close()


async def test_queue_overflow_marks_only_slow_subscription_overloaded() -> None:
    bus = FakeRedisPubSubBus()
    transport = RedisCodingEventTransport(bus.client(), queue_size=1)
    slow = await transport.subscribe("ct_1")

    await transport.publish(event(1))
    await transport.publish(event(2))

    with pytest.raises(CodingEventSubscriptionOverloaded):
        await asyncio.wait_for(slow.get(), timeout=0.1)
    await asyncio.sleep(0)
    assert bus.unsubscribe_calls == 1
    await transport.close()

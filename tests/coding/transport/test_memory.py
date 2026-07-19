from datetime import UTC, datetime, timedelta

import asyncio
import pytest

from neos.coding.auth.ws_tickets import InMemoryWsTicketStore
from neos.coding.domain.events import make_event
from neos.coding.events.broker import InProcessCodingEventBroker
from neos.coding.transport.base import CodingEventSubscriptionClosed


async def test_wrong_task_consumes_ticket_and_expired_entries_are_swept() -> None:
    now = datetime(2026, 7, 18, tzinfo=UTC)
    current = [now]
    store = InMemoryWsTicketStore(clock=lambda: current[0])
    wrong = await store.issue(owner_id="u1", task_id="ct_1")
    expired = await store.issue(owner_id="u1", task_id="ct_2")

    assert await store.consume(wrong, task_id="ct_other") is None
    assert await store.consume(wrong, task_id="ct_1") is None
    current[0] += timedelta(seconds=31)
    await store.issue(owner_id="u1", task_id="ct_3")

    assert store.pending_count == 1
    assert await store.consume(expired, task_id="ct_2") is None


async def test_subscriptions_close_idempotently_and_transport_closes_all() -> None:
    transport = InProcessCodingEventBroker(queue_size=2)
    first = await transport.subscribe("ct_1")
    second = await transport.subscribe("ct_1")
    event = make_event(
        task_id="ct_1",
        seq=1,
        event_type="text.delta",
        payload={"delta": "hi"},
        now=datetime(2026, 7, 18, tzinfo=UTC),
    )

    await transport.publish(event)

    assert await first.get() is event
    assert await second.get() is event
    await first.close()
    await first.close()
    assert transport.subscriber_count("ct_1") == 1

    await transport.close()
    await transport.close()
    assert transport.subscriber_count("ct_1") == 0


async def test_transport_close_unblocks_waiting_subscription() -> None:
    transport = InProcessCodingEventBroker()
    subscription = await transport.subscribe("ct_1")
    waiting = asyncio.create_task(subscription.get())

    await transport.close()

    with pytest.raises(CodingEventSubscriptionClosed):
        await asyncio.wait_for(waiting, timeout=0.1)

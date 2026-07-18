from datetime import UTC, datetime

from neos.coding.domain.events import make_event
from neos.coding.events.broker import InProcessCodingEventBroker


async def test_publish_delivers_event_to_task_subscribers_only() -> None:
    broker = InProcessCodingEventBroker()
    own = await broker.subscribe("ct_1")
    other = await broker.subscribe("ct_2")
    event = make_event(
        task_id="ct_1",
        seq=1,
        event_type="text.delta",
        payload={"delta": "hi"},
        now=datetime(2026, 7, 18, tzinfo=UTC),
    )

    await broker.publish(event)

    assert await own.get() is event
    assert other.empty()


async def test_unsubscribe_stops_delivery_and_releases_subscription() -> None:
    broker = InProcessCodingEventBroker()
    subscription = await broker.subscribe("ct_1")
    await broker.unsubscribe("ct_1", subscription)
    event = make_event(
        task_id="ct_1",
        seq=1,
        event_type="task.created",
        payload={},
        now=datetime(2026, 7, 18, tzinfo=UTC),
    )

    await broker.publish(event)

    assert subscription.empty()
    assert broker.subscriber_count("ct_1") == 0

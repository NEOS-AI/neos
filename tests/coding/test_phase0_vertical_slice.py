from datetime import UTC, datetime

from neos.api.handlers.coding_ws_handlers import replay_protocol_messages
from neos.coding.application.task_service import (
    CodingTaskService,
    InMemoryCodingTaskRepository,
)
from neos.coding.events.store import InMemoryCodingEventStore
from neos.coding.outbox.dispatcher import CodingOutboxDispatcher
from neos.coding.outbox.models import ClaimedOutboxEvent


async def test_create_snapshot_and_reconnect_replay_are_consistent() -> None:
    now = datetime(2026, 7, 18, tzinfo=UTC)
    events = InMemoryCodingEventStore()
    service = CodingTaskService(
        InMemoryCodingTaskRepository(), events, clock=lambda: now
    )
    task = await service.create_task(
        owner_id="u1", prompt="Fix the parser", task_id="ct_vertical"
    )
    await events.append(
        task_id=task.task_id,
        event_type="text.delta",
        payload={"part_id": "answer", "delta": "Fixed "},
        now=now,
    )
    await events.append(
        task_id=task.task_id,
        event_type="text.delta",
        payload={"part_id": "answer", "delta": "and verified."},
        now=now,
    )

    snapshot = await service.snapshot(task.task_id, "u1")
    reconnect = await replay_protocol_messages(service, task.task_id, "u1", 1)

    assert snapshot is not None
    assert snapshot.head_seq == 3
    assert reconnect is not None
    assert [message["type"] for message in reconnect] == [
        "hello",
        "text.delta",
        "text.delta",
        "caught_up",
    ]
    assert [message["seq"] for message in reconnect[1:3]] == [2, 3]
    assert reconnect[-1]["head_seq"] == snapshot.head_seq


async def test_outbox_live_delivery_matches_durable_replay_order() -> None:
    now = datetime(2026, 7, 18, tzinfo=UTC)
    events = InMemoryCodingEventStore()
    service = CodingTaskService(
        InMemoryCodingTaskRepository(), events, clock=lambda: now
    )
    task = await service.create_task(owner_id="u1", prompt="Fix it")
    second = await events.append(
        task_id=task.task_id,
        event_type="text.delta",
        payload={"part_id": "answer", "delta": "A"},
        now=now,
    )
    third = await events.append(
        task_id=task.task_id,
        event_type="text.delta",
        payload={"part_id": "answer", "delta": "B"},
        now=now,
    )

    class Repository:
        async def claim_batch(self, **_):
            return [
                ClaimedOutboxEvent("co_2", second, 0),
                ClaimedOutboxEvent("co_3", third, 0),
            ]

        async def mark_published(self, *_args, **_kwargs):
            return None

        async def mark_failed(self, *_args, **_kwargs):
            raise AssertionError("publisher should not fail")

    class Publisher:
        def __init__(self):
            self.sequences = []

        async def publish(self, event):
            self.sequences.append(event.seq)

    publisher = Publisher()
    await CodingOutboxDispatcher(
        Repository(), publisher, clock=lambda: now
    ).run_once()
    replay = await service.events.list_after(task.task_id, after_seq=1)

    assert publisher.sequences == [event.seq for event in replay] == [2, 3]

from datetime import UTC, datetime

from neos.coding.domain.events import make_event
from neos.coding.events.store import InMemoryCodingEventStore


NOW = datetime(2026, 7, 18, 10, 0, tzinfo=UTC)


async def test_append_assigns_strictly_increasing_task_sequence() -> None:
    store = InMemoryCodingEventStore()

    first = await store.append(
        task_id="ct_1", event_type="task.created", payload={}, now=NOW
    )
    second = await store.append(
        task_id="ct_1", event_type="text.delta", payload={"delta": "hi"}, now=NOW
    )

    assert [first.seq, second.seq] == [1, 2]


async def test_list_after_is_exclusive_ordered_and_bounded() -> None:
    store = InMemoryCodingEventStore()
    for index in range(4):
        await store.append(
            task_id="ct_1",
            event_type="text.delta",
            payload={"index": index},
            now=NOW,
        )

    replay = await store.list_after("ct_1", after_seq=1, limit=2)

    assert [event.seq for event in replay] == [2, 3]


async def test_append_preserves_explicit_event_metadata() -> None:
    store = InMemoryCodingEventStore()
    expected = make_event(
        task_id="ct_1",
        seq=1,
        event_type="run.started",
        payload={},
        now=NOW,
        event_id="ce_fixed",
        run_id="cr_1",
    )

    actual = await store.append_event(expected)

    assert actual == expected
    assert await store.head_seq("ct_1") == 1

import json
import logging
from typing import Any

import pytest

from neos.workflow.async_research_event_stream import (
    AsyncResearchEventStream,
    validate_event_id,
)


class FakeRedisStreams:
    def __init__(self, *, return_bytes: bool = False) -> None:
        self.return_bytes = return_bytes
        self.records: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.xadd_calls: list[tuple[str, dict[str, str], int, bool]] = []
        self.expire_calls: list[tuple[str, int]] = []
        self.xread_calls: list[tuple[dict[str, str], int, int]] = []

    async def xadd(
        self,
        key: str,
        fields: dict[str, str],
        *,
        maxlen: int,
        approximate: bool,
    ) -> str | bytes:
        event_id = f"{len(self.records.get(key, [])) + 1}-0"
        self.records.setdefault(key, []).append((event_id, fields))
        self.xadd_calls.append((key, fields, maxlen, approximate))
        return event_id.encode() if self.return_bytes else event_id

    async def expire(self, key: str, ttl_seconds: int) -> bool:
        self.expire_calls.append((key, ttl_seconds))
        return True

    async def xread(
        self,
        streams: dict[str, str],
        *,
        count: int,
        block: int,
    ) -> list[Any]:
        self.xread_calls.append((streams, count, block))
        key, cursor = next(iter(streams.items()))
        records = [
            (event_id, fields)
            for event_id, fields in self.records.get(key, [])
            if tuple(map(int, event_id.split("-")))
            > tuple(map(int, cursor.split("-")))
        ][:count]
        if not records:
            return []
        if not self.return_bytes:
            return [(key, records)]
        return [
            (
                key.encode(),
                [
                    (
                        event_id.encode(),
                        {
                            field.encode(): value.encode()
                            for field, value in fields.items()
                        },
                    )
                    for event_id, fields in records
                ],
            )
        ]


async def test_append_sets_max_length_and_refreshes_ttl() -> None:
    redis = FakeRedisStreams()
    store = AsyncResearchEventStream(redis, ttl_seconds=86400, max_length=1000)

    event_id = await store.append(
        "s1", "workflow_started", {"task_id": "j1"}
    )

    assert event_id == "1-0"
    assert redis.xadd_calls == [
        (
            "neos:async-research:events:s1",
            {
                "event": "workflow_started",
                "data": json.dumps({"task_id": "j1"}, ensure_ascii=False),
            },
            1000,
            True,
        )
    ]
    assert redis.expire_calls == [
        ("neos:async-research:events:s1", 86400)
    ]


async def test_separate_store_instances_replay_only_after_cursor() -> None:
    redis = FakeRedisStreams()
    producer = AsyncResearchEventStream(redis)
    consumer = AsyncResearchEventStream(redis)
    first = await producer.append("s1", "workflow_started", {"step": 1})
    await producer.append("s1", "workflow_completed", {"step": 2})

    events = await consumer.read_after("s1", first, block_ms=0)

    assert [(event.id, event.event, event.data) for event in events] == [
        ("2-0", "workflow_completed", '{"step": 2}')
    ]
    assert redis.xread_calls == [
        ({"neos:async-research:events:s1": "1-0"}, 100, 0)
    ]


async def test_bytes_responses_are_decoded() -> None:
    redis = FakeRedisStreams(return_bytes=True)
    store = AsyncResearchEventStream(redis)
    event_id = await store.append("s1", "workflow_started", "안녕")

    events = await store.read_after("s1", "0-0", block_ms=0)

    assert event_id == "1-0"
    assert [(event.id, event.event, event.data) for event in events] == [
        ("1-0", "workflow_started", '"안녕"')
    ]


async def test_empty_read_returns_no_events() -> None:
    store = AsyncResearchEventStream(FakeRedisStreams())

    assert await store.read_after("s1", "0-0", block_ms=0) == []


async def test_malformed_record_is_skipped_with_payload_free_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    redis = FakeRedisStreams()
    key = "neos:async-research:events:s1"
    redis.records[key] = [
        ("1-0", {"event": "workflow_started", "data": "secret-not-json"}),
        ("2-0", {"event": "workflow_completed", "data": '{"ok": true}'}),
    ]
    store = AsyncResearchEventStream(redis)

    with caplog.at_level(logging.WARNING):
        events = await store.read_after("s1", "0-0", block_ms=0)

    assert [(event.id, event.event) for event in events] == [
        ("2-0", "workflow_completed")
    ]
    assert "session=s1" in caplog.text
    assert "event_id=1-0" in caplog.text
    assert "secret-not-json" not in caplog.text


@pytest.mark.parametrize(
    "event_id",
    ["", "1", "1-", "-1", "-1-0", "1.0-0", "1-0 extra"],
)
def test_validate_event_id_rejects_invalid_values(event_id: str) -> None:
    with pytest.raises(ValueError, match="Invalid Redis stream event ID"):
        validate_event_id(event_id)


@pytest.mark.parametrize("event_id", ["0-0", "1-0", "1712345678901-12"])
def test_validate_event_id_accepts_redis_ids(event_id: str) -> None:
    assert validate_event_id(event_id) == event_id

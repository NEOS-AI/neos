import asyncio
import hashlib
import json
from typing import Any

from neos.coding.transport.redis_tickets import RedisCodingTicketStore


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.set_calls: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    async def set(
        self, key: str, value: str, *, ex: int, nx: bool
    ) -> bool | None:
        self.set_calls.append({"key": key, "value": value, "ex": ex, "nx": nx})
        async with self._lock:
            if nx and key in self.values:
                return None
            self.values[key] = value.encode()
            return True

    async def eval(self, script: str, numkeys: int, key: str) -> bytes | None:
        assert "GET" in script and "DEL" in script
        assert numkeys == 1
        async with self._lock:
            return self.values.pop(key, None)


async def test_ticket_is_consumed_atomically_across_store_instances() -> None:
    redis = FakeRedis()
    issuer = RedisCodingTicketStore(redis)
    consumer = RedisCodingTicketStore(redis)
    ticket = await issuer.issue(owner_id="u1", task_id="ct_1")

    first, second = await asyncio.gather(
        consumer.consume(ticket, task_id="ct_1"),
        issuer.consume(ticket, task_id="ct_1"),
    )

    assert sorted([first, second], key=lambda value: value is None) == ["u1", None]


async def test_ticket_key_is_hashed_and_set_with_expiry_and_nx() -> None:
    redis = FakeRedis()
    store = RedisCodingTicketStore(redis)

    ticket = await store.issue(owner_id="u1", task_id="ct_1")

    call = redis.set_calls[0]
    assert call["key"] == (
        "neos:coding:ws-ticket:" + hashlib.sha256(ticket.encode()).hexdigest()
    )
    assert ticket not in call["key"]
    assert call["ex"] == 30
    assert call["nx"] is True
    assert store.expires_in == 30


async def test_wrong_task_and_malformed_records_are_consumed_fail_closed() -> None:
    redis = FakeRedis()
    store = RedisCodingTicketStore(redis)
    wrong = await store.issue(owner_id="u1", task_id="ct_1")

    assert await store.consume(wrong, task_id="ct_other") is None
    assert await store.consume(wrong, task_id="ct_1") is None

    malformed = "cwt_malformed"
    malformed_key = "neos:coding:ws-ticket:" + hashlib.sha256(
        malformed.encode()
    ).hexdigest()
    redis.values[malformed_key] = b"not-json"

    assert await store.consume(malformed, task_id="ct_1") is None
    assert malformed_key not in redis.values


async def test_record_does_not_embed_raw_ticket() -> None:
    redis = FakeRedis()
    store = RedisCodingTicketStore(redis)

    ticket = await store.issue(owner_id="u1", task_id="ct_1")
    record = json.loads(redis.set_calls[0]["value"])

    assert record == {"owner_id": "u1", "task_id": "ct_1"}
    assert ticket not in redis.set_calls[0]["value"]

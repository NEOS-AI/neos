"""Q16b: the Redis relay against a **real** Redis (B6).

The contract fake in `test_device_bridge.py` runs everywhere; this file runs only when
`NEOS_TEST_REDIS_URL` is set, e.g.

    docker run --rm -d --name q16b-redis -p 6391:6379 redis:7-alpine
    NEOS_TEST_REDIS_URL=redis://localhost:6391/0 pytest tests/coding/test_device_bridge_relay_redis.py

The API side is built like `cache_manager` (one pool, bytes, health checks); the worker side
like `build_device_bridge_service` (a fresh client per operation). Each test has its own prefix.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets

import pytest

from neos.coding.bridge.relay import (
    DISPLACED,
    KICKED,
    LOST,
    BridgeView,
    DeviceRelayError,
    RedisDeviceBridgeRelay,
)

REDIS_URL = os.environ.get("NEOS_TEST_REDIS_URL", "")

pytestmark = [
    pytest.mark.no_db,
    pytest.mark.skipif(not REDIS_URL, reason="NEOS_TEST_REDIS_URL is not set"),
]


def _view(user="alice", *, conn="c1", bridge="dbr_1", tools=("read_file",), unattended=False):
    return BridgeView(user, bridge, conn, frozenset(tools), unattended)


@pytest.fixture
async def redis_pair():
    import redis.asyncio as redis

    prefix = f"neos:test-q16b:{secrets.token_hex(6)}"
    pool = redis.ConnectionPool.from_url(
        REDIS_URL,
        max_connections=20,
        decode_responses=False,
        encoding="utf-8",
        socket_keepalive=True,
        socket_connect_timeout=5,
        retry_on_timeout=True,
        health_check_interval=30,
    )
    shared = redis.Redis(connection_pool=pool, decode_responses=False)
    await shared.ping()
    opened: list = []

    def factory():
        client = redis.Redis.from_url(REDIS_URL)
        opened.append(client)
        return client

    api_side = RedisDeviceBridgeRelay(client=shared, ttl_seconds=5, prefix=prefix)
    worker_side = RedisDeviceBridgeRelay(client_factory=factory, ttl_seconds=5, prefix=prefix)
    yield shared, api_side, worker_side, prefix, opened
    keys = [key async for key in shared.scan_iter(match=f"{prefix}:*")]
    if keys:
        await shared.delete(*keys)
    await shared.aclose()
    await pool.aclose()


async def _noop(_message):
    return None


async def test_presence_is_set_with_a_ttl_and_refreshed_only_by_its_owner(redis_pair) -> None:
    """Lua compare-and-refresh. Mutation: refresh with a plain SET/PEXPIRE -> the displaced
    connection keeps the presence alive (or takes it back)."""
    shared, api, worker, prefix, _ = redis_pair
    key = f"{prefix}:presence:alice"

    old = await api.attach(_view(conn="c1"), _noop)
    ttl = await shared.pttl(key)
    assert 0 < ttl <= 5000
    assert (await worker.view("alice")).conn_id == "c1"

    new = await api.attach(_view(conn="c2"), _noop)
    await shared.pexpire(key, 1000)
    assert await old.refresh() is False and old.reason == DISPLACED
    assert await shared.pttl(key) <= 1000  # the loser did not extend it
    assert await new.refresh() is True and await shared.pttl(key) > 1000

    await old.detach()  # releases only its own value
    assert (await worker.view("alice")).conn_id == "c2"
    await shared.delete(key)
    assert await new.refresh() is False and new.reason == LOST
    await new.detach()


async def test_a_call_crosses_on_the_connection_channel_and_comes_back_on_the_reply_list(
    redis_pair,
) -> None:
    shared, api, worker, prefix, opened = redis_pair
    seen: list[dict] = []

    async def deliver(message):
        seen.append(dict(message))
        await api.respond(
            message["id"], {"id": message["id"], "user_id": "alice", "ok": True, "result": {"x": 1}}
        )

    attachment = await api.attach(_view(conn="c9"), deliver)
    view = await worker.view("alice")
    reply = await worker.request(view, {"id": "r1", "user_id": "alice", "tool": "read_file"}, timeout=2)

    assert reply == {"id": "r1", "user_id": "alice", "ok": True, "result": {"x": 1}}
    assert seen == [{"id": "r1", "user_id": "alice", "tool": "read_file", "type": "call"}]
    assert opened and all(c.connection_pool is not shared.connection_pool for c in opened)
    # Nothing waits on a reply nobody asked for -- and it does not live forever.
    await api.respond("orphan", {"id": "orphan"})
    assert 0 < await shared.ttl(f"{prefix}:reply:orphan") <= 60
    await attachment.detach()


async def test_another_connections_channel_does_not_hear_the_call(redis_pair) -> None:
    """Per-connection channel: a call for c1 never reaches c2 (B5 -- one answering device)."""
    _shared, api, worker, _prefix, _ = redis_pair
    heard: list[str] = []

    async def deliver_c1(message):
        heard.append("c1")
        await api.respond(message["id"], {"id": message["id"], "user_id": "alice", "ok": True})

    async def deliver_c2(message):
        heard.append("c2")

    first = await api.attach(_view("alice", conn="c1"), deliver_c1)
    other = await api.attach(_view("bob", conn="c2"), deliver_c2)

    await worker.request(_view("alice", conn="c1"), {"id": "r2", "user_id": "alice"}, timeout=2)

    assert heard == ["c1"]
    await first.detach()
    await other.detach()


async def test_unavailable_and_timeout_are_named(redis_pair) -> None:
    _shared, api, worker, _prefix, _ = redis_pair

    with pytest.raises(DeviceRelayError) as gone:
        await worker.request(_view(conn="nobody"), {"id": "r3"}, timeout=0.5)
    assert gone.value.code == "device_bridge_unavailable"

    attachment = await api.attach(_view(conn="c3"), _noop)
    started = asyncio.get_running_loop().time()
    with pytest.raises(DeviceRelayError) as late:
        await worker.request(_view(conn="c3"), {"id": "r4"}, timeout=0.3)
    assert late.value.code == "device_bridge_timeout"
    assert asyncio.get_running_loop().time() - started < 2.0
    await attachment.detach()


async def test_a_garbled_reply_is_named_not_raised(redis_pair) -> None:
    shared, api, worker, prefix, _ = redis_pair

    async def deliver(message):
        await shared.rpush(f"{prefix}:reply:{message['id']}", b"\xff not json")

    attachment = await api.attach(_view(conn="c4"), deliver)
    with pytest.raises(DeviceRelayError) as bad:
        await worker.request(_view(conn="c4"), {"id": "r5"}, timeout=2)
    assert bad.value.code == "device_result_invalid"
    await attachment.detach()


async def test_kick_releases_presence_and_closes_only_the_named_bridge(redis_pair) -> None:
    _shared, api, worker, _prefix, _ = redis_pair
    attachment = await api.attach(_view(conn="c5"), _noop)

    await worker.kick("alice", "dbr_other")
    assert await worker.view("alice") is not None and not attachment.closed.is_set()

    await worker.kick("alice", "dbr_1")
    await asyncio.wait_for(attachment.closed.wait(), 3)
    assert attachment.reason == KICKED and await worker.view("alice") is None
    await attachment.detach()


async def test_the_socket_session_and_the_service_over_real_redis(redis_pair) -> None:
    """End to end over Redis: socket session (API side) <-> service (worker side), a write
    included, and the displaced socket closes with 4409."""
    from neos.coding.bridge.session import CLOSE_DISPLACED
    from tests.coding.test_device_bridge import _answer_calls, _open, _registry, _service

    _shared, api, worker, _prefix, _ = redis_pair
    view = _view(tools=("read_file", "write_file"), conn="c6")

    class Live:
        allow_unattended = False
        allow_writes = True
        revoked = False

        async def get(self):
            return self

    socket, _session, task, _ = await _open(api, view, credential=Live(), presence_ttl_seconds=5)
    answering = asyncio.create_task(
        _answer_calls(socket, {"sha256": "d" * 64, "size": 2, "created": True, "text": "hi"})
    )
    service = _service(worker, call_timeout_seconds=3.0)

    wrote = await service.execute(
        "alice",
        _registry().validate("device_write_file.v1", {"path": "a.md", "content": "hi"}),
        unattended=False,
    )
    assert wrote.status == "ok" and wrote.checksum == "d" * 64
    assert json.loads(json.dumps(socket.calls()[0]["args"])) == {
        "path": "a.md",
        "content": "hi",
        "base_sha256": None,
        "max_bytes": 262_144,
    }

    newer, _s2, newer_task, _ = await _open(api, _view(conn="c7"), presence_ttl_seconds=5)
    assert await asyncio.wait_for(task, 5) == CLOSE_DISPLACED
    answering.cancel()
    newer_task.cancel()
    await asyncio.gather(newer_task, return_exceptions=True)


async def test_a_command_crosses_real_redis_with_its_executables_and_limits(redis_pair) -> None:
    """Q16c over Redis: the presence carries the declared executables to the worker (the service
    refuses one the bridge did not declare), and a command's wait covers its own time limit."""
    from neos.coding.bridge.service import DeviceBridgeService
    from neos.config.schema import DeviceBridgeConfig
    from tests.coding.test_device_bridge import _answer_calls, _open
    from tests.coding.test_device_bridge_commands import _run

    _shared, api, worker, _prefix, _ = redis_pair
    view = BridgeView(
        "alice", "dbr_1", "c8", frozenset({"read_file", "run_command"}), False, frozenset({"pytest"})
    )

    class Live:
        allow_unattended = False
        allow_commands = True
        revoked = False

        async def get(self):
            return self

    socket, _session, task, _ = await _open(api, view, credential=Live(), presence_ttl_seconds=5)
    seen = await worker.view("alice")
    assert seen is not None and seen.executables == {"pytest"}
    answering = asyncio.create_task(
        _answer_calls(socket, {"exit_code": 0, "timed_out": False, "stdout": "ok", "stderr": ""})
    )
    config = DeviceBridgeConfig(
        call_timeout_seconds=0.5, command_allowlist=["pytest", "ruff"], command_timeout_seconds=2
    )
    service = DeviceBridgeService(worker, config)

    ran = await service.execute("alice", _run(["pytest", "-q"]), unattended=False)
    other = await service.execute("alice", _run(["ruff"]), unattended=False)

    assert ran.status == "ok" and ran.exit_code == 0
    assert other.reason_code == "device_command_not_offered"
    assert json.loads(json.dumps(socket.calls()[0]["args"])) == {
        "argv": ["pytest", "-q"],
        "cwd": ".",
        "timeout_sec": 2.0,
        "max_output_bytes": 65_536,
    }
    answering.cancel()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from neos.api.channels.inbound_idempotency import EMPTY_CLAIM_TTL
from neos.api.channels.session_bind import InMemoryChannelCodingBindStore
from tests.api.channels.test_gateway_router import FakeCoding, _message
from tests.api.channels.test_session_bind import _gateway as _bound_gateway

pytestmark = pytest.mark.no_db


def test_empty_inbound_claim_ttl_stays_five_minutes() -> None:
    assert EMPTY_CLAIM_TTL == timedelta(minutes=5)


async def test_replayed_new_same_generation_id_skips_second_teardown(
    monkeypatch,
) -> None:
    store = InMemoryChannelCodingBindStore()
    gateway, workflow, coding = _bound_gateway(monkeypatch, binds=store)
    session = "v2:slack:T:C:gen"
    await gateway.dispatch(_message("/code first", session))

    first = _message("/new", session)
    first.metadata["generation_id"] = "gen-1"
    second = _message("/new", session)
    second.metadata["generation_id"] = "gen-1"

    assert await gateway.dispatch(first) == "Session reset."
    await gateway.dispatch(_message("/code second", session))
    assert await store.get(session) is not None

    replay = await gateway.dispatch(second)

    assert replay == "Session reset."
    assert coding.stopped == ["ct_channel"]
    assert await store.get(session) is not None
    assert workflow.calls == []


async def test_new_generation_token_on_command_is_idempotent(monkeypatch) -> None:
    store = InMemoryChannelCodingBindStore()
    gateway, _workflow, coding = _bound_gateway(monkeypatch, binds=store)
    session = "v2:slack:T:C:cmd"
    await gateway.dispatch(_message("/code first", session))

    assert await gateway.dispatch(_message("/new gen-cmd", session)) == "Session reset."
    await gateway.dispatch(_message("/code second", session))

    replay = await gateway.dispatch(_message("/new gen-cmd", session))

    assert replay == "Session reset."
    assert coding.stopped == ["ct_channel"]
    assert await store.get(session) is not None


async def test_different_generation_id_tears_down_again(monkeypatch) -> None:
    store = InMemoryChannelCodingBindStore()
    gateway, _workflow, coding = _bound_gateway(monkeypatch, binds=store)
    session = "v2:slack:T:C:next"
    await gateway.dispatch(_message("/code first", session))

    first = _message("/new", session)
    first.metadata["generation"] = "gen-a"
    assert await gateway.dispatch(first) == "Session reset."
    await gateway.dispatch(_message("/code second", session))

    second = _message("/new", session)
    second.metadata["generation"] = "gen-b"
    assert await gateway.dispatch(second) == "Session reset."
    assert coding.stopped == ["ct_channel", "ct_channel"]
    assert await store.get(session) is None


async def test_generation_fence_expires_after_24h(monkeypatch) -> None:
    from neos.api.channels.generation_fence import (
        GENERATION_FENCE_TTL,
        InMemoryChannelGenerationFenceStore,
    )

    clock_now = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)

    def clock() -> datetime:
        return clock_now

    store = InMemoryChannelCodingBindStore()
    fences = InMemoryChannelGenerationFenceStore(clock=clock)
    gateway, _workflow, coding = _bound_gateway(monkeypatch, binds=store)
    gateway._generations = fences
    session = "v2:slack:T:C:ttl"
    await gateway.dispatch(_message("/code first", session))

    first = _message("/new", session)
    first.metadata["generation_id"] = "gen-ttl"
    assert await gateway.dispatch(first) == "Session reset."
    await gateway.dispatch(_message("/code second", session))

    clock_now = clock_now + GENERATION_FENCE_TTL + timedelta(seconds=1)
    replay = _message("/new", session)
    replay.metadata["generation_id"] = "gen-ttl"
    assert await gateway.dispatch(replay) == "Session reset."
    assert coding.stopped == ["ct_channel", "ct_channel"]
    assert await store.get(session) is None

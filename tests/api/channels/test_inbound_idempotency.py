from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from neos.api.channels.inbound_idempotency import (
    EMPTY_CLAIM_TTL,
    InMemoryChannelInboundIdempotencyStore,
)

pytestmark = pytest.mark.no_db


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


async def test_empty_claim_expires_and_can_be_reclaimed() -> None:
    clock = _Clock(datetime(2026, 9, 13, 12, 0, tzinfo=UTC))
    store = InMemoryChannelInboundIdempotencyStore(clock=clock)

    won, first = await store.claim("sess", "k1")
    assert won is True
    assert first is not None
    assert first.outcome == ""

    clock.now = first.created_at + EMPTY_CLAIM_TTL + timedelta(seconds=1)
    assert await store.get("sess", "k1") is None

    won_again, second = await store.claim("sess", "k1")
    assert won_again is True
    assert second is not None
    assert second.outcome == ""
    assert second.created_at == clock.now


async def test_empty_claim_within_ttl_is_still_busy() -> None:
    clock = _Clock(datetime(2026, 9, 13, 12, 0, tzinfo=UTC))
    store = InMemoryChannelInboundIdempotencyStore(clock=clock)

    await store.claim("sess", "k1")
    clock.now = clock.now + EMPTY_CLAIM_TTL - timedelta(seconds=1)

    won, existing = await store.claim("sess", "k1")
    assert won is False
    assert existing is not None
    assert existing.outcome == ""
    assert await store.get("sess", "k1") is not None


async def test_remembered_outcome_does_not_expire_with_empty_claim_ttl() -> None:
    clock = _Clock(datetime(2026, 9, 13, 12, 0, tzinfo=UTC))
    store = InMemoryChannelInboundIdempotencyStore(clock=clock)

    await store.claim("sess", "k1")
    remembered = await store.remember("sess", "k1", "workflow-ok")
    clock.now = remembered.created_at + EMPTY_CLAIM_TTL + timedelta(hours=1)

    found = await store.get("sess", "k1")
    assert found is not None
    assert found.outcome == "workflow-ok"
    won, existing = await store.claim("sess", "k1")
    assert won is False
    assert existing is not None
    assert existing.outcome == "workflow-ok"

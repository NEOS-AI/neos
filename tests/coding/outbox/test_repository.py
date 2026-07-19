from datetime import UTC, datetime, timedelta

import pytest

from neos.coding.outbox.repository import PostgresCodingOutboxRepository


NOW = datetime(2026, 7, 18, 11, 0, tzinfo=UTC)


class FakeResult:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def all(self):
        return self._rows


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


class FakeSession:
    def __init__(self, rows=()):
        self.rows = rows
        self.statements: list[tuple[str, dict]] = []

    def begin(self):
        return FakeTransaction()

    async def execute(self, statement, params=None):
        self.statements.append((str(statement), params or {}))
        return FakeResult(self.rows)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


def repository_for(session: FakeSession) -> PostgresCodingOutboxRepository:
    async def session_factory():
        return session

    return PostgresCodingOutboxRepository(session_factory)


async def test_claim_uses_skip_locked_and_preserves_per_task_order() -> None:
    session = FakeSession()
    repository = repository_for(session)

    await repository.claim_batch(
        limit=100,
        now=NOW,
        stale_before=NOW - timedelta(seconds=30),
    )

    sql = "\n".join(statement for statement, _ in session.statements)
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "NOT EXISTS" in sql
    assert "earlier.task_id = candidate.task_id" in sql
    assert "earlier.seq < candidate.seq" in sql
    assert "next_attempt_at <= :now" in sql
    assert "claimed_at < :stale_before" in sql


async def test_claim_maps_canonical_event_envelope() -> None:
    session = FakeSession(
        rows=[
            (
                "co_1", 2, 1, "ct_1", 7, "ce_7", "text.delta",
                {"delta": "hi"}, NOW, "cr_1", "turn_1", None, "cc_7",
            )
        ]
    )

    claimed = await repository_for(session).claim_batch(
        limit=1, now=NOW, stale_before=NOW - timedelta(seconds=30)
    )

    assert claimed[0].outbox_id == "co_1"
    assert claimed[0].attempt_count == 2
    assert claimed[0].event.event_id == "ce_7"
    assert claimed[0].event.seq == 7
    assert claimed[0].event.payload == {"delta": "hi"}
    assert claimed[0].event.checkpoint_id == "cc_7"


@pytest.mark.parametrize("limit", [0, 501])
async def test_claim_rejects_unbounded_limit(limit: int) -> None:
    with pytest.raises(ValueError):
        await repository_for(FakeSession()).claim_batch(
            limit=limit, now=NOW, stale_before=NOW
        )


async def test_mark_failed_truncates_error_and_releases_claim() -> None:
    session = FakeSession()

    await repository_for(session).mark_failed(
        "co_1", error="x" * 3000, next_attempt_at=NOW
    )

    sql, params = session.statements[0]
    assert "attempt_count = attempt_count + 1" in sql
    assert "claimed_at = NULL" in sql
    assert len(params["error"]) == 2000

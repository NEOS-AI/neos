from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest

from neos.coding.domain.durability import (
    ExecutionLease,
    StaleExecutionLease,
    ToolExecutionClaim,
    ToolExecutionDisposition,
)
from neos.coding.domain.events import CodingEvent
from neos.coding.repositories.run_repository import PostgresCodingRunRepository


NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
EXPIRES = NOW + timedelta(seconds=30)
LEASE = ExecutionLease(
    task_id="ct_1",
    run_id="cr_1",
    worker_id="worker-a",
    fencing_token=2,
    acquired_at=NOW,
    expires_at=EXPIRES,
)


class FakeResult:
    def __init__(self, row=None) -> None:
        self._row = row

    def first(self):
        return self._row


class FakeSession:
    def __init__(self, *, rows=()) -> None:
        self.rows = list(rows)
        self.sql: list[str] = []
        self.params: list[dict] = []

    def begin(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.sql.append(sql)
        self.params.append(params or {})
        row = self.rows.pop(0) if self.rows else None
        return FakeResult(row)


@asynccontextmanager
async def async_session(session: FakeSession):
    yield session


def repository_for(session: FakeSession) -> PostgresCodingRunRepository:
    async def session_factory():
        return async_session(session)

    return PostgresCodingRunRepository(session_factory)


async def test_acquire_lease_uses_one_atomic_upsert() -> None:
    session = FakeSession(
        rows=[("ct_1", "cr_1", "worker-a", 3, NOW, EXPIRES, True)]
    )
    repository = repository_for(session)

    lease = await repository.acquire_execution_lease(
        task_id="ct_1",
        run_id="cr_1",
        worker_id="worker-a",
        now=NOW,
        expires_at=EXPIRES,
    )

    sql = "\n".join(session.sql)
    assert "INSERT INTO coding_run_leases" in sql
    assert "expires_at <= :now" in sql
    assert "fencing_token + 1" in sql
    assert lease is not None
    assert lease.fencing_token == 3
    assert lease.recovered is True


async def test_renew_rejects_stale_fencing_token() -> None:
    session = FakeSession(rows=[None])
    repository = repository_for(session)

    with pytest.raises(StaleExecutionLease):
        await repository.renew_execution_lease(
            LEASE, now=NOW, expires_at=EXPIRES
        )

    assert "fencing_token = :fencing_token" in "\n".join(session.sql)


async def test_release_expires_row_without_deleting_fencing_history() -> None:
    session = FakeSession(rows=[("ct_1",)])
    repository = repository_for(session)

    await repository.release_execution_lease(LEASE, now=NOW)

    sql = "\n".join(session.sql)
    assert "UPDATE coding_run_leases" in sql
    assert "SET expires_at = :now" in sql
    assert "DELETE FROM coding_run_leases" not in sql


async def test_tool_claim_is_written_before_execution() -> None:
    session = FakeSession(rows=[("claimed", None)])
    repository = repository_for(session)

    claim = await repository.claim_tool_execution(
        lease=LEASE,
        tool_call_id="tool_1",
        now=NOW,
        claim_expires_at=EXPIRES,
    )

    sql = "\n".join(session.sql)
    assert "INSERT INTO coding_tool_executions" in sql
    assert "fencing_token" in sql
    assert claim.disposition is ToolExecutionDisposition.CLAIMED


async def test_completed_tool_claim_returns_persisted_result() -> None:
    session = FakeSession(rows=[("completed", {"ok": True})])
    repository = repository_for(session)

    claim = await repository.claim_tool_execution(
        lease=LEASE,
        tool_call_id="tool_1",
        now=NOW,
        claim_expires_at=EXPIRES,
    )

    assert claim.disposition is ToolExecutionDisposition.COMPLETED
    assert claim.result == {"ok": True}


async def test_tool_claim_rejects_stale_execution_lease() -> None:
    session = FakeSession(rows=[(None, None, False)])
    repository = repository_for(session)

    with pytest.raises(StaleExecutionLease):
        await repository.claim_tool_execution(
            lease=LEASE,
            tool_call_id="tool_1",
            now=NOW,
            claim_expires_at=EXPIRES,
        )


async def test_complete_tool_result_requires_current_claim() -> None:
    session = FakeSession(rows=[("ct_1",), (8,)])
    repository = repository_for(session)
    claim = ToolExecutionClaim(
        disposition=ToolExecutionDisposition.CLAIMED,
        tool_call_id="tool_1",
        lease=LEASE,
    )

    event = await repository.complete_tool_execution(
        claim, result={"ok": True}, now=NOW
    )

    sql = "\n".join(session.sql)
    assert "UPDATE coding_tool_executions" in sql
    assert "status = 'completed'" in sql
    assert "INSERT INTO coding_events" in sql
    assert "INSERT INTO coding_event_outbox" in sql
    assert isinstance(event, CodingEvent)
    assert event.tool_call_id == "tool_1"


async def test_complete_tool_result_rejects_stale_claim() -> None:
    session = FakeSession(rows=[None])
    repository = repository_for(session)
    claim = ToolExecutionClaim(
        disposition=ToolExecutionDisposition.CLAIMED,
        tool_call_id="tool_1",
        lease=LEASE,
    )

    with pytest.raises(StaleExecutionLease):
        await repository.complete_tool_execution(
            claim, result={"ok": True}, now=NOW
        )

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest

from neos.coding.domain.durability import (
    ExecutionLease,
    StaleExecutionLease,
    ToolExecutionClaim,
    ToolExecutionDisposition,
)
from neos.coding.domain.phases import CodingRun, CodingRunStatus
from neos.coding.repositories.run_repository import PostgresCodingRunRepository
from tests.coding.fakes import InMemoryCodingRunRepository


NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
EXPIRES = NOW + timedelta(seconds=30)
CHILD_POINTERS = {
    "child_run_id": "sa_1",
    "child_checkpoint_id": "sc_1",
}
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
        reads_row = "SELECT" in sql or "RETURNING" in sql
        row = self.rows.pop(0) if self.rows and reads_row else None
        return FakeResult(row)


@asynccontextmanager
async def async_session(session: FakeSession):
    yield session


def repository_for(session: FakeSession) -> PostgresCodingRunRepository:
    async def session_factory():
        return async_session(session)

    return PostgresCodingRunRepository(session_factory)


def _running_repo() -> InMemoryCodingRunRepository:
    run = CodingRun(
        run_id="cr_1",
        task_id="ct_1",
        attempt=1,
        status=CodingRunStatus.RUNNING,
        resume_from_checkpoint_id=None,
        started_at=NOW,
    )
    repository = InMemoryCodingRunRepository(active_run=run)
    repository.created_runs.append(run)
    repository.task_statuses["ct_1"] = "running"
    return repository


async def _acquire(repository, *, worker_id: str, now: datetime):
    return await repository.acquire_execution_lease(
        task_id="ct_1",
        run_id="cr_1",
        worker_id=worker_id,
        now=now,
        expires_at=now + timedelta(seconds=30),
    )


async def _handoff_to_next_delivery(repository, lease, *, now: datetime, worker_id: str):
    await repository.release_execution_lease(lease, now=now)
    next_lease = await _acquire(repository, worker_id=worker_id, now=now)
    assert next_lease is not None
    return next_lease


@pytest.mark.no_db
async def test_fake_unexpired_delegated_adopts_this_delivery_and_is_not_busy() -> None:
    repository = _running_repo()
    lease_a = await _acquire(repository, worker_id="w1", now=NOW)
    assert lease_a is not None
    claim_a = await repository.claim_tool_execution(
        lease=lease_a,
        tool_call_id="tool_1",
        now=NOW,
        claim_expires_at=NOW + timedelta(seconds=150),
    )
    assert claim_a.disposition is ToolExecutionDisposition.CLAIMED
    await repository.mark_tool_delegated(
        claim_a,
        child_run_id="sa_1",
        child_checkpoint_id="sc_1",
        claim_expires_at=NOW + timedelta(seconds=150),
        now=NOW,
    )

    later = NOW + timedelta(seconds=1)
    lease_b = await _handoff_to_next_delivery(
        repository, lease_a, now=later, worker_id="w2"
    )
    claim_b = await repository.claim_tool_execution(
        lease=lease_b,
        tool_call_id="tool_1",
        now=later,
        claim_expires_at=later + timedelta(seconds=150),
    )

    assert claim_b.disposition is ToolExecutionDisposition.DELEGATED
    assert claim_b.disposition is not ToolExecutionDisposition.BUSY
    assert claim_b.lease.worker_id == "w2"
    assert claim_b.lease.fencing_token == lease_b.fencing_token
    assert claim_b.result == CHILD_POINTERS
    stored, expiry = repository.tool_claims[("ct_1", "tool_1")]
    assert stored.disposition is ToolExecutionDisposition.DELEGATED
    assert stored.lease.worker_id == "w2"
    assert stored.lease.fencing_token == lease_b.fencing_token
    assert expiry == later + timedelta(seconds=150)


@pytest.mark.no_db
async def test_fake_expired_delegated_is_reclaimed() -> None:
    repository = _running_repo()
    lease_a = await _acquire(repository, worker_id="w1", now=NOW)
    assert lease_a is not None
    claim_a = await repository.claim_tool_execution(
        lease=lease_a,
        tool_call_id="tool_1",
        now=NOW,
        claim_expires_at=NOW + timedelta(seconds=30),
    )
    await repository.mark_tool_delegated(
        claim_a,
        child_run_id="sa_1",
        child_checkpoint_id="sc_1",
        claim_expires_at=NOW + timedelta(seconds=30),
        now=NOW,
    )

    later = NOW + timedelta(seconds=31)
    lease_b = await _handoff_to_next_delivery(
        repository, lease_a, now=later, worker_id="w2"
    )
    claim_b = await repository.claim_tool_execution(
        lease=lease_b,
        tool_call_id="tool_1",
        now=later,
        claim_expires_at=later + timedelta(seconds=150),
    )

    assert claim_b.disposition is ToolExecutionDisposition.RECLAIMED
    stored, _ = repository.tool_claims[("ct_1", "tool_1")]
    assert stored.disposition is ToolExecutionDisposition.RECLAIMED
    assert stored.lease.worker_id == "w2"
    assert stored.lease.fencing_token == lease_b.fencing_token


@pytest.mark.no_db
async def test_fake_adopt_lets_delivery_b_complete_and_rejects_stale_lease_a() -> None:
    repository = _running_repo()
    lease_a = await _acquire(repository, worker_id="w1", now=NOW)
    assert lease_a is not None
    assert lease_a.fencing_token == 1
    claim_a = await repository.claim_tool_execution(
        lease=lease_a,
        tool_call_id="tool_1",
        now=NOW,
        claim_expires_at=NOW + timedelta(seconds=150),
    )
    await repository.mark_tool_delegated(
        claim_a,
        child_run_id="sa_1",
        child_checkpoint_id="sc_1",
        claim_expires_at=NOW + timedelta(seconds=150),
        now=NOW,
    )

    later = NOW + timedelta(seconds=1)
    lease_b = await _handoff_to_next_delivery(
        repository, lease_a, now=later, worker_id="w2"
    )
    assert lease_b.worker_id == "w2"
    assert lease_b.fencing_token == 2
    claim_b = await repository.claim_tool_execution(
        lease=lease_b,
        tool_call_id="tool_1",
        now=later,
        claim_expires_at=later + timedelta(seconds=150),
    )
    assert claim_b.disposition is ToolExecutionDisposition.DELEGATED
    assert claim_b.lease.fencing_token == 2

    with pytest.raises(StaleExecutionLease):
        await repository.complete_tool_execution(
            claim_a, result={"folded": False}, now=later
        )

    fold_claim = ToolExecutionClaim(
        disposition=ToolExecutionDisposition.DELEGATED,
        tool_call_id="tool_1",
        lease=lease_b,
        result=claim_b.result,
    )
    event = await repository.complete_tool_execution(
        fold_claim, result={"folded": True}, now=later
    )
    assert event.type == "tool.completed"
    assert event.payload["result"] == {"folded": True}


@pytest.mark.no_db
async def test_claim_sql_adopts_unexpired_delegated_without_old_fencing() -> None:
    session = FakeSession(rows=[("delegated", CHILD_POINTERS)])
    repository = repository_for(session)

    claim = await repository.claim_tool_execution(
        lease=LEASE,
        tool_call_id="tool_1",
        now=NOW,
        claim_expires_at=EXPIRES,
    )

    sql = "\n".join(session.sql)
    assert claim.disposition is ToolExecutionDisposition.DELEGATED
    assert claim.result == CHILD_POINTERS
    assert "adopted AS" in sql
    assert "execution.status = 'delegated'" in sql
    assert "SELECT 'delegated' AS disposition" in sql
    adopted = sql.split("adopted AS")[1].split("SELECT 'delegated'")[0]
    assert "AND execution.worker_id" not in adopted
    assert "AND execution.fencing_token" not in adopted


@pytest.mark.no_db
async def test_complete_accepts_delegated_under_current_status_predicate() -> None:
    session = FakeSession(rows=[("ct_1",), (8,)])
    repository = repository_for(session)
    claim = ToolExecutionClaim(
        disposition=ToolExecutionDisposition.DELEGATED,
        tool_call_id="tool_1",
        lease=LEASE,
        result=CHILD_POINTERS,
    )

    event = await repository.complete_tool_execution(
        claim, result={"folded": True}, now=NOW
    )

    sql = "\n".join(session.sql)
    assert "IN ('claimed', 'delegated')" in sql
    assert event.tool_call_id == "tool_1"
    assert event.payload["result"] == {"folded": True}


@pytest.mark.no_db
async def test_mark_tool_delegated_writes_child_pointers_under_current_fencing() -> None:
    session = FakeSession(rows=[("ct_1",)])
    repository = repository_for(session)
    claim = ToolExecutionClaim(
        disposition=ToolExecutionDisposition.CLAIMED,
        tool_call_id="tool_1",
        lease=LEASE,
    )

    await repository.mark_tool_delegated(
        claim,
        child_run_id="sa_1",
        child_checkpoint_id="sc_1",
        claim_expires_at=EXPIRES,
        now=NOW,
    )

    sql = "\n".join(session.sql)
    params = session.params[0]
    assert "status = 'delegated'" in sql
    assert "status IN ('claimed', 'delegated')" in sql
    assert "worker_id = :worker_id" in sql
    assert "fencing_token = :fencing_token" in sql
    assert params["worker_id"] == "worker-a"
    assert params["fencing_token"] == 2
    assert '"child_run_id": "sa_1"' in params["result"]
    assert '"child_checkpoint_id": "sc_1"' in params["result"]

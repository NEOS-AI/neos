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
from neos.coding.domain.phases import (
    CodingCheckpoint,
    CodingPhase,
    CodingPhaseKind,
    CodingPhaseStatus,
    SteeringRequest,
    SteeringMode,
)
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
ACTIVE_PHASE = CodingPhase(
    phase_id="cp_cr_1_understand_1",
    task_id="ct_1",
    run_id="cr_1",
    kind=CodingPhaseKind.UNDERSTAND,
    attempt=1,
    status=CodingPhaseStatus.ACTIVE,
    started_at=NOW,
)
SAFE_POINT_CHECKPOINT = CodingCheckpoint(
    checkpoint_id="cc_safe_1",
    task_id="ct_1",
    run_id="cr_1",
    seq=10,
    loop_state={
        "phase_index": 0,
        "transcript": [{"role": "assistant", "content": "understood"}],
        "current_instruction": "Fix it",
        "pending_instruction": None,
    },
    workspace_revision="rev_1",
    created_at=NOW,
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


async def test_acquire_lease_uses_one_atomic_upsert() -> None:
    session = FakeSession(rows=[("ct_1", "cr_1", "worker-a", 3, NOW, EXPIRES, True)])
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
    assert "previous.worker_id <> :worker_id" in sql
    assert lease is not None
    assert lease.fencing_token == 3
    assert lease.recovered is True


async def test_acquire_lease_fences_expected_checkpoint_in_same_statement() -> None:
    session = FakeSession(rows=[None])
    repository = repository_for(session)

    lease = await repository.acquire_execution_lease(
        task_id="ct_1",
        run_id="cr_1",
        worker_id="worker-a",
        now=NOW,
        expires_at=EXPIRES,
        expected_checkpoint_id="cc_expected",
    )

    sql = "\n".join(session.sql)
    assert "checkpoint_matches" in sql
    assert "run_id = :run_id" in sql
    assert "IS NOT DISTINCT FROM :expected_checkpoint_id" in sql
    assert "ORDER BY candidate.attempt DESC" in sql
    assert "canonical.run_id = :run_id" in sql
    assert "canonical.status = 'running'" in sql
    assert session.params[0]["expected_checkpoint_id"] == "cc_expected"
    assert session.params[0]["validate_checkpoint"] is True
    assert lease is None


async def test_renew_rejects_stale_fencing_token() -> None:
    session = FakeSession(rows=[None])
    repository = repository_for(session)

    with pytest.raises(StaleExecutionLease):
        await repository.renew_execution_lease(LEASE, now=NOW, expires_at=EXPIRES)

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


async def test_expired_tool_claim_is_reported_as_reclaimed() -> None:
    session = FakeSession(rows=[("reclaimed", None)])
    repository = repository_for(session)

    claim = await repository.claim_tool_execution(
        lease=LEASE,
        tool_call_id="tool_1",
        now=NOW,
        claim_expires_at=EXPIRES,
    )

    assert claim.disposition is ToolExecutionDisposition.RECLAIMED
    assert "prior_execution" in "\n".join(session.sql)


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
        await repository.complete_tool_execution(claim, result={"ok": True}, now=NOW)


async def test_begin_phase_returns_existing_active_attempt_without_event() -> None:
    session = FakeSession(
        rows=[
            ("ct_1",),
            (
                ACTIVE_PHASE.phase_id,
                ACTIVE_PHASE.task_id,
                ACTIVE_PHASE.run_id,
                ACTIVE_PHASE.kind.value,
                ACTIVE_PHASE.attempt,
                ACTIVE_PHASE.status.value,
                ACTIVE_PHASE.started_at,
                None,
            ),
        ]
    )
    repository = repository_for(session)

    started = await repository.begin_phase(
        lease=LEASE, kind=CodingPhaseKind.UNDERSTAND, now=NOW
    )

    assert started.phase == ACTIVE_PHASE
    assert started.event is None
    assert started.resumed is True
    assert "INSERT INTO coding_phases" not in "\n".join(session.sql)


async def test_begin_phase_does_not_lock_aggregate_result() -> None:
    session = FakeSession(rows=[("ct_1",), None, (1,), (5,)])
    repository = repository_for(session)

    started = await repository.begin_phase(
        lease=LEASE, kind=CodingPhaseKind.PLAN, now=NOW
    )

    aggregate_sql = next(sql for sql in session.sql if "MAX(attempt)" in sql)
    assert "FOR UPDATE" not in aggregate_sql
    assert started.phase.attempt == 1
    assert started.event is not None and started.event.seq == 5


async def test_phase_checkpoint_satisfies_fk_order_in_one_transaction() -> None:
    session = FakeSession(rows=[("ct_1",), (11,), (ACTIVE_PHASE.phase_id,)])
    repository = repository_for(session)

    committed = await repository.commit_phase_checkpoint(
        lease=LEASE,
        phase=ACTIVE_PHASE,
        tool_call_id="tool_1",
        result={"summary": "done"},
        loop_state={
            "phase_index": 0,
            "transcript": [],
            "current_instruction": "Fix it",
            "pending_instruction": None,
        },
        workspace_revision="rev_1",
        now=NOW,
    )

    sql = "\n".join(session.sql)
    assert sql.index("INSERT INTO coding_checkpoints") < sql.index(
        "INSERT INTO coding_events"
    )
    assert sql.index("INSERT INTO coding_events") < sql.index(
        "INSERT INTO coding_event_outbox"
    )
    assert "UPDATE coding_phases" in sql
    assert isinstance(committed.checkpoint, CodingCheckpoint)
    assert committed.checkpoint.seq == committed.event.seq == 11
    assert committed.phase.status is CodingPhaseStatus.COMPLETED


async def test_model_checkpoint_is_fenced_and_has_no_tool_claim() -> None:
    session = FakeSession(rows=[("ct_1",), ("cr_1",), (12,)])
    repository = repository_for(session)

    committed = await repository.commit_model_checkpoint(
        lease=LEASE,
        event_type="model.completed",
        event_payload={"stop_reason": "end_turn"},
        loop_state={"transcript": [], "current_instruction": "Fix it"},
        workspace_revision="rev_1",
        now=NOW,
    )

    sql = "\n".join(session.sql)
    assert "fencing_token = :fencing_token" in sql
    assert "FROM coding_runs" in sql and "FOR UPDATE" in sql
    assert sql.index("INSERT INTO coding_checkpoints") < sql.index(
        "INSERT INTO coding_events"
    )
    assert "INSERT INTO coding_event_outbox" in sql
    assert "coding_tool_executions" not in sql
    assert committed.checkpoint.seq == committed.event.seq == 12


async def test_model_checkpoint_rejects_stale_fencing_token() -> None:
    session = FakeSession(rows=[None])
    repository = repository_for(session)

    with pytest.raises(StaleExecutionLease):
        await repository.commit_model_checkpoint(
            lease=LEASE,
            event_type="tool.denied",
            event_payload={"reason_code": "policy_unknown_tool"},
            loop_state={"transcript": []},
            workspace_revision="rev_1",
            now=NOW,
        )

    assert "INSERT INTO coding_checkpoints" not in "\n".join(session.sql)


async def test_safe_steering_reclaims_expired_claim_and_transitions_atomically() -> (
    None
):
    session = FakeSession(
        rows=[
            ("ct_1",),
            (
                "cs_1",
                "ct_1",
                SteeringMode.SAFE_POINT.value,
                "Inspect cache first",
                NOW - timedelta(seconds=10),
            ),
            (11,),
            ("cr_1", "ct_1", 1, "running", None, NOW, None),
            ("ct_1", "cr_2", "worker-b", 3, NOW, EXPIRES, False),
        ]
    )
    repository = repository_for(session)

    applied = await repository.apply_steering_at_safe_point(
        lease=LEASE,
        checkpoint=SAFE_POINT_CHECKPOINT,
        worker_id="worker-b",
        claim_expires_at=EXPIRES,
        now=NOW,
    )

    sql = "\n".join(session.sql)
    assert "claim_expires_at <= :now" in sql
    assert sql.index("INSERT INTO coding_checkpoints") < sql.index(
        "INSERT INTO coding_events"
    )
    assert "UPDATE coding_steering_requests" in sql
    assert "UPDATE coding_runs" in sql
    assert "INSERT INTO coding_runs" in sql
    assert "UPDATE coding_run_leases" in sql
    assert applied is not None
    assert applied.request.instruction == "Inspect cache first"
    assert applied.run.attempt == 2
    assert applied.lease.fencing_token == 3


async def test_interruption_commit_requires_stopped_process_and_is_atomic() -> None:
    request = SteeringRequest(
        steering_id="cs_interrupt_1",
        task_id="ct_1",
        mode=SteeringMode.INTERRUPT_NOW,
        instruction="Inspect cache now",
        requested_at=NOW,
    )
    session = FakeSession(
        rows=[
            ("ct_1",),
            (12,),
            ("cr_1", "ct_1", 1, "running", None, NOW, None),
            ("ct_1", "cr_2", "worker-a", 3, NOW, EXPIRES, False),
        ]
    )
    repository = repository_for(session)

    with pytest.raises(ValueError, match="process must be stopped"):
        await repository.commit_interruption(
            lease=LEASE,
            request=request,
            workspace_revision="rev_interrupt",
            process_stopped=False,
            now=NOW,
        )

    applied = await repository.commit_interruption(
        lease=LEASE,
        request=request,
        workspace_revision="rev_interrupt",
        process_stopped=True,
        now=NOW,
    )

    sql = "\n".join(session.sql)
    assert sql.index("INSERT INTO coding_checkpoints") < sql.index(
        "INSERT INTO coding_events"
    )
    assert "UPDATE coding_steering_requests" in sql
    assert "UPDATE coding_runs" in sql
    assert "INSERT INTO coding_runs" in sql
    assert "UPDATE coding_run_leases" in sql
    assert applied.event.type == "run.interrupted"
    assert applied.run.attempt == 2

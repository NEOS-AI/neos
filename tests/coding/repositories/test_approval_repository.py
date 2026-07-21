from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from neos.coding.domain.approvals import (
    ApprovalDecision,
    ApprovalStatus,
    canonical_approval_hash,
)
from neos.coding.domain.durability import ExecutionLease
from neos.coding.model.base import ToolCallCompleted
from neos.coding.repositories.run_repository import PostgresCodingRunRepository
from neos.coding.domain.phases import CodingRun, CodingRunStatus
from neos.coding.tools.registry import ToolRisk, ValidatedToolCall
from tests.coding.fakes import InMemoryCodingRunRepository


NOW = datetime(2026, 7, 21, 0, 0, tzinfo=UTC)
LEASE = ExecutionLease(
    task_id="ct_1",
    run_id="cr_1",
    worker_id="worker-1",
    fencing_token=3,
    acquired_at=NOW,
    expires_at=NOW + timedelta(seconds=30),
)
CALL = ToolCallCompleted(
    tool_call_id="tool_1",
    name="write_file.v1",
    input={"path": "src/main.py", "content": "raw-secret"},
)
VALIDATED = ValidatedToolCall(CALL.name, CALL.input, ToolRisk.WORKSPACE_WRITE)


class FakeResult:
    def __init__(self, row=None) -> None:
        self._row = row

    def first(self):
        return self._row


class FakeSession:
    def __init__(self, rows=()) -> None:
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


def repository_for(session: FakeSession) -> PostgresCodingRunRepository:
    @asynccontextmanager
    async def session_context():
        yield session

    async def session_factory():
        return session_context()

    return PostgresCodingRunRepository(session_factory)


def request_kwargs() -> dict:
    return {
        "lease": LEASE,
        "tool_call": CALL,
        "validated": VALIDATED,
        "loop_state": {"pending_tool_index": 0},
        "workspace_revision": "rev-1",
        "requested_at": NOW,
        "expires_at": NOW + timedelta(seconds=900),
    }


async def test_request_is_one_fenced_durable_transaction() -> None:
    session = FakeSession(
        rows=[("ct_1",), ("user-1",), None, (10,), ("ct_1",), (11,)]
    )
    repository = repository_for(session)

    commit = await repository.request_tool_approval(**request_kwargs())

    sql = "\n".join(session.sql)
    assert "fencing_token = :fencing_token" in sql
    assert "status = 'running'" in sql
    assert "INSERT INTO coding_checkpoints" in sql
    assert "INSERT INTO coding_approvals" in sql
    assert "SET status = 'waiting_approval'" in sql
    assert sql.count("INSERT INTO coding_events") == 2
    assert sql.count("INSERT INTO coding_event_outbox") == 2
    assert "normalized_input" not in sql
    assert "raw-secret" not in sql
    assert commit.created is True
    assert commit.approval.status is ApprovalStatus.PENDING
    assert commit.approval.checkpoint_id == commit.checkpoint.checkpoint_id
    assert [event.type for event in commit.events] == [
        "approval.requested",
        "task.status.changed",
    ]


async def test_duplicate_request_reuses_matching_approval_without_new_events() -> None:
    first_session = FakeSession(
        rows=[("ct_1",), ("user-1",), None, (10,), ("ct_1",), (11,)]
    )
    first = await repository_for(first_session).request_tool_approval(**request_kwargs())
    row = (
        first.approval.approval_id,
        first.approval.task_id,
        first.approval.run_id,
        first.approval.tool_call_id,
        first.approval.checkpoint_id,
        first.approval.tool_name,
        first.approval.risk.value,
        first.approval.workspace_revision,
        first.approval.request_hash,
        dict(first.approval.display_summary),
        first.approval.status.value,
        first.approval.requested_by,
        first.approval.requested_at,
        first.approval.expires_at,
        None,
        None,
        None,
        10,
        {"pending_tool_index": 0},
        NOW,
    )
    duplicate_session = FakeSession(rows=[("ct_1",), ("user-1",), row])

    duplicate = await repository_for(duplicate_session).request_tool_approval(
        **request_kwargs()
    )

    sql = "\n".join(duplicate_session.sql)
    assert duplicate.created is False
    assert duplicate.approval == first.approval
    assert "INSERT INTO coding_checkpoints" not in sql
    assert "INSERT INTO coding_events" not in sql


async def test_lookup_returns_typed_approval() -> None:
    session = FakeSession(rows=[None])
    repository = repository_for(session)

    assert (
        await repository.get_tool_approval(
            task_id="ct_1", run_id="cr_1", tool_call_id="tool_1"
        )
        is None
    )
    assert "FROM coding_approvals" in "\n".join(session.sql)


async def test_in_memory_request_matches_atomic_contract() -> None:
    repository = InMemoryCodingRunRepository(task_prompts={"ct_1": "Fix it"})
    run = CodingRun(
        run_id="cr_1",
        task_id="ct_1",
        attempt=1,
        status=CodingRunStatus.RUNNING,
        resume_from_checkpoint_id=None,
        started_at=NOW,
    )
    repository.created_runs = [run]
    repository.active_run = run
    repository.task_statuses["ct_1"] = "running"
    repository.execution_leases["ct_1"] = LEASE

    first = await repository.request_tool_approval(**request_kwargs())
    duplicate = await repository.request_tool_approval(**request_kwargs())

    assert first.created is True
    assert duplicate.created is False
    assert duplicate.approval == first.approval
    assert repository.task_statuses["ct_1"] == "waiting_approval"
    assert [event.type for event in first.events] == [
        "approval.requested",
        "task.status.changed",
    ]
    assert await repository.get_tool_approval(
        task_id="ct_1", run_id="cr_1", tool_call_id="tool_1"
    ) == first.approval


async def prepared_in_memory(*, expires_at=None):
    repository = InMemoryCodingRunRepository(task_prompts={"ct_1": "Fix it"})
    run = CodingRun(
        run_id="cr_1", task_id="ct_1", attempt=1,
        status=CodingRunStatus.RUNNING, resume_from_checkpoint_id=None,
        started_at=NOW,
    )
    repository.created_runs = [run]
    repository.active_run = run
    repository.task_statuses["ct_1"] = "running"
    repository.execution_leases["ct_1"] = LEASE
    kwargs = request_kwargs()
    if expires_at is not None:
        kwargs["expires_at"] = expires_at
    requested = await repository.request_tool_approval(**kwargs)
    return repository, requested


async def test_in_memory_resolution_is_single_winner_and_returns_running() -> None:
    repository, requested = await prepared_in_memory()

    commit = await repository.resolve_tool_approval(
        task_id="ct_1", approval_id=requested.approval.approval_id,
        owner_id="test-owner", decision=ApprovalDecision.APPROVE,
        now=NOW + timedelta(seconds=1),
    )

    assert commit.approval.status is ApprovalStatus.APPROVED
    assert repository.task_statuses["ct_1"] == "running"
    assert [event.type for event in commit.events] == [
        "approval.approved", "task.status.changed",
    ]


async def test_in_memory_expiry_precedes_approve() -> None:
    repository, requested = await prepared_in_memory(
        expires_at=NOW + timedelta(seconds=1)
    )

    commit = await repository.resolve_tool_approval(
        task_id="ct_1", approval_id=requested.approval.approval_id,
        owner_id="test-owner", decision=ApprovalDecision.APPROVE,
        now=NOW + timedelta(seconds=1),
    )

    assert commit.approval.status is ApprovalStatus.EXPIRED
    assert commit.conflict_code == "approval_expired"
    assert repository.task_statuses["ct_1"] == "running"


async def test_postgres_resolution_locks_and_revalidates_binding() -> None:
    loop_state = {
        "pending_tool_calls": [
            {"tool_call_id": "tool_1", "name": CALL.name, "input": dict(CALL.input)}
        ]
    }
    request_hash = canonical_approval_hash(
        {
            "task_id": "ct_1", "run_id": "cr_1", "tool_call_id": "tool_1",
            "tool_name": CALL.name, "normalized_input": dict(CALL.input),
            "checkpoint_id": "cc_1", "workspace_revision": "rev-1",
        }
    )
    row = (
        "ca_1", "ct_1", "cr_1", "tool_1", "cc_1", CALL.name,
        "workspace_write", "rev-1", request_hash, {"path": "src/main.py"},
        "pending", "user-1", NOW, NOW + timedelta(seconds=900),
        None, None, None, loop_state, "rev-1", "cr_1",
    )
    session = FakeSession(rows=[row, ("ct_1",), (12,), (13,)])

    commit = await repository_for(session).resolve_tool_approval(
        task_id="ct_1", approval_id="ca_1", owner_id="user-1",
        decision=ApprovalDecision.APPROVE, now=NOW + timedelta(seconds=1),
    )

    sql = "\n".join(session.sql)
    assert "ORDER BY candidate.attempt DESC" in sql
    assert "checkpoint.loop_state_json" in sql
    assert "binding.workspace_revision" in sql
    assert "FOR UPDATE OF approval, task" in sql
    assert "AND status = 'pending'" in sql
    assert "SET status = 'running'" in sql
    assert commit.approval.status is ApprovalStatus.APPROVED

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from neos.coding.domain.approvals import ApprovalStatus
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

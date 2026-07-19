from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest

from neos.coding.domain.durability import ExecutionLease
from neos.coding.domain.phases import CodingRunStatus
from neos.coding.repositories.run_repository import PostgresCodingRunRepository
from tests.coding.fakes import InMemoryCodingRunRepository


NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
TASK_ROW = ("ct_1", "Fix it", "queued")
RUN_ROW = ("cr_1", "ct_1", 1, "running", None, NOW, None)
COMPLETED_RUN_ROW = (
    "cr_1",
    "ct_1",
    1,
    "completed",
    None,
    NOW,
    NOW,
)
LEASE = ExecutionLease(
    task_id="ct_1",
    run_id="cr_1",
    worker_id="worker-a",
    fencing_token=2,
    acquired_at=NOW,
    expires_at=NOW + timedelta(seconds=30),
)


class FakeResult:
    def __init__(self, row=None, rows=None) -> None:
        self._row = row
        self._rows = list(rows or ())

    def first(self):
        return self._row

    def all(self):
        return self._rows


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
        if isinstance(row, list):
            return FakeResult(rows=row)
        return FakeResult(row=row)


@asynccontextmanager
async def async_session(session: FakeSession):
    yield session


def repository_for(session: FakeSession) -> PostgresCodingRunRepository:
    async def session_factory():
        return async_session(session)

    return PostgresCodingRunRepository(session_factory)


async def test_ensure_run_started_commits_task_run_event_and_outbox() -> None:
    session = FakeSession(rows=[TASK_ROW, None, (0,), (1,)])
    repository = repository_for(session)

    run = await repository.ensure_run_started(
        task_id="ct_1",
        instruction="Fix it",
        development_mode=True,
        now=NOW,
    )

    sql = "\n".join(session.sql)
    assert "FOR UPDATE" in sql
    assert "INSERT INTO coding_runs" in sql
    assert "SET status = 'running'" in sql
    assert "INSERT INTO coding_events" in sql
    assert "INSERT INTO coding_event_outbox" in sql
    assert run.status is CodingRunStatus.RUNNING
    assert run.attempt == 1


async def test_queued_run_start_requires_development_mode() -> None:
    session = FakeSession(rows=[TASK_ROW])
    repository = repository_for(session)

    with pytest.raises(ValueError, match="development mode"):
        await repository.ensure_run_started(
            task_id="ct_1",
            instruction="Fix it",
            development_mode=False,
            now=NOW,
        )

    assert "INSERT INTO coding_runs" not in "\n".join(session.sql)


async def test_ensure_run_started_returns_existing_running_run() -> None:
    session = FakeSession(rows=[("ct_1", "Fix it", "running"), RUN_ROW])
    repository = repository_for(session)

    run = await repository.ensure_run_started(
        task_id="ct_1",
        instruction="Fix it",
        development_mode=True,
        now=NOW,
    )

    assert run.run_id == "cr_1"
    assert run.attempt == 1
    assert "INSERT INTO coding_runs" not in "\n".join(session.sql)
    assert "INSERT INTO coding_events" not in "\n".join(session.sql)


async def test_ensure_run_started_returns_terminal_run_for_late_delivery() -> None:
    session = FakeSession(
        rows=[
            ("ct_1", "Fix it", "completed"),
            None,
            COMPLETED_RUN_ROW,
        ]
    )
    repository = repository_for(session)

    run = await repository.ensure_run_started(
        task_id="ct_1",
        instruction="Fix it",
        development_mode=True,
        now=NOW,
    )

    assert run.status is CodingRunStatus.COMPLETED
    assert run.run_id == "cr_1"
    assert "INSERT INTO coding_runs" not in "\n".join(session.sql)
    assert "INSERT INTO coding_events" not in "\n".join(session.sql)


async def test_complete_run_is_fenced_and_atomic() -> None:
    session = FakeSession(
        rows=[("ct_1",), RUN_ROW, (8,), ("cr_1",)]
    )
    repository = repository_for(session)

    committed = await repository.complete_run(lease=LEASE, now=NOW)

    sql = "\n".join(session.sql)
    assert "fencing_token = :fencing_token" in sql
    assert "INSERT INTO coding_events" in sql
    assert "INSERT INTO coding_event_outbox" in sql
    assert "SET status = :status" in sql
    assert committed.run.status is CodingRunStatus.COMPLETED
    assert committed.event.type == "run.completed"


async def test_fail_run_persists_only_normalized_error_code() -> None:
    session = FakeSession(
        rows=[("ct_1",), RUN_ROW, (9,), ("cr_1",)]
    )
    repository = repository_for(session)

    committed = await repository.fail_run(
        lease=LEASE,
        error_code="supervisor_retry_exhausted",
        now=NOW,
    )

    assert committed.run.status is CodingRunStatus.FAILED
    assert committed.event.payload == {
        "status": "failed",
        "error_code": "supervisor_retry_exhausted",
    }


async def test_claimable_tasks_are_bounded_and_oldest_first() -> None:
    session = FakeSession(rows=[[("ct_old",), ("ct_new",)]])
    repository = repository_for(session)

    task_ids = await repository.claimable_task_ids(limit=2)

    sql = "\n".join(session.sql)
    assert "status IN ('queued', 'running')" in sql
    assert "ORDER BY task.last_activity_at, task.task_id" in sql
    assert "LIMIT :limit" in sql
    assert task_ids == ("ct_old", "ct_new")


async def test_in_memory_lifecycle_matches_atomic_repository_contract() -> None:
    repository = InMemoryCodingRunRepository(
        task_prompts={"ct_1": "Fix it", "ct_2": "Break safely"}
    )

    run = await repository.ensure_run_started(
        task_id="ct_1",
        instruction="Fix it",
        development_mode=True,
        now=NOW,
    )
    same_run = await repository.ensure_run_started(
        task_id="ct_1",
        instruction="Fix it",
        development_mode=True,
        now=NOW,
    )
    lease = await repository.acquire_execution_lease(
        task_id="ct_1",
        run_id=run.run_id,
        worker_id="worker-a",
        now=NOW,
        expires_at=NOW + timedelta(seconds=30),
    )
    assert lease is not None

    committed = await repository.complete_run(lease=lease, now=NOW)

    assert same_run == run
    assert committed.run.status is CodingRunStatus.COMPLETED
    assert committed.event.type == "run.completed"
    assert repository.task_statuses["ct_1"] == "completed"
    assert await repository.claimable_task_ids(limit=100) == ("ct_2",)

    failed_run = await repository.ensure_run_started(
        task_id="ct_2",
        instruction="Break safely",
        development_mode=True,
        now=NOW,
    )
    failed_lease = await repository.acquire_execution_lease(
        task_id="ct_2",
        run_id=failed_run.run_id,
        worker_id="worker-a",
        now=NOW,
        expires_at=NOW + timedelta(seconds=30),
    )
    assert failed_lease is not None
    failed = await repository.fail_run(
        lease=failed_lease,
        error_code="supervisor_retry_exhausted",
        now=NOW,
    )
    assert failed.event.payload["error_code"] == "supervisor_retry_exhausted"
    assert repository.task_statuses["ct_2"] == "failed"

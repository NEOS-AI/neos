from contextlib import asynccontextmanager
from datetime import UTC, datetime

from neos.coding.domain.phases import (
    CodingCheckpoint,
    CodingRun,
    CodingRunStatus,
    SteeringMode,
    SteeringRequest,
)
from neos.coding.repositories.run_repository import PostgresCodingRunRepository


NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


class FakeResult:
    def __init__(self, *, row=None) -> None:
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
        return FakeResult(row=row)


@asynccontextmanager
async def async_session(session: FakeSession):
    yield session


def repository_for(session: FakeSession) -> PostgresCodingRunRepository:
    async def session_factory():
        return async_session(session)

    return PostgresCodingRunRepository(session_factory)


def checkpoint_fixture(seq: int = 7) -> CodingCheckpoint:
    return CodingCheckpoint(
        checkpoint_id=f"cc_{seq}",
        task_id="ct_1",
        run_id="cr_1",
        seq=seq,
        loop_state={"phase": "implement"},
        workspace_revision="rev_1",
        created_at=NOW,
    )


async def test_checkpoint_and_tool_result_are_idempotent() -> None:
    session = FakeSession()
    repository = repository_for(session)

    await repository.save_checkpoint(checkpoint_fixture())
    await repository.record_tool_result(
        task_id="ct_1",
        run_id="cr_1",
        tool_call_id="tool_1",
        result={"ok": True},
        completed_at=NOW,
    )
    await repository.record_tool_result(
        task_id="ct_1",
        run_id="cr_2",
        tool_call_id="tool_1",
        result={"ok": False},
        completed_at=NOW,
    )

    sql = "\n".join(session.sql)
    assert "ON CONFLICT (task_id, tool_call_id) DO NOTHING" in sql
    assert "INSERT INTO coding_checkpoints" in sql


async def test_claim_pending_steering_uses_skip_locked_and_maps_request() -> None:
    session = FakeSession(
        rows=[("cs_1", "ct_1", "safe_point", "Also update docs", NOW)]
    )
    repository = repository_for(session)

    request = await repository.claim_pending_steering("ct_1")

    assert "FOR UPDATE SKIP LOCKED" in "\n".join(session.sql)
    assert request == SteeringRequest(
        steering_id="cs_1",
        task_id="ct_1",
        mode=SteeringMode.SAFE_POINT,
        instruction="Also update docs",
        requested_at=NOW,
    )


async def test_create_and_read_latest_run() -> None:
    session = FakeSession(
        rows=[("cr_2", "ct_1", 2, "running", "cc_1", NOW, None)]
    )
    repository = repository_for(session)
    run = CodingRun(
        run_id="cr_2",
        task_id="ct_1",
        attempt=2,
        status=CodingRunStatus.RUNNING,
        resume_from_checkpoint_id="cc_1",
        started_at=NOW,
    )

    await repository.create_run(run)
    restored = await repository.latest_run("ct_1")

    assert "INSERT INTO coding_runs" in "\n".join(session.sql)
    assert restored == run


async def test_completed_tool_result_only_reads_completed_rows() -> None:
    session = FakeSession(rows=[({"ok": True},)])
    repository = repository_for(session)

    result = await repository.completed_tool_result("ct_1", "tool_1")

    assert result == {"ok": True}
    assert "status = 'completed'" in "\n".join(session.sql)

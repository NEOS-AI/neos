from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest

from neos.coding.domain.durability import ExecutionLease, StaleExecutionLease
from neos.coding.domain.phases import CodingRun, CodingRunStatus
from neos.coding.domain.text_parts import TextPartConflict, TextPartStatus
from neos.coding.repositories.run_repository import PostgresCodingRunRepository
from tests.coding.fakes import InMemoryCodingRunRepository


NOW = datetime(2026, 7, 22, tzinfo=UTC)
LEASE = ExecutionLease(
    task_id="ct_1",
    run_id="cr_1",
    worker_id="worker-1",
    fencing_token=1,
    acquired_at=NOW,
    expires_at=NOW + timedelta(minutes=1),
)


def prepared_repository() -> InMemoryCodingRunRepository:
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
    return repository


class FakeResult:
    def __init__(self, row=None) -> None:
        self.row = row

    def first(self):
        return self.row

    def __iter__(self):
        if isinstance(self.row, list):
            return iter(self.row)
        return iter(())


class FakeSession:
    def __init__(self, rows) -> None:
        self.rows = list(rows)
        self.sql = []
        self.params = []

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


def postgres_repository(session: FakeSession) -> PostgresCodingRunRepository:
    @asynccontextmanager
    async def session_context():
        yield session

    async def session_factory():
        return session_context()

    return PostgresCodingRunRepository(session_factory)


async def test_text_part_lifecycle_preserves_unicode_bytes_and_turn_identity() -> None:
    repository = prepared_repository()

    started = await repository.start_model_text_part(
        lease=LEASE, part_id="part_1", turn_id="turn_1", now=NOW
    )
    appended = await repository.append_model_text_delta(
        lease=LEASE,
        part_id="part_1",
        turn_id="turn_1",
        delta="안녕",
        delta_bytes=6,
        max_part_bytes=100,
        now=NOW,
    )
    completed = await repository.complete_model_text_part(
        lease=LEASE, part_id="part_1", turn_id="turn_1", now=NOW
    )

    assert started.part.status is TextPartStatus.STREAMING
    assert started.event.type == "model.text_part.started"
    assert started.event.turn_id == "turn_1"
    assert appended.part.content == "안녕"
    assert appended.part.content_bytes == 6
    assert appended.event.payload == {"part_id": "part_1", "delta": "안녕"}
    assert completed.part.status is TextPartStatus.COMPLETED
    assert completed.event.type == "model.text_part.completed"
    assert [started.event.seq, appended.event.seq, completed.event.seq] == [1, 2, 3]


async def test_start_interrupts_previous_streaming_part_atomically() -> None:
    repository = prepared_repository()
    first = await repository.start_model_text_part(
        lease=LEASE, part_id="part_1", turn_id="turn_1", now=NOW
    )

    second = await repository.start_model_text_part(
        lease=LEASE, part_id="part_2", turn_id="turn_2", now=NOW
    )

    interrupted = repository.text_parts["part_1"]
    assert first.part.status is TextPartStatus.STREAMING
    assert interrupted.status is TextPartStatus.INTERRUPTED
    assert interrupted.last_seq == second.event.seq
    assert second.interrupted_part_ids == ("part_1",)
    assert second.event.payload["interrupted_part_ids"] == ["part_1"]


async def test_rejected_delta_does_not_consume_sequence_or_mutate_content() -> None:
    repository = prepared_repository()
    await repository.start_model_text_part(
        lease=LEASE, part_id="part_1", turn_id="turn_1", now=NOW
    )
    sequence = repository._durability_seq

    with pytest.raises(TextPartConflict, match="model_public_text_budget_exceeded"):
        await repository.append_model_text_delta(
            lease=LEASE,
            part_id="part_1",
            turn_id="turn_1",
            delta="abcd",
            delta_bytes=4,
            max_part_bytes=3,
            now=NOW,
        )

    assert repository._durability_seq == sequence
    assert repository.text_parts["part_1"].content == ""


async def test_duplicate_identity_and_stale_lease_are_rejected() -> None:
    repository = prepared_repository()
    await repository.start_model_text_part(
        lease=LEASE, part_id="part_1", turn_id="turn_1", now=NOW
    )

    with pytest.raises(TextPartConflict, match="model_text_part_exists"):
        await repository.start_model_text_part(
            lease=LEASE, part_id="part_1", turn_id="turn_2", now=NOW
        )

    stale = ExecutionLease(
        task_id="ct_1",
        run_id="cr_1",
        worker_id="worker-1",
        fencing_token=2,
        acquired_at=NOW,
        expires_at=NOW + timedelta(minutes=1),
    )
    with pytest.raises(StaleExecutionLease):
        await repository.complete_model_text_part(
            lease=stale, part_id="part_1", turn_id="turn_1", now=NOW
        )


async def test_postgres_start_is_fenced_and_persists_event_with_turn() -> None:
    session = FakeSession(
        rows=[("ct_1",), ("cr_1",), None, (1,), [("old_part",)]]
    )

    commit = await postgres_repository(session).start_model_text_part(
        lease=LEASE, part_id="part_1", turn_id="turn_1", now=NOW
    )

    sql = "\n".join(session.sql)
    assert "fencing_token = :fencing_token" in sql
    assert "MAX(candidate.attempt)" in sql
    assert "SET status = 'interrupted'" in sql
    assert "INSERT INTO coding_text_parts" in sql
    assert "INSERT INTO coding_events" in sql
    assert "INSERT INTO coding_event_outbox" in sql
    assert commit.interrupted_part_ids == ("old_part",)
    assert commit.event.turn_id == "turn_1"
    event_params = next(
        params
        for sql, params in zip(session.sql, session.params, strict=True)
        if "INSERT INTO coding_events" in sql
    )
    assert event_params["turn_id"] == "turn_1"


async def test_postgres_append_checks_budget_before_allocating_sequence() -> None:
    part_row = (
        "part_1",
        "ct_1",
        "cr_1",
        "turn_1",
        1,
        1,
        "streaming",
        "abc",
        3,
        NOW,
        NOW,
    )
    session = FakeSession(rows=[("ct_1",), ("cr_1",), part_row])

    with pytest.raises(TextPartConflict, match="model_public_text_budget_exceeded"):
        await postgres_repository(session).append_model_text_delta(
            lease=LEASE,
            part_id="part_1",
            turn_id="turn_1",
            delta="d",
            delta_bytes=1,
            max_part_bytes=3,
            now=NOW,
        )

    assert "SET last_seq = last_seq + 1" not in "\n".join(session.sql)

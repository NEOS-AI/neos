import asyncio
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from neos.coding.domain.durability import StaleExecutionLease
from neos.coding.domain.phases import CodingCheckpoint, CodingPhaseKind
from neos.coding.repositories.run_repository import PostgresCodingRunRepository


NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
async def coding_postgres_session_factory():
    url = os.getenv("CODING_TEST_DATABASE_URL")
    if not url:
        pytest.skip("CODING_TEST_DATABASE_URL is not configured")
    engine = create_async_engine(url)
    migration = Path("db/migrations/040_add_coding_execution_leases.sql")
    async with engine.begin() as connection:
        for statement in migration.read_text().split(";"):
            if statement.strip():
                await connection.exec_driver_sql(statement)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def session_factory():
        @asynccontextmanager
        async def context():
            async with maker() as session:
                yield session

        return context()

    try:
        yield session_factory
    finally:
        async with engine.begin() as connection:
            await connection.exec_driver_sql(
                "TRUNCATE coding_event_outbox, coding_events, "
                "coding_tool_executions, coding_steering_requests, "
                "coding_run_leases, coding_checkpoints, coding_phases, "
                "coding_runs, coding_tasks CASCADE"
            )
        await engine.dispose()


async def _seed_run(session_factory):
    task_id = f"ct_{uuid4().hex}"
    run_id = f"cr_{uuid4().hex}"
    async with await session_factory() as session:
        async with session.begin():
            owner = await session.execute(text("SELECT user_id FROM users LIMIT 1"))
            owner_row = owner.first()
            if owner_row is None:
                pytest.skip("prepared PostgreSQL schema has no test user")
            await session.execute(
                text(
                    """
                    INSERT INTO coding_tasks
                        (task_id, owner_id, prompt, status, version, last_seq,
                         created_at, updated_at, last_activity_at)
                    VALUES
                        (:task_id, :owner_id, 'Fix it', 'running', 1, 0,
                         :now, :now, :now)
                    """
                ),
                {"task_id": task_id, "owner_id": owner_row[0], "now": NOW},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO coding_runs
                        (run_id, task_id, attempt, status, started_at)
                    VALUES (:run_id, :task_id, 1, 'running', :now)
                    """
                ),
                {"run_id": run_id, "task_id": task_id, "now": NOW},
            )
    return task_id, run_id


@pytest.mark.integration
async def test_checkpoint_event_fk_and_phase_commit_are_atomic(
    coding_postgres_session_factory,
) -> None:
    task_id, run_id = await _seed_run(coding_postgres_session_factory)
    repository = PostgresCodingRunRepository(coding_postgres_session_factory)
    lease = await repository.acquire_execution_lease(
        task_id=task_id,
        run_id=run_id,
        worker_id="worker-a",
        now=NOW,
        expires_at=NOW + timedelta(seconds=30),
    )
    assert lease is not None
    started = await repository.begin_phase(
        lease=lease, kind=CodingPhaseKind.UNDERSTAND, now=NOW
    )

    committed = await repository.commit_phase_checkpoint(
        lease=lease,
        phase=started.phase,
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

    assert committed.event.checkpoint_id == committed.checkpoint.checkpoint_id
    async with await coding_postgres_session_factory() as session:
        result = await session.execute(
            text(
                """
                SELECT
                    (SELECT count(*) FROM coding_checkpoints
                     WHERE task_id = :task_id),
                    (SELECT count(*) FROM coding_events
                     WHERE task_id = :task_id
                       AND event_type = 'phase.completed'),
                    (SELECT status FROM coding_phases
                     WHERE phase_id = :phase_id)
                """
            ),
            {"task_id": task_id, "phase_id": started.phase.phase_id},
        )
        row = result.first()
    assert row == (1, 1, "completed")


@pytest.mark.integration
async def test_only_one_worker_holds_lease_and_stale_write_is_rejected(
    coding_postgres_session_factory,
) -> None:
    task_id, run_id = await _seed_run(coding_postgres_session_factory)
    repository = PostgresCodingRunRepository(coding_postgres_session_factory)

    async def acquire(worker_id, now):
        return await repository.acquire_execution_lease(
            task_id=task_id,
            run_id=run_id,
            worker_id=worker_id,
            now=now,
            expires_at=now + timedelta(seconds=30),
        )

    first, second = await asyncio.gather(
        acquire("worker-a", NOW), acquire("worker-b", NOW)
    )
    winner = first or second
    assert winner is not None
    assert (first is None) != (second is None)

    replacement_now = NOW + timedelta(seconds=31)
    replacement = await acquire("worker-c", replacement_now)
    assert replacement is not None
    assert replacement.fencing_token > winner.fencing_token
    with pytest.raises(StaleExecutionLease):
        await repository.renew_execution_lease(
            winner,
            now=replacement_now,
            expires_at=replacement_now + timedelta(seconds=30),
        )


@pytest.mark.integration
async def test_phase_commit_rolls_back_when_event_insert_fails(
    coding_postgres_session_factory,
) -> None:
    task_id, run_id = await _seed_run(coding_postgres_session_factory)
    repository = PostgresCodingRunRepository(coding_postgres_session_factory)
    lease = await repository.acquire_execution_lease(
        task_id=task_id,
        run_id=run_id,
        worker_id="worker-a",
        now=NOW,
        expires_at=NOW + timedelta(seconds=30),
    )
    assert lease is not None
    started = await repository.begin_phase(
        lease=lease, kind=CodingPhaseKind.PLAN, now=NOW
    )
    async with await coding_postgres_session_factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    """
                    CREATE OR REPLACE FUNCTION fail_phase_completed()
                    RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN
                        IF NEW.event_type = 'phase.completed' THEN
                            RAISE EXCEPTION 'injected phase event failure';
                        END IF;
                        RETURN NEW;
                    END;
                    $$
                    """
                )
            )
            await session.execute(
                text(
                    """
                    CREATE TRIGGER fail_phase_completed_trigger
                    BEFORE INSERT ON coding_events
                    FOR EACH ROW EXECUTE FUNCTION fail_phase_completed()
                    """
                )
            )
    try:
        with pytest.raises(Exception, match="injected phase event failure"):
            await repository.commit_phase_checkpoint(
                lease=lease,
                phase=started.phase,
                tool_call_id="tool_failure",
                result={"summary": "must rollback"},
                loop_state={
                    "phase_index": 1,
                    "transcript": [],
                    "current_instruction": "Fix it",
                    "pending_instruction": None,
                },
                workspace_revision="rev_failure",
                now=NOW,
            )
    finally:
        async with await coding_postgres_session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        "DROP TRIGGER IF EXISTS fail_phase_completed_trigger "
                        "ON coding_events"
                    )
                )
                await session.execute(
                    text("DROP FUNCTION IF EXISTS fail_phase_completed()")
                )
    async with await coding_postgres_session_factory() as session:
        result = await session.execute(
            text(
                """
                SELECT
                    (SELECT count(*) FROM coding_checkpoints
                     WHERE task_id = :task_id),
                    (SELECT count(*) FROM coding_events
                     WHERE task_id = :task_id
                       AND event_type = 'phase.completed'),
                    (SELECT status FROM coding_phases
                     WHERE phase_id = :phase_id)
                """
            ),
            {"task_id": task_id, "phase_id": started.phase.phase_id},
        )
        row = result.first()
    assert row == (0, 0, "active")


@pytest.mark.integration
async def test_expired_steering_claim_is_recovered_once(
    coding_postgres_session_factory,
) -> None:
    task_id, run_id = await _seed_run(coding_postgres_session_factory)
    repository = PostgresCodingRunRepository(coding_postgres_session_factory)
    first = await repository.acquire_execution_lease(
        task_id=task_id,
        run_id=run_id,
        worker_id="worker-a",
        now=NOW,
        expires_at=NOW + timedelta(seconds=30),
    )
    assert first is not None
    async with await coding_postgres_session_factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    """
                    INSERT INTO coding_steering_requests
                        (steering_id, task_id, mode, instruction, status,
                         requested_at, claimed_by, claimed_at, claim_expires_at)
                    VALUES
                        ('cs_expired', :task_id, 'safe_point',
                         'Inspect cache first', 'claimed', :now,
                         'dead-worker', :now, :claim_expires_at)
                    """
                ),
                {
                    "task_id": task_id,
                    "now": NOW,
                    "claim_expires_at": NOW + timedelta(seconds=10),
                },
            )
    replacement_now = NOW + timedelta(seconds=31)
    replacement = await repository.acquire_execution_lease(
        task_id=task_id,
        run_id=run_id,
        worker_id="worker-b",
        now=replacement_now,
        expires_at=replacement_now + timedelta(seconds=30),
    )
    assert replacement is not None
    applied = await repository.apply_steering_at_safe_point(
        lease=replacement,
        checkpoint=CodingCheckpoint(
            checkpoint_id="cc_input",
            task_id=task_id,
            run_id=run_id,
            seq=0,
            loop_state={
                "phase_index": 0,
                "transcript": [],
                "current_instruction": "Fix it",
                "pending_instruction": None,
            },
            workspace_revision="rev_before_steer",
            created_at=replacement_now,
        ),
        worker_id="worker-b",
        claim_expires_at=replacement_now + timedelta(seconds=30),
        now=replacement_now,
    )
    assert applied is not None
    assert applied.lease.fencing_token == replacement.fencing_token + 1
    async with await coding_postgres_session_factory() as session:
        result = await session.execute(
            text(
                """
                SELECT
                    (SELECT count(*) FROM coding_steering_requests
                     WHERE task_id = :task_id AND status = 'applied'),
                    (SELECT count(*) FROM coding_events
                     WHERE task_id = :task_id
                       AND event_type = 'steer.applied'),
                    (SELECT count(*) FROM coding_runs
                     WHERE task_id = :task_id AND status = 'running')
                """
            ),
            {"task_id": task_id},
        )
        row = result.first()
    assert row == (1, 1, 1)

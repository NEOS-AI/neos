import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from neos.coding.managed.admission import AdmissionRequest
from neos.coding.managed.domain import AdmissionDecision, AdmissionReason
from neos.coding.managed.repository import PostgresManagedSandboxRepository


NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


async def _seed_runs(session_factory, count: int) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    async with await session_factory() as session:
        async with session.begin():
            owner = await session.execute(text("SELECT user_id FROM users LIMIT 1"))
            owner_row = owner.first()
            if owner_row is None:
                pytest.skip("prepared PostgreSQL schema has no test user")
            for index in range(count):
                task_id = f"ct_{uuid4().hex}"
                run_id = f"cr_{uuid4().hex}"
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
                rows.append((task_id, run_id))
    return rows


@pytest.mark.integration
async def test_concurrent_admissions_cannot_overbook_tenant_quota(
    managed_postgres_session_factory,
) -> None:
    runs = await _seed_runs(managed_postgres_session_factory, 4)
    repository = PostgresManagedSandboxRepository(managed_postgres_session_factory)

    async def admit(index: int):
        task_id, run_id = runs[index]
        return await repository.admit(
            AdmissionRequest(
                tenant_id="tenant_race",
                task_id=task_id,
                run_id=run_id,
                repository_organization="acme",
                provider="fake",
                region="local",
                required_capabilities=frozenset(),
                idempotency_key=f"idem_{index}",
                estimated_active_seconds=60,
                estimated_archive_bytes=100,
                estimated_cost_micros=10,
            ),
            decision=AdmissionDecision.ADMITTED,
            reason=AdmissionReason.ALLOWED,
            now=NOW,
            reevaluate_after=NOW + timedelta(seconds=30),
            reservation_expires_at=NOW + timedelta(seconds=60),
            concurrent_quota=3,
            daily_quota=50,
            daily_active_seconds_quota=43_200,
            archive_bytes_quota=5 * 1024**3,
            daily_cost_micros_quota=10_000_000,
        )

    results = await asyncio.gather(*(admit(index) for index in range(4)))

    assert sum(result.decision is AdmissionDecision.ADMITTED for result in results) == 3
    async with await managed_postgres_session_factory() as session:
        result = await session.execute(
            text(
                """
                SELECT
                    count(*) FILTER (WHERE decision = 'admitted'),
                    count(*) FILTER (WHERE reservation_state = 'reserved'),
                    (SELECT count(*) FROM coding_managed_sandboxes
                     WHERE tenant_id = 'tenant_race' AND state = 'admitted')
                FROM coding_sandbox_admissions
                WHERE tenant_id = 'tenant_race'
                """
            )
        )
        row = result.first()
    assert row == (3, 3, 3)


@pytest.mark.integration
async def test_expired_live_allocation_stays_counted_and_can_settle(
    managed_postgres_session_factory,
) -> None:
    runs = await _seed_runs(managed_postgres_session_factory, 2)
    repository = PostgresManagedSandboxRepository(managed_postgres_session_factory)
    expired_at = NOW + timedelta(seconds=60)

    async def admit(index: int):
        task_id, run_id = runs[index]
        return await repository.admit(
            AdmissionRequest(
                tenant_id="tenant_live_expiry",
                task_id=task_id,
                run_id=run_id,
                repository_organization="acme",
                provider="fake",
                region="local",
                required_capabilities=frozenset(),
                idempotency_key=f"idem_live_{index}",
                estimated_active_seconds=60,
                estimated_archive_bytes=100,
                estimated_cost_micros=10,
            ),
            decision=AdmissionDecision.ADMITTED,
            reason=AdmissionReason.ALLOWED,
            now=NOW if index == 0 else expired_at,
            reevaluate_after=expired_at + timedelta(seconds=30),
            reservation_expires_at=expired_at + timedelta(seconds=60 * index),
            concurrent_quota=1,
            daily_quota=50,
            daily_active_seconds_quota=43_200,
            archive_bytes_quota=5 * 1024**3,
            daily_cost_micros_quota=10_000_000,
        )

    first = await admit(0)
    assert first.allocation_id is not None
    async with await managed_postgres_session_factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    """
                    UPDATE coding_managed_sandboxes
                    SET state = 'allocating', updated_at = :now
                    WHERE allocation_id = :allocation_id
                    """
                ),
                {
                    "allocation_id": first.allocation_id,
                    "now": expired_at,
                },
            )

    released = await repository.release_expired_reservations(
        now=expired_at,
        limit=10,
    )
    second = await admit(1)
    settled = await repository.settle_reservation(
        first.allocation_id,
        active_seconds=75,
        archive_bytes=125,
        cost_micros=15,
        now=expired_at,
    )

    assert released == []
    assert second.reason is AdmissionReason.QUOTA_EXCEEDED
    assert settled is True
    async with await managed_postgres_session_factory() as session:
        result = await session.execute(
            text(
                """
                SELECT reservation_state, actual_active_seconds,
                       actual_archive_bytes, actual_cost_micros
                FROM coding_sandbox_admissions
                WHERE admission_id = :admission_id
                """
            ),
            {"admission_id": first.admission_id},
        )
        row = result.first()
    assert row == ("settled", 75, 125, 15)

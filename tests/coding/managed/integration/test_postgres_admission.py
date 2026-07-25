import asyncio
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from neos.coding.managed.admission import AdmissionRequest
from neos.coding.managed.domain import AdmissionDecision, AdmissionReason
from neos.coding.managed.repository import PostgresManagedSandboxRepository


NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
async def managed_postgres_session_factory():
    url = os.getenv("CODING_TEST_DATABASE_URL")
    if not url:
        pytest.skip("CODING_TEST_DATABASE_URL is not configured")
    engine = create_async_engine(url)
    migration = Path("db/migrations/045_add_coding_managed_sandboxes.sql")
    async with engine.begin() as connection:
        for statement in migration.read_text().split(";"):
            if statement.strip() not in {"BEGIN", "COMMIT"}:
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
                "TRUNCATE coding_sandbox_cleanup_attempts, "
                "coding_managed_sandboxes, coding_sandbox_admissions, "
                "coding_runs, coding_tasks CASCADE"
            )
        await engine.dispose()


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
                policy_version="integration-policy-v1",
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

import os
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture(scope="module")
async def managed_postgres_session_factory():
    """`coding_managed_sandboxes`/`coding_sandbox_admissions` 통합 테스트가 공유하는
    실제 Postgres 세션 팩토리.

    `test_postgres_admission.py`와 `test_postgres_allocation.py`가 모두 쓰므로
    conftest로 옮겨 공유한다.
    """
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

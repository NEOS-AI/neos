import os
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


# 마이그레이션 045가 만드는, 이 스위트가 소유하는 테이블만 나열한다.
# `coding_tasks`/`coding_runs`는 다른 스위트 소유이므로 정리 대상에서 뺀다.
# 자식 -> 부모 순서를 지켜야 FK 제약을 건드리지 않고 지울 수 있다.
_OWNED_TABLES_CHILD_FIRST = (
    # 057. 코딩 런타임은 할당 행을 참조하므로 할당보다 먼저 지운다.
    "coding_managed_physical_objects",
    "coding_managed_runtime_snapshots",
    "coding_managed_runtime",
    "coding_sandbox_cleanup_attempts",
    "coding_managed_sandboxes",
    "coding_sandbox_admissions",
    # 046. FK 가 없으므로 순서는 무관하지만 목록에는 있어야 테스트 간
    # 격리가 유지된다 -- 빠지면 드레인 한 건이 다음 테스트로 새어 나간다.
    "coding_sandbox_provider_health",
)

# 이 스위트가 소유하는 마이그레이션. 새 마이그레이션을 추가하면 여기에
# 더한다 -- 빠뜨리면 그 테이블을 쓰는 테스트가 "관계가 없다"로 죽고,
# 원인이 제품이 아니라 픽스처라는 것을 알아내는 데 시간이 든다.
_OWNED_MIGRATIONS = (
    "db/migrations/045_add_coding_managed_sandboxes.sql",
    "db/migrations/046_add_coding_sandbox_provider_health.sql",
    "db/migrations/057_add_coding_sandbox_ledger.sql",
)


async def _drop_owned_tables(connection) -> None:
    for table_name in _OWNED_TABLES_CHILD_FIRST:
        await connection.exec_driver_sql(f"DROP TABLE IF EXISTS {table_name} CASCADE")


@pytest.fixture(scope="session")
async def managed_postgres_session_factory():
    """`coding_managed_sandboxes`/`coding_sandbox_admissions` 통합 테스트가 공유하는
    실제 Postgres 세션 팩토리.

    `test_postgres_admission.py`와 `test_postgres_allocation.py`가 모두 쓰므로
    conftest로 옮겨 공유한다. 세션 스코프라 스키마는 프로세스당 한 번만
    적용되지만, pytest를 반복 실행하면 이전 실행이 남긴 테이블이 여전히
    존재할 수 있으므로 CREATE 전에 항상 DROP IF EXISTS 로 멱등하게 만든다.
    """
    url = os.getenv("CODING_TEST_DATABASE_URL")
    if not url:
        pytest.skip("CODING_TEST_DATABASE_URL is not configured")
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await _drop_owned_tables(connection)
        for migration_path in _OWNED_MIGRATIONS:
            for statement in Path(migration_path).read_text().split(";"):
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
            await _drop_owned_tables(connection)
        await engine.dispose()


@pytest.fixture(autouse=True)
async def _reset_managed_sandbox_tables(managed_postgres_session_factory):
    """테스트 간 순서 의존성을 없애기 위해 매 테스트가 끝날 때마다 이 스위트가
    소유한 테이블만 비운다.

    `coding_tasks`/`coding_runs`는 이 스위트 소유가 아니므로 절대 지우지
    않는다 -- `CODING_TEST_DATABASE_URL`이 실제 데이터를 가진 DB를 가리켜도
    안전해야 한다.
    """
    yield
    async with await managed_postgres_session_factory() as session:
        async with session.begin():
            for table_name in _OWNED_TABLES_CHILD_FIRST:
                await session.execute(text(f"DELETE FROM {table_name}"))

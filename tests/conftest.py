"""Pytest configuration and fixtures."""

import os
import pathlib
import sys
from typing import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "neos-test-only-secret-key-2026-07-19",
)
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

# Several tests assert the production-shaped app (for example that unauthenticated
# WebSocket routes are stripped). `neos.main` captures `IS_DEBUG` at import time, so
# the shape depends on ambient config — and a developer `.env` with `DEBUG=true`
# silently flips it. Pin the session to production shape while still letting an
# explicit `DEBUG=1 pytest ...` opt back in.
os.environ.setdefault("DEBUG", "false")


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

# `db_manager.initialize()` 는 `Base.metadata.create_all` 로 **ORM 모델만** 만든다.
# 채팅 스키마(conversations·messages·participants·templates + create_conversation
# 같은 저장 함수)는 ORM 모델이 아니라 이 SQL 파일에 있고, 부트스트랩은 그것을
# 적용한 적이 없다. 그래서 이것을 쓰는 테스트들은 **개발 기계에 누군가 손으로
# 적용해 뒀을 때만** 통과했다 -- CI 범위를 넓히자마자(D64) 세 건이 깨졌다.
#
# 순서가 중요하다: 이 파일의 FK 는 `users` 를 참조하므로 `create_all` 이 먼저다.
_CHAT_SYSTEM_SQL = _REPO_ROOT / "db" / "chat_system.sql"
_MIGRATIONS_DIR = _REPO_ROOT / "db" / "migrations"

_sql_schema_applied = False
skipped_migrations: list[tuple[str, str]] = []


async def _run_sql_file(path: pathlib.Path) -> None:
    """SQL 파일 하나를 통째로 실행한다.

    여러 문장을 한 번에 보내야 하므로(본문에 `$$` 달러 인용이 있어 순진한 분리는
    틀린다) asyncpg 드라이버 커넥션의 simple query 경로를 쓴다 -- SQLAlchemy 의
    `execute()` 는 문장 하나만 받는다. 파일마다 커넥션을 새로 잡는 것은 한 파일이
    실패해도 다음 파일이 중단된 트랜잭션에 갇히지 않게 하기 위해서다.

    이 경로의 한계 하나: 스크립트 하나가 곧 하나의 암묵적 트랜잭션이라
    `CONCURRENTLY` 나 자체 `BEGIN` 을 쓰는 마이그레이션은 이렇게 적용할 수 없다
    (psql 은 문장을 하나씩 보내므로 된다). `skipped_migrations` 7건 중 2건이
    그 이유이고, AUTOCOMMIT 으로 바꿔도 달라지지 않는다 -- 실제로 해봤다.
    """
    from neos.database.connection import db_manager

    async with db_manager.engine.begin() as conn:
        raw = await conn.get_raw_connection()
        await raw.driver_connection.execute(path.read_text(encoding="utf-8"))


async def _apply_sql_schema() -> None:
    """세션당 한 번, 테스트가 쓰는 SQL 스키마를 적용한다.

    `chat_system.sql` 만으로는 부족하다 -- `ChatService` 는 마이그레이션이
    더한 컬럼(`conversations.visibility`, 008)까지 읽는다. 조각을 떼어 적용하면
    실패가 한 층씩 아래로 내려갈 뿐이라는 것을 두 번 확인했다: 저장 함수만
    만들었더니 `relation "conversations" does not exist`, 파일만 적용했더니
    `column "visibility" does not exist`.

    **범위를 분명히 한다.** 이것은 배포 스키마의 재현이 아니라 *테스트가 실제로
    건드리는 것*의 부트스트랩이다. 신선한 DB 에 마이그레이션 44개를 순서대로
    적용하면 7개가 실패한다 -- 다른 `db/*.sql` 이 만드는 테이블에 기대거나
    (`hyper_research_reports`·`message_embeddings`), pgvector 가 3072차원에 hnsw
    를 못 만들거나, 위 `_run_sql_file` 의 한계 때문이다. 그 7개는 테스트가
    건드리지 않으므로 건너뛰고 `skipped_migrations` 에 남긴다. **배포 스키마
    전체가 신선한 DB 에서 재현되지 않는다는 것은 별개의 실제 문제**이고 로드맵에
    적어 뒀다 -- 여기서 조용히 반쯤 고치지 않는다.

    적용 결과는 `tests/test_database_schema_bootstrap.py` 가 검사한다.
    """
    global _sql_schema_applied
    if _sql_schema_applied:
        return
    _sql_schema_applied = True

    if _CHAT_SYSTEM_SQL.exists():
        await _run_sql_file(_CHAT_SYSTEM_SQL)

    for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        try:
            await _run_sql_file(path)
        except Exception as error:  # noqa: BLE001 -- 위 docstring 의 6개
            skipped_migrations.append((path.name, str(error).splitlines()[0]))

    if skipped_migrations:
        print(f"적용하지 못한 마이그레이션 {len(skipped_migrations)}개:")
        for name, reason in skipped_migrations:
            print(f"  - {name}: {reason}")


def _skip_database_fixtures(request: pytest.FixtureRequest) -> bool:
    nodeid = getattr(request.node, "nodeid", "")
    return (
        request.node.get_closest_marker("no_db") is not None
        or "tests/workflow/harness/" in nodeid
        or "tests/workflow/test_harness_" in nodeid
        or "tests/workflow/processors/test_research_harness_processor.py" in nodeid
    )


@pytest.fixture(scope="function", autouse=True)
def restore_checkpointer_singleton():
    """`neos.workflow.checkpointer._checkpointer` 를 테스트 경계에서 되돌린다.

    §10.3 이 "전역 싱글턴이 바뀐 채 남음" 으로 이름 붙인 계열의 세 번째 사례를
    막는다. 이 전역이 특별히 위험한 이유는 **오염된 값이 즉시 터지지 않는 것**이다:
    `get_checkpointer()` 가 캐시한 AsyncMock 은 그것을 심은 테스트에서는 정상
    동작하고, 한참 뒤 `use_checkpointer=True` 로 그래프를 컴파일하는 **무관한
    파일**에서 LangGraph 가 거부하면서 터진다. 시드가 바뀌면 실패하는 파일도
    바뀌므로 증상에서 원인으로 가는 길이 없다.

    `unittest.mock.patch` 로는 못 막는다 -- 그쪽은 **클래스**를 복원하지만
    캐시된 **인스턴스**는 건드리지 않는다. 되돌릴 곳은 캐시 쪽이다.

    이미 import 된 경우에만 손댄다: 로드되지 않은 모듈은 오염될 수도 없으므로,
    가드 때문에 무거운 import(langgraph 등)를 끌어오지 않는다.
    """
    module = sys.modules.get("neos.workflow.checkpointer")
    before = getattr(module, "_checkpointer", None) if module else None

    yield

    # 테스트 도중에 처음 import 됐을 수 있다. 그때 되돌릴 값은 초기값 None 이다.
    module = sys.modules.get("neos.workflow.checkpointer")
    if module is not None and getattr(module, "_checkpointer", None) is not before:
        module._checkpointer = before


@pytest.fixture(scope="function", autouse=True)
async def cleanup_test_data(request):
    """
    Clean test data before and after each test.
    """
    if _skip_database_fixtures(request):
        yield
        return

    from neos.database.connection import db_manager
    from sqlalchemy import text

    async def do_cleanup():
        """Helper function to clean up test data"""
        try:
            if db_manager.engine is None:
                await db_manager.initialize()
        except Exception as e:
            print(f"DB init error: {e}")
            # 엔진 객체는 `create_all` 이 터지기 **전에** 만들어진다. 그대로 두면
            # 다음 호출이 `engine is None` 을 거짓으로 보고 초기화를 건너뛴 채
            # 스키마 적용으로 직행한다 -- DB 가 없는 잡(quality)에서 그게 터졌다.
            db_manager.engine = None
            return

        # 스키마 적용 실패는 **삼키지 않는다**. 아래 DELETE 들은 best-effort 라
        # 관용적으로 처리하지만, 그 관용이 바로 `relation "conversations" does
        # not exist` 를 CI 에서 매 테스트마다 조용히 삼키고 있던 것이다.
        await _apply_sql_schema()

        try:
            async with await db_manager.get_session() as session:
                # Clean up test data in correct order (respecting foreign keys)
                # Delete child tables first, then parent tables
                await session.execute(text("DELETE FROM api_keys WHERE user_id IN (SELECT user_id FROM users WHERE email LIKE '%@example.com' OR email LIKE 'test%@%' OR email LIKE 'fixture@%')"))
                await session.execute(text("DELETE FROM refresh_tokens WHERE user_id IN (SELECT user_id FROM users WHERE email LIKE '%@example.com' OR email LIKE 'test%@%' OR email LIKE 'fixture@%')"))
                await session.execute(text("DELETE FROM messages WHERE conversation_id IN (SELECT conversation_id FROM conversations WHERE user_id IN (SELECT user_id FROM users WHERE email LIKE '%@example.com' OR email LIKE 'test%@%' OR email LIKE 'fixture@%'))"))
                await session.execute(text("DELETE FROM conversations WHERE user_id IN (SELECT user_id FROM users WHERE email LIKE '%@example.com' OR email LIKE 'test%@%' OR email LIKE 'fixture@%')"))
                await session.execute(text("DELETE FROM conversation_templates WHERE created_by LIKE 'user_%'"))
                await session.execute(text("DELETE FROM users WHERE email LIKE '%@example.com' OR email LIKE 'test%@%' OR email LIKE 'fixture@%'"))
                await session.commit()
        except Exception as e:
            print(f"Cleanup error: {e}")  # Debug output
            pass

    # Clean BEFORE test
    await do_cleanup()

    yield

    # Clean AFTER test
    await do_cleanup()


@pytest.fixture(scope="session", autouse=True)
async def database_engine_lifecycle():
    """세션 전체에서 DB 엔진 하나를 재사용하고, 끝에서 한 번만 정리한다.

    이전에는 테스트마다 엔진을 폐기·재생성했다. 그러면 매 테스트가 새 커넥션 풀을
    만들고, `close()`는 `dispose(close=False)`라 이전 커넥션을 닫지 않은 채 버린다.
    2000개가 넘는 테스트를 지나며 그 잔여물이 쌓여 후반부에 커넥션 생성이
    간헐적으로 실패했다.

    엔진 생성은 첫 사용 시점까지 미룬다 — `no_db` 테스트만 돌릴 때 DB를 요구하지
    않기 위해서다.
    """
    yield

    from neos.database.connection import db_manager

    if db_manager.engine is not None:
        try:
            await db_manager.close()
        except Exception:
            pass
        db_manager.engine = None
        db_manager.session_factory = None


@pytest.fixture(scope="function")
async def client() -> AsyncGenerator[AsyncClient, None]:
    """
    Test client fixture with proper cleanup.
    Function-scoped to ensure each test gets a fresh client and event loop.
    """
    from neos.main import app

    # Create a new client for each test
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        timeout=30.0
    ) as ac:
        yield ac


@pytest.fixture
async def auth_headers(client: AsyncClient) -> dict:
    """
    Authentication headers fixture.
    Creates a test user and returns bearer token headers.
    """
    # Register a test user
    register_response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "fixture@example.com",
            "password": "SecurePass123!",
        }
    )

    # If user already exists, just login
    if register_response.status_code == 400:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "fixture@example.com",
                "password": "SecurePass123!",
            }
        )
    else:
        # If registration successful, login
        login_response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "fixture@example.com",
                "password": "SecurePass123!",
            }
        )

    access_token = login_response.json()["access_token"]
    return {"Authorization": f"Bearer {access_token}"}

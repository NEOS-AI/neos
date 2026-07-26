"""Pytest configuration and fixtures."""

import os
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


def _skip_database_fixtures(request: pytest.FixtureRequest) -> bool:
    nodeid = getattr(request.node, "nodeid", "")
    return (
        request.node.get_closest_marker("no_db") is not None
        or "tests/workflow/harness/" in nodeid
        or "tests/workflow/test_harness_" in nodeid
        or "tests/workflow/processors/test_research_harness_processor.py" in nodeid
    )


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

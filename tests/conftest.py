"""Pytest configuration and fixtures."""

import asyncio
import os
from typing import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "neos-test-only-secret-key-2026-07-19",
)


def _skip_database_fixtures(request: pytest.FixtureRequest) -> bool:
    nodeid = getattr(request.node, "nodeid", "")
    return (
        request.node.get_closest_marker("no_db") is not None
        or "tests/workflow/harness/" in nodeid
        or "tests/workflow/test_harness_" in nodeid
        or "tests/workflow/processors/test_research_harness_processor.py" in nodeid
    )


@pytest.fixture(scope="function")
def event_loop():
    """
    Create a new event loop for each test function.
    This ensures database connections don't leak between tests.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


@pytest.fixture(scope="function", autouse=True)
async def cleanup_test_data(event_loop, request):
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


@pytest.fixture(scope="function", autouse=True)
async def reset_db_manager(event_loop, cleanup_test_data, request):
    """
    Reset the database manager before and after each test to prevent event loop conflicts.
    This ensures each test gets a fresh database connection pool bound to the current event loop.
    """
    if _skip_database_fixtures(request):
        yield
        return

    from neos.database.connection import db_manager

    # Dispose existing connections before test
    if db_manager.engine is not None:
        try:
            await db_manager.close()
            db_manager.engine = None
            db_manager.session_factory = None
        except Exception:
            pass

    yield

    # Clean up database connections after test
    if db_manager.engine is not None:
        try:
            await db_manager.close()
            db_manager.engine = None
            db_manager.session_factory = None
        except Exception:
            pass


@pytest.fixture(scope="function")
async def client(event_loop) -> AsyncGenerator[AsyncClient, None]:
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

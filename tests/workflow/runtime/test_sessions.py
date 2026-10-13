"""세션 저장소 (spec 2026-10-13 §4.3). 메모리 구현과 Postgres 구현이 같은 계약을 지난다."""

from datetime import UTC, datetime, timedelta

import pytest

from neos.workflow.runtime.sessions import (
    InMemorySessionStore,
    PostgresSessionStore,
    SessionConflict,
    carry,
    trim,
)
from neos.workflow.state import SearchResult

A = SearchResult(source="web", title="A", content="a", url="https://a")
B = SearchResult(source="web", title="B", content="b", url="https://b")


@pytest.fixture(params=["memory", "postgres"])
async def store(request):
    if request.param == "memory":
        yield InMemorySessionStore()
        return
    from sqlalchemy import text

    from neos.database.connection import db_manager

    yield PostgresSessionStore(db_manager.get_session)
    async with await db_manager.get_session() as session:
        await session.execute(text("DELETE FROM workflow_sessions WHERE session_id LIKE 'test-ws-%'"))
        await session.commit()


@pytest.mark.asyncio
async def test_first_save_then_load_roundtrips_types(store) -> None:
    version = await store.save("test-ws-1", user_id="u1", state={"search_results": [A], "q": "x"}, expected_version=None)
    snap = await store.load("test-ws-1")
    assert snap.version == version == 1
    assert snap.user_id == "u1"
    assert snap.state == {"search_results": [A], "q": "x"}
    assert isinstance(snap.state["search_results"][0], SearchResult)


@pytest.mark.asyncio
async def test_save_with_the_loaded_version_wins_and_stale_loses(store) -> None:
    await store.save("test-ws-2", user_id="u1", state={"n": 1}, expected_version=None)
    assert await store.save("test-ws-2", user_id="u1", state={"n": 2}, expected_version=1) == 2
    with pytest.raises(SessionConflict):
        await store.save("test-ws-2", user_id="u1", state={"n": 3}, expected_version=1)
    assert (await store.load("test-ws-2")).state == {"n": 2}


@pytest.mark.asyncio
async def test_a_second_first_save_conflicts(store) -> None:
    await store.save("test-ws-3", user_id="u1", state={}, expected_version=None)
    with pytest.raises(SessionConflict):
        await store.save("test-ws-3", user_id="u1", state={}, expected_version=None)


@pytest.mark.asyncio
async def test_reset_removes_the_session(store) -> None:
    await store.save("test-ws-4", user_id="u1", state={"n": 1}, expected_version=None)
    assert await store.reset("test-ws-4") is True
    assert await store.load("test-ws-4") is None
    assert await store.reset("test-ws-4") is False


@pytest.mark.asyncio
async def test_purge_removes_only_old_rows(store) -> None:
    await store.save("test-ws-5", user_id="u1", state={}, expected_version=None)
    assert await store.purge_older_than(datetime.now(UTC) - timedelta(days=1)) == 0
    assert await store.load("test-ws-5") is not None
    assert await store.purge_older_than(datetime.now(UTC) + timedelta(seconds=1)) >= 1
    assert await store.load("test-ws-5") is None


@pytest.mark.no_db
def test_carry_applies_the_turn_input_as_an_update() -> None:
    saved = {"search_results": [A], "skill_sources": [A], "kept": 1}
    initial = {"search_results": [], "skill_sources": None, "original_query": "q2"}
    merged = carry(saved, initial)
    assert merged["search_results"] == [A]  # 누적은 남는다
    assert merged["skill_sources"] is None  # 교체 필드는 이번 턴 값
    assert merged["kept"] == 1  # 입력이 건드리지 않는 키는 이어진다
    assert merged["original_query"] == "q2"
    assert carry(None, initial) == initial


@pytest.mark.no_db
def test_trim_keeps_the_newest_accumulated_items() -> None:
    state = {"search_results": [A, B, A], "errors": ["e"], "other": [1, 2, 3]}
    trimmed, cut = trim(state, max_items=2)
    assert trimmed["search_results"] == [B, A]
    assert trimmed["errors"] == ["e"]
    assert trimmed["other"] == [1, 2, 3]  # 누적 필드가 아니다
    assert cut == {"search_results": 1}

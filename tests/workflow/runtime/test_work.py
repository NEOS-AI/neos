"""작업 기록 (spec 2026-10-13 §4.4). 메모리 구현과 Postgres 구현이 같은 계약을 지난다."""

import pytest

from neos.workflow.runtime.work import (
    InMemoryWorkStore,
    PostgresWorkStore,
    WorkConflict,
    WorkLifecycle,
    entry_and_delivery,
)


@pytest.fixture(params=["memory", "postgres"])
async def lifecycle(request):
    if request.param == "memory":
        yield WorkLifecycle(InMemoryWorkStore())
        return
    from sqlalchemy import text

    from neos.database.connection import db_manager

    yield WorkLifecycle(PostgresWorkStore(db_manager.get_session))
    async with await db_manager.get_session() as session:
        await session.execute(text("DELETE FROM workflow_runs WHERE user_id = 'test-work-user'"))
        await session.commit()


async def _start(lifecycle, session_id="test-work-s1"):
    return await lifecycle.start(
        "web", "workflow", user_id="test-work-user", session_id=session_id,
        delivery={"kind": "sse", "conversation_id": session_id},
    )


@pytest.mark.asyncio
async def test_a_turn_runs_then_completes(lifecycle) -> None:
    work_id = await _start(lifecycle)
    assert work_id.startswith("wk_")
    await lifecycle.complete(work_id, {"final_response": "답", "author": None, "verified_by": None})
    record = await lifecycle.store.get(work_id)
    assert record.status == "completed"
    assert record.result["final_response"] == "답"
    assert record.delivery == {"kind": "sse", "conversation_id": "test-work-s1"}


@pytest.mark.asyncio
async def test_interrupt_claim_and_the_waiting_lookup(lifecycle) -> None:
    work_id = await _start(lifecycle, "test-work-s2")
    await lifecycle.interrupt(work_id, {"next_node": "execution_approval", "request_ids": ["apr_1"], "pending": [{"request_id": "apr_1"}]})
    waiting = await lifecycle.store.waiting_for_session("test-work-s2")
    assert waiting.work_id == work_id and waiting.status == "waiting_approval"
    claimed = await lifecycle.claim(work_id, expected_version=waiting.version)
    assert claimed.status == "running" and claimed.pending is None
    assert await lifecycle.store.waiting_for_session("test-work-s2") is None


@pytest.mark.asyncio
async def test_a_stale_claim_conflicts(lifecycle) -> None:
    work_id = await _start(lifecycle, "test-work-s3")
    await lifecycle.interrupt(work_id, {"next_node": "x", "request_ids": ["r"], "pending": []})
    version = (await lifecycle.store.get(work_id)).version
    await lifecycle.claim(work_id, expected_version=version)
    with pytest.raises(WorkConflict):
        await lifecycle.claim(work_id, expected_version=version)


@pytest.mark.asyncio
async def test_expire_closes_a_waiting_work(lifecycle) -> None:
    work_id = await _start(lifecycle, "test-work-s4")
    await lifecycle.interrupt(work_id, {"next_node": "x", "request_ids": ["r"], "pending": []})
    record = await lifecycle.store.get(work_id)
    expired = await lifecycle.expire(work_id, expected_version=record.version)
    assert expired.status == "expired"


@pytest.mark.asyncio
async def test_illegal_transitions_conflict(lifecycle) -> None:
    work_id = await _start(lifecycle, "test-work-s5")
    await lifecycle.complete(work_id, {"final_response": None})
    with pytest.raises(WorkConflict):
        await lifecycle.fail(work_id, "late")


@pytest.mark.asyncio
async def test_children_and_refs(lifecycle) -> None:
    parent = await _start(lifecycle, "test-work-s6")
    child = await lifecycle.start(
        "web", "coding", user_id="test-work-user", session_id=None, delivery={"kind": "none"},
        parent=parent, ref_id="ct_test_1",
    )
    record = await lifecycle.store.by_ref("coding", "ct_test_1")
    assert record.work_id == child and record.parent_work_id == parent


@pytest.mark.asyncio
async def test_waiting_rows_and_the_request_lookup(lifecycle) -> None:
    """한 세션에 대기 행이 둘이어도 둘 다 보이고, request_id 로 옛 행을 찾는다(최신 행이 아니다)."""
    older = await _start(lifecycle, "test-work-s7")
    await lifecycle.interrupt(older, {"next_node": "x", "request_ids": ["apr_old"], "pending": []})
    newer = await _start(lifecycle, "test-work-s7")
    await lifecycle.interrupt(newer, {"next_node": "x", "request_ids": ["apr_new"], "pending": []})
    rows = await lifecycle.store.waiting_rows_for_session("test-work-s7")
    assert sorted(r.work_id for r in rows) == sorted([older, newer])
    assert (await lifecycle.store.waiting_by_request("test-work-s7", "apr_old")).work_id == older
    assert (await lifecycle.store.waiting_by_request("test-work-s7", "apr_new")).work_id == newer
    assert await lifecycle.store.waiting_by_request("test-work-s7", "apr_none") is None
    assert await lifecycle.store.waiting_by_request("test-work-other", "apr_old") is None
    record = await lifecycle.store.get(older)
    await lifecycle.expire(older, expected_version=record.version)
    assert await lifecycle.store.waiting_by_request("test-work-s7", "apr_old") is None
    assert [r.work_id for r in await lifecycle.store.waiting_rows_for_session("test-work-s7")] == [newer]


@pytest.mark.no_db
@pytest.mark.parametrize(
    ("user_input", "entry", "delivery"),
    [
        ({"session_id": "c1"}, "web", {"kind": "sse", "conversation_id": "c1"}),
        ({"session_id": "v2:x", "channel_source": "slack", "channel_type": "slack", "channel_id": "C1"}, "channel",
         {"kind": "channel", "channel_type": "slack", "channel_id": "C1"}),
        ({"session_id": "scheduled_1", "channel_source": "scheduler"}, "schedule", {"kind": "none"}),
    ],
)
def test_entry_and_delivery_come_from_existing_input_keys(user_input, entry, delivery) -> None:
    assert entry_and_delivery(user_input) == (entry, delivery)

from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import pytest
from fastapi import HTTPException

from neos.api.handlers import async_research_handlers
from neos.utils.cache import cache_manager
from neos.workflow.stream_manager import StreamEvent


def _user(user_id: str = "owner") -> SimpleNamespace:
    return SimpleNamespace(user_id=user_id, is_active=True)


def _request(
    *,
    last_event_id: str | None = None,
    disconnected: list[bool] | None = None,
) -> SimpleNamespace:
    headers = {}
    if last_event_id is not None:
        headers["last-event-id"] = last_event_id
    return SimpleNamespace(
        headers=headers,
        is_disconnected=AsyncMock(
            side_effect=disconnected if disconnected is not None else [False]
        ),
    )


async def _chunks(response) -> list[str]:
    return [chunk async for chunk in response.body_iterator]


async def test_stream_replays_after_last_event_id_without_duplicates(
    monkeypatch,
) -> None:
    monkeypatch.setattr(cache_manager, "get", AsyncMock(return_value="owner"))
    read_after = AsyncMock(
        side_effect=[
            [StreamEvent("2-0", "workflow_started", '{"step": 1}')],
            [StreamEvent("3-0", "workflow_completed", '{"ok": true}')],
        ]
    )
    monkeypatch.setattr(
        async_research_handlers.async_research_event_stream,
        "read_after",
        read_after,
    )

    response = await async_research_handlers.stream_research_progress(
        "s1",
        _request(last_event_id="1-0", disconnected=[False, False]),
        current_user=_user(),
    )
    chunks = await _chunks(response)

    assert read_after.await_args_list == [
        call("s1", "1-0", block_ms=15000, count=100),
        call("s1", "2-0", block_ms=15000, count=100),
    ]
    assert sum("id: 2-0" in chunk for chunk in chunks) == 1
    assert "event: workflow_completed" in chunks[-1]


async def test_stream_without_header_reads_from_beginning(monkeypatch) -> None:
    monkeypatch.setattr(cache_manager, "get", AsyncMock(return_value="owner"))
    read_after = AsyncMock(
        return_value=[
            StreamEvent("1-0", "workflow_completed", '{"ok": true}')
        ]
    )
    monkeypatch.setattr(
        async_research_handlers.async_research_event_stream,
        "read_after",
        read_after,
    )

    response = await async_research_handlers.stream_research_progress(
        "s1", _request(), current_user=_user()
    )
    await _chunks(response)

    read_after.assert_awaited_once_with(
        "s1", "0-0", block_ms=15000, count=100
    )


async def test_empty_read_yields_one_heartbeat(monkeypatch) -> None:
    monkeypatch.setattr(cache_manager, "get", AsyncMock(return_value="owner"))
    read_after = AsyncMock(return_value=[])
    monkeypatch.setattr(
        async_research_handlers.async_research_event_stream,
        "read_after",
        read_after,
    )

    response = await async_research_handlers.stream_research_progress(
        "s1",
        _request(disconnected=[False, True]),
        current_user=_user(),
    )

    assert await _chunks(response) == [": heartbeat\n\n"]


async def test_workflow_failed_event_closes_stream(monkeypatch) -> None:
    monkeypatch.setattr(cache_manager, "get", AsyncMock(return_value="owner"))
    read_after = AsyncMock(
        return_value=[
            StreamEvent("4-0", "workflow_failed", '{"error": "failed"}')
        ]
    )
    monkeypatch.setattr(
        async_research_handlers.async_research_event_stream,
        "read_after",
        read_after,
    )

    response = await async_research_handlers.stream_research_progress(
        "s1", _request(), current_user=_user()
    )
    chunks = await _chunks(response)

    assert len(chunks) == 1
    assert "event: workflow_failed" in chunks[0]


async def test_invalid_last_event_id_is_rejected_before_read(
    monkeypatch,
) -> None:
    monkeypatch.setattr(cache_manager, "get", AsyncMock(return_value="owner"))
    read_after = AsyncMock()
    monkeypatch.setattr(
        async_research_handlers.async_research_event_stream,
        "read_after",
        read_after,
    )

    with pytest.raises(HTTPException) as exc:
        await async_research_handlers.stream_research_progress(
            "s1",
            _request(last_event_id="not-a-cursor"),
            current_user=_user(),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Invalid Last-Event-ID"
    read_after.assert_not_awaited()


async def test_redis_read_failure_yields_terminal_stream_error(
    monkeypatch,
) -> None:
    monkeypatch.setattr(cache_manager, "get", AsyncMock(return_value="owner"))
    read_after = AsyncMock(side_effect=ConnectionError("redis unavailable"))
    monkeypatch.setattr(
        async_research_handlers.async_research_event_stream,
        "read_after",
        read_after,
    )

    response = await async_research_handlers.stream_research_progress(
        "s1", _request(last_event_id="9-0"), current_user=_user()
    )
    chunks = await _chunks(response)

    assert len(chunks) == 1
    assert "id: 9-0" in chunks[0]
    assert "event: stream_error" in chunks[0]
    assert "Event stream unavailable" in chunks[0]
    assert "redis unavailable" not in chunks[0]


@pytest.mark.parametrize("owner_id", [None, "other"])
async def test_missing_or_foreign_owner_never_reads_stream(
    monkeypatch,
    owner_id,
) -> None:
    monkeypatch.setattr(cache_manager, "get", AsyncMock(return_value=owner_id))
    read_after = AsyncMock()
    monkeypatch.setattr(
        async_research_handlers.async_research_event_stream,
        "read_after",
        read_after,
    )

    with pytest.raises(HTTPException) as exc:
        await async_research_handlers.stream_research_progress(
            "s1", _request(), current_user=_user()
        )

    assert exc.value.status_code == 404
    read_after.assert_not_awaited()

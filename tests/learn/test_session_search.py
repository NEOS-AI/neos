import sys
from types import SimpleNamespace

import pytest

from neos.learn.session_search import search_user_sessions

pytestmark = pytest.mark.no_db


@pytest.mark.asyncio
async def test_search_user_sessions_requires_user_id() -> None:
    with pytest.raises(ValueError, match="user_id is required"):
        await search_user_sessions("", "rate limit")


@pytest.mark.asyncio
async def test_search_user_sessions_passes_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    async def fake_find(*, user_id: str, query: str, limit: int):
        called["user_id"] = user_id
        called["query"] = query
        called["limit"] = limit
        return [{"message_id": "m1", "user_id": user_id}]

    # Late import inside search_user_sessions; stub the module so embeddings/LLM
    # providers are never loaded.
    monkeypatch.setitem(
        sys.modules,
        "neos.services.similarity_search_service",
        SimpleNamespace(
            similarity_search_service=SimpleNamespace(
                find_similar_across_conversations=fake_find,
            )
        ),
    )

    result = await search_user_sessions("user-1", "rate limit", limit=3)

    assert result == [{"message_id": "m1", "user_id": "user-1"}]
    assert called == {"user_id": "user-1", "query": "rate limit", "limit": 3}


def _stub_find(monkeypatch: pytest.MonkeyPatch, rows: list[dict]) -> None:
    async def fake_find(*, user_id: str, query: str, limit: int):
        return list(rows)

    monkeypatch.setitem(
        sys.modules,
        "neos.services.similarity_search_service",
        SimpleNamespace(
            similarity_search_service=SimpleNamespace(
                find_similar_across_conversations=fake_find,
            )
        ),
    )


@pytest.mark.asyncio
async def test_search_clips_content_and_prefers_shorter_snippet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_find(
        monkeypatch,
        [
            {
                "message_id": "m1",
                "conversation_id": "c1",
                "content": "C" * 500,
            },
            {
                "message_id": "m2",
                "conversation_id": "c2",
                "content": "full message body that should not leak",
                "snippet": "short hit",
            },
        ],
    )

    result = await search_user_sessions("user-1", "rate limit")

    by_id = {row["message_id"]: row for row in result}
    assert len(by_id["m1"].get("snippet") or by_id["m1"].get("content") or "") == 240
    assert "C" * 241 not in str(by_id["m1"].get("content") or "")
    assert by_id["m2"].get("snippet") == "short hit"
    content = by_id["m2"].get("content")
    assert content is None or content == "short hit"


@pytest.mark.asyncio
async def test_search_hides_cron_and_subagent_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_find(
        monkeypatch,
        [
            {"message_id": "keep", "conversation_id": "c1", "content": "user chat"},
            {"message_id": "cron", "conversation_id": "c2", "content": "tick", "source": "cron"},
            {
                "message_id": "sub",
                "conversation_id": "c3",
                "content": "spawned",
                "origin": "subagent",
            },
            {
                "message_id": "run",
                "conversation_id": "c4",
                "content": "child",
                "mode": "subrun",
            },
            {
                "message_id": "tool",
                "conversation_id": "c5",
                "content": "integration",
                "metadata": {"origin": "tool"},
            },
            {
                "message_id": "board",
                "conversation_id": "c6",
                "content": "card",
                "conversation": {"mode": "kanban"},
            },
        ],
    )

    result = await search_user_sessions("user-1", "rate limit")

    assert [row["message_id"] for row in result] == ["keep"]


@pytest.mark.asyncio
async def test_search_excludes_live_conversation_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_find(
        monkeypatch,
        [
            {"message_id": "live", "conversation_id": "conv-live", "content": "now"},
            {"message_id": "old", "conversation_id": "conv-old", "content": "then"},
        ],
    )

    result = await search_user_sessions(
        "user-1",
        "rate limit",
        exclude_conversation_id="conv-live",
    )

    assert [row["message_id"] for row in result] == ["old"]


def test_curate_learned_skills_registered_in_beat_schedule() -> None:
    from neos.workflow.celery_app import app

    entry = app.conf.beat_schedule.get("curate-learned-skills")
    assert entry is not None
    assert entry["task"] == "neos.tasks.curate_learned_skills"
    assert entry["schedule"] == 86400.0

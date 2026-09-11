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


def test_curate_learned_skills_registered_in_beat_schedule() -> None:
    from neos.workflow.celery_app import app

    entry = app.conf.beat_schedule.get("curate-learned-skills")
    assert entry is not None
    assert entry["task"] == "neos.tasks.curate_learned_skills"
    assert entry["schedule"] == 86400.0

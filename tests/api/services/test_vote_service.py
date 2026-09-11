from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neos.api.services.vote_service import VoteService

pytestmark = pytest.mark.no_db


def _vote_service(existing=None) -> VoteService:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return VoteService(db)


@pytest.mark.asyncio
async def test_submit_feedback_learns_factual_text() -> None:
    existing = SimpleNamespace(
        chat_id="c1",
        message_id="m1",
        is_upvoted=False,
        feedback_text=None,
        feedback_category=None,
    )
    service = _vote_service(existing)
    knowledge = "The sources cited were outdated"

    with patch(
        "neos.memory.manager.MemoryManager.learn",
        new_callable=AsyncMock,
        return_value=True,
    ) as learn:
        response = await service.submit_feedback(
            chat_id="c1",
            message_id="m1",
            is_upvoted=False,
            feedback_text=knowledge,
            feedback_category="source_quality",
            user_id="u1",
        )

    assert response.feedback_text == knowledge
    learn.assert_awaited_once()
    assert learn.await_args.args[0] == "u1"
    assert learn.await_args.kwargs["key"] == "feedback:c1:m1"
    assert learn.await_args.kwargs["knowledge"] == knowledge
    assert learn.await_args.kwargs["metadata"] == {"category": "source_quality"}


@pytest.mark.asyncio
async def test_submit_feedback_skips_imperative_learn() -> None:
    existing = SimpleNamespace(
        chat_id="c1",
        message_id="m1",
        is_upvoted=True,
        feedback_text=None,
        feedback_category=None,
    )
    service = _vote_service(existing)

    with patch(
        "neos.memory.manager.MemoryManager.learn",
        new_callable=AsyncMock,
        return_value=True,
    ) as learn:
        response = await service.submit_feedback(
            chat_id="c1",
            message_id="m1",
            is_upvoted=True,
            feedback_text="Always respond concisely",
            feedback_category="prompt_issue",
            user_id="u1",
        )

    assert response.chat_id == "c1"
    learn.assert_not_awaited()

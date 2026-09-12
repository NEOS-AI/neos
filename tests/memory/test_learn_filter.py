from unittest.mock import AsyncMock, MagicMock

import pytest

from neos.memory.manager import MemoryManager

pytestmark = pytest.mark.no_db


def _manager_with_store() -> tuple[MemoryManager, AsyncMock]:
    manager = MemoryManager()
    store = AsyncMock(return_value=True)
    manager._initialized = True
    manager._long_term = MagicMock()
    manager._long_term.store = store
    return manager, store


@pytest.mark.asyncio
async def test_learn_does_not_store_imperative() -> None:
    manager, store = _manager_with_store()

    result = await manager.learn(
        "u1",
        "pref",
        "Always respond concisely",
    )

    assert result is False
    store.assert_not_awaited()


@pytest.mark.asyncio
async def test_learn_stores_factual_sentence() -> None:
    manager, store = _manager_with_store()
    knowledge = "The API rate limit is 60 requests per minute"

    result = await manager.learn("u1", "rate-limit", knowledge)

    assert result is True
    store.assert_awaited_once()
    assert store.await_args.args[:3] == ("u1", "rate-limit", knowledge)


@pytest.mark.asyncio
async def test_learn_clips_knowledge_before_store() -> None:
    from neos.config.schema import AppConfig

    manager, store = _manager_with_store()
    knowledge = "The API rate limit is 60 requests per minute. " * 20

    result = await manager.learn("u1", "rate-limit", knowledge)

    assert result is True
    stored = store.await_args.args[2]
    assert len(stored) == AppConfig().learn.max_knowledge_chars
    assert stored == knowledge.strip()[: AppConfig().learn.max_knowledge_chars]

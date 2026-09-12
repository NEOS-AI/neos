from unittest.mock import AsyncMock

import pytest

from neos.learn.lessons import LessonStatus, reset_lesson_store
from neos.learn.memory_gate import maybe_learn_ltm
from neos.learn.policy import namespace

pytestmark = pytest.mark.no_db


@pytest.mark.asyncio
async def test_write_approval_on_stages_lesson_and_skips_learn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from neos.config.settings import settings

    store = reset_lesson_store()
    monkeypatch.setattr(settings.config.learn, "write_approval", True)
    learn = AsyncMock(return_value=True)
    monkeypatch.setattr("neos.memory.manager.memory_manager.learn", learn)

    result = await maybe_learn_ltm(
        "u1",
        key="feedback:c1:m1",
        knowledge="The sources cited were outdated",
        metadata={"category": "source_quality"},
    )

    assert result == "staged"
    learn.assert_not_awaited()
    lessons = store.list(namespace("u1"))
    assert len(lessons) == 1
    assert lessons[0].status is LessonStatus.STAGED
    assert lessons[0].kind == "fact"
    assert lessons[0].body == "The sources cited were outdated"
    assert lessons[0].namespace == "owner:u1"


@pytest.mark.asyncio
async def test_write_approval_off_calls_learn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from neos.config.settings import settings

    store = reset_lesson_store()
    monkeypatch.setattr(settings.config.learn, "write_approval", False)
    learn = AsyncMock(return_value=True)
    monkeypatch.setattr("neos.memory.manager.memory_manager.learn", learn)

    result = await maybe_learn_ltm(
        "u1",
        key="feedback:c1:m1",
        knowledge="The sources cited were outdated",
        metadata={"category": "source_quality"},
    )

    assert result == "learned"
    learn.assert_awaited_once()
    assert learn.await_args.args[0] == "u1"
    assert learn.await_args.kwargs["key"] == "feedback:c1:m1"
    assert learn.await_args.kwargs["knowledge"] == "The sources cited were outdated"
    assert learn.await_args.kwargs["metadata"] == {"category": "source_quality"}
    assert store.list(namespace("u1")) == ()


@pytest.mark.asyncio
async def test_store_failure_is_fail_closed_and_does_not_learn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from neos.config.settings import settings
    from neos.learn.lessons import set_lesson_session_factory

    reset_lesson_store()
    monkeypatch.setattr(settings.config.learn, "write_approval", True)

    async def boom():
        raise RuntimeError("db down")

    set_lesson_session_factory(boom)
    learn = AsyncMock(return_value=True)
    monkeypatch.setattr("neos.memory.manager.memory_manager.learn", learn)

    with pytest.raises(RuntimeError, match="db down"):
        await maybe_learn_ltm(
            "u1",
            key="episode:s1",
            knowledge="Query about x: findings",
        )

    learn.assert_not_awaited()

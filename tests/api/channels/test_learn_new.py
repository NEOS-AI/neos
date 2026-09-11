from __future__ import annotations

import pytest

from neos.api.channels.session_bind import InMemoryChannelCodingBindStore
from neos.learn.lessons import LessonStatus, reset_lesson_store
from tests.api.channels.test_gateway_router import _gateway, _message
from tests.api.channels.test_session_bind import _gateway as _bound_gateway

pytestmark = pytest.mark.no_db


async def test_learn_disabled_by_default(monkeypatch) -> None:
    store = reset_lesson_store()
    gateway, workflow, coding = _gateway(monkeypatch)
    reply = await gateway.dispatch(_message("/learn the rate limit is 60"))
    assert reply == "Learning is disabled."
    assert store.list() == ()
    assert workflow.calls == []
    assert coding.started == []


async def test_learn_stages_when_channel_learn_on(monkeypatch) -> None:
    import neos.config.settings as settings_module

    store = reset_lesson_store()
    gateway, workflow, coding = _gateway(monkeypatch)
    monkeypatch.setattr(settings_module.settings.config.learn, "channel_learn", True)
    assert settings_module.settings.config.learn.coding_lessons is False

    reply = await gateway.dispatch(_message("/learn the rate limit is 60"))

    assert "staged" in reply.lower()
    lessons = store.list()
    assert len(lessons) == 1
    assert lessons[0].status is LessonStatus.STAGED
    assert "rate limit is 60" in lessons[0].body
    assert workflow.calls == []
    assert coding.started == []


async def test_learn_enabled_by_coding_lessons_flag(monkeypatch) -> None:
    import neos.config.settings as settings_module

    store = reset_lesson_store()
    gateway, _workflow, _coding = _gateway(monkeypatch)
    monkeypatch.setattr(settings_module.settings.config.learn, "coding_lessons", True)
    assert settings_module.settings.config.learn.channel_learn is False

    reply = await gateway.dispatch(_message("!learn prefer citations"))

    assert "staged" in reply.lower()
    assert store.list()
    assert store.list()[0].status is LessonStatus.STAGED


async def test_new_unbinds_only_this_session(monkeypatch) -> None:
    store = InMemoryChannelCodingBindStore()
    gateway, workflow, _coding = _bound_gateway(monkeypatch, binds=store)
    other = "v2:slack:T:C:other"
    this = "v2:slack:T:C:1"
    await gateway.dispatch(_message("/code fix a", this))
    await gateway.dispatch(_message("/code fix b", other))

    reply = await gateway.dispatch(_message("/new", this))

    assert reply == "Session reset."
    assert await store.get(this) is None
    remaining = await store.get(other)
    assert remaining is not None
    assert remaining.task_id
    assert workflow.calls == []
    assert await gateway.dispatch(_message("/status", this)) == (
        "No coding task in this thread."
    )
    assert "queued" in await gateway.dispatch(_message("/status", other))


@pytest.mark.parametrize("text", ["/reset", "!new", "!reset"])
async def test_reset_aliases_unbind_this_session(monkeypatch, text: str) -> None:
    store = InMemoryChannelCodingBindStore()
    gateway, _workflow, _coding = _bound_gateway(monkeypatch, binds=store)
    session_id = "v2:slack:T:C:reset"
    await gateway.dispatch(_message("/code do it", session_id))

    reply = await gateway.dispatch(_message(text, session_id))

    assert reply == "Session reset."
    assert await store.get(session_id) is None


async def test_in_memory_unbind_is_session_scoped() -> None:
    store = InMemoryChannelCodingBindStore()
    await store.bind("sess-a", "ct_a", "u1")
    await store.bind("sess-b", "ct_b", "u2")
    await store.unbind("sess-a")
    assert await store.get("sess-a") is None
    found = await store.get("sess-b")
    assert found is not None
    assert found.task_id == "ct_b"

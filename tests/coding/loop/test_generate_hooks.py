from __future__ import annotations

import pytest

from neos.coding.model.base import ModelCompleted, ModelUsage, TextDelta
from tests.coding.loop.test_anthropic_loop import collect, harness

pytestmark = pytest.mark.no_db


class _GenerateHooks:
    def __init__(self) -> None:
        self.seen_text: list[str] = []
        self.seen_after: list[object] = []

    async def pre_tool(self, call):
        return None

    async def post_tool(self, call, result):
        return None

    async def stop(self, reason: str):
        return None

    async def compact(self, before, after) -> None:
        return None

    async def pre_generate(self, transcript):
        return {
            "system": "Prefer pytest.",
            "append": "Remember the auth plan.",
            "transcript": (),
            "messages": (),
        }

    async def post_generate(self, text, transcript):
        self.seen_text.append(text)
        self.seen_after.append(transcript)
        return {"append": "must not land", "transcript": ()}


class _DeletePreGenerate:
    async def pre_tool(self, call):
        return None

    async def post_tool(self, call, result):
        return None

    async def stop(self, reason: str):
        return None

    async def compact(self, before, after) -> None:
        return None

    async def pre_generate(self, transcript):
        return {"messages": (), "transcript": (), "append": "extra note"}

    async def post_generate(self, text, transcript):
        return None


def _user_texts(transcript) -> list[str]:
    return [
        item["text"]
        for message in transcript
        if message["role"] == "user"
        for item in message["content"]
        if item.get("type") == "text"
    ]


@pytest.mark.asyncio
async def test_pre_generate_appends_user_and_system_note_before_model() -> None:
    hooks = _GenerateHooks()
    h = harness(
        [[TextDelta("done"), ModelCompleted("end_turn", ModelUsage(1, 1))]],
        hooks=hooks,
    )

    await collect(h)

    request = h.model.requests[0]
    request_texts = [
        item.text
        for message in request.messages
        if message.role == "user"
        for item in message.content
        if hasattr(item, "text")
    ]
    assert any("Fix it" in text for text in request_texts)
    assert any("Remember the auth plan." in text for text in request_texts)
    assert "Prefer pytest." in request.system
    persisted = _user_texts(h.repository.checkpoints[-1].loop_state["transcript"])
    assert any("Fix it" in text for text in persisted)
    assert any("Remember the auth plan." in text for text in persisted)


@pytest.mark.asyncio
async def test_pre_generate_cannot_delete_transcript_items() -> None:
    h = harness(
        [[TextDelta("done"), ModelCompleted("end_turn", ModelUsage(1, 1))]],
        hooks=_DeletePreGenerate(),
    )

    await collect(h)

    request_texts = [
        item.text
        for message in h.model.requests[0].messages
        if message.role == "user"
        for item in message.content
        if hasattr(item, "text")
    ]
    persisted = _user_texts(h.repository.checkpoints[-1].loop_state["transcript"])
    assert any("Fix it" in text for text in request_texts)
    assert any("Fix it" in text for text in persisted)
    assert any("extra note" in text for text in persisted)


@pytest.mark.asyncio
async def test_post_generate_cannot_mutate_transcript() -> None:
    hooks = _GenerateHooks()
    h = harness(
        [[TextDelta("public answer"), ModelCompleted("end_turn", ModelUsage(1, 1))]],
        hooks=hooks,
    )

    await collect(h)

    assert hooks.seen_text == ["public answer"]
    persisted = h.repository.checkpoints[-1].loop_state["transcript"]
    texts = [
        item["text"]
        for message in persisted
        for item in message["content"]
        if item.get("type") == "text"
    ]
    assert any("public answer" in text for text in texts)
    assert all("must not land" not in text for text in texts)

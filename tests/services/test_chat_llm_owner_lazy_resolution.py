"""Fix round 2, Item 2 — a turn with no attachments must not touch the DB
to resolve an attachment owner.

`_resolve_owner_user_id` calls `ChatRepository.get_conversation`, a real
`SELECT ... FROM conversations`. The first pass of the security fix (Finding
1) called it unconditionally before `resolve_attachments`, so even a plain
text turn — and every auto title generation — paid for an extra
conversations round-trip that `resolve_attachments`' own early return could
no longer prevent. `_resolve_owner_user_id_if_needed` now checks whether any
user message actually carries `attachments` before doing that lookup.

Round 3, Item 3 extends this file: a verifier found that reverting sites 3
and 4 (`generate_response_stream_with_tools`,
`generate_response_stream_with_tool_search` — the two raw-Anthropic-SDK
streaming paths) back to the eager call left the suite green, because only
sites 1 and 2 (`generate_response`, `generate_response_stream`) had
end-to-end coverage here. The fake Anthropic client below reuses the shape
already built in `tests/services/test_chat_llm_attachment_paths.py`.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from neos.services import chat_llm_service
from neos.services.attachment_blocks import AttachmentPlan


class _FakeResponse:
    def __init__(self):
        self.content = "answer"
        self.response_metadata = {"usage": {"input_tokens": 1, "output_tokens": 1}}


class _FakeLLM:
    async def ainvoke(self, messages, **kwargs):
        return _FakeResponse()


def _install_fake_llm(monkeypatch):
    monkeypatch.setattr(chat_llm_service, "create_llm", lambda **kwargs: _FakeLLM())


# ---------------------------------------------------------------------------
# Unit-level: the gate function itself.
# ---------------------------------------------------------------------------


def test_has_any_attachment_is_false_for_plain_text_messages():
    messages = [
        {"role": "assistant", "content": "hi"},
        {"role": "user", "content": "hello"},
    ]
    assert chat_llm_service._has_any_attachment(messages) is False


def test_has_any_attachment_is_true_when_a_user_message_carries_one():
    messages = [
        {"role": "user", "content": "봐줘", "attachments": [{"name": "a.png"}]},
    ]
    assert chat_llm_service._has_any_attachment(messages) is True


@pytest.mark.asyncio
async def test_resolve_owner_if_needed_skips_the_lookup_without_attachments(
    monkeypatch,
):
    get_conversation = AsyncMock(return_value=None)
    monkeypatch.setattr(
        chat_llm_service.ChatRepository, "get_conversation", get_conversation
    )

    owner = await chat_llm_service._resolve_owner_user_id_if_needed(
        "c1", [{"role": "user", "content": "hello"}]
    )

    assert owner is None
    get_conversation.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_owner_if_needed_looks_up_when_an_attachment_is_present(
    monkeypatch,
):
    conversation = type("C", (), {"user_id": "u1"})()
    get_conversation = AsyncMock(return_value=conversation)
    monkeypatch.setattr(
        chat_llm_service.ChatRepository, "get_conversation", get_conversation
    )

    owner = await chat_llm_service._resolve_owner_user_id_if_needed(
        "c1",
        [{"role": "user", "content": "봐줘", "attachments": [{"name": "a.png"}]}],
    )

    assert owner == "u1"
    get_conversation.assert_awaited_once_with("c1")


# ---------------------------------------------------------------------------
# End-to-end: the real entry points must not look up the conversation when
# the turn carries no attachments at all.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_response_skips_conversation_lookup_without_attachments(
    monkeypatch,
):
    get_conversation = AsyncMock(return_value=None)
    monkeypatch.setattr(
        chat_llm_service.ChatRepository, "get_conversation", get_conversation
    )
    _install_fake_llm(monkeypatch)

    service = chat_llm_service.ChatLLMService()
    await service.generate_response(
        conversation_id="c1",
        message_id="m1",
        conversation_messages=[{"role": "user", "content": "hello"}],
        model_name="claude-sonnet-5",
        enable_context_optimization=False,
    )

    get_conversation.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_response_looks_up_conversation_when_attachments_present(
    monkeypatch,
):
    conversation = type("C", (), {"user_id": "u1"})()
    get_conversation = AsyncMock(return_value=conversation)
    monkeypatch.setattr(
        chat_llm_service.ChatRepository, "get_conversation", get_conversation
    )
    _install_fake_llm(monkeypatch)

    async def fake_resolve(messages, *, model, owner_user_id):
        assert owner_user_id == "u1"
        return AttachmentPlan(by_index={}, notices=[])

    monkeypatch.setattr(chat_llm_service, "resolve_attachments", fake_resolve)

    service = chat_llm_service.ChatLLMService()
    await service.generate_response(
        conversation_id="c1",
        message_id="m1",
        conversation_messages=[
            {"role": "user", "content": "봐줘", "attachments": [{"name": "a.png"}]}
        ],
        model_name="claude-sonnet-5",
        enable_context_optimization=False,
    )

    get_conversation.assert_awaited_once_with("c1")


@pytest.mark.asyncio
async def test_generate_response_stream_skips_conversation_lookup_without_attachments(
    monkeypatch,
):
    get_conversation = AsyncMock(return_value=None)
    monkeypatch.setattr(
        chat_llm_service.ChatRepository, "get_conversation", get_conversation
    )

    class _FakeStreamLLM:
        async def astream(self, messages, **kwargs):
            return
            yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(chat_llm_service, "create_llm", lambda **kwargs: _FakeStreamLLM())

    service = chat_llm_service.ChatLLMService()
    async for _ in service.generate_response_stream(
        conversation_id="c1",
        message_id="m1",
        conversation_messages=[{"role": "user", "content": "hello"}],
        model_name="claude-sonnet-5",
        enable_context_optimization=False,
    ):
        pass

    get_conversation.assert_not_awaited()


# ---------------------------------------------------------------------------
# Round 3, Item 3 — the two raw-Anthropic-SDK streaming paths (sites 3 and
# 4) get the same end-to-end coverage as sites 1 and 2 above.
# ---------------------------------------------------------------------------


def _make_fake_anthropic_client():
    """Same shape as `test_chat_llm_attachment_paths.py`'s fake client —
    reused rather than reinvented, per the fix-round-3 instructions."""

    class _FakeStream:
        def __aiter__(self):
            async def _empty():
                return
                yield  # pragma: no cover

            return _empty()

        async def get_final_message(self):
            return SimpleNamespace(
                usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                content=[],
                stop_reason="end_turn",
            )

    class _FakeStreamCM:
        async def __aenter__(self):
            return _FakeStream()

        async def __aexit__(self, *exc):
            return False

    class _FakeMessages:
        def stream(self, **kwargs):
            return _FakeStreamCM()

    class _FakeClient:
        messages = _FakeMessages()
        beta = SimpleNamespace(messages=_FakeMessages())

    return _FakeClient()


def _install_fake_anthropic(monkeypatch):
    monkeypatch.setattr(
        chat_llm_service,
        "build_async_anthropic",
        lambda *a, **k: _make_fake_anthropic_client(),
    )
    monkeypatch.setattr(
        chat_llm_service,
        "normalize_anthropic_usage",
        lambda usage, **kwargs: {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "total_input_tokens": 0,
            "cache_status": "disabled",
            "iterations": [],
        },
    )


@pytest.mark.asyncio
async def test_generate_response_stream_with_tools_skips_conversation_lookup_without_attachments(
    monkeypatch,
):
    get_conversation = AsyncMock(return_value=None)
    monkeypatch.setattr(
        chat_llm_service.ChatRepository, "get_conversation", get_conversation
    )
    _install_fake_anthropic(monkeypatch)

    service = chat_llm_service.ChatLLMService()
    async for _ in service.generate_response_stream_with_tools(
        conversation_id="c1",
        message_id="m1",
        conversation_messages=[{"role": "user", "content": "hello"}],
        tools=[],
        model_name="claude-sonnet-5",
    ):
        pass

    get_conversation.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_response_stream_with_tools_looks_up_conversation_when_attachments_present(
    monkeypatch,
):
    conversation = type("C", (), {"user_id": "u1"})()
    get_conversation = AsyncMock(return_value=conversation)
    monkeypatch.setattr(
        chat_llm_service.ChatRepository, "get_conversation", get_conversation
    )
    _install_fake_anthropic(monkeypatch)

    async def fake_resolve(messages, *, model, owner_user_id):
        assert owner_user_id == "u1"
        return AttachmentPlan(by_index={}, notices=[])

    monkeypatch.setattr(chat_llm_service, "resolve_attachments", fake_resolve)

    service = chat_llm_service.ChatLLMService()
    async for _ in service.generate_response_stream_with_tools(
        conversation_id="c1",
        message_id="m1",
        conversation_messages=[
            {"role": "user", "content": "봐줘", "attachments": [{"name": "a.png"}]}
        ],
        tools=[],
        model_name="claude-sonnet-5",
    ):
        pass

    get_conversation.assert_awaited_once_with("c1")


@pytest.mark.asyncio
async def test_generate_response_stream_with_tool_search_skips_conversation_lookup_without_attachments(
    monkeypatch,
):
    get_conversation = AsyncMock(return_value=None)
    monkeypatch.setattr(
        chat_llm_service.ChatRepository, "get_conversation", get_conversation
    )
    _install_fake_anthropic(monkeypatch)

    service = chat_llm_service.ChatLLMService()
    async for _ in service.generate_response_stream_with_tool_search(
        conversation_id="c1",
        message_id="m1",
        conversation_messages=[{"role": "user", "content": "hello"}],
        core_tools=[],
        search_handler=object(),
        model_name="claude-sonnet-5",
    ):
        pass

    get_conversation.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_response_stream_with_tool_search_looks_up_conversation_when_attachments_present(
    monkeypatch,
):
    conversation = type("C", (), {"user_id": "u1"})()
    get_conversation = AsyncMock(return_value=conversation)
    monkeypatch.setattr(
        chat_llm_service.ChatRepository, "get_conversation", get_conversation
    )
    _install_fake_anthropic(monkeypatch)

    async def fake_resolve(messages, *, model, owner_user_id):
        assert owner_user_id == "u1"
        return AttachmentPlan(by_index={}, notices=[])

    monkeypatch.setattr(chat_llm_service, "resolve_attachments", fake_resolve)

    service = chat_llm_service.ChatLLMService()
    async for _ in service.generate_response_stream_with_tool_search(
        conversation_id="c1",
        message_id="m1",
        conversation_messages=[
            {"role": "user", "content": "봐줘", "attachments": [{"name": "a.png"}]}
        ],
        core_tools=[],
        search_handler=object(),
        model_name="claude-sonnet-5",
    ):
        pass

    get_conversation.assert_awaited_once_with("c1")

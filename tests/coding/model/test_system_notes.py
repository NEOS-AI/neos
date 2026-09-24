"""Turn-scoped system notes are appended, never edited (roadmap K2)."""

from __future__ import annotations

import pytest

from neos.coding.loop._durable.support import (
    _message_from_mapping,
    _message_to_mapping,
)
from neos.coding.model.anthropic import _to_anthropic_request
from neos.coding.model.base import (
    CanonicalMessage,
    ModelLimits,
    ModelRequest,
    SystemNoteContent,
    TextContent,
    ToolResultContent,
    ToolUseContent,
)
from neos.coding.model.gemini import _messages_to_gemini
from neos.coding.model.ollama import _message_to_ollama
from neos.coding.model.openai import _to_openai_request

CLEAR_AT_BETA = "mid-conversation-system-clear-at-2026-08-21"

TOOL_ROUND = (
    CanonicalMessage("user", (TextContent("Run the script"),)),
    CanonicalMessage(
        "assistant",
        (ToolUseContent("toolu_1", "execute.v1", {"argv": ["python", "a.py"]}),),
    ),
    CanonicalMessage("tool", (ToolResultContent("toolu_1", "ok", {"stdout": "done"}),)),
)
NOTE = CanonicalMessage("system", (SystemNoteContent("Check the output first."),))
NOTE_TEXT_BLOCK = {
    "role": "user",
    "content": [{"type": "text", "text": "Check the output first."}],
}


def _request(messages, *, model: str) -> ModelRequest:
    return ModelRequest(
        system="Work safely.",
        messages=tuple(messages),
        tools=(),
        model=model,
        limits=ModelLimits(max_output_tokens=100, timeout_sec=5),
        task_id="ct_1",
        run_id="cr_1",
        turn_id="turn_1",
    )


def test_system_role_holds_only_system_notes() -> None:
    CanonicalMessage("system", (SystemNoteContent("ok"),))

    with pytest.raises(ValueError):
        CanonicalMessage("system", (TextContent("plain text"),))
    with pytest.raises(ValueError):
        CanonicalMessage("user", (SystemNoteContent("misplaced"),))


def test_system_note_is_turn_scoped_by_default() -> None:
    assert SystemNoteContent("x").clear_at == "next_user_message"


def test_supported_model_gets_a_turn_scoped_system_message() -> None:
    payload = _to_anthropic_request(
        _request(TOOL_ROUND + (NOTE,), model="claude-fable-5-1")
    )

    assert payload["messages"][-1] == {
        "role": "system",
        "content": "Check the output first.",
        "clear_at": "next_user_message",
    }
    assert CLEAR_AT_BETA in payload["extra_headers"]["anthropic-beta"]


def test_unsupported_model_gets_the_note_as_text_after_tool_results() -> None:
    payload = _to_anthropic_request(
        _request(TOOL_ROUND + (NOTE,), model="claude-sonnet-5")
    )

    assert payload["messages"][-1] == NOTE_TEXT_BLOCK
    assert "extra_headers" not in payload


def test_note_directly_followed_by_a_user_message_degrades_to_text() -> None:
    later = CanonicalMessage("user", (TextContent("go on"),))

    payload = _to_anthropic_request(
        _request(TOOL_ROUND + (NOTE, later), model="claude-fable-5-1")
    )

    assert payload["messages"][3] == NOTE_TEXT_BLOCK


def test_note_followed_by_an_assistant_turn_stays_a_system_message() -> None:
    reply = CanonicalMessage("assistant", (TextContent("Output checked."),))

    payload = _to_anthropic_request(
        _request(TOOL_ROUND + (NOTE, reply), model="claude-fable-5-1")
    )

    assert payload["messages"][3]["role"] == "system"


def test_other_providers_render_the_note_as_user_text() -> None:
    openai_payload = _to_openai_request(
        _request(TOOL_ROUND + (NOTE,), model="gpt-6-sol")
    )

    assert openai_payload["messages"][-1] == {
        "role": "user",
        "content": "Check the output first.",
    }
    assert _message_to_ollama(NOTE) == [
        {"role": "user", "content": "Check the output first."}
    ]
    assert _messages_to_gemini((NOTE,)) == [
        {"role": "user", "parts": [{"text": "Check the output first."}]}
    ]


def test_transcript_mapping_round_trips_system_notes() -> None:
    assert _message_from_mapping(_message_to_mapping(NOTE)) == NOTE

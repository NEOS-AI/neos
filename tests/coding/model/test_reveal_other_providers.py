"""A reveal must not become an empty turn elsewhere (roadmap K2b).

Only a model with mid-conversation tool changes gets a reveal appended, but
the transcript is provider-agnostic and *persisted*: a checkpoint written
under Fable 5.1 can be resumed under a model without them. Those adapters
keep only `SystemNoteContent` from a system message, so a reveal-only message
renders with nothing in it -- an empty user turn, which providers reject.

Dropping the message is right rather than merely safe: those providers never
had a constant tool array to begin with, so they have nothing to announce.
"""

from __future__ import annotations

import pytest

from neos.coding.model.base import (
    CanonicalMessage,
    SystemNoteContent,
    ToolAdditionContent,
)
from neos.coding.model.gemini import _messages_to_gemini
from neos.coding.model.ollama import _message_to_ollama
from neos.coding.model.openai import _message_to_openai

pytestmark = pytest.mark.no_db

REVEAL = CanonicalMessage("system", (ToolAdditionContent("git_status.v1"),))
NOTE = CanonicalMessage("system", (SystemNoteContent("Check the output."),))


def test_openai_drops_a_reveal_instead_of_sending_an_empty_turn() -> None:
    assert _message_to_openai(REVEAL) == []


def test_ollama_drops_a_reveal_instead_of_sending_an_empty_turn() -> None:
    assert _message_to_ollama(REVEAL) == []


def test_gemini_drops_a_reveal_instead_of_sending_empty_parts() -> None:
    assert _messages_to_gemini((REVEAL,)) == []


def test_openai_still_renders_a_real_note() -> None:
    assert _message_to_openai(NOTE) == [
        {"role": "user", "content": "Check the output."}
    ]


def test_ollama_still_renders_a_real_note() -> None:
    assert _message_to_ollama(NOTE) == [
        {"role": "user", "content": "Check the output."}
    ]


def test_gemini_still_renders_a_real_note() -> None:
    assert _messages_to_gemini((NOTE,)) == [
        {"role": "user", "parts": [{"text": "Check the output."}]}
    ]

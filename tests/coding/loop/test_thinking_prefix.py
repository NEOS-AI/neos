"""The durable loop keeps the sent prefix byte-identical (roadmap K1, K7).

Claude Fable 5.1 binds each thinking block to the conversation prefix that
produced it. Any edit before a replayed block is a 400 on enforced accounts,
so the loop strips thinking once at the boundary where its prefix changed.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from neos.coding.loop import initial_state
from neos.coding.model.anthropic import _to_anthropic_request
from neos.coding.model.base import (
    CanonicalMessage,
    ModelCompleted,
    ModelUsage,
    TextContent,
    TextDelta,
    ThinkingCompleted,
    ThinkingContent,
    ToolResultContent,
    ToolUseContent,
)
from tests.coding.loop.support import INPUT, collect, completed, harness, tool_call

pytestmark = pytest.mark.no_db


def _has_thinking(transcript) -> bool:
    return any(
        isinstance(item, ThinkingContent)
        for message in transcript
        for item in message.content
    )


def _thinking_transcript() -> tuple[CanonicalMessage, ...]:
    return (
        CanonicalMessage("user", (TextContent("Fix it"),)),
        CanonicalMessage(
            "assistant",
            (
                ThinkingContent("", "sig-1"),
                ToolUseContent("toolu_1", "read_file.v1", {"path": "a.txt"}),
            ),
        ),
        CanonicalMessage("tool", (ToolResultContent("toolu_1", "ok", {"preview": "x"}),)),
    )


async def _run_until_model_turns_are_spent(h, *, limit: int = 8) -> None:
    checkpoint = None
    for _ in range(limit):
        if not h.model.turns:
            return
        await collect(h, checkpoint)
        checkpoint = h.repository.checkpoints[-1]


@pytest.mark.asyncio
async def test_consecutive_requests_share_a_byte_identical_prefix() -> None:
    h = harness(
        [
            [ThinkingCompleted("Plan: write a.txt", "sig-1"), tool_call(), completed()],
            [
                ThinkingCompleted("", "sig-2"),
                TextDelta("done"),
                ModelCompleted("end_turn", ModelUsage(5, 3)),
            ],
        ]
    )

    await _run_until_model_turns_are_spent(h)

    assert len(h.model.requests) == 2
    first = _to_anthropic_request(h.model.requests[0])
    second = _to_anthropic_request(h.model.requests[1])
    assert second["system"] == first["system"]
    assert second["tools"] == first["tools"]
    shared = len(first["messages"])
    assert json.dumps(second["messages"][:shared], sort_keys=True) == json.dumps(
        first["messages"], sort_keys=True
    )
    assert second["messages"][shared]["content"][0] == {
        "type": "thinking",
        "thinking": "Plan: write a.txt",
        "signature": "sig-1",
    }


def test_appending_keeps_earlier_thinking() -> None:
    h = harness([])
    state = replace(initial_state(INPUT), transcript=_thinking_transcript())

    sent = h.loop._guard_thinking_prefix(state, "code", ())
    appended = replace(
        sent,
        transcript=sent.transcript + (CanonicalMessage("user", (TextContent("more"),)),),
    )
    again = h.loop._guard_thinking_prefix(appended, "code", ())

    assert _has_thinking(again.transcript)


def test_editing_earlier_history_strips_thinking() -> None:
    h = harness([])
    state = replace(initial_state(INPUT), transcript=_thinking_transcript())

    sent = h.loop._guard_thinking_prefix(state, "code", ())
    edited = replace(
        sent,
        transcript=(
            CanonicalMessage("user", (TextContent("Prior transcript compacted."),)),
        )
        + sent.transcript[1:],
    )
    again = h.loop._guard_thinking_prefix(edited, "code", ())

    assert not _has_thinking(again.transcript)
    assert again.transcript_digest == h.loop._digest(again.transcript)


def test_changing_the_system_prompt_strips_thinking_once() -> None:
    h = harness([])
    state = replace(initial_state(INPUT), transcript=_thinking_transcript())

    sent = h.loop._guard_thinking_prefix(state, "code", ())
    changed = h.loop._guard_thinking_prefix(sent, "code, now with a summary", ())
    assert not _has_thinking(changed.transcript)

    fresh = replace(
        changed,
        transcript=changed.transcript
        + (
            CanonicalMessage(
                "assistant",
                (ThinkingContent("", "sig-2"), TextContent("done")),
            ),
        ),
    )
    kept = h.loop._guard_thinking_prefix(fresh, "code, now with a summary", ())
    assert _has_thinking(kept.transcript)

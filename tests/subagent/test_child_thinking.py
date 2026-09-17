"""A child replays its thinking, and drops it where it edits history (K1c).

The child's system prompt and tool set are fixed by its spec, so the only
prefix change it can make is its own compaction.
"""

from __future__ import annotations

import pytest

from neos.coding.model.base import (
    ModelCompleted,
    ModelUsage,
    TextDelta,
    ThinkingCompleted,
    ThinkingContent,
    ToolCallCompleted,
)
from neos.subagent.types import StepKind
from tests.subagent.test_runtime import FakeToolPort, _runtime, _ticket

pytestmark = pytest.mark.no_db


def _thinking_tool_turn(signature: str, call_id: str, path: str):
    return (
        ThinkingCompleted("Read the handler", signature),
        TextDelta("looking"),
        ToolCallCompleted(call_id, "read_file.v1", {"path": path}),
        ModelCompleted("tool_use", ModelUsage(4, 1)),
    )


def _report_turn():
    return (
        TextDelta("login.py handles POST /login"),
        ModelCompleted("end_turn", ModelUsage(3, 2)),
    )


def _replayed(request) -> list[ThinkingContent]:
    return [
        item
        for message in request.messages
        for item in message.content
        if isinstance(item, ThinkingContent)
    ]


async def _advance_until_done(runtime, *, limit: int = 8):
    outcome = await runtime.advance(_ticket())
    run_id = outcome.run_id
    for _ in range(limit):
        if outcome.kind is StepKind.COMPLETED:
            return outcome
        outcome = await runtime.advance(
            _ticket(run_id=run_id, expected_checkpoint_id=outcome.checkpoint_id)
        )
    return outcome


@pytest.mark.asyncio
async def test_child_replays_its_thinking_block_on_the_next_turn() -> None:
    runtime, _store, _tools, model, _events = _runtime(
        [_thinking_tool_turn("sig-child-1", "call_1", "login.py"), _report_turn()]
    )

    outcome = await _advance_until_done(runtime)

    assert outcome.kind is StepKind.COMPLETED
    assert _replayed(model.requests[0]) == []
    assert _replayed(model.requests[1]) == [
        ThinkingContent("Read the handler", "sig-child-1")
    ]


@pytest.mark.asyncio
async def test_child_drops_thinking_when_compaction_edits_the_transcript() -> None:
    runtime, _store, _tools, model, _events = _runtime(
        [
            _thinking_tool_turn("sig-child-1", "call_1", "login.py"),
            _thinking_tool_turn("sig-child-2", "call_2", "signup.py"),
            _report_turn(),
        ],
        tools=FakeToolPort(results={"read_file.v1": {"body": "x" * (40 * 1024)}}),
    )

    outcome = await _advance_until_done(runtime)

    assert outcome.kind is StepKind.COMPLETED
    # The second model turn still sees the first block: nothing was edited yet.
    assert _replayed(model.requests[1]) == [
        ThinkingContent("Read the handler", "sig-child-1")
    ]
    # Compaction rewrote the oversized tool results, so the blocks bound to the
    # old prefix are gone rather than replayed against an edited history.
    assert _replayed(model.requests[2]) == []

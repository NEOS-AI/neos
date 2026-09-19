"""Revealing a tool must not invalidate replayed thinking (roadmap K2b).

`search_tools.v1` surfaces a deferred tool, and today that *grows* the
`tools[]` array. A thinking block is bound to the tool set, so the guard sees
a changed prefix and strips every block -- the model loses the reasoning that
led it to search in the first place, at exactly the moment it was about to act
on the result.

Declaring every tool once and gating visibility with `defer_loading`, then
announcing the reveal with a `tool_addition` block, keeps the array constant.
The reveal becomes an append like any other, which is what R-01 asks for.

The assertions read the rendered payload rather than a new canonical type, so
each one fails for its own reason today instead of collapsing into a single
import error.
"""

from __future__ import annotations

import pytest

from neos.coding.loop.anthropic import AnthropicLoopConfig
from neos.coding.model.anthropic import _to_anthropic_request
from neos.coding.model.base import (
    ModelCompleted,
    ModelUsage,
    TextDelta,
    ThinkingCompleted,
    ToolCallCompleted,
)
from neos.coding.tools.executor import ToolResult
from tests.coding.loop.test_anthropic_loop import collect, harness

pytestmark = pytest.mark.no_db

# Deferred in the default registry, so revealing it is what changes `tools[]`.
REVEALED = "git_status.v1"


async def _search_result(session, call, **_kwargs):
    return ToolResult(
        status="ok",
        reason_code="ok",
        preview="1 tool",
        original_bytes=0,
        truncated=False,
        checksum="",
        workspace_revision="1",
        entries=(
            {
                "name": REVEALED,
                "description": "Show the working tree status",
                "input_schema": {"type": "object", "properties": {}},
            },
        ),
    )


def _revealing_harness():
    # A catalogued model: the reveal path is gated on the catalog, and
    # `claude-test` is not in it.
    config = AnthropicLoopConfig(model="claude-fable-5-1", system="code")
    h = harness(
        [
            [
                ThinkingCompleted("I need the git tools.", "sig-1"),
                ToolCallCompleted("st1", "search_tools.v1", {"query": "git status"}),
                ModelCompleted("tool_use", ModelUsage(5, 3)),
            ],
            [
                TextDelta("done"),
                ModelCompleted("end_turn", ModelUsage(5, 3)),
            ],
        ],
        config=config,
    )
    h.executor.execute = _search_result
    return h


async def _run_two_turns(h) -> None:
    checkpoint = None
    for _ in range(6):
        if not h.model.turns:
            return
        await collect(h, checkpoint)
        if not h.repository.checkpoints:
            return
        checkpoint = h.repository.checkpoints[-1]


def _tool_names(request) -> list[str]:
    return [tool.name for tool in request.tools]


@pytest.mark.asyncio
async def test_revealing_a_tool_keeps_the_tool_array_constant() -> None:
    h = _revealing_harness()

    await _run_two_turns(h)

    assert len(h.model.requests) >= 2
    assert _tool_names(h.model.requests[1]) == _tool_names(h.model.requests[0])


@pytest.mark.asyncio
async def test_revealing_a_tool_keeps_earlier_thinking() -> None:
    h = _revealing_harness()

    await _run_two_turns(h)

    replayed = [
        item
        for message in h.model.requests[1].messages
        for item in message.content
        if type(item).__name__ == "ThinkingContent"
    ]
    assert replayed, "the reveal stripped the thinking it was reasoning with"


@pytest.mark.asyncio
async def test_the_reveal_is_announced_instead_of_rewriting_the_tools() -> None:
    h = _revealing_harness()

    await _run_two_turns(h)

    payload = _to_anthropic_request(h.model.requests[1])
    deferred = [
        tool for tool in payload["tools"] if tool.get("defer_loading") is True
    ]
    assert deferred, "no tool is declared as deferred, so the array still churns"
    # Not a substring search: the revealed name already appears inside the
    # search tool's own result, so `REVEALED in str(messages)` is true even
    # when nothing was announced at all. Look for the block itself.
    announced = [
        block
        for message in payload["messages"]
        if isinstance(message.get("content"), list)
        for block in message["content"]
        if isinstance(block, dict) and block.get("type") == "tool_addition"
    ]
    assert [block["tool"]["name"] for block in announced] == [REVEALED], (
        "a deferred tool is hidden until it is announced, so without the "
        "block the reveal silently never happens"
    )

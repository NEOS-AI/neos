"""The checkpoint seam: a run's first state and its stored form, without a loop."""

import json
from dataclasses import replace

import pytest

from neos.coding.loop import encode_state, initial_state
from neos.coding.loop.base import LoopInput, WorkspaceEditContext
from neos.coding.model.base import CanonicalMessage, TextContent

pytestmark = pytest.mark.no_db

INPUT = LoopInput("ct_1", "cr_1", "Fix it")
EDITED = LoopInput(
    "ct_1",
    "cr_1",
    "Fix it",
    workspace_edits=(WorkspaceEditContext("cwe_1", "src/app.py", "13"),),
)


def _texts(state) -> list[str]:
    return [
        item.text
        for message in state.transcript
        for item in message.content
        if isinstance(item, TextContent)
    ]


def test_initial_state_starts_from_the_instruction() -> None:
    state = initial_state(INPUT)

    assert _texts(state) == ["Fix it"]
    assert state.transcript[0].role == "user"
    assert state.turn_count == 0
    assert state.tool_count == 0
    assert not state.has_pending_tool
    assert state.transcript_digest


def test_initial_state_carries_workspace_edits() -> None:
    texts = _texts(initial_state(EDITED))

    assert texts[0] == "Fix it"
    assert any("src/app.py @ revision 13" in text for text in texts[1:])


def test_encode_state_is_the_stored_json_form() -> None:
    encoded = encode_state(INPUT, initial_state(INPUT))

    assert json.loads(json.dumps(encoded)) == encoded
    assert encoded["current_instruction"] == "Fix it"
    assert encoded["transcript"][0]["role"] == "user"
    assert encoded["transcript"][0]["content"] == [{"type": "text", "text": "Fix it"}]


def test_encode_state_keeps_the_task_seed_when_the_input_is_a_command() -> None:
    command = LoopInput("ct_1", "cr_1", "/clear")

    encoded = encode_state(command, initial_state(INPUT))

    assert encoded["current_instruction"] == "Fix it"


def test_encode_state_changes_with_the_state() -> None:
    state = initial_state(INPUT)
    later = replace(
        state,
        transcript=state.transcript + (CanonicalMessage("user", (TextContent("more"),)),),
        turn_count=2,
    )

    encoded = encode_state(INPUT, later)

    assert encoded["turn_count"] == 2
    assert [m["content"][0]["text"] for m in encoded["transcript"]] == ["Fix it", "more"]



@pytest.mark.asyncio
async def test_starting_from_the_encoded_initial_state_matches_a_fresh_start() -> None:
    from tests.coding.loop.support import checkpoint_for, collect, completed, harness, tool_call

    fresh = harness([[tool_call(), completed()]])
    seeded = harness([[tool_call(), completed()]])

    await collect(fresh)
    await collect(seeded, checkpoint_for(initial_state(INPUT)))

    assert [c.loop_state for c in seeded.repository.checkpoints] == [
        c.loop_state for c in fresh.repository.checkpoints
    ]
    assert len(seeded.model.requests) == len(fresh.model.requests) == 1

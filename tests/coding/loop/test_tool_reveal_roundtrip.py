"""A reveal must survive a checkpoint (roadmap K2b).

`_message_from_mapping` is an elif chain ending in a bare `else` that builds a
`ToolResultContent`. Any content type without its own branch does not degrade
there -- it raises `KeyError: 'tool_call_id'`. So a task that revealed a tool
and then resumed would die on the way back in, and the durable loop resumes
from a checkpoint on every single step.

The reveal is also the one message that must not be lost silently: drop it and
the model is never offered the tool it just asked for, while the transcript
still claims the search succeeded.
"""

from __future__ import annotations

import pytest

from neos.coding.loop._durable.codec import (
    _message_from_mapping,
    _message_to_mapping,
)
from neos.coding.model.base import (
    CanonicalMessage,
    SystemNoteContent,
    ToolAdditionContent,
)

pytestmark = pytest.mark.no_db


def test_a_reveal_survives_the_checkpoint() -> None:
    message = CanonicalMessage("system", (ToolAdditionContent("git_status.v1"),))

    restored = _message_from_mapping(_message_to_mapping(message))

    assert restored == message


def test_several_reveals_keep_their_order() -> None:
    message = CanonicalMessage(
        "system",
        (
            ToolAdditionContent("git_status.v1"),
            ToolAdditionContent("git_diff.v1"),
        ),
    )

    restored = _message_from_mapping(_message_to_mapping(message))

    assert [item.name for item in restored.content] == [
        "git_status.v1",
        "git_diff.v1",
    ]


def test_a_note_still_round_trips_beside_the_new_branch() -> None:
    """The reveal branch must not shadow the note it sits next to."""
    message = CanonicalMessage("system", (SystemNoteContent("Check first."),))

    restored = _message_from_mapping(_message_to_mapping(message))

    assert restored == message

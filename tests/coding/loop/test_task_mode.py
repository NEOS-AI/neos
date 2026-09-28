"""K9: a task's mode decides whether an approval request can wait.

`interactive` (the Code UI, and every task before this) asks a person and
waits. `autonomous` has nobody to ask: REQUIRE_APPROVAL folds to DENY -- the
D-L1 fold that existed but never ran in production, because
`approval_unattended` was a runtime-wide setting nothing turned on.

The same policy, the same call, two modes. Real `evaluate_approval`.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from neos.coding.domain.approvals import evaluate_approval
from neos.coding.loop.base import LoopInput
from tests.coding.loop.test_anthropic_loop import (
    INPUT,
    completed,
    harness,
    tool_call,
)

pytestmark = pytest.mark.no_db


def _write_turn():
    # A workspace write: manual mode's static policy says REQUIRE_APPROVAL.
    return [
        [tool_call("w1", "write_file.v1", {"path": "a.py", "content": "x"}), completed()],
        [completed()],
    ]


async def _run(input: LoopInput):
    h = harness(_write_turn(), approval_evaluator=evaluate_approval)
    events = []
    try:
        async for event in h.loop.run(input, None, h.deps):
            events.append(event)
    except Exception as error:
        return h, events, error
    return h, events, None


@pytest.mark.asyncio
async def test_an_interactive_task_waits_for_a_person() -> None:
    _h, events, error = await _run(INPUT)

    assert error is None
    assert [e.type for e in events][-2:] == ["approval.requested", "task.status.changed"]
    assert events[-1].payload["status"] == "waiting_approval"
    assert not [e for e in events if e.type == "tool.denied"]


@pytest.mark.asyncio
async def test_an_autonomous_task_is_refused_instead_of_waiting_forever() -> None:
    """Mutation: drop `unattended=` from `_approval_gate_step` -> it parks."""
    _h, events, error = await _run(replace(INPUT, mode="autonomous"))

    assert error is None
    denied = [e for e in events if e.type == "tool.denied"]
    assert [e.payload.get("reason_code") for e in denied] == ["policy_approval_denied"]


def test_the_default_mode_is_interactive() -> None:
    """Every caller that does not say otherwise keeps today's behaviour."""
    from neos.api.models.coding_models import CreateCodingTaskRequest
    from neos.coding.domain.models import CodingTaskMode

    assert LoopInput("ct", "cr", "x").mode == "interactive"
    assert CreateCodingTaskRequest(prompt="x").mode == "interactive"
    assert CodingTaskMode.INTERACTIVE.value == "interactive"

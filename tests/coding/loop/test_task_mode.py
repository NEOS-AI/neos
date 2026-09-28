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


# ---- the autonomous overlay (P-01) -------------------------------------------------


def test_an_interactive_prompt_is_byte_identical() -> None:
    """Every task today is interactive; its system prompt must not move."""
    from neos.coding.loop._durable.model_turn import with_mode_overlay

    assert with_mode_overlay("BASE", "interactive") == "BASE"
    assert with_mode_overlay("BASE", "") == "BASE"


def test_an_autonomous_prompt_opens_with_the_official_blocks() -> None:
    """P-01: "Apply both", and the opening sentence carries the effect. P-02
    follows (autonomous only, 2026-09-28). Mutation: append instead of
    prepend, or drop any block."""
    from neos.coding.loop._durable.model_turn import with_mode_overlay
    from neos.coding.prompts.official import (
        AUTONOMOUS_EXECUTION,
        DELIVERING_WORK,
        SCOPE_OF_CHANGES,
    )

    system = with_mode_overlay("BASE", "autonomous")

    assert system.startswith("You are operating autonomously.")
    assert system == (
        f"{AUTONOMOUS_EXECUTION}\n\n{DELIVERING_WORK}\n\n{SCOPE_OF_CHANGES}\n\nBASE"
    )


def test_the_blocks_are_the_ones_in_the_spec_file() -> None:
    """§10.5: the spec file is fixed first, the code follows it. One character
    off fails -- the measured effect is attached to the wording."""
    from pathlib import Path

    from neos.coding.prompts.official import (
        AUTONOMOUS_EXECUTION,
        DELIVERING_WORK,
        SCOPE_OF_CHANGES,
    )

    spec = (
        Path(__file__).resolve().parents[3] / "docs/fable-5-1-multiagent-spec.md"
    ).read_text(encoding="utf-8")

    assert AUTONOMOUS_EXECUTION in spec
    assert DELIVERING_WORK in spec
    assert SCOPE_OF_CHANGES in spec


@pytest.mark.asyncio
async def test_the_model_sees_the_overlay_only_on_an_autonomous_task() -> None:
    """End to end through the loop. Mutation: drop `with_mode_overlay` from
    `_prepare_turn` -> the autonomous request's system has no P-01."""
    interactive, _events, _error = await _run(INPUT)
    autonomous, _events, _error = await _run(replace(INPUT, mode="autonomous"))

    [first_i, *_] = interactive.model.requests
    [first_a, *_] = autonomous.model.requests
    assert "operating autonomously" not in first_i.system
    assert first_a.system.startswith("You are operating autonomously.")

"""Q1 in the loop: a background task reads and never writes, and says why.

Background is unattended (nobody is watching -- REQUIRE_APPROVAL has nobody
to wait for) *and* capped at READ_ONLY. The refusal carries
`policy_mode_ceiling`, the name the Q5 fallback rule FB2 counts.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest

from neos.coding.domain.approvals import evaluate_approval
from neos.coding.loop.anthropic import AnthropicLoopConfig
from neos.coding.model.base import ModelCompleted, ModelUsage
from tests.coding.loop.test_anthropic_loop import (
    INPUT,
    completed,
    harness,
    tool_call,
)

pytestmark = pytest.mark.no_db

BACKGROUND = replace(INPUT, mode="background")


async def _run(turns, input=BACKGROUND, config=None):
    h = harness(turns, approval_evaluator=evaluate_approval, config=config)
    events = [event async for event in h.loop.run(input, None, h.deps)]
    return h, events


@pytest.mark.asyncio
async def test_a_background_write_is_refused_not_parked() -> None:
    """Unattended already folds REQUIRE_APPROVAL to DENY; the ceiling names it.

    Mutation: `policy_denial_reason` loses the ceiling -> the reason is generic.
    """
    h, events = await _run(
        [
            [tool_call("w1", "write_file.v1", {"path": "a.py", "content": "x"}), completed()],
            [completed()],
        ]
    )

    assert not [e for e in events if e.type == "approval.requested"]
    denied = [e for e in events if e.type == "tool.denied"]
    assert [e.payload.get("reason_code") for e in denied] == ["policy_mode_ceiling"]
    assert h.executor.calls == []


@pytest.mark.asyncio
async def test_an_operator_allow_list_does_not_lift_the_ceiling() -> None:
    """The case the ceiling exists for: the operator's policy says ALLOW, so the
    unattended fold never fires. Mutation: drop `read_only_ceiling=` from
    `_approval_gate_step` -> the write runs. (The write test above cannot see
    that mutation -- there the fold denies too.)"""
    config = AnthropicLoopConfig(
        model="claude-test",
        system="code",
        approval_allow_tools=frozenset({"write_file.v1"}),
    )
    h, events = await _run(
        [
            [tool_call("w1", "write_file.v1", {"path": "a.py", "content": "x"}), completed()],
            [completed()],
        ],
        config=config,
    )

    denied = [e for e in events if e.type == "tool.denied"]
    assert [e.payload.get("reason_code") for e in denied] == ["policy_mode_ceiling"]
    assert h.executor.calls == []


@pytest.mark.asyncio
async def test_a_background_read_runs() -> None:
    h, events = await _run(
        [
            [tool_call("r1", "read_file.v1", {"path": "a.py"}), completed()],
            [completed()],
        ]
    )

    assert not [e for e in events if e.type == "tool.denied"]
    assert [call.name for call in h.executor.calls] == ["read_file.v1"]


def test_every_task_mode_is_accepted_by_the_api_and_the_database() -> None:
    """By name: the enum, the request model and the latest CHECK agree."""
    from typing import get_args

    from neos.api.models.coding_models import CreateCodingTaskRequest
    from neos.coding.domain.models import CodingTaskMode

    modes = {mode.value for mode in CodingTaskMode}
    assert "background" in modes
    assert set(get_args(CreateCodingTaskRequest.model_fields["mode"].annotation)) == modes

    migrations = sorted(
        path
        for path in (Path(__file__).resolve().parents[3] / "db" / "migrations").glob("*.sql")
        if "coding_tasks_mode_check" in path.read_text(encoding="utf-8")
        or "CHECK (mode IN" in path.read_text(encoding="utf-8")
    )
    latest = migrations[-1].read_text(encoding="utf-8")
    checked = set(re.findall(r"'([a-z]+)'", latest.split("CHECK (mode IN", 1)[1].split(")")[0]))
    assert checked == modes


@pytest.mark.asyncio
async def test_a_background_phase_change_is_refused_not_parked() -> None:
    """`set_phase.v1` is READ_ONLY, so the ceiling lets it through -- but moving
    to implement needs approval, and nobody will give it. Background must be
    unattended too. Mutation: `_unattended` forgets background -> it parks."""
    h = harness(
        [
            [ModelCompleted("end_turn", ModelUsage(1, 1))],
            [tool_call("p1", "set_phase.v1", {"phase": "implement"}), completed()],
            [ModelCompleted("end_turn", ModelUsage(1, 1))],
        ],
        approval_evaluator=evaluate_approval,
    )
    [_ async for _ in h.loop.run(BACKGROUND, None, h.deps)]
    checkpoint = h.repository.checkpoints[-1]
    checkpoint.loop_state["phase"] = "plan"
    checkpoint.loop_state["terminal_pending"] = False
    checkpoint.loop_state["pending_instruction"] = "Look around"

    events = [event async for event in h.loop.run(BACKGROUND, checkpoint, h.deps)]

    assert not [e for e in events if e.type == "approval.requested"]
    denied = [e for e in events if e.type == "tool.denied"]
    assert [e.payload.get("reason_code") for e in denied] == ["policy_approval_denied"]

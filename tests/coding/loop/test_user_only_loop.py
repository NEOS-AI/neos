"""Q2 in the loop: a USER_ONLY call is refused with its own reason code.

The operator widened `command_allowlist` to `gh` -- the scenario the floor
exists for. The same call in both modes is refused, never parked for
approval, and the ledger says why (`policy_user_only`) so the Q5 fallback
rule FB1 can tell it from an ordinary policy denial. Real `evaluate_approval`.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from neos.coding.domain.approvals import evaluate_approval
from tests.coding.loop.test_anthropic_loop import (
    INPUT,
    completed,
    harness,
    tool_call,
)

pytestmark = pytest.mark.no_db


def _gh_auth_turn():
    return [
        [tool_call("g1", "execute.v1", {"argv": ["gh", "auth", "login"]}), completed()],
        [completed()],
    ]


async def _run(input):
    h = harness(
        _gh_auth_turn(),
        approval_evaluator=evaluate_approval,
        command_allowlist=frozenset({"gh"}),
    )
    events = [event async for event in h.loop.run(input, None, h.deps)]
    return h, events


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["interactive", "autonomous"])
async def test_user_only_is_refused_in_every_mode(mode: str) -> None:
    """Mutation: drop the floor check in `_evaluate_approval` -> interactive parks."""
    h, events = await _run(replace(INPUT, mode=mode))

    assert not [e for e in events if e.type == "approval.requested"]
    denied = [e for e in events if e.type == "tool.denied"]
    assert [e.payload.get("reason_code") for e in denied] == ["policy_user_only"]
    assert h.executor.calls == []

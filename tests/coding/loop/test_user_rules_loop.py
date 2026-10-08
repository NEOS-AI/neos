"""Q2 in the loop: the owner's rules are read at every step and never stored.

Real `evaluate_approval`. A rule added while the task runs applies from the
next step. A source that cannot be read fails the step retryably -- deciding
without the rules would silently drop the user's blocks.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from neos.coding.application.user_rules import InMemoryUserRuleStore
from neos.coding.domain.approvals import evaluate_approval
from neos.coding.loop._durable.state import CodingLoopFailure
from tests.coding.loop.support import INPUT, completed, harness, tool_call

pytestmark = pytest.mark.no_db

OWNED = replace(INPUT, owner_id="alice", mode="autonomous")


def _two_reads():
    return [
        [tool_call("r1", "read_file.v1", {"path": "a.py"}), completed()],
        [tool_call("r2", "read_file.v1", {"path": "b.py"}), completed()],
        [completed()],
    ]


def _loop(rules, turns=None, **kwargs):
    return harness(
        turns or _two_reads(),
        approval_evaluator=evaluate_approval,
        user_rules=rules,
        **kwargs,
    )


async def _step(h, input, checkpoint=None):
    return [event async for event in h.loop.run(input, checkpoint, h.deps)]


def _denied(events):
    return [e.payload.get("reason_code") for e in events if e.type == "tool.denied"]


@pytest.mark.asyncio
async def test_a_block_refuses_the_call_with_its_own_reason() -> None:
    rules = InMemoryUserRuleStore()
    await rules.create("alice", effect="block", tool="read_file.v1")
    h = _loop(rules)

    events = await _step(h, OWNED)

    assert _denied(events) == ["policy_user_rule_blocked"]
    assert h.executor.calls == []


@pytest.mark.asyncio
async def test_a_rule_added_mid_task_applies_from_the_next_step() -> None:
    rules = InMemoryUserRuleStore()
    h = _loop(rules)
    first = await _step(h, OWNED)
    assert _denied(first) == []

    await rules.create("alice", effect="block", tool="read_file.v1")
    second = await _step(h, OWNED, h.repository.checkpoints[-1])

    assert _denied(second) == ["policy_user_rule_blocked"]
    assert [call.name for call in h.executor.calls] == ["read_file.v1"]


@pytest.mark.asyncio
async def test_someone_elses_rules_do_not_apply() -> None:
    rules = InMemoryUserRuleStore()
    await rules.create("bob", effect="block", tool="read_file.v1")
    h = _loop(rules)

    assert _denied(await _step(h, OWNED)) == []


@pytest.mark.asyncio
async def test_rules_are_never_written_into_the_checkpoint() -> None:
    rules = InMemoryUserRuleStore()
    await rules.create("alice", effect="require", tool="write_file.v1")
    h = _loop(rules)

    await _step(h, OWNED)

    stored = h.repository.checkpoints[-1].loop_state
    assert "user_rules" not in stored
    assert "write_file.v1" not in str(stored)


@pytest.mark.asyncio
async def test_an_unreadable_source_fails_the_step_retryably() -> None:
    class Down:
        async def list_for_user(self, user_id):
            raise ConnectionError("db down")

    h = _loop(Down())

    with pytest.raises(CodingLoopFailure) as raised:
        await _step(h, OWNED)

    assert raised.value.code == "user_rules_unavailable"
    assert raised.value.retryable is True
    assert h.model.requests == []


@pytest.mark.asyncio
async def test_no_source_or_no_owner_reads_nothing() -> None:
    class Counting(InMemoryUserRuleStore):
        reads = 0

        async def list_for_user(self, user_id):
            Counting.reads += 1
            return await super().list_for_user(user_id)

    await _step(_loop(None), OWNED)
    await _step(_loop(Counting()), INPUT)

    assert Counting.reads == 0


@pytest.mark.asyncio
async def test_an_allow_lets_an_autonomous_run_execute_without_asking() -> None:
    rules = InMemoryUserRuleStore()
    await rules.create("alice", effect="allow", tool="execute.v1", argv_prefix=["git"])
    turns = [
        [tool_call("g1", "execute.v1", {"argv": ["git", "status"]}), completed()],
        [completed()],
    ]
    allowed = _loop(rules, turns)
    plain = _loop(InMemoryUserRuleStore(), [list(t) for t in turns])

    assert _denied(await _step(allowed, OWNED)) == []
    assert [c.name for c in allowed.executor.calls] == ["execute.v1"]
    assert _denied(await _step(plain, OWNED)) == ["policy_approval_denied"]

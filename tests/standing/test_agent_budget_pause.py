"""Q10b in the loop: an enforcing envelope pauses an agent task at the model-turn safe point.

The pause is the first thing a model turn does -- before detached children get
their step and before the model is called -- and it is one transaction: the
judgement (`budget.judged`, `enforced: true`) and `task.status.changed` to
`paused`. The run stays `running`; a person resumes the task. Off (`enforce`
False) the loop is the Q10a shadow, byte for byte.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from neos.coding.domain.durability import is_pause_event
from neos.coding.model.base import ModelCompleted, ModelUsage
from neos.standing.budget import (
    OVER_BACKGROUND_SHARE,
    AgentBudgetEnvelope,
    InMemoryAgentSpendSource,
)
from neos.standing.notifications import (
    KIND_BUDGET_WARNING,
    KIND_TASK_PAUSED,
    InMemoryNotificationStore,
    NotifyTarget,
    StandingNotifier,
)
from tests.coding.loop.test_anthropic_loop import INPUT, NOW, completed, harness, tool_call
from tests.coding.monitor.test_monitor_in_the_loop import LedgerEvents

pytestmark = pytest.mark.no_db

AGENT_INPUT = replace(INPUT, agent_id="sa_1", mode="background")


def _three_reads():
    return [
        [tool_call(f"r{i}", "read_file.v1", {"path": f"f{i}.py"}), completed()]
        for i in range(3)
    ] + [[ModelCompleted("end_turn", ModelUsage(1, 1))]]


def _envelope(spent_micros, *, limit=100, enforce=True, notifier=None, warn_ratio=0.8):
    source = InMemoryAgentSpendSource()
    source.record(
        "ct_0", agent_id="sa_1", mode="background", created_at=NOW, cost_micros=spent_micros
    )
    return AgentBudgetEnvelope(
        source,
        limit_micros=limit,
        background_share=0.5,
        enforce=enforce,
        warn_ratio=warn_ratio,
        notifier=notifier,
        clock=lambda: NOW,
    )


def _notifier(*, target=True):
    store = InMemoryNotificationStore({"sa_1": "user_1"})
    if target:
        store.targets["sa_1"] = NotifyTarget("slack", "C1")
    return store, StandingNotifier(store, max_body_chars=1_000, clock=lambda: NOW)


async def _run(envelope, *, input=AGENT_INPUT, steps=12):
    h = harness(_three_reads(), envelope=envelope)
    ledger = LedgerEvents()
    h.deps = type(h.deps)(repository=h.deps.repository, events=ledger, lease=h.deps.lease)
    yielded = []
    checkpoint = None
    for _ in range(steps):
        async for event in h.loop.run(input, checkpoint, h.deps):
            yielded.append(event)
        if any(is_pause_event(event) for event in yielded) or not h.model.turns:
            break
        checkpoint = h.repository.checkpoints[-1]
    return h, ledger, yielded


@pytest.mark.asyncio
async def test_over_the_envelope_the_task_pauses_before_the_model_is_called() -> None:
    h, ledger, yielded = await _run(_envelope(50))

    [judged, status] = h.repository.pause_events
    assert judged.type == "budget.judged"
    assert judged.payload["enforced"] is True
    assert judged.payload["would_pause"] is True
    assert judged.payload["reason"] == OVER_BACKGROUND_SHARE
    assert status.type == "task.status.changed"
    assert status.payload == {"status": "paused", "reason_code": OVER_BACKGROUND_SHARE}
    assert yielded == [status]
    assert h.repository.task_statuses["ct_1"] == "paused"
    # Nothing ran: no model call, no tool, and the shadow did not write a second judgement.
    assert len(h.model.turns) == 4
    assert h.executor.calls == []
    assert [e for e in ledger.items if e.type == "budget.judged"] == []


@pytest.mark.asyncio
async def test_the_run_is_left_running_so_a_resume_continues_it() -> None:
    h, _ledger, _yielded = await _run(_envelope(50))

    assert h.repository.active_run.status.value == "running"


@pytest.mark.asyncio
async def test_under_the_envelope_nothing_pauses() -> None:
    h, _ledger, yielded = await _run(_envelope(49))

    assert h.repository.pause_events == []
    assert not any(is_pause_event(event) for event in yielded)
    assert [call.name for call in h.executor.calls] == ["read_file.v1"] * 3
    assert not h.model.turns


@pytest.mark.asyncio
async def test_enforce_off_is_the_q10a_shadow() -> None:
    h, ledger, _yielded = await _run(_envelope(50, enforce=False))

    assert h.repository.pause_events == []
    [judged] = [e for e in ledger.items if e.type == "budget.judged"]
    assert judged.payload["enforced"] is False
    assert [call.name for call in h.executor.calls] == ["read_file.v1"] * 3


@pytest.mark.asyncio
async def test_a_human_task_is_never_paused() -> None:
    h, _ledger, _yielded = await _run(_envelope(10**9), input=INPUT)

    assert h.repository.pause_events == []
    assert not h.model.turns


@pytest.mark.asyncio
async def test_an_envelope_that_cannot_be_read_does_not_pause() -> None:
    """The next turn judges again -- a blip costs at most one turn."""

    class Broken(AgentBudgetEnvelope):
        async def judge(self, agent_id, mode):
            raise RuntimeError("db down")

    envelope = Broken(InMemoryAgentSpendSource(), limit_micros=0, background_share=0.5, enforce=True)
    h, _ledger, _yielded = await _run(envelope)

    assert h.repository.pause_events == []
    assert not h.model.turns


@pytest.mark.asyncio
async def test_the_pause_comes_before_detached_children_take_a_step() -> None:
    h = harness(_three_reads(), envelope=_envelope(50))
    h.deps = type(h.deps)(repository=h.deps.repository, events=LedgerEvents(), lease=h.deps.lease)
    stepped = []
    original = h.loop._advance_detached_children

    async def spy(state, bound, deps):
        stepped.append(True)
        return await original(state, bound, deps)

    h.loop._advance_detached_children = spy
    events = [event async for event in h.loop.run(AGENT_INPUT, None, h.deps)]

    assert any(is_pause_event(event) for event in events)
    assert stepped == []


@pytest.mark.asyncio
async def test_a_pause_is_told_to_the_owner_once() -> None:
    store, notifier = _notifier()
    h, _ledger, _yielded = await _run(_envelope(50, notifier=notifier))

    # 50 of 100 hits the background share (50) but not the 80% warning line.
    kinds = sorted(row["kind"] for row in store.rows.values())
    assert kinds == [KIND_TASK_PAUSED]
    [paused] = [row for row in store.rows.values() if row["kind"] == KIND_TASK_PAUSED]
    status = h.repository.pause_events[-1]
    assert paused["dedupe_key"] == f"task_paused:ct_1:{status.seq}"
    assert "ct_1" in paused["body"] and "resume" in paused["body"]
    assert paused["channel_type"] == "slack" and paused["channel_id"] == "C1"


@pytest.mark.asyncio
async def test_the_warning_goes_once_a_month_however_many_turns_cross_it() -> None:
    store, notifier = _notifier()
    # The warning reads the whole envelope: 85 >= 200 x 0.4, while the background
    # share (100) is not yet spent -- so every turn runs and judges.
    envelope = _envelope(85, limit=200, notifier=notifier, warn_ratio=0.4)
    h, _ledger, _yielded = await _run(envelope)

    warnings = [row for row in store.rows.values() if row["kind"] == KIND_BUDGET_WARNING]
    assert len(warnings) == 1
    assert warnings[0]["dedupe_key"] == "budget_warning:2026-07"
    assert h.repository.pause_events == []  # 85 < 100 (the background share): still running
    assert not h.model.turns  # every turn judged, one warning


@pytest.mark.asyncio
async def test_no_target_no_notice_and_the_pause_still_happens() -> None:
    store, notifier = _notifier(target=False)
    h, _ledger, _yielded = await _run(_envelope(50, notifier=notifier))

    assert store.rows == {}
    assert h.repository.task_statuses["ct_1"] == "paused"


@pytest.mark.asyncio
async def test_a_failing_notice_does_not_change_the_pause() -> None:
    class Exploding(InMemoryNotificationStore):
        async def enqueue(self, notice, *, now):
            raise RuntimeError("db down")

    notifier = StandingNotifier(Exploding({"sa_1": "user_1"}), max_body_chars=500)
    h, _ledger, _yielded = await _run(_envelope(50, notifier=notifier))

    assert h.repository.task_statuses["ct_1"] == "paused"


@pytest.mark.asyncio
async def test_the_shadow_also_warns_when_notices_are_on() -> None:
    store, notifier = _notifier()
    _h, _ledger, _yielded = await _run(_envelope(85, limit=200, enforce=False, notifier=notifier, warn_ratio=0.4))

    assert [row["kind"] for row in store.rows.values()] == [KIND_BUDGET_WARNING]

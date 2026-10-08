"""Q5b in the loop: an enforcing trajectory monitor pauses the task at the model-turn safe point.

Same path as the envelope (Q10b): the pause is the first thing a model turn does
-- before detached children get their step and before the model is called -- and
it is one `pause_task` transaction: the judgement (`monitor.judged`,
`enforced: true`) and `task.status.changed` to `paused`. Jev and the fallback
rules lift together. Off (`enforce` False) the loop is the Q5 shadow, byte for
byte. Unlike the envelope, the monitor watches every task, not only agent tasks.

docs/Q5B_MONITOR_PAUSE_DESIGN_261002.md
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from neos.coding.domain.durability import is_pause_event
from neos.coding.model.base import ModelCompleted, ModelUsage
from neos.coding.monitor.monitor import TrajectoryMonitor, pause_reason_code
from neos.coding.monitor.rules import RULESET_VERSION, FallbackThresholds
from neos.jev.gate import RiskScore
from neos.standing.budget import AgentBudgetEnvelope, InMemoryAgentSpendSource
from tests.coding.loop.support import INPUT, NOW, completed, harness, tool_call
from tests.coding.monitor.test_monitor_in_the_loop import LedgerEvents

pytestmark = pytest.mark.no_db

AGENT_INPUT = replace(INPUT, agent_id="sa_1", mode="background")
LIMITS = FallbackThresholds(1, 2, 10, 3, 3, 1, 4.0, 5)


class Scorer:
    def __init__(self, probability=0.2, error=None):
        self.probability = probability
        self.error = error
        self.calls = 0

    async def score_tool_risk(self, state):
        self.calls += 1
        if self.error:
            raise self.error
        return RiskScore(probability=self.probability, model="jev-1.13.0", rubric_digest="abc")


def _monitor(scorer, *, enforce=True, every_n=2):
    return TrajectoryMonitor(
        scorer=scorer,
        pause_at_or_above=0.8,
        limits=LIMITS,
        every_n_tool_results=every_n,
        enforce=enforce,
    )


def _reads(paths):
    return [
        [tool_call(f"r{i}", "read_file.v1", {"path": path}), completed()]
        for i, path in enumerate(paths)
    ] + [[ModelCompleted("end_turn", ModelUsage(1, 1))]]


async def _run(monitor, *, input=INPUT, envelope=None, paths=("a.py", "b.py", "c.py"), steps=12):
    """Drive the durable loop step by step; stop at a pause or when the model is done."""
    h = harness(_reads(paths), monitor=monitor, envelope=envelope)
    ledger = LedgerEvents()
    h.deps = type(h.deps)(repository=h.deps.repository, events=ledger, lease=h.deps.lease)
    checkpoint = None
    for _ in range(steps):
        async for event in h.loop.run(input, checkpoint, h.deps):
            ledger.yielded.append(event)
        if any(is_pause_event(e) for e in ledger.yielded) or not h.model.turns:
            break
        checkpoint = h.repository.checkpoints[-1]
    return h, ledger


def _judged(ledger):
    return [e for e in ledger.items if e.type == "monitor.judged"]


@pytest.mark.asyncio
async def test_a_jev_verdict_over_the_line_pauses_the_task_before_the_model_is_called() -> None:
    scorer = Scorer(probability=0.9)
    h, ledger = await _run(_monitor(scorer))

    [judged, status] = h.repository.pause_events
    assert judged.type == "monitor.judged"
    assert judged.payload["judge"] == "jev"
    assert judged.payload["enforced"] is True
    assert judged.payload["would_pause"] is True
    assert judged.payload["pause_at_or_above"] == 0.8
    assert judged.payload["rubric_digest"] == "abc"
    assert judged.payload["tool_results"] == 2
    assert status.payload == {"status": "paused", "reason_code": "monitor_jev"}
    assert [e for e in ledger.yielded if is_pause_event(e)] == [status]
    assert h.repository.task_statuses["ct_1"] == "paused"
    # Two reads ran, then the pause turn called neither the model nor a tool;
    # the judgement lives in the pause transaction, not as a second shadow event.
    assert [call.name for call in h.executor.calls] == ["read_file.v1"] * 2
    assert len(h.model.turns) == 2
    assert _judged(ledger) == []


@pytest.mark.asyncio
async def test_the_run_is_left_running_so_a_resume_continues_it() -> None:
    h, _ledger = await _run(_monitor(Scorer(probability=0.9)))

    assert h.repository.active_run.status.value == "running"


@pytest.mark.asyncio
async def test_the_fallback_rules_pause_too_when_jev_cannot_answer() -> None:
    """One flag lifts both (§6.1). FB4: the same read three times, with Jev down."""
    scorer = Scorer(error=TimeoutError("jev slow"))
    h, _ledger = await _run(
        _monitor(scorer, every_n=3), paths=("same.py", "same.py", "same.py")
    )

    [judged, status] = h.repository.pause_events
    assert judged.payload["judge"] == "fallback_rules"
    assert judged.payload["jev_unavailable"] is True
    assert judged.payload["jev_reason"] == "TimeoutError"
    assert judged.payload["ruleset"] == RULESET_VERSION
    assert (judged.payload["rule"], judged.payload["threshold"]) == ("FB4", 3)
    assert judged.payload["enforced"] is True
    assert status.payload == {"status": "paused", "reason_code": "monitor_fallback_fb4"}


@pytest.mark.asyncio
async def test_a_verdict_under_the_line_is_recorded_once_and_the_task_runs_on() -> None:
    h, ledger = await _run(_monitor(Scorer(probability=0.2)))

    assert h.repository.pause_events == []
    [judged] = _judged(ledger)
    assert judged.payload["enforced"] is True
    assert judged.payload["would_pause"] is False
    assert [call.name for call in h.executor.calls] == ["read_file.v1"] * 3
    assert not h.model.turns


@pytest.mark.asyncio
async def test_enforce_off_is_the_q5_shadow_byte_for_byte() -> None:
    """Off, a would-pause verdict is a shadow event and nothing stops."""
    h, ledger = await _run(_monitor(Scorer(probability=0.9), enforce=False))

    assert h.repository.pause_events == []
    [judged] = _judged(ledger)
    assert judged.payload == {
        "tool_results": 2,
        "mode": "interactive",
        "enforced": False,
        "judge": "jev",
        "probability": 0.9,
        "pause_at_or_above": 0.8,
        "would_pause": True,
        "rubric_digest": "abc",
        "model": "jev-1.13.0",
    }
    assert list(judged.payload) == [
        "tool_results", "mode", "enforced", "judge", "probability",
        "pause_at_or_above", "would_pause", "rubric_digest", "model",
    ]
    assert [call.name for call in h.executor.calls] == ["read_file.v1"] * 3


@pytest.mark.asyncio
async def test_enforce_off_judges_after_the_children_step_as_before() -> None:
    """The shadow keeps its old place (after detached children) -- off moves nothing."""
    order = []
    h = harness(_reads(["a.py", "b.py", "c.py"]), monitor=_monitor(Scorer(), enforce=False, every_n=1))
    ledger = LedgerEvents()
    h.deps = type(h.deps)(repository=h.deps.repository, events=ledger, lease=h.deps.lease)
    children, judge = h.loop._advance_detached_children, h.loop._monitor.judge

    async def spy_children(state, bound, deps):
        order.append("children")
        return await children(state, bound, deps)

    async def spy_judge(events, *, mode):
        order.append("judge")
        return await judge(events, mode=mode)

    h.loop._advance_detached_children = spy_children
    h.loop._monitor.judge = spy_judge
    checkpoint = None
    for _ in range(3):
        async for event in h.loop.run(INPUT, checkpoint, h.deps):
            ledger.yielded.append(event)
        checkpoint = h.repository.checkpoints[-1]

    assert order[:3] == ["children", "children", "judge"]


@pytest.mark.asyncio
async def test_the_monitor_pauses_a_human_task_too() -> None:
    """Not only agent tasks: the run is the monitor's concern, whoever opened it."""
    h, _ledger = await _run(_monitor(Scorer(probability=0.9)), input=INPUT)

    assert INPUT.agent_id is None
    assert h.repository.task_statuses["ct_1"] == "paused"


@pytest.mark.asyncio
async def test_the_pause_comes_before_detached_children_take_a_step() -> None:
    h = harness(_reads(["a.py", "b.py", "c.py"]), monitor=_monitor(Scorer(probability=0.9)))
    ledger = LedgerEvents()
    h.deps = type(h.deps)(repository=h.deps.repository, events=ledger, lease=h.deps.lease)
    stepped = []
    original = h.loop._advance_detached_children

    async def spy(state, bound, deps):
        stepped.append(True)
        return await original(state, bound, deps)

    h.loop._advance_detached_children = spy
    checkpoint = None
    for _ in range(12):
        stepped.clear()
        async for event in h.loop.run(INPUT, checkpoint, h.deps):
            ledger.yielded.append(event)
        if any(is_pause_event(e) for e in ledger.yielded):
            break
        checkpoint = h.repository.checkpoints[-1]

    assert h.repository.task_statuses["ct_1"] == "paused"
    assert stepped == []  # the pausing step gave no child a step


@pytest.mark.asyncio
async def test_a_broken_monitor_does_not_pause() -> None:
    """A monitor fault is not a verdict. (A Jev fault is -- the fallback rules judge.)"""

    class Broken(TrajectoryMonitor):
        def due(self, events):
            raise RuntimeError("monitor bug")

    monitor = Broken(
        scorer=Scorer(probability=0.9),
        pause_at_or_above=0.8,
        limits=LIMITS,
        every_n_tool_results=1,
        enforce=True,
    )
    h, _ledger = await _run(monitor)

    assert h.repository.pause_events == []
    assert [call.name for call in h.executor.calls] == ["read_file.v1"] * 3


@pytest.mark.asyncio
async def test_an_unreadable_sink_is_never_judged_or_paused() -> None:
    from tests.coding.loop.support import Events

    scorer = Scorer(probability=0.9)
    h = harness(_reads(["a.py", "b.py", "c.py"]), monitor=_monitor(scorer, every_n=1))
    h.deps = type(h.deps)(repository=h.deps.repository, events=Events(), lease=h.deps.lease)
    checkpoint = None
    for _ in range(8):
        async for _event in h.loop.run(INPUT, checkpoint, h.deps):
            pass
        if not h.model.turns:
            break
        checkpoint = h.repository.checkpoints[-1]

    assert scorer.calls == 0
    assert h.repository.pause_events == []


@pytest.mark.asyncio
async def test_when_both_want_to_pause_one_turn_there_is_one_pause_and_it_is_the_envelopes() -> None:
    """MP4: the envelope goes first. The envelope crosses on the very turn the monitor
    is due with a would-pause verdict: one transaction, the envelope's, and the
    monitor does not judge the turn the envelope paused."""
    source = InMemoryAgentSpendSource()
    source.record("ct_0", agent_id="sa_1", mode="background", created_at=NOW, cost_micros=0)
    envelope = AgentBudgetEnvelope(
        source, limit_micros=100, background_share=0.5, enforce=True, clock=lambda: NOW
    )
    scorer = Scorer(probability=0.9)
    h = harness(_reads(["a.py", "b.py", "c.py"]), monitor=_monitor(scorer), envelope=envelope)
    ledger = LedgerEvents()
    h.deps = type(h.deps)(repository=h.deps.repository, events=ledger, lease=h.deps.lease)
    pause_calls = []
    original = h.repository.pause_task

    async def counting(**kwargs):
        pause_calls.append(kwargs["judgement_type"])
        return await original(**kwargs)

    h.repository.pause_task = counting
    checkpoint = None
    for _ in range(12):
        if len(h.executor.calls) == 2:
            # The monitor is due on the next turn -- and now the envelope is over too.
            source.record(
                "ct_9", agent_id="sa_1", mode="background", created_at=NOW, cost_micros=50
            )
        async for event in h.loop.run(AGENT_INPUT, checkpoint, h.deps):
            ledger.yielded.append(event)
        if any(is_pause_event(e) for e in ledger.yielded):
            break
        checkpoint = h.repository.checkpoints[-1]

    assert pause_calls == ["budget.judged"]
    assert scorer.calls == 0
    assert _judged(ledger) == []


def test_reason_codes_name_the_judge_and_the_rule() -> None:
    assert pause_reason_code({"judge": "jev"}) == "monitor_jev"
    assert pause_reason_code({"judge": "fallback_rules", "rule": "FB1"}) == "monitor_fallback_fb1"


def test_the_cadence_survives_a_pause() -> None:
    """The pause's own `monitor.judged` remembers `tool_results` -- after a resume the
    monitor waits for N more results instead of pausing again on the same evidence."""
    from neos.coding.domain.events import make_event

    monitor = _monitor(Scorer(), every_n=2)

    def ev(seq, kind, payload=None):
        return make_event(task_id="ct_1", seq=seq, event_type=kind, payload=payload or {}, now=NOW)

    before = [ev(1, "tool.completed"), ev(2, "tool.completed")]
    paused = before + [ev(3, "monitor.judged", {"tool_results": 2, "would_pause": True})]

    assert monitor.due(before)
    assert not monitor.due(paused)
    assert not monitor.due(paused + [ev(4, "tool.completed")])
    assert monitor.due(paused + [ev(4, "tool.completed"), ev(5, "tool.completed")])


@pytest.mark.asyncio
async def test_under_enforce_the_shadow_place_does_not_judge_the_turn_again() -> None:
    """Like Q10b P9: on, the pause point owns the turn. A pause point that faulted
    must not be retried by the shadow place -- one judgement attempt per turn."""

    class Faulty(TrajectoryMonitor):
        attempts_this_step = 0

        async def judge(self, events, *, mode):
            Faulty.attempts_this_step += 1
            raise RuntimeError("monitor bug")

    monitor = Faulty(
        scorer=Scorer(probability=0.9),
        pause_at_or_above=0.8,
        limits=LIMITS,
        every_n_tool_results=1,
        enforce=True,
    )
    h = harness(_reads(["a.py", "b.py", "c.py"]), monitor=monitor)
    ledger = LedgerEvents()
    h.deps = type(h.deps)(repository=h.deps.repository, events=ledger, lease=h.deps.lease)
    per_step = []
    checkpoint = None
    for _ in range(12):
        Faulty.attempts_this_step = 0
        async for event in h.loop.run(INPUT, checkpoint, h.deps):
            ledger.yielded.append(event)
        per_step.append(Faulty.attempts_this_step)
        if not h.model.turns:
            break
        checkpoint = h.repository.checkpoints[-1]

    assert max(per_step) == 1
    assert h.repository.pause_events == []

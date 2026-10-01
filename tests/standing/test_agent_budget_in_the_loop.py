"""Q10a in the loop: the envelope judges at the model-turn safe point, in shadow.

Only agent tasks are judged. Over the envelope, the run gets one
`budget.judged` -- not one per turn -- and nothing else changes: the tools
still run and the run still ends on its own. A crashing envelope must not
change the run either.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from neos.coding.model.base import ModelCompleted, ModelUsage
from neos.standing.budget import (
    OVER_BACKGROUND_SHARE,
    AgentBudgetEnvelope,
    InMemoryAgentSpendSource,
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


def _envelope(spent_micros, *, limit=100, mode="background"):
    source = InMemoryAgentSpendSource()
    source.record("ct_0", agent_id="sa_1", mode=mode, created_at=NOW, cost_micros=spent_micros)
    return AgentBudgetEnvelope(source, limit_micros=limit, background_share=0.5, clock=lambda: NOW)


async def _run(envelope, *, input=AGENT_INPUT, events=None):
    """Drive the durable loop step by step (one model turn XOR one tool per call)."""
    h = harness(_three_reads(), envelope=envelope)
    ledger = events if events is not None else LedgerEvents()
    h.deps = type(h.deps)(repository=h.deps.repository, events=ledger, lease=h.deps.lease)
    checkpoint = None
    for _ in range(12):
        async for event in h.loop.run(input, checkpoint, h.deps):
            if hasattr(ledger, "yielded"):
                ledger.yielded.append(event)
        if not h.model.turns:
            break
        checkpoint = h.repository.checkpoints[-1]
    return h, ledger


def _judged(ledger):
    return [e for e in ledger.items if e.type == "budget.judged"]


@pytest.mark.asyncio
async def test_an_agent_task_over_its_envelope_is_marked_once_and_keeps_running() -> None:
    h, ledger = await _run(_envelope(50))

    [judged] = _judged(ledger)
    assert judged.run_id == "cr_1"
    assert judged.payload["would_pause"] is True
    assert judged.payload["reason"] == OVER_BACKGROUND_SHARE
    assert judged.payload["enforced"] is False
    assert judged.payload["mode"] == "background"
    assert [call.name for call in h.executor.calls] == ["read_file.v1"] * 3
    assert not h.model.turns


@pytest.mark.asyncio
async def test_a_new_run_is_marked_again() -> None:
    """One per run, not one per task: a retried run says so again."""
    ledger = LedgerEvents()
    await _run(_envelope(50), events=ledger)
    await _run(_envelope(50), input=replace(AGENT_INPUT, run_id="cr_2"), events=ledger)

    assert [e.run_id for e in _judged(ledger)] == ["cr_1", "cr_2"]


@pytest.mark.asyncio
async def test_under_the_envelope_leaves_no_mark() -> None:
    _h, ledger = await _run(_envelope(49))

    assert _judged(ledger) == []


@pytest.mark.asyncio
async def test_handed_over_work_is_judged_by_the_whole_envelope() -> None:
    _h, ledger = await _run(_envelope(50), input=replace(AGENT_INPUT, mode="autonomous"))

    assert _judged(ledger) == []


@pytest.mark.asyncio
async def test_a_human_task_is_never_judged() -> None:
    class Counting(AgentBudgetEnvelope):
        calls = 0

        async def judge(self, agent_id, mode):
            Counting.calls += 1
            return await super().judge(agent_id, mode)

    envelope = Counting(InMemoryAgentSpendSource(), limit_micros=0, background_share=0.5)
    _h, ledger = await _run(envelope, input=INPUT)

    assert Counting.calls == 0
    assert _judged(ledger) == []


@pytest.mark.asyncio
async def test_no_envelope_no_judgement() -> None:
    _h, ledger = await _run(None)

    assert _judged(ledger) == []


@pytest.mark.asyncio
async def test_a_sink_that_cannot_be_read_is_not_judged() -> None:
    """Without `list_after` the once-per-run guard cannot hold -- stay out."""
    from tests.coding.loop.test_anthropic_loop import Events

    events = Events()
    await _run(_envelope(10**9), events=events)

    assert _judged(events) == []


@pytest.mark.asyncio
async def test_a_broken_envelope_does_not_change_the_run() -> None:
    class Broken:
        async def judge(self, agent_id, mode):
            raise RuntimeError("db down")

    h, ledger = await _run(Broken())

    assert [call.name for call in h.executor.calls] == ["read_file.v1"] * 3
    assert _judged(ledger) == []


class _Recording:
    """A loop that only remembers what it was handed."""

    def __init__(self):
        self.inputs = []

    async def run(self, input, checkpoint, deps):
        self.inputs.append(input)
        yield await deps.events.append(
            task_id=input.task_id,
            event_type="run.completed",
            payload={"status": "completed"},
            run_id=input.run_id,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("by_agent", [True, False])
async def test_the_run_service_hands_the_loop_the_tasks_agent(by_agent) -> None:
    """The safe point can only judge what the run service passes in."""
    from neos.coding.application.run_service import CodingRunService, InProcessRunInterrupter
    from neos.coding.application.task_service import (
        CodingTaskService,
        InMemoryCodingTaskRepository,
    )
    from neos.coding.events.store import InMemoryCodingEventStore
    from neos.standing.store import InMemoryStandingAgentStore
    from neos.standing.tasks import open_agent_task
    from tests.coding.fakes import InMemoryCodingRunRepository

    tasks, events = InMemoryCodingTaskRepository(), InMemoryCodingEventStore()
    coding = CodingTaskService(tasks, events)
    agents = InMemoryStandingAgentStore()
    agent = await agents.create("alice", "Dot")
    task = (
        await open_agent_task(agents, coding, owner_id="alice", prompt="p")
        if by_agent
        else await coding.create_task(owner_id="alice", prompt="p")
    )
    loop = _Recording()
    runs = CodingRunService(
        tasks=tasks,
        runs=InMemoryCodingRunRepository(task_prompts={task.task_id: "p"}),
        events=events,
        interrupter=InProcessRunInterrupter(),
        loop=loop,
        on_completed=None,
    )
    await runs.ensure_started(task_id=task.task_id)

    await runs.advance_one_safe_point(task_id=task.task_id, worker_id="w1")

    [handed] = loop.inputs
    assert handed.agent_id == (agent.agent_id if by_agent else None)
    assert handed.mode == ("background" if by_agent else "interactive")

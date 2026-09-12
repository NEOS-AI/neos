from __future__ import annotations

import asyncio

import pytest

from neos.coding.model.base import ModelCompleted, ModelUsage, TextDelta, ToolCallCompleted
from neos.subagent.catalog import SpecRegistry
from neos.subagent.memory import CrashAfterInsert, InMemorySubagentStore
from neos.subagent.ports import SystemClock
from neos.subagent.runtime import SubagentRuntime
from neos.subagent.stepper import ChildStepper
from neos.subagent.types import (
    ModelPin,
    ParentBriefing,
    ParentKind,
    StepKind,
    SubagentStatus,
    SubagentTicket,
)


pytestmark = pytest.mark.no_db


class ScriptedCodingModel:
    def __init__(self, script) -> None:
        self.script = [tuple(turn) for turn in script]
        self.requests = []

    async def stream(self, request):
        self.requests.append(request)
        for event in self.script.pop(0):
            yield event


class FakeToolPort:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def definitions(self):
        return ("read_file.v1",)

    async def execute(self, name: str, input):
        self.calls.append((name, dict(input)))
        return {"ok": True, "path": input.get("path", "")}


class NullSink:
    async def emit(self, event_type: str, payload) -> None:
        return None


def _ticket(**overrides) -> SubagentTicket:
    payload = {
        "parent_kind": ParentKind.CODING,
        "parent_id": "ct_cas",
        "parent_run_id": "cr_cas",
        "parent_tool_call_id": "toolu_cas",
        "spec": "explore",
        "briefing": ParentBriefing(goal="cas"),
        "model": ModelPin(provider="anthropic", model="claude-test"),
    }
    payload.update(overrides)
    return SubagentTicket(**payload)


def _runtime(store, script):
    model = ScriptedCodingModel(script)
    tools = FakeToolPort()
    runtime = SubagentRuntime(
        store=store,
        catalog=SpecRegistry(),
        stepper=ChildStepper(model=model, tools=tools),
        events=NullSink(),
        clock=SystemClock(),
    )
    return runtime, model, tools


def _text(text: str = "done"):
    return (TextDelta(text), ModelCompleted("end_turn", ModelUsage(1, 1)))


def _tool():
    return (
        TextDelta("look"),
        ToolCallCompleted("c1", "read_file.v1", {"path": "a.py"}),
        ModelCompleted("tool_use", ModelUsage(1, 1)),
    )


@pytest.mark.asyncio
async def test_crash_after_insert_then_advance_none_finishes_seq_one() -> None:
    store = InMemorySubagentStore()
    store.crash_after_insert = True
    runtime, model, _tools = _runtime(store, [_text("recovered")])
    with pytest.raises(CrashAfterInsert):
        await runtime.advance(_ticket())
    store.crash_after_insert = False
    outcome = await runtime.advance(_ticket(expected_checkpoint_id=None))
    run = await store.get(outcome.run_id)
    assert run.latest_seq == 1
    assert outcome.kind is StepKind.COMPLETED
    assert len(model.requests) == 1


@pytest.mark.asyncio
async def test_crash_after_insert_with_placeholder_expected_does_not_create_seq_two() -> None:
    store = InMemorySubagentStore()
    store.crash_after_insert = True
    runtime, _model, _tools = _runtime(store, [_text("takeover")])
    with pytest.raises(CrashAfterInsert):
        await runtime.advance(_ticket())
    created = next(iter(store._runs.values()))
    placeholder_id = created.latest_checkpoint_id
    assert created.latest_seq == 1
    store.crash_after_insert = False
    outcome = await runtime.advance(
        _ticket(run_id=created.run_id, expected_checkpoint_id=placeholder_id)
    )
    run = await store.get(created.run_id)
    assert run.latest_seq == 1
    assert outcome.checkpoint_id == placeholder_id
    assert outcome.kind is StepKind.COMPLETED


@pytest.mark.asyncio
async def test_completed_latest_with_expected_none_does_not_step() -> None:
    store = InMemorySubagentStore()
    runtime, model, _tools = _runtime(store, [_text("only once"), _text("nope")])
    first = await runtime.advance(_ticket())
    assert first.kind is StepKind.COMPLETED
    second = await runtime.advance(
        _ticket(run_id=first.run_id, expected_checkpoint_id=None)
    )
    assert second.kind is StepKind.COMPLETED
    assert second.status is SubagentStatus.COMPLETED
    assert (await store.get(first.run_id)).latest_seq == 1
    assert len(model.requests) == 1


@pytest.mark.asyncio
async def test_concurrent_advance_same_expected_has_one_writer() -> None:
    store = InMemorySubagentStore()
    runtime, _model, tools = _runtime(
        store,
        [_tool(), _text("after tools"), _text("should not run")],
    )
    first = await runtime.advance(_ticket())
    assert first.kind is StepKind.CONTINUING
    ticket = _ticket(run_id=first.run_id, expected_checkpoint_id=first.checkpoint_id)
    left, right = await asyncio.gather(runtime.advance(ticket), runtime.advance(ticket))
    kinds = {left.kind, right.kind}
    assert StepKind.CONTINUING in kinds
    assert (await store.get(first.run_id)).latest_seq == 2
    assert len(tools.calls) == 1


@pytest.mark.asyncio
async def test_terminal_mismatch_is_mapped_not_silently_continuing() -> None:
    store = InMemorySubagentStore()
    runtime, _model, _tools = _runtime(store, [_text("terminal")])
    first = await runtime.advance(_ticket())
    stale = await runtime.advance(
        _ticket(run_id=first.run_id, expected_checkpoint_id="sc_stale")
    )
    assert stale.kind is StepKind.COMPLETED
    assert stale.status is SubagentStatus.COMPLETED
    assert stale.kind is not StepKind.CONTINUING
    assert (await store.get(first.run_id)).latest_seq == 1
    folded = await runtime.fold(first.run_id)
    assert folded.summary == "terminal"

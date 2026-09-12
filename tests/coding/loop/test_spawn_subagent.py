from __future__ import annotations

import logging
from dataclasses import replace
from datetime import timedelta

import pytest

from neos.coding.domain.durability import ToolExecutionClaim, ToolExecutionDisposition
from neos.coding.domain.phases import CodingCheckpoint, SteeringMode, SteeringRequest
from neos.coding.loop.anthropic import AnthropicLoopConfig, CodingLoopFailure
from neos.coding.model.base import ModelCompleted, ModelUsage, TextDelta, ToolCallCompleted
from neos.coding.tools.registry import CodingToolRegistry, ToolRisk
from neos.subagent.catalog import SpecRegistry
from neos.subagent.memory import InMemorySubagentStore
from neos.subagent.ports import SystemClock
from neos.subagent.runtime import SubagentRuntime
from neos.subagent.stepper import ChildStepper
from neos.subagent.types import (
    ModelPin,
    ParentBriefing,
    ParentKind,
    SandboxMode,
    SubagentStatus,
    SubagentTicket,
)
from tests.coding.loop.test_anthropic_loop import (
    INPUT,
    LEASE,
    NOW,
    collect,
    completed,
    harness,
    tool_call,
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


class FakeChildTools:
    def __init__(self, names=("read_file.v1",)) -> None:
        self._names = names
        self.calls: list[tuple[str, dict]] = []

    def definitions(self):
        return self._names

    async def execute(self, name: str, input):
        self.calls.append((name, dict(input)))
        return {"ok": True, "path": input.get("path", "")}


class RecordingSubagents:
    def __init__(self, inner: SubagentRuntime) -> None:
        self.inner = inner
        self.cancel_calls: list[tuple[str, str]] = []
        self.cancel_for_parent_calls: list[tuple[object, str, str]] = []

    async def advance(self, ticket):
        return await self.inner.advance(ticket)

    async def fold(self, run_id):
        return await self.inner.fold(run_id)

    async def cancel(self, run_id, reason):
        self.cancel_calls.append((run_id, reason))
        return await self.inner.cancel(run_id, reason)

    async def cancel_for_parent(self, parent_kind, parent_id, reason):
        self.cancel_for_parent_calls.append((parent_kind, parent_id, reason))
        return await self.inner.cancel_for_parent(parent_kind, parent_id, reason)


def _text(text: str = "found login.py"):
    return (TextDelta(text), ModelCompleted("end_turn", ModelUsage(1, 1)))


def _child_tool(path: str = "a.py"):
    return (
        TextDelta("looking"),
        ToolCallCompleted("c1", "read_file.v1", {"path": path}),
        ModelCompleted("tool_use", ModelUsage(1, 1)),
    )


def _make_runtime(script=None):
    model = ScriptedCodingModel(script or [_child_tool(), _text()])
    runtime = SubagentRuntime(
        store=InMemorySubagentStore(),
        catalog=SpecRegistry(),
        stepper=ChildStepper(model=model, tools=FakeChildTools()),
        events=_NullSink(),
        clock=SystemClock(),
    )
    return runtime, model


class _NullSink:
    async def emit(self, event_type, payload) -> None:
        return None


def _flag_on(**kwargs):
    return AnthropicLoopConfig(
        model="claude-test", system="code", subagent_enabled=True, **kwargs
    )


def test_coding_loop_config_clamps_subagent_max_active() -> None:
    low = AnthropicLoopConfig(
        model="claude-test", system="code", provider="anthropic", subagent_max_active=0
    )
    high = AnthropicLoopConfig(
        model="claude-test", system="code", provider="anthropic", subagent_max_active=5
    )
    assert low.subagent_max_active == 1
    assert high.subagent_max_active == 4


def _user_texts(state) -> list[str]:
    return [
        item["text"]
        for message in state["transcript"]
        if message["role"] == "user"
        for item in message["content"]
        if item.get("type") == "text"
    ]


def _tool_results(state) -> list[dict]:
    return [
        item
        for message in state["transcript"]
        for item in message["content"]
        if item.get("type") == "tool_result"
    ]


def _spawn_turns(prompt: str = "look around", call_id: str = "s1"):
    return [
        [
            tool_call(call_id, "spawn_agent.v1", {"prompt": prompt, "max_turns": 4}),
            completed(),
        ]
    ]


@pytest.mark.asyncio
async def test_flag_on_first_delivery_parks_without_completing_or_pasting() -> None:
    runtime, _child = _make_runtime([_child_tool()])
    h = harness(_spawn_turns(), config=_flag_on(), subagents=runtime)
    events = await collect(h)
    state = h.repository.checkpoints[-1].loop_state
    assert state["pending_tool_index"] == 0
    assert state["active_child_run_id"]
    assert str(state["active_child_run_id"]).startswith("sa_")
    assert state["active_child_tool_call_id"] == "s1"
    assert state["active_child_checkpoint_id"]
    assert not any("look around" in text for text in _user_texts(state))
    assert _tool_results(state) == []
    assert not any(event.type == "tool.completed" for event in events)
    parked = [event for event in events if event.type == "phase.completed"]
    assert parked
    payload = parked[-1].payload
    assert payload["child_run_id"] == state["active_child_run_id"]
    assert payload["step_kind"] == "continuing"
    assert "transcript" not in payload


@pytest.mark.asyncio
async def test_flag_on_multi_delivery_folds_summary_into_parent_tool_result() -> None:
    runtime, child = _make_runtime([_child_tool(), _text("handler lives in login.py")])
    h = harness(_spawn_turns(), config=_flag_on(), subagents=runtime)
    first = await collect(h)
    assert not any(event.type == "tool.completed" for event in first)
    parked = h.repository.checkpoints[-1]
    assert parked.loop_state["active_child_run_id"]
    assert parked.loop_state["pending_tool_index"] == 0

    folded = None
    checkpoint = parked
    for _ in range(4):
        events = await collect(h, checkpoint)
        completed_events = [event for event in events if event.type == "tool.completed"]
        if completed_events:
            folded = completed_events[-1]
            break
        checkpoint = h.repository.checkpoints[-1]
    assert folded is not None
    result = folded.payload["result"]
    assert "login.py" in str(result.get("summary") or result)
    state = h.repository.checkpoints[-1].loop_state
    assert state["pending_tool_index"] == 1
    assert state["active_child_run_id"] is None
    assert not any("look around" in text for text in _user_texts(state))
    results = _tool_results(state)
    assert results
    assert "login.py" in str(results[-1]["content"].get("summary") or results[-1])
    assert child.requests
    assert child.requests[0].task_id.startswith("sa_")


@pytest.mark.asyncio
async def test_flag_on_interrupt_aborts_and_calls_cancel_for_parent() -> None:
    inner, _child = _make_runtime([_child_tool(), _text()])
    runtime = RecordingSubagents(inner)
    h = harness(_spawn_turns(), config=_flag_on(), subagents=runtime)
    original = h.repository.claim_tool_execution

    async def claim_and_interrupt(**kwargs):
        claimed = await original(**kwargs)
        await h.repository.queue_steering(
            SteeringRequest(
                steering_id="cs_stop",
                task_id="ct_1",
                mode=SteeringMode.INTERRUPT_NOW,
                instruction="stop",
                requested_at=NOW,
            )
        )
        return claimed

    h.repository.claim_tool_execution = claim_and_interrupt
    events = await collect(h)
    completed_events = [event for event in events if event.type == "tool.completed"]
    assert completed_events
    result = completed_events[-1].payload["result"]
    assert result["status"] == "error"
    assert result["reason_code"] == "aborted"
    assert runtime.cancel_for_parent_calls
    kind, parent_id, reason = runtime.cancel_for_parent_calls[-1]
    assert kind is ParentKind.CODING
    assert parent_id == "ct_1"
    assert reason == "aborted"


@pytest.mark.asyncio
async def test_flag_on_then_off_cancels_active_child_without_prompt_paste() -> None:
    inner, _child = _make_runtime([_child_tool(), _text()])
    runtime = RecordingSubagents(inner)
    h = harness(_spawn_turns(), config=_flag_on(), subagents=runtime)
    await collect(h)
    parked = h.repository.checkpoints[-1]
    assert parked.loop_state["active_child_run_id"]
    h.loop._config = replace(h.loop._config, subagent_enabled=False)
    events = await collect(h, parked)
    completed_events = [event for event in events if event.type == "tool.completed"]
    assert completed_events
    result = completed_events[-1].payload["result"]
    assert result["status"] == "error"
    assert result["reason_code"] == "subagent_disabled"
    state = h.repository.checkpoints[-1].loop_state
    assert not any("look around" in text for text in _user_texts(state))
    assert state["active_child_run_id"] is None
    assert runtime.cancel_calls or runtime.cancel_for_parent_calls


@pytest.mark.asyncio
async def test_second_spawn_while_active_is_policy_child_already_active() -> None:
    runtime, _child = _make_runtime([_child_tool()])
    h = harness(_spawn_turns(), config=_flag_on(), subagents=runtime)
    await collect(h)
    parked = h.repository.checkpoints[-1]
    state = dict(parked.loop_state)
    pending = [dict(item) for item in state["pending_tool_calls"]]
    pending[0]["tool_call_id"] = "s2"
    state["pending_tool_calls"] = pending
    mutated = replace(parked, loop_state=state)
    events = await collect(h, mutated)
    completed_events = [event for event in events if event.type == "tool.completed"]
    assert completed_events
    result = completed_events[-1].payload["result"]
    assert result["status"] == "error"
    assert result["reason_code"] == "policy_child_already_active"


@pytest.mark.asyncio
async def test_flag_on_without_runtime_raises_subagent_runtime_missing() -> None:
    h = harness(_spawn_turns(), config=_flag_on())
    with pytest.raises(CodingLoopFailure) as caught:
        await collect(h)
    assert caught.value.code == "subagent_runtime_missing"
    assert caught.value.retryable is False


def test_restore_missing_active_child_keys_are_none() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    state = h.loop._restore(INPUT, None)
    assert state.active_child_run_id is None
    assert state.active_child_checkpoint_id is None
    assert state.active_child_tool_call_id is None


def _checkpoint(loop_state: dict) -> CodingCheckpoint:
    return CodingCheckpoint(
        checkpoint_id="ck_restore",
        task_id="ct_1",
        run_id="cr_1",
        seq=1,
        loop_state=loop_state,
        workspace_revision="1",
        created_at=NOW,
    )


def test_restore_missing_list_uses_scalars() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    state = h.loop._restore(
        INPUT,
        _checkpoint(
            {
                "transcript": [],
                "pending_tool_calls": [],
                "pending_tool_index": 0,
                "active_child_run_id": "sa_legacy",
                "active_child_checkpoint_id": "sc_legacy",
                "active_child_tool_call_id": "s1",
            }
        ),
    )
    assert state.active_child_run_id == "sa_legacy"
    assert state.active_child_checkpoint_id == "sc_legacy"
    assert state.active_child_tool_call_id == "s1"
    assert len(state.active_children) == 1
    child = state.active_children[0]
    assert child.run_id == "sa_legacy"
    assert child.checkpoint_id == "sc_legacy"
    assert child.tool_call_id == "s1"
    assert child.last_advanced_at == "1970-01-01T00:00:00+00:00"


def test_restore_list_mirrors_scalars(caplog: pytest.LogCaptureFixture) -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    children = [
        {
            "run_id": "sa_1",
            "checkpoint_id": "sc_1",
            "tool_call_id": "s1",
            "last_advanced_at": "2026-07-19T00:00:00+00:00",
        },
        {
            "run_id": "sa_2",
            "checkpoint_id": "sc_2",
            "tool_call_id": "s2",
            "last_advanced_at": "2026-07-19T00:00:01+00:00",
        },
    ]
    with caplog.at_level(logging.WARNING, logger="neos.coding.loop.durable"):
        state = h.loop._restore(
            INPUT,
            _checkpoint(
                {
                    "transcript": [],
                    "pending_tool_calls": [],
                    "pending_tool_index": 0,
                    "active_child_run_id": "sa_stale",
                    "active_child_checkpoint_id": "sc_stale",
                    "active_child_tool_call_id": "s2",
                    "active_children": children,
                }
            ),
        )
    assert [child.tool_call_id for child in state.active_children] == ["s1", "s2"]
    assert state.active_child_run_id == "sa_1"
    assert state.active_child_checkpoint_id == "sc_1"
    assert state.active_child_tool_call_id == "s1"
    assert any(
        "active_child scalars disagree" in record.getMessage()
        for record in caplog.records
    )
    stale = replace(
        state,
        active_child_run_id="sa_stale",
        active_child_checkpoint_id="sc_stale",
        active_child_tool_call_id="s2",
    )
    dumped = h.loop._dump_state(INPUT, stale)
    assert dumped["active_children"][0]["tool_call_id"] == "s1"
    assert dumped["active_children"][1]["tool_call_id"] == "s2"
    assert dumped["active_child_run_id"] == "sa_1"
    assert dumped["active_child_tool_call_id"] == "s1"
    again = h.loop._restore(INPUT, _checkpoint(dumped))
    assert [child.tool_call_id for child in again.active_children] == ["s1", "s2"]
    assert again.active_child_run_id == "sa_1"
    assert again.active_child_tool_call_id == "s1"


async def _plant_second_child(h, runtime, parked, *, tool_call_id: str = "s2"):
    store = runtime.inner._store if hasattr(runtime, "inner") else runtime._store
    record = await store.resolve_or_create(
        SubagentTicket(
            parent_kind=ParentKind.CODING,
            parent_id="ct_1",
            parent_run_id="cr_1",
            parent_tool_call_id=tool_call_id,
            spec="explore",
            briefing=ParentBriefing(goal="sibling look"),
            model=ModelPin(provider="anthropic", model="claude-test"),
            max_turns=4,
            sandbox_mode=SandboxMode.PARENT_RO,
        )
    )
    state = dict(parked.loop_state)
    existing = [dict(item) for item in state.get("active_children") or ()]
    if not existing and state.get("active_child_run_id"):
        existing = [
            {
                "run_id": state["active_child_run_id"],
                "checkpoint_id": state.get("active_child_checkpoint_id"),
                "tool_call_id": state.get("active_child_tool_call_id"),
                "last_advanced_at": NOW.isoformat(),
            }
        ]
    existing.append(
        {
            "run_id": record.run_id,
            "checkpoint_id": record.latest_checkpoint_id,
            "tool_call_id": tool_call_id,
            "last_advanced_at": NOW.isoformat(),
        }
    )
    state["active_children"] = existing
    pending = [dict(item) for item in state.get("pending_tool_calls") or ()]
    if not any(item.get("tool_call_id") == tool_call_id for item in pending):
        pending.append(
            {
                "tool_call_id": tool_call_id,
                "name": "spawn_agent.v1",
                "input": {"prompt": "sibling look", "max_turns": 4},
            }
        )
    state["pending_tool_calls"] = pending
    h.repository.tool_claims[("ct_1", tool_call_id)] = (
        ToolExecutionClaim(
            ToolExecutionDisposition.DELEGATED,
            tool_call_id,
            LEASE,
            {
                "child_run_id": record.run_id,
                "child_checkpoint_id": record.latest_checkpoint_id or "",
            },
        ),
        NOW + timedelta(minutes=1),
    )
    return replace(parked, loop_state=state), record


@pytest.mark.asyncio
async def test_flag_off_with_two_live_children_completes_every_claim() -> None:
    inner, _child = _make_runtime([_child_tool(), _text()])
    runtime = RecordingSubagents(inner)
    h = harness(_spawn_turns(), config=_flag_on(), subagents=runtime)
    await collect(h)
    parked = h.repository.checkpoints[-1]
    planted, sibling = await _plant_second_child(h, runtime, parked)
    h.loop._config = replace(h.loop._config, subagent_enabled=False)
    events = await collect(h, planted)
    completed_events = [event for event in events if event.type == "tool.completed"]
    assert completed_events
    s1_completes = [
        item for item in h.repository.tool_execution_calls if item["tool_call_id"] == "s1"
    ]
    s2_completes = [
        item for item in h.repository.tool_execution_calls if item["tool_call_id"] == "s2"
    ]
    assert len(s1_completes) == 1
    assert len(s2_completes) == 1
    assert s1_completes[0]["result"]["reason_code"] == "subagent_disabled"
    assert s2_completes[0]["result"]["reason_code"] == "subagent_disabled"
    state = h.repository.checkpoints[-1].loop_state
    results = _tool_results(state)
    assert {item["tool_call_id"] for item in results} == {"s1", "s2"}
    assert all(item["status"] == "error" for item in results)
    assert not any("look around" in text for text in _user_texts(state))
    assert not any("sibling look" in text for text in _user_texts(state))
    assert state["active_child_run_id"] is None
    assert state.get("active_children") in (None, [], ())
    s1_run = planted.loop_state["active_child_run_id"]
    assert (await inner._store.get(s1_run)).status is SubagentStatus.KILLED
    assert (await inner._store.get(sibling.run_id)).status is SubagentStatus.KILLED


@pytest.mark.asyncio
async def test_checkpoint_aborted_completes_every_live_spawn_claim() -> None:
    inner, _child = _make_runtime([_child_tool(), _text()])
    runtime = RecordingSubagents(inner)
    h = harness(_spawn_turns(), config=_flag_on(), subagents=runtime)
    await collect(h)
    parked = h.repository.checkpoints[-1]
    planted, sibling = await _plant_second_child(h, runtime, parked)
    bound = await h.loop._bindings.resolve(h.deps.lease)
    state = h.loop._restore(INPUT, planted)
    await h.loop._checkpoint_aborted(INPUT, state, bound, h.deps)
    assert h.repository.completed_tools[("ct_1", "s1")]["reason_code"] == "aborted"
    assert h.repository.completed_tools[("ct_1", "s2")]["reason_code"] == "aborted"
    s1_run = planted.loop_state["active_child_run_id"]
    assert (await inner._store.get(s1_run)).status is SubagentStatus.KILLED
    assert (await inner._store.get(sibling.run_id)).status is SubagentStatus.KILLED


@pytest.mark.asyncio
async def test_coding_tool_port_intersects_and_refuses_writes() -> None:
    from neos.coding.subagent_port import CodingToolPort

    registry = CodingToolRegistry.default(command_allowlist=frozenset({"git"}))
    port = CodingToolPort(registry=registry, executor=object())
    names = {item.name for item in port.definitions()}
    assert "read_file.v1" in names
    assert "spawn_agent.v1" not in names
    assert "write_file.v1" not in names
    assert "execute.v1" not in names
    with pytest.raises(Exception):
        await port.execute("write_file.v1", {"path": "a.txt", "content": "x"})
    write = registry.validate("write_file.v1", {"path": "a.txt", "content": "x"})
    assert write.risk is not ToolRisk.READ_ONLY

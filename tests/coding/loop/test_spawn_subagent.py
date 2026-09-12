from __future__ import annotations

import logging
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from prometheus_client import CollectorRegistry

from neos.coding.domain.durability import (
    StaleExecutionLease,
    ToolExecutionClaim,
    ToolExecutionDisposition,
)
from neos.coding.application.run_service import (
    CodingRunService,
    InProcessRunInterrupter,
)
from neos.coding.application.task_service import InMemoryCodingTaskRepository
from neos.coding.domain.models import CodingTask, CodingTaskStatus
from neos.coding.domain.phases import (
    CodingCheckpoint,
    CodingRunStatus,
    SteeringMode,
    SteeringRequest,
)
from neos.coding.events.store import InMemoryCodingEventStore
from neos.coding.loop.anthropic import AnthropicLoopConfig, CodingLoopFailure
from neos.coding.loop.durable import _select_spawn_work
from neos.observability.metrics import EnterpriseMetricsCollector
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
        self.advance_tickets: list[SubagentTicket] = []
        self.cancel_calls: list[tuple[str, str]] = []
        self.cancel_for_parent_calls: list[tuple[object, str, str]] = []
        self.fail_if_stale_calls: list[tuple[str, object, float]] = []

    async def advance(self, ticket):
        self.advance_tickets.append(ticket)
        return await self.inner.advance(ticket)

    async def fold(self, run_id):
        return await self.inner.fold(run_id)

    async def fail_if_stale(self, run_id, *, now, stale_after_sec=990):
        self.fail_if_stale_calls.append((run_id, now, stale_after_sec))
        return await self.inner.fail_if_stale(
            run_id, now=now, stale_after_sec=stale_after_sec
        )

    async def cancel(self, run_id, reason):
        self.cancel_calls.append((run_id, reason))
        return await self.inner.cancel(run_id, reason)

    async def cancel_for_parent(self, parent_kind, parent_id, reason):
        self.cancel_for_parent_calls.append((parent_kind, parent_id, reason))
        return await self.inner.cancel_for_parent(parent_kind, parent_id, reason)


def _text(text: str = "found login.py"):
    return (TextDelta(text), ModelCompleted("end_turn", ModelUsage(1, 1)))


def _child_tool(path: str = "a.py", input_tokens: int = 1, output_tokens: int = 1):
    return (
        TextDelta("looking"),
        ToolCallCompleted("c1", "read_file.v1", {"path": path}),
        ModelCompleted("tool_use", ModelUsage(input_tokens, output_tokens)),
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


class TickableClock:
    def __init__(self, now=NOW) -> None:
        self.now = now

    def __call__(self):
        return self.now

    def tick(self, seconds: int = 1):
        self.now = self.now + timedelta(seconds=seconds)
        return self.now


def _two_spawn_turns():
    return [
        [
            tool_call("s1", "spawn_agent.v1", {"prompt": "look one", "max_turns": 4}),
            tool_call("s2", "spawn_agent.v1", {"prompt": "look two", "max_turns": 4}),
            completed(),
        ]
    ]


def _subagent_store(runtime):
    return runtime.inner._store if hasattr(runtime, "inner") else runtime._store


def _child_by_id(state, tool_call_id: str):
    for child in state.get("active_children") or ():
        if child["tool_call_id"] == tool_call_id:
            return child
    return None


async def _park_two(h, clock):
    await collect(h)
    clock.tick()
    parked = h.repository.checkpoints[-1]
    await collect(h, parked)
    clock.tick()
    return h.repository.checkpoints[-1]


async def _collect_until_folded(h, clock, checkpoint, tool_call_id: str, *, limit: int = 8):
    current = checkpoint
    for _ in range(limit):
        await collect(h, current)
        clock.tick()
        current = h.repository.checkpoints[-1]
        if any(
            item["tool_call_id"] == tool_call_id
            for item in _tool_results(current.loop_state)
        ):
            return current
    raise AssertionError(f"{tool_call_id} never folded")


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
    assert payload["live_count"] == 1
    assert "transcript" not in payload
    assert "brief" not in payload
    assert "briefing" not in payload
    assert "content" not in payload


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


@pytest.mark.asyncio
async def test_max_active_2_allows_two_different_tool_call_ids() -> None:
    runtime, _child = _make_runtime([_child_tool(), _child_tool()])
    clock = TickableClock()
    h = harness(
        _two_spawn_turns(),
        config=_flag_on(subagent_max_active=2),
        subagents=runtime,
    )
    h.loop._clock = clock
    parked = await _park_two(h, clock)
    state = parked.loop_state
    ids = [child["tool_call_id"] for child in state["active_children"]]
    assert ids == ["s1", "s2"]
    assert state["pending_tool_index"] == 0
    s1_claim, _ = h.repository.tool_claims[("ct_1", "s1")]
    s2_claim, _ = h.repository.tool_claims[("ct_1", "s2")]
    assert s1_claim.disposition is ToolExecutionDisposition.DELEGATED
    assert s2_claim.disposition is ToolExecutionDisposition.DELEGATED


@pytest.mark.asyncio
async def test_same_tool_call_id_resume_still_parks() -> None:
    runtime, _child = _make_runtime([_child_tool(), _child_tool()])
    clock = TickableClock()
    h = harness(_spawn_turns(), config=_flag_on(), subagents=runtime)
    h.loop._clock = clock
    await collect(h)
    first = h.repository.checkpoints[-1]
    first_run = first.loop_state["active_child_run_id"]
    clock.tick()
    await collect(h, first)
    again = h.repository.checkpoints[-1].loop_state
    assert again["active_child_run_id"] == first_run
    assert again["active_child_tool_call_id"] == "s1"
    assert again["pending_tool_index"] == 0
    assert _tool_results(again) == []
    store = _subagent_store(runtime)
    assert len(store._runs) == 1
    assert list(store._by_parent.values()) == [first_run]


@pytest.mark.asyncio
async def test_old_last_advanced_at_folds_stalled_without_advance() -> None:
    inner, child = _make_runtime([_child_tool(), _text("should not run")])
    runtime = RecordingSubagents(inner)
    clock = TickableClock()
    h = harness(_spawn_turns(), config=_flag_on(), subagents=runtime)
    h.loop._clock = clock
    await collect(h)
    parked = h.repository.checkpoints[-1]
    state = dict(parked.loop_state)
    children = [dict(item) for item in state["active_children"]]
    assert children
    children[0]["last_advanced_at"] = (NOW - timedelta(seconds=2000)).isoformat()
    state["active_children"] = children
    mutated = replace(parked, loop_state=state)
    advances_before = len(runtime.advance_tickets)
    events = await collect(h, mutated)
    assert len(runtime.advance_tickets) == advances_before
    assert runtime.fail_if_stale_calls
    assert runtime.fail_if_stale_calls[-1][0] == children[0]["run_id"]
    completed_events = [event for event in events if event.type == "tool.completed"]
    assert completed_events
    result = completed_events[-1].payload["result"]
    assert result["status"] == "error"
    assert result["reason_code"] == "stalled"
    assert result.get("exit_reason") == "stalled"
    assert result.get("child_status") == "failed"
    loaded = await inner._store.get(children[0]["run_id"])
    assert loaded.status is SubagentStatus.FAILED
    assert loaded.error_code == "stalled"
    after = h.repository.checkpoints[-1].loop_state
    assert _child_by_id(after, "s1") is None
    assert after.get("active_children") in (None, [], ())
    assert child.requests  # first park advanced; resume must not


@pytest.mark.asyncio
async def test_epoch_last_advanced_at_still_advances() -> None:
    inner, _child = _make_runtime([_child_tool(), _child_tool()])
    runtime = RecordingSubagents(inner)
    clock = TickableClock()
    h = harness(_spawn_turns(), config=_flag_on(), subagents=runtime)
    h.loop._clock = clock
    await collect(h)
    parked = h.repository.checkpoints[-1]
    state = dict(parked.loop_state)
    children = [dict(item) for item in state["active_children"]]
    assert children
    children[0]["last_advanced_at"] = "1970-01-01T00:00:00+00:00"
    state["active_children"] = children
    mutated = replace(parked, loop_state=state)
    advances_before = len(runtime.advance_tickets)
    await collect(h, mutated)
    assert len(runtime.advance_tickets) == advances_before + 1
    assert runtime.fail_if_stale_calls
    assert runtime.fail_if_stale_calls[-1][0] == children[0]["run_id"]
    assert runtime.fail_if_stale_calls[-1][2] != 0
    loaded = await inner._store.get(children[0]["run_id"])
    assert loaded.status is SubagentStatus.RUNNING
    assert loaded.error_code != "stalled"


@pytest.mark.asyncio
async def test_one_delivery_advances_exactly_one_child() -> None:
    inner, _child = _make_runtime(
        [_child_tool(), _child_tool(), _child_tool(), _child_tool()]
    )
    runtime = RecordingSubagents(inner)
    clock = TickableClock()
    h = harness(
        _two_spawn_turns(),
        config=_flag_on(subagent_max_active=2),
        subagents=runtime,
    )
    h.loop._clock = clock
    parked = await _park_two(h, clock)
    assert len(parked.loop_state["active_children"]) == 2
    before = len(runtime.advance_tickets)
    await collect(h, parked)
    assert len(runtime.advance_tickets) == before + 1


@pytest.mark.asyncio
async def test_fill_before_rr() -> None:
    inner, _child = _make_runtime(
        [_child_tool(), _child_tool(), _child_tool(), _child_tool()]
    )
    runtime = RecordingSubagents(inner)
    clock = TickableClock()
    h = harness(
        _two_spawn_turns(),
        config=_flag_on(subagent_max_active=2),
        subagents=runtime,
    )
    h.loop._clock = clock
    await collect(h)
    first = h.repository.checkpoints[-1]
    s1 = _child_by_id(first.loop_state, "s1")
    assert s1 is not None
    assert _child_by_id(first.loop_state, "s2") is None
    s1_stamp = s1["last_advanced_at"]
    s1_run = s1["run_id"]
    store = _subagent_store(runtime)
    s1_seq = (await store.get(s1_run)).latest_seq
    clock.tick()
    await collect(h, first)
    second = h.repository.checkpoints[-1].loop_state
    assert [child["tool_call_id"] for child in second["active_children"]] == [
        "s1",
        "s2",
    ]
    assert _child_by_id(second, "s1")["last_advanced_at"] == s1_stamp
    assert (await store.get(s1_run)).latest_seq == s1_seq
    assert runtime.advance_tickets[-1].parent_tool_call_id == "s2"
    assert runtime.advance_tickets[-1].run_id is None


@pytest.mark.asyncio
async def test_rr_picks_oldest_last_advanced_at() -> None:
    runtime, _child = _make_runtime(
        [_child_tool(), _child_tool(), _child_tool(), _child_tool()]
    )
    clock = TickableClock()
    h = harness(
        _two_spawn_turns(),
        config=_flag_on(subagent_max_active=2),
        subagents=runtime,
    )
    h.loop._clock = clock
    parked = await _park_two(h, clock)
    store = _subagent_store(runtime)
    s1 = _child_by_id(parked.loop_state, "s1")
    s2 = _child_by_id(parked.loop_state, "s2")
    s1_before = await store.get(s1["run_id"])
    s2_before = await store.get(s2["run_id"])
    await collect(h, parked)
    clock.tick()
    after_s1 = h.repository.checkpoints[-1]
    s1_mid = await store.get(s1["run_id"])
    s2_mid = await store.get(s2["run_id"])
    assert s1_mid.latest_seq == s1_before.latest_seq + 1
    assert s1_mid.latest_checkpoint_id != s1_before.latest_checkpoint_id
    assert s2_mid.latest_seq == s2_before.latest_seq
    assert s2_mid.turn_count == s2_before.turn_count
    await collect(h, after_s1)
    s2_after = await store.get(s2["run_id"])
    assert s2_after.latest_seq == s2_before.latest_seq + 1
    assert s2_after.latest_checkpoint_id != s2_before.latest_checkpoint_id
    assert s2_after.turn_count >= s2_before.turn_count


@pytest.mark.asyncio
async def test_resume_uses_child_ref_not_scalars() -> None:
    inner, _child = _make_runtime(
        [_child_tool(), _child_tool(), _child_tool(), _child_tool()]
    )
    runtime = RecordingSubagents(inner)
    clock = TickableClock()
    h = harness(
        _two_spawn_turns(),
        config=_flag_on(subagent_max_active=2),
        subagents=runtime,
    )
    h.loop._clock = clock
    parked = await _park_two(h, clock)
    state = parked.loop_state
    s1 = _child_by_id(state, "s1")
    s2 = _child_by_id(state, "s2")
    assert state["active_child_run_id"] == s1["run_id"]
    assert state["active_child_checkpoint_id"] == s1["checkpoint_id"]
    assert state["active_child_tool_call_id"] == "s1"
    await collect(h, parked)
    clock.tick()
    after_s1 = h.repository.checkpoints[-1]
    runtime.advance_tickets.clear()
    await collect(h, after_s1)
    assert len(runtime.advance_tickets) == 1
    ticket = runtime.advance_tickets[0]
    assert ticket.parent_tool_call_id == "s2"
    assert ticket.run_id == s2["run_id"]
    assert ticket.expected_checkpoint_id == s2["checkpoint_id"]


@pytest.mark.asyncio
async def test_fold_of_one_child_does_not_complete_the_sibling() -> None:
    runtime, _child = _make_runtime(
        [_child_tool(), _child_tool(), _text("s1 report"), _child_tool()]
    )
    clock = TickableClock()
    h = harness(
        _two_spawn_turns(),
        config=_flag_on(subagent_max_active=2),
        subagents=runtime,
    )
    h.loop._clock = clock
    parked = await _park_two(h, clock)
    folded = await _collect_until_folded(h, clock, parked, "s1")
    state = folded.loop_state
    assert [child["tool_call_id"] for child in state["active_children"]] == ["s2"]
    assert state["pending_tool_index"] == 1
    assert state["active_child_tool_call_id"] == "s2"
    results = _tool_results(state)
    assert {item["tool_call_id"] for item in results} == {"s1"}
    s2_claim, _ = h.repository.tool_claims[("ct_1", "s2")]
    assert s2_claim.disposition is ToolExecutionDisposition.DELEGATED
    assert ("ct_1", "s1") in h.repository.completed_tools
    assert ("ct_1", "s2") not in h.repository.completed_tools


@pytest.mark.asyncio
async def test_out_of_order_fold_does_not_double_append() -> None:
    runtime, _child = _make_runtime(
        [_child_tool(), _child_tool(), _text("s2 report"), _text("s1 report")]
    )
    clock = TickableClock()
    h = harness(
        _two_spawn_turns(),
        config=_flag_on(subagent_max_active=2),
        subagents=runtime,
    )
    h.loop._clock = clock
    parked = await _park_two(h, clock)
    state = dict(parked.loop_state)
    children = [dict(child) for child in state["active_children"]]
    children[1]["last_advanced_at"] = "1970-01-01T00:00:00+00:00"
    state["active_children"] = children
    mutated = replace(parked, loop_state=state)
    after_s2 = await _collect_until_folded(h, clock, mutated, "s2")
    mid = after_s2.loop_state
    s2_results = [
        item for item in _tool_results(mid) if item["tool_call_id"] == "s2"
    ]
    assert len(s2_results) == 1
    assert mid["pending_tool_index"] == 0
    assert [child["tool_call_id"] for child in mid["active_children"]] == ["s1"]
    await _collect_until_folded(h, clock, after_s2, "s1")
    final = h.repository.checkpoints[-1].loop_state
    s2_results = [
        item for item in _tool_results(final) if item["tool_call_id"] == "s2"
    ]
    s1_results = [
        item for item in _tool_results(final) if item["tool_call_id"] == "s1"
    ]
    assert len(s2_results) == 1
    assert len(s1_results) == 1
    assert final["pending_tool_index"] == 2


@pytest.mark.asyncio
async def test_non_spawn_breaks_the_window() -> None:
    runtime, _child = _make_runtime([_child_tool(), _child_tool()])
    clock = TickableClock()
    h = harness(
        [
            [
                tool_call(
                    "s1", "spawn_agent.v1", {"prompt": "look one", "max_turns": 4}
                ),
                tool_call("r1", "read_file.v1", {"path": "a.py"}),
                tool_call(
                    "s2", "spawn_agent.v1", {"prompt": "look two", "max_turns": 4}
                ),
                completed(),
            ]
        ],
        config=_flag_on(subagent_max_active=2),
        subagents=runtime,
    )
    h.loop._clock = clock
    await collect(h)
    clock.tick()
    first = h.repository.checkpoints[-1]
    assert [child["tool_call_id"] for child in first.loop_state["active_children"]] == [
        "s1"
    ]
    await collect(h, first)
    second = h.repository.checkpoints[-1].loop_state
    assert [child["tool_call_id"] for child in second["active_children"]] == ["s1"]
    assert _child_by_id(second, "s2") is None
    assert ("ct_1", "s2") not in h.repository.tool_claims
    assert second["pending_tool_index"] == 0
    assert not any(item["tool_call_id"] == "r1" for item in _tool_results(second))


@pytest.mark.asyncio
async def test_adopt_all_rewrites_sibling_fencing() -> None:
    runtime, _child = _make_runtime(
        [_child_tool(), _child_tool(), _child_tool(), _child_tool()]
    )
    clock = TickableClock()
    h = harness(
        _two_spawn_turns(),
        config=_flag_on(subagent_max_active=2),
        subagents=runtime,
    )
    h.loop._clock = clock
    parked = await _park_two(h, clock)
    claim_a_s1, _ = h.repository.tool_claims[("ct_1", "s1")]
    lease_a = h.deps.lease
    await h.repository.release_execution_lease(lease_a, now=clock.now)
    lease_b = await h.repository.acquire_execution_lease(
        task_id="ct_1",
        run_id="cr_1",
        worker_id="worker-b",
        now=clock.now,
        expires_at=clock.now + timedelta(minutes=1),
    )
    assert lease_b is not None
    h.deps = replace(h.deps, lease=lease_b)
    await collect(h, parked)
    s1_claim, _ = h.repository.tool_claims[("ct_1", "s1")]
    s2_claim, _ = h.repository.tool_claims[("ct_1", "s2")]
    assert s1_claim.lease.worker_id == "worker-b"
    assert s2_claim.lease.worker_id == "worker-b"
    assert s1_claim.lease.fencing_token == lease_b.fencing_token
    assert s2_claim.lease.fencing_token == lease_b.fencing_token
    await h.repository.complete_tool_execution(
        s2_claim, result={"folded": True}, now=clock.now
    )
    assert h.repository.completed_tools[("ct_1", "s2")] == {"folded": True}
    with pytest.raises(StaleExecutionLease):
        await h.repository.complete_tool_execution(
            claim_a_s1, result={"folded": False}, now=clock.now
        )


@pytest.mark.asyncio
async def test_deny_of_non_prefix_spawn_does_not_advance_index() -> None:
    runtime, _child = _make_runtime([_child_tool(), _child_tool()])
    clock = TickableClock()
    h = harness(
        [
            [
                tool_call(
                    "s1", "spawn_agent.v1", {"prompt": "look one", "max_turns": 4}
                ),
                tool_call("s2", "spawn_agent.v1", {"prompt": "", "max_turns": 4}),
                completed(),
            ]
        ],
        config=_flag_on(subagent_max_active=2),
        subagents=runtime,
    )
    h.loop._clock = clock
    await collect(h)
    clock.tick()
    parked = h.repository.checkpoints[-1]
    assert [child["tool_call_id"] for child in parked.loop_state["active_children"]] == [
        "s1"
    ]
    assert parked.loop_state["pending_tool_index"] == 0
    await collect(h, parked)
    state = h.repository.checkpoints[-1].loop_state
    assert state["pending_tool_index"] == 0
    assert [child["tool_call_id"] for child in state["active_children"]] == ["s1"]
    s2_results = [
        item for item in _tool_results(state) if item["tool_call_id"] == "s2"
    ]
    assert len(s2_results) == 1
    s1_claim, _ = h.repository.tool_claims[("ct_1", "s1")]
    assert s1_claim.disposition is ToolExecutionDisposition.DELEGATED


@pytest.mark.asyncio
async def test_adopt_all_remarks_expired_sibling_delegated() -> None:
    runtime, _child = _make_runtime(
        [_child_tool(), _child_tool(), _child_tool(), _child_tool()]
    )
    clock = TickableClock()
    h = harness(
        _two_spawn_turns(),
        config=_flag_on(subagent_max_active=2),
        subagents=runtime,
    )
    h.loop._clock = clock
    parked = await _park_two(h, clock)
    clock.tick(160)
    lease_a = h.deps.lease
    await h.repository.release_execution_lease(lease_a, now=clock.now)
    lease_b = await h.repository.acquire_execution_lease(
        task_id="ct_1",
        run_id="cr_1",
        worker_id="worker-b",
        now=clock.now,
        expires_at=clock.now + timedelta(minutes=5),
    )
    assert lease_b is not None
    h.deps = replace(h.deps, lease=lease_b)
    await collect(h, parked)
    s2_claim, _ = h.repository.tool_claims[("ct_1", "s2")]
    assert s2_claim.disposition is ToolExecutionDisposition.DELEGATED
    clock.tick()
    after_s1 = h.repository.checkpoints[-1]
    await collect(h, after_s1)
    s2_after, _ = h.repository.tool_claims[("ct_1", "s2")]
    assert s2_after.disposition is ToolExecutionDisposition.DELEGATED
    assert ("ct_1", "s2") not in h.repository.completed_tools
    store = _subagent_store(runtime)
    s2 = _child_by_id(after_s1.loop_state, "s2")
    assert s2 is not None
    s2_record = await store.get(s2["run_id"])
    assert s2_record.latest_seq >= 2


def _usage_turn(text: str, input_tokens: int, output_tokens: int):
    return (
        TextDelta(text),
        ModelCompleted("end_turn", ModelUsage(input_tokens, output_tokens)),
    )


def _priced(**kwargs):
    return _flag_on(
        input_cost_micros_per_million=1_000_000,
        output_cost_micros_per_million=1_000_000,
        **kwargs,
    )


async def _run_service(h, clock):
    tasks = InMemoryCodingTaskRepository()
    await tasks.create(
        CodingTask(
            task_id="ct_1",
            owner_id="u1",
            prompt="Fix it",
            status=CodingTaskStatus.RUNNING,
            version=1,
            last_seq=0,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await h.repository.release_execution_lease(h.deps.lease, now=clock.now)
    return CodingRunService(
        tasks=tasks,
        runs=h.repository,
        events=InMemoryCodingEventStore(),
        interrupter=InProcessRunInterrupter(),
        loop=h.loop,
        clock=clock,
    )


@pytest.mark.asyncio
async def test_cost_rollup_increments_parent_tokens() -> None:
    inner, _child = _make_runtime([_usage_turn("found login.py", 2, 3)])
    runtime = RecordingSubagents(inner)
    original_fold = runtime.fold

    async def inflated(run_id):
        folded = await original_fold(run_id)
        assert folded.input_tokens == 2
        assert folded.output_tokens == 3
        return replace(folded, cost_micros=999_999)

    runtime.fold = inflated
    h = harness(_spawn_turns(), config=_priced(), subagents=runtime)
    await collect(h)
    after = h.repository.checkpoints[-1].loop_state
    before = next(
        checkpoint.loop_state
        for checkpoint in h.repository.checkpoints
        if checkpoint.loop_state.get("pending_tool_calls")
        and not checkpoint.loop_state.get("active_children")
    )
    assert after["input_tokens"] == before["input_tokens"] + 2
    assert after["output_tokens"] == before["output_tokens"] + 3
    assert after["cost_micros"] == before["cost_micros"] + 5
    results = [item for item in _tool_results(after) if item["tool_call_id"] == "s1"]
    assert len(results) == 1


@pytest.mark.asyncio
async def test_cost_rollup_completed_reuse_counts_once() -> None:
    runtime, _child = _make_runtime(
        [
            _child_tool(input_tokens=0, output_tokens=0),
            _usage_turn("found login.py", 2, 3),
        ]
    )
    h = harness(_spawn_turns(), config=_priced(), subagents=runtime)
    await collect(h)
    parked = h.repository.checkpoints[-1]
    await collect(h, parked)
    parked = h.repository.checkpoints[-1]
    before = parked.loop_state
    original = h.repository.commit_phase_checkpoint

    async def kill(**kwargs):
        raise RuntimeError("killed before checkpoint")

    h.repository.commit_phase_checkpoint = kill
    with pytest.raises(RuntimeError, match="killed before checkpoint"):
        await collect(h, parked)
    assert ("ct_1", "s1") in h.repository.completed_tools
    assert h.repository.checkpoints[-1].checkpoint_id == parked.checkpoint_id
    h.repository.commit_phase_checkpoint = original
    await collect(h, parked)
    after = h.repository.checkpoints[-1].loop_state
    assert after["input_tokens"] == before["input_tokens"] + 2
    assert after["output_tokens"] == before["output_tokens"] + 3
    assert after["cost_micros"] == before["cost_micros"] + 5
    results = [item for item in _tool_results(after) if item["tool_call_id"] == "s1"]
    assert len(results) == 1


@pytest.mark.asyncio
async def test_flag_off_completed_reuse_drops_child_and_counts_result_once() -> None:
    inner, _child = _make_runtime([_child_tool(), _text()])
    runtime = RecordingSubagents(inner)
    h = harness(_two_spawn_turns(), config=_flag_on(), subagents=runtime)
    await collect(h)
    parked = h.repository.checkpoints[-1]
    assert _child_by_id(parked.loop_state, "s1") is not None
    assert _child_by_id(parked.loop_state, "s2") is None
    h.loop._config = replace(h.loop._config, subagent_enabled=False)
    original = h.repository.commit_phase_checkpoint

    async def kill(**kwargs):
        raise RuntimeError("killed before checkpoint")

    h.repository.commit_phase_checkpoint = kill
    with pytest.raises(RuntimeError, match="killed before checkpoint"):
        await collect(h, parked)
    assert ("ct_1", "s1") in h.repository.completed_tools
    assert "child_status" not in h.repository.completed_tools[("ct_1", "s1")]
    assert h.repository.checkpoints[-1].checkpoint_id == parked.checkpoint_id
    h.repository.commit_phase_checkpoint = original
    advances_before = len(runtime.advance_tickets)
    await collect(h, parked)
    after = h.repository.checkpoints[-1].loop_state
    results = [item for item in _tool_results(after) if item["tool_call_id"] == "s1"]
    assert len(results) == 1
    assert results[0]["status"] == "error"
    assert after.get("active_children") in (None, [], ())
    assert after["active_child_run_id"] is None
    assert _child_by_id(after, "s1") is None
    await collect(h, h.repository.checkpoints[-1])
    final = h.repository.checkpoints[-1].loop_state
    results = [item for item in _tool_results(final) if item["tool_call_id"] == "s1"]
    assert len(results) == 1
    assert _child_by_id(final, "s1") is None
    assert len(runtime.advance_tickets) == advances_before


@pytest.mark.asyncio
async def test_budget_exceed_keeps_folded_result_and_cancels_siblings() -> None:
    inner, _child = _make_runtime(
        [
            _child_tool(input_tokens=0, output_tokens=0),
            _child_tool(input_tokens=0, output_tokens=0),
            _usage_turn("s1 report", 2, 3),
            _child_tool(),
        ]
    )
    runtime = RecordingSubagents(inner)
    clock = TickableClock()
    h = harness(
        _two_spawn_turns(),
        config=_priced(subagent_max_active=2),
        subagents=runtime,
    )
    h.loop._clock = clock
    parked = await _park_two(h, clock)
    parent_cost = int(parked.loop_state["cost_micros"])
    h.loop._config = replace(h.loop._config, max_cost_micros=max(1, parent_cost))
    service = await _run_service(h, clock)
    with pytest.raises(CodingLoopFailure) as caught:
        for _ in range(8):
            await service.advance_one_safe_point(task_id="ct_1", worker_id="worker-a")
            clock.tick()
    assert caught.value.code == "cost_budget_exceeded"
    state = h.repository.checkpoints[-1].loop_state
    folded = [
        item
        for item in _tool_results(state)
        if item["tool_call_id"] in {"s1", "s2"} and item["status"] == "ok"
    ]
    assert len(folded) == 1
    folded_id = folded[0]["tool_call_id"]
    sibling_id = "s2" if folded_id == "s1" else "s1"
    assert ("ct_1", folded_id) in h.repository.completed_tools
    sibling = h.repository.completed_tools[("ct_1", sibling_id)]
    assert sibling["reason_code"] == "cost_budget_exceeded"
    last_fold = max(
        index
        for index, ticket in enumerate(runtime.advance_tickets)
        if ticket.parent_tool_call_id == folded_id
    )
    last_sibling = max(
        (
            index
            for index, ticket in enumerate(runtime.advance_tickets)
            if ticket.parent_tool_call_id == sibling_id
        ),
        default=-1,
    )
    assert last_sibling < last_fold
    await service.fail_active_run(
        task_id="ct_1",
        worker_id="worker-a",
        error_code="cost_budget_exceeded",
    )
    assert h.repository.active_run.status is CodingRunStatus.FAILED


def _metrics():
    return EnterpriseMetricsCollector(registry=CollectorRegistry())


def _histogram_sample(histogram, suffix: str, **labels) -> float:
    for metric in histogram.collect():
        for sample in metric.samples:
            if not sample.name.endswith(suffix):
                continue
            if all(sample.labels.get(key) == value for key, value in labels.items()):
                return sample.value
    return 0.0


def _live_sum(metrics) -> float:
    return _histogram_sample(
        metrics.subagent_live_children,
        "_sum",
        parent_kind="coding",
        spec="explore",
    )


def _live_count(metrics) -> float:
    return _histogram_sample(
        metrics.subagent_live_children,
        "_count",
        parent_kind="coding",
        spec="explore",
    )


def _live_bucket(metrics, le: str) -> float:
    return _histogram_sample(
        metrics.subagent_live_children,
        "_bucket",
        parent_kind="coding",
        spec="explore",
        le=le,
    )


@pytest.mark.asyncio
async def test_spawn_delivery_observes_live_children_histogram() -> None:
    runtime, _child = _make_runtime([_child_tool()])
    metrics = _metrics()
    h = harness(_spawn_turns(), config=_flag_on(), subagents=runtime)
    h.loop._metrics = metrics
    events = await collect(h)
    assert _live_count(metrics) == 1
    assert _live_sum(metrics) == 1.0
    parked = [event for event in events if event.type == "phase.completed"]
    assert parked
    payload = parked[-1].payload
    assert payload["live_count"] == 1
    assert "transcript" not in payload
    assert "brief" not in payload


@pytest.mark.asyncio
async def test_policy_child_already_active_increments_capped_counter() -> None:
    runtime, _child = _make_runtime([_child_tool()])
    metrics = _metrics()
    h = harness(_spawn_turns(), config=_flag_on(), subagents=runtime)
    h.loop._metrics = metrics
    await collect(h)
    parked = h.repository.checkpoints[-1]
    state = dict(parked.loop_state)
    pending = [dict(item) for item in state["pending_tool_calls"]]
    pending[0]["tool_call_id"] = "s2"
    state["pending_tool_calls"] = pending
    mutated = replace(parked, loop_state=state)
    await collect(h, mutated)
    assert (
        metrics.subagent_policy_capped_total.labels(parent_kind="coding")._value.get()
        == 1
    )


@pytest.mark.asyncio
async def test_child_fold_records_parent_priced_rollup_not_folded_cost() -> None:
    inner, _child = _make_runtime([_usage_turn("found login.py", 2, 3)])
    runtime = RecordingSubagents(inner)
    original_fold = runtime.fold

    async def inflated(run_id):
        folded = await original_fold(run_id)
        return replace(folded, cost_micros=999_999)

    runtime.fold = inflated
    metrics = _metrics()
    h = harness(_spawn_turns(), config=_priced(), subagents=runtime)
    h.loop._metrics = metrics
    await collect(h)
    assert (
        metrics.subagent_fold_rollup_tokens_total.labels(
            parent_kind="coding", direction="input"
        )._value.get()
        == 2
    )
    assert (
        metrics.subagent_fold_rollup_tokens_total.labels(
            parent_kind="coding", direction="output"
        )._value.get()
        == 3
    )
    assert (
        metrics.subagent_fold_rollup_cost_micros_total.labels(
            parent_kind="coding", provider="anthropic"
        )._value.get()
        == 5
    )
    assert (
        metrics.subagent_cost_micros_total.labels(
            spec="explore", parent_kind="coding", provider="anthropic"
        )._value.get()
        == 0
    )


@pytest.mark.asyncio
async def test_child_fold_observes_live_children_after_drop() -> None:
    runtime, _child = _make_runtime([_usage_turn("found login.py", 2, 3)])
    metrics = _metrics()
    h = harness(_spawn_turns(), config=_priced(), subagents=runtime)
    h.loop._metrics = metrics
    await collect(h)
    state = h.repository.checkpoints[-1].loop_state
    assert not state.get("active_children")
    assert state["active_child_run_id"] is None
    assert _live_count(metrics) == 1
    assert _live_sum(metrics) == 0.0
    assert _live_bucket(metrics, "0.0") == 1.0


@pytest.mark.asyncio
async def test_token_budget_exceed_cancels_siblings_with_token_reason() -> None:
    inner, _child = _make_runtime(
        [
            _child_tool(input_tokens=0, output_tokens=0),
            _child_tool(input_tokens=0, output_tokens=0),
            _usage_turn("s1 report", 2, 3),
            _child_tool(),
        ]
    )
    runtime = RecordingSubagents(inner)
    clock = TickableClock()
    h = harness(
        _two_spawn_turns(),
        config=_priced(subagent_max_active=2),
        subagents=runtime,
    )
    h.loop._clock = clock
    parked = await _park_two(h, clock)
    parent_tokens = int(parked.loop_state["input_tokens"]) + int(
        parked.loop_state["output_tokens"]
    )
    h.loop._config = replace(
        h.loop._config,
        max_total_tokens=max(1, parent_tokens),
        max_cost_micros=10**12,
    )
    service = await _run_service(h, clock)
    with pytest.raises(CodingLoopFailure) as caught:
        for _ in range(8):
            await service.advance_one_safe_point(task_id="ct_1", worker_id="worker-a")
            clock.tick()
    assert caught.value.code == "token_budget_exceeded"
    state = h.repository.checkpoints[-1].loop_state
    folded = [
        item
        for item in _tool_results(state)
        if item["tool_call_id"] in {"s1", "s2"} and item["status"] == "ok"
    ]
    assert len(folded) == 1
    folded_id = folded[0]["tool_call_id"]
    sibling_id = "s2" if folded_id == "s1" else "s1"
    assert ("ct_1", folded_id) in h.repository.completed_tools
    sibling = h.repository.completed_tools[("ct_1", sibling_id)]
    assert sibling["reason_code"] == "token_budget_exceeded"
    last_fold = max(
        index
        for index, ticket in enumerate(runtime.advance_tickets)
        if ticket.parent_tool_call_id == folded_id
    )
    last_sibling = max(
        (
            index
            for index, ticket in enumerate(runtime.advance_tickets)
            if ticket.parent_tool_call_id == sibling_id
        ),
        default=-1,
    )
    assert last_sibling < last_fold


@pytest.mark.asyncio
async def test_completed_reuse_skips_after_result_and_drains_prefix() -> None:
    runtime, _child = _make_runtime([_child_tool(), _text()])
    h = harness(_spawn_turns(), config=_flag_on(), subagents=runtime)
    await collect(h)
    parked = h.repository.checkpoints[-1]
    assert parked.loop_state["pending_tool_index"] == 0
    assert _child_by_id(parked.loop_state, "s1") is not None
    state = dict(parked.loop_state)
    transcript = list(state.get("transcript") or ())
    transcript.append(
        {
            "role": "tool",
            "content": [
                {
                    "type": "tool_result",
                    "tool_call_id": "s1",
                    "status": "ok",
                    "content": {"summary": "already folded"},
                }
            ],
        }
    )
    state["transcript"] = transcript
    h.repository.completed_tools[("ct_1", "s1")] = {
        "status": "ok",
        "summary": "already folded",
    }
    mutated = replace(parked, loop_state=state)
    await collect(h, mutated)
    after = h.repository.checkpoints[-1].loop_state
    results = [item for item in _tool_results(after) if item["tool_call_id"] == "s1"]
    assert len(results) == 1
    assert after["pending_tool_index"] == 1
    assert _child_by_id(after, "s1") is None
    assert after.get("active_children") in (None, [], ())
    assert after["active_child_run_id"] is None


def test_restore_empty_stamps_when_len_gt_1_use_epoch() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    state = h.loop._restore(
        INPUT,
        _checkpoint(
            {
                "transcript": [],
                "pending_tool_calls": [],
                "pending_tool_index": 0,
                "active_children": [
                    {
                        "run_id": "sa_1",
                        "checkpoint_id": "sc_1",
                        "tool_call_id": "s1",
                        "last_advanced_at": "",
                    },
                    {
                        "run_id": "sa_2",
                        "checkpoint_id": "sc_2",
                        "tool_call_id": "s2",
                        "last_advanced_at": "",
                    },
                ],
            }
        ),
    )
    assert [child.tool_call_id for child in state.active_children] == ["s1", "s2"]
    assert {child.last_advanced_at for child in state.active_children} == {
        "1970-01-01T00:00:00+00:00"
    }


def test_select_spawn_work_resume_call_none_on_pending_mutation() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    state = h.loop._restore(
        INPUT,
        _checkpoint(
            {
                "transcript": [],
                "pending_tool_calls": [
                    {
                        "tool_call_id": "s2",
                        "name": "spawn_agent.v1",
                        "input": {"prompt": "look two", "max_turns": 4},
                    }
                ],
                "pending_tool_index": 0,
                "active_children": [
                    {
                        "run_id": "sa_1",
                        "checkpoint_id": "sc_1",
                        "tool_call_id": "s1",
                        "last_advanced_at": "2026-07-19T00:00:00+00:00",
                    }
                ],
            }
        ),
    )
    work = _select_spawn_work(state, max_active=1)
    assert work is not None
    assert work.kind == "resume"
    assert work.call is None
    assert work.child is not None
    assert work.child.tool_call_id == "s1"


@pytest.mark.asyncio
async def test_flag_off_mid_flight_cancels_all_live_children() -> None:
    inner, _child = _make_runtime(
        [_child_tool(), _child_tool(), _child_tool(), _child_tool()]
    )
    runtime = RecordingSubagents(inner)
    clock = TickableClock()
    h = harness(
        _two_spawn_turns(),
        config=_flag_on(subagent_max_active=2),
        subagents=runtime,
    )
    h.loop._clock = clock
    parked = await _park_two(h, clock)
    assert [child["tool_call_id"] for child in parked.loop_state["active_children"]] == [
        "s1",
        "s2",
    ]
    h.loop._config = replace(h.loop._config, subagent_enabled=False)
    await collect(h, parked)
    state = h.repository.checkpoints[-1].loop_state
    results = _tool_results(state)
    assert {item["tool_call_id"] for item in results} == {"s1", "s2"}
    assert all(item["status"] == "error" for item in results)
    assert all(
        item["content"].get("reason_code") == "subagent_disabled"
        or item.get("reason_code") == "subagent_disabled"
        for item in results
    )
    assert not any("look one" in text for text in _user_texts(state))
    assert not any("look two" in text for text in _user_texts(state))
    assert state["active_child_run_id"] is None
    assert state.get("active_children") in (None, [], ())
    s1 = _child_by_id(parked.loop_state, "s1")
    s2 = _child_by_id(parked.loop_state, "s2")
    assert s1 is not None and s2 is not None
    assert (await inner._store.get(s1["run_id"])).status is SubagentStatus.KILLED
    assert (await inner._store.get(s2["run_id"])).status is SubagentStatus.KILLED


@pytest.mark.asyncio
async def test_unknown_spawn_spec_is_policy_unknown_spec() -> None:
    runtime, _child = _make_runtime([_child_tool()])
    h = harness(
        [
            [
                tool_call(
                    "s1",
                    "spawn_agent.v1",
                    {
                        "prompt": "look around",
                        "max_turns": 4,
                        "spec": "general-purpose",
                    },
                ),
                completed(),
            ]
        ],
        config=_flag_on(),
        subagents=runtime,
    )
    events = await collect(h)
    completed_events = [event for event in events if event.type == "tool.completed"]
    assert completed_events
    result = completed_events[-1].payload["result"]
    assert result["status"] == "error"
    assert result["reason_code"] == "policy_unknown_spec"
    state = h.repository.checkpoints[-1].loop_state
    assert state.get("active_children") in (None, [], ())
    assert state["active_child_run_id"] is None
    assert len(_subagent_store(runtime)._runs) == 0


def test_price_child_usage_mapping_and_object_use_parent_prices() -> None:
    h = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]], config=_priced())
    mapping = {"input_tokens": 2, "output_tokens": 3, "cost_micros": 999_999}
    obj = SimpleNamespace(input_tokens=2, output_tokens=3, cost_micros=999_999)
    assert h.loop._price_child_usage(mapping) == (2, 3, 5)
    assert h.loop._price_child_usage(obj) == (2, 3, 5)


@pytest.mark.asyncio
async def test_fail_all_skips_completed_and_already_on_transcript() -> None:
    inner, _child = _make_runtime(
        [_child_tool(), _child_tool(), _child_tool(), _child_tool()]
    )
    runtime = RecordingSubagents(inner)
    clock = TickableClock()
    h = harness(
        _two_spawn_turns(),
        config=_flag_on(subagent_max_active=2),
        subagents=runtime,
    )
    h.loop._clock = clock
    parked = await _park_two(h, clock)
    original_s1 = {"status": "ok", "summary": "already folded"}
    h.repository.completed_tools[("ct_1", "s1")] = dict(original_s1)
    state = dict(parked.loop_state)
    transcript = list(state.get("transcript") or ())
    for tool_call_id, content in (
        ("s1", {"summary": "already folded"}),
        ("s2", {"summary": "already on transcript"}),
    ):
        transcript.append(
            {
                "role": "tool",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_call_id": tool_call_id,
                        "status": "ok",
                        "content": content,
                    }
                ],
            }
        )
    state["transcript"] = transcript
    mutated = replace(parked, loop_state=state)
    bound = await h.loop._bindings.resolve(h.deps.lease)
    restored = h.loop._restore(INPUT, mutated)
    after = await h.loop.fail_all_live_spawn_claims(
        restored,
        h.deps,
        bound,
        reason="aborted",
        task_id="ct_1",
    )
    dumped = h.loop._dump_state(INPUT, after)
    results = _tool_results(dumped)
    s1_results = [item for item in results if item["tool_call_id"] == "s1"]
    s2_results = [item for item in results if item["tool_call_id"] == "s2"]
    assert len(s1_results) == 1
    assert len(s2_results) == 1
    assert s1_results[0]["content"] == {"summary": "already folded"}
    assert s2_results[0]["content"] == {"summary": "already on transcript"}
    assert h.repository.completed_tools[("ct_1", "s1")] == original_s1
    assert h.repository.completed_tools[("ct_1", "s2")]["reason_code"] == "aborted"
    assert after.active_children == ()

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from neos.coding.model.base import ModelCompleted, ModelUsage, TextDelta, ToolCallCompleted
from neos.coding.model.errors import CodingModelError
from neos.subagent.catalog import SpecRegistry, UnknownSpec
from neos.subagent.fold import FoldNotReady
from neos.subagent.memory import InMemorySubagentStore
from neos.subagent.ports import SystemClock
from neos.subagent.runtime import DEFAULT_STALE_AFTER_SEC, SubagentRuntime
from neos.subagent.stepper import ChildStepper, REFUSED_TOOLS
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
        if not self.script:
            raise CodingModelError("model_script_exhausted", retryable=False)
        for event in self.script.pop(0):
            yield event


class FakeToolPort:
    def __init__(self, names=None, results=None) -> None:
        self._names = tuple(names or ("read_file.v1", "search_text.v1", "execute.v1"))
        self.results = results or {}
        self.calls: list[tuple[str, dict]] = []

    def definitions(self):
        return self._names

    async def execute(self, name: str, input):
        self.calls.append((name, dict(input)))
        if name in self.results:
            return self.results[name]
        return {"ok": True, "path": input.get("path", name)}


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def emit(self, event_type: str, payload) -> None:
        self.events.append((event_type, dict(payload)))


def _ticket(**overrides) -> SubagentTicket:
    payload = {
        "parent_kind": ParentKind.CODING,
        "parent_id": "ct_parent",
        "parent_run_id": "cr_parent",
        "parent_tool_call_id": "toolu_spawn",
        "spec": "explore",
        "briefing": ParentBriefing(goal="Find the login handler", success="Name it"),
        "model": ModelPin(provider="anthropic", model="claude-test"),
    }
    payload.update(overrides)
    return SubagentTicket(**payload)


def _runtime(
    script,
    *,
    store=None,
    tools=None,
    input_cost_micros_per_million: int = 0,
    output_cost_micros_per_million: int = 0,
):
    store = store or InMemorySubagentStore()
    tools = tools or FakeToolPort()
    model = ScriptedCodingModel(script)
    events = RecordingSink()
    runtime = SubagentRuntime(
        store=store,
        catalog=SpecRegistry(),
        stepper=ChildStepper(
            model=model,
            tools=tools,
            input_cost_micros_per_million=input_cost_micros_per_million,
            output_cost_micros_per_million=output_cost_micros_per_million,
        ),
        events=events,
        clock=SystemClock(),
    )
    return runtime, store, tools, model, events


def _text(text: str = "report"):
    return (TextDelta(text), ModelCompleted("end_turn", ModelUsage(3, 2)))


def _tool(name: str = "read_file.v1", **input):
    return (
        TextDelta("looking"),
        ToolCallCompleted("call_1", name, input or {"path": "README.md"}),
        ModelCompleted("tool_use", ModelUsage(4, 1)),
    )


@pytest.mark.asyncio
async def test_advance_completes_when_model_returns_no_tools() -> None:
    runtime, store, _tools, model, events = _runtime([_text("handler is login.py")])
    outcome = await runtime.advance(_ticket())
    assert outcome.kind is StepKind.COMPLETED
    assert outcome.status is SubagentStatus.COMPLETED
    assert outcome.run_id.startswith("sa_")
    assert outcome.checkpoint_id.startswith("sc_")
    assert outcome.turn_count == 1
    assert model.requests[0].task_id == outcome.run_id
    assert model.requests[0].run_id == outcome.run_id
    assert getattr(model.requests[0], "thinking", None) in {None, False}
    snap = await runtime.status(outcome.run_id)
    assert snap.status is SubagentStatus.COMPLETED
    assert (await store.get(outcome.run_id)).latest_seq == 1
    assert events.events[0][0] == "subagent.started"
    assert any(kind == "subagent.completed" for kind, _ in events.events)


@pytest.mark.asyncio
async def test_child_cost_micros_stays_zero_without_prices() -> None:
    runtime, store, _tools, _model, events = _runtime([_text("handler is login.py")])
    outcome = await runtime.advance(_ticket())
    snap = await runtime.status(outcome.run_id)
    assert snap.input_tokens == 3
    assert snap.output_tokens == 2
    assert snap.cost_micros == 0
    folded = await runtime.fold(outcome.run_id)
    assert folded.cost_micros == 0
    completed = next(payload for kind, payload in events.events if kind == "subagent.completed")
    assert completed["cost_micros"] == 0
    assert (await store.get(outcome.run_id)).cost_micros == 0


@pytest.mark.asyncio
async def test_child_cost_micros_uses_stepper_injected_prices() -> None:
    runtime, store, _tools, _model, events = _runtime(
        [_text("handler is login.py")],
        input_cost_micros_per_million=1_000_000,
        output_cost_micros_per_million=2_000_000,
    )
    outcome = await runtime.advance(_ticket())
    snap = await runtime.status(outcome.run_id)
    assert snap.input_tokens == 3
    assert snap.output_tokens == 2
    assert snap.cost_micros == 7
    folded = await runtime.fold(outcome.run_id)
    assert folded.cost_micros == 7
    completed = next(payload for kind, payload in events.events if kind == "subagent.completed")
    assert completed["cost_micros"] == 7
    assert (await store.get(outcome.run_id)).cost_micros == 7


@pytest.mark.asyncio
async def test_child_cost_micros_prefers_ticket_prices() -> None:
    runtime, store, *_ = _runtime(
        [_text("handler is login.py")],
        input_cost_micros_per_million=1_000_000,
        output_cost_micros_per_million=1_000_000,
    )
    outcome = await runtime.advance(
        _ticket(
            input_cost_micros_per_million=2_000_000,
            output_cost_micros_per_million=0,
        )
    )
    snap = await runtime.status(outcome.run_id)
    assert snap.cost_micros == 6
    folded = await runtime.fold(outcome.run_id)
    assert folded.cost_micros == 6
    assert (await store.get(outcome.run_id)).cost_micros == 6


@pytest.mark.asyncio
async def test_one_shot_still_allows_tool_then_report_across_advances() -> None:
    runtime, store, tools, model, _events = _runtime(
        [
            _tool("read_file.v1", path="login.py"),
            _text("login.py handles POST /login"),
        ],
        tools=FakeToolPort(names=("read_file.v1", "execute.v1")),
    )
    ticket = _ticket()
    first = await runtime.advance(ticket)
    assert first.kind is StepKind.CONTINUING
    assert first.status is SubagentStatus.RUNNING
    assert tools.calls == []
    request_tools = {item.name for item in model.requests[0].tools}
    assert "read_file.v1" in request_tools
    assert "execute.v1" not in request_tools
    second = await runtime.advance(
        _ticket(run_id=first.run_id, expected_checkpoint_id=first.checkpoint_id)
    )
    assert tools.calls == [("read_file.v1", {"path": "login.py"})]
    assert second.kind is StepKind.CONTINUING
    third = await runtime.advance(
        _ticket(run_id=first.run_id, expected_checkpoint_id=second.checkpoint_id)
    )
    assert third.kind is StepKind.COMPLETED
    assert third.turn_count == 2
    folded = await runtime.fold(first.run_id)
    assert "login.py handles POST /login" in folded.summary
    assert (await store.get(first.run_id)).latest_seq == 3


@pytest.mark.asyncio
async def test_max_turns_completes_before_another_model_turn() -> None:
    runtime, _store, tools, model, _events = _runtime(
        [_tool("read_file.v1", path="a.py")],
    )
    first = await runtime.advance(_ticket(max_turns=1))
    assert first.kind is StepKind.CONTINUING
    second = await runtime.advance(
        _ticket(
            max_turns=1,
            run_id=first.run_id,
            expected_checkpoint_id=first.checkpoint_id,
        )
    )
    assert second.kind is StepKind.COMPLETED
    assert second.error_code == "turns_exhausted"
    assert len(model.requests) == 1
    assert tools.calls == []
    folded = await runtime.fold(first.run_id)
    assert folded.summary == "looking"


@pytest.mark.asyncio
async def test_unknown_spec_is_fail_closed_before_create() -> None:
    runtime, store, *_ = _runtime([_text()])
    with pytest.raises(UnknownSpec):
        await runtime.advance(_ticket(spec="general-purpose"))
    assert store._runs == {}


@pytest.mark.asyncio
async def test_refuses_forbidden_tools_without_executing() -> None:
    runtime, _store, tools, _model, _events = _runtime(
        [
            _tool("write_file.v1", path="secret.py", content="x"),
            _text("stopped"),
        ],
        tools=FakeToolPort(names=("read_file.v1", "write_file.v1")),
    )
    first = await runtime.advance(_ticket())
    assert first.kind is StepKind.CONTINUING
    second = await runtime.advance(
        _ticket(run_id=first.run_id, expected_checkpoint_id=first.checkpoint_id)
    )
    assert tools.calls == []
    assert second.kind is StepKind.CONTINUING
    assert REFUSED_TOOLS


class FakeNestedSpawn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, dict]] = []

    async def spawn(self, parent, call):
        self.calls.append((parent.spec, parent.spawn_depth, dict(call)))
        return {"ok": True, "nested_run_id": "sa_nested", "summary": "child report"}


@pytest.mark.asyncio
async def test_explore_child_can_spawn_via_host() -> None:
    host = FakeNestedSpawn()
    model = ScriptedCodingModel(
        [_tool("spawn_agent.v1", prompt="look deeper"), _text("done")]
    )
    tools = FakeToolPort(names=("read_file.v1", "spawn_agent.v1"))
    runtime = SubagentRuntime(
        store=InMemorySubagentStore(),
        catalog=SpecRegistry(),
        stepper=ChildStepper(model=model, tools=tools, nested_spawn=host),
        events=RecordingSink(),
        clock=SystemClock(),
    )
    first = await runtime.advance(_ticket())
    second = await runtime.advance(
        _ticket(run_id=first.run_id, expected_checkpoint_id=first.checkpoint_id)
    )
    assert host.calls[0][0] == "explore"
    assert host.calls[0][1] == 0
    assert host.calls[0][2]["prompt"] == "look deeper"
    assert tools.calls == []
    assert second.kind is StepKind.CONTINUING


class ContinuingThenDone:
    def __init__(self) -> None:
        self.n = 0

    async def spawn(self, parent, call):
        self.n += 1
        if self.n == 1:
            return {
                "ok": True,
                "status": "continuing",
                "nested_run_id": "sa_nested",
            }
        return {"ok": True, "status": "completed", "summary": "child report"}


@pytest.mark.asyncio
async def test_continuing_nested_spawn_keeps_sibling_tools() -> None:
    host = ContinuingThenDone()
    model = ScriptedCodingModel(
        [
            (
                TextDelta("looking"),
                ToolCallCompleted(
                    "call_1", "spawn_agent.v1", {"prompt": "look deeper"}
                ),
                ToolCallCompleted("call_2", "read_file.v1", {"path": "a.py"}),
                ModelCompleted("tool_use", ModelUsage(4, 1)),
            ),
            _text("done"),
        ]
    )
    tools = FakeToolPort(names=("read_file.v1", "spawn_agent.v1"))
    runtime = SubagentRuntime(
        store=InMemorySubagentStore(),
        catalog=SpecRegistry(),
        stepper=ChildStepper(model=model, tools=tools, nested_spawn=host),
        events=RecordingSink(),
        clock=SystemClock(),
    )
    first = await runtime.advance(_ticket())
    parked = await runtime.advance(
        _ticket(run_id=first.run_id, expected_checkpoint_id=first.checkpoint_id)
    )
    pending = (await runtime._store.get_loop_state(first.run_id))["pending_tools"]
    assert parked.kind is StepKind.CONTINUING
    assert [item["name"] for item in pending] == ["spawn_agent.v1", "read_file.v1"]
    assert tools.calls == []
    third = await runtime.advance(
        _ticket(run_id=first.run_id, expected_checkpoint_id=parked.checkpoint_id)
    )
    assert host.n == 2
    assert tools.calls == [("read_file.v1", {"path": "a.py"})]
    assert third.kind is StepKind.CONTINUING


@pytest.mark.asyncio
async def test_nested_explore_and_implement_cannot_spawn() -> None:
    host = FakeNestedSpawn()
    for ticket in (_ticket(spawn_depth=1), _ticket(spec="implement")):
        model = ScriptedCodingModel(
            [_tool("spawn_agent.v1", prompt="again"), _text("done")]
        )
        runtime = SubagentRuntime(
            store=InMemorySubagentStore(),
            catalog=SpecRegistry(),
            stepper=ChildStepper(
                model=model,
                tools=FakeToolPort(names=("read_file.v1", "spawn_agent.v1")),
                nested_spawn=host,
            ),
            events=RecordingSink(),
            clock=SystemClock(),
        )
        first = await runtime.advance(ticket)
        await runtime.advance(
            replace(ticket, run_id=first.run_id, expected_checkpoint_id=first.checkpoint_id)
        )
    assert host.calls == []


@pytest.mark.asyncio
async def test_implement_child_can_execute_write_tools() -> None:
    tools = FakeToolPort(names=("write_file.v1", "read_file.v1"))
    runtime, _store, tools, _model, _events = _runtime(
        [_tool("write_file.v1", path="a.py", content="ok"), _text("wrote")],
        tools=tools,
    )
    first = await runtime.advance(_ticket(spec="implement"))
    second = await runtime.advance(
        _ticket(
            spec="implement",
            run_id=first.run_id,
            expected_checkpoint_id=first.checkpoint_id,
        )
    )
    assert tools.calls == [("write_file.v1", {"path": "a.py", "content": "ok"})]
    assert second.kind is StepKind.CONTINUING
    assert "worktree" in _model.requests[0].system.lower()


@pytest.mark.asyncio
async def test_cancel_and_cancel_for_parent() -> None:
    runtime, _store, *_ = _runtime([_tool(), _tool()])
    first = await runtime.advance(_ticket())
    killed = await runtime.cancel(first.run_id, "aborted")
    assert killed.status is SubagentStatus.KILLED
    unchanged = await runtime.cancel(first.run_id, "again")
    assert unchanged.status is SubagentStatus.KILLED
    folded = await runtime.fold(first.run_id)
    assert folded.summary == "looking"

    other = await runtime.advance(_ticket(parent_tool_call_id="other"))
    snaps = await runtime.cancel_for_parent(ParentKind.CODING, "ct_parent", "stop")
    statuses = {item.run_id: item.status for item in snaps}
    assert statuses[other.run_id] is SubagentStatus.KILLED


@pytest.mark.asyncio
async def test_fold_on_running_is_fail_closed() -> None:
    runtime, *_ = _runtime([_tool()])
    first = await runtime.advance(_ticket())
    with pytest.raises(FoldNotReady):
        await runtime.fold(first.run_id)


@pytest.mark.asyncio
async def test_terminal_advance_does_not_call_model_again() -> None:
    runtime, store, _tools, model, _events = _runtime([_text("done")])
    first = await runtime.advance(_ticket())
    second = await runtime.advance(
        _ticket(run_id=first.run_id, expected_checkpoint_id=None)
    )
    assert second.kind is StepKind.COMPLETED
    assert second.status is SubagentStatus.COMPLETED
    assert len(model.requests) == 1
    assert (await store.get(first.run_id)).latest_seq == 1


@pytest.mark.asyncio
async def test_non_retryable_model_error_fails_child() -> None:
    class Boom(ScriptedCodingModel):
        async def stream(self, request):
            self.requests.append(request)
            raise CodingModelError("model_provider_failed", retryable=False)
            yield TextDelta("")  # pragma: no cover — makes this an async generator

    store = InMemorySubagentStore()
    tools = FakeToolPort()
    runtime = SubagentRuntime(
        store=store,
        catalog=SpecRegistry(),
        stepper=ChildStepper(model=Boom([]), tools=tools),
        events=RecordingSink(),
        clock=SystemClock(),
    )
    outcome = await runtime.advance(_ticket())
    assert outcome.kind is StepKind.FAILED
    assert outcome.status is SubagentStatus.FAILED
    assert outcome.error_code == "model_provider_failed"
    folded = await runtime.fold(outcome.run_id)
    assert folded.summary == "failed"


@pytest.mark.asyncio
async def test_child_transcript_too_large_fails() -> None:
    huge = {"body": "x" * (1024 * 1024 + 10)}
    runtime, *_ = _runtime(
        [_tool("read_file.v1", path="big.txt")],
        tools=FakeToolPort(
            names=("read_file.v1",),
            results={"read_file.v1": huge},
        ),
    )
    first = await runtime.advance(_ticket())
    second = await runtime.advance(
        _ticket(run_id=first.run_id, expected_checkpoint_id=first.checkpoint_id)
    )
    assert second.kind is StepKind.FAILED
    assert second.error_code == "child_transcript_too_large"


def test_two_steers_during_tool_batch_apply_once() -> None:
    from neos.subagent.stepper import _apply_pending_steer, _queue_pending_steer

    state: dict = {
        "messages": [],
        "pending_steer": "",
        "steer_applied": "",
    }
    _queue_pending_steer(state, "A")
    _queue_pending_steer(state, "A\nB")
    assert state["pending_steer"] == "A\nB"
    _apply_pending_steer(state)
    user_texts = [item["text"] for item in state["messages"] if item.get("role") == "user"]
    assert user_texts == ["A\nB"]
    _queue_pending_steer(state, "A\nB")
    assert state["pending_steer"] == ""
    _queue_pending_steer(state, "A\nB\nC")
    assert state["pending_steer"] == "C"
    _apply_pending_steer(state)
    user_texts = [item["text"] for item in state["messages"] if item.get("role") == "user"]
    assert user_texts == ["A\nB", "C"]
    assert state["steer_applied"] == "A\nB\nC"
    _queue_pending_steer(state, "A\nB\nC\nD")
    assert state["pending_steer"] == "D"
    _apply_pending_steer(state)
    user_texts = [item["text"] for item in state["messages"] if item.get("role") == "user"]
    assert user_texts == ["A\nB", "C", "D"]
    assert state["steer_applied"] == "A\nB\nC\nD"


@pytest.mark.asyncio
async def test_runtime_two_steers_during_tools_make_one_user_message() -> None:
    runtime, store, _tools, _model, _events = _runtime(
        [_tool("read_file.v1", path="a.py"), _text("done")]
    )
    first = await runtime.advance(_ticket())
    second = await runtime.advance(
        _ticket(
            run_id=first.run_id,
            expected_checkpoint_id=first.checkpoint_id,
            pending_steer="A",
        )
    )
    third = await runtime.advance(
        _ticket(
            run_id=first.run_id,
            expected_checkpoint_id=second.checkpoint_id,
            pending_steer="A\nB",
        )
    )
    assert third.kind is StepKind.COMPLETED
    state = await store.get_loop_state(first.run_id)
    user_texts = [
        str(item.get("text") or "")
        for item in state.get("messages") or ()
        if isinstance(item, dict) and item.get("role") == "user"
    ]
    assert "A\nA\nB" not in user_texts
    assert user_texts[-1] == "A\nB"
    assert user_texts.count("A\nB") == 1


def test_compact_keeps_size_ref_pointer() -> None:
    from neos.subagent.stepper import _compact

    body = "x" * 40_000
    state = {
        "turn_count": 2,
        "messages": [
            {"role": "user", "text": "look"},
            {"role": "tool", "name": "read_file.v1", "content": {"body": body}},
        ],
    }
    _compact(state)
    content = state["messages"][1]["content"]
    assert content["_ref"]
    assert content["bytes"] >= len(body)
    assert body not in str(content)


def test_compact_skips_large_body_before_turn_or_char_threshold() -> None:
    from neos.subagent.stepper import _compact

    body = "y" * 40_000
    state = {
        "turn_count": 1,
        "messages": [
            {"role": "tool", "content": {"body": body}},
        ],
    }
    _compact(state)
    assert state["messages"][0]["content"] == {"body": body}


def test_runtime_has_no_run_until_done_or_inner_loop() -> None:
    assert not hasattr(SubagentRuntime, "run_until_done")
    for path in Path("neos/subagent").glob("*.py"):
        text = path.read_text()
        assert "run_until_done" not in text
        assert "while True" not in text


@pytest.mark.asyncio
async def test_live_cas_mismatch_emits_and_does_not_step() -> None:
    runtime, _store, _tools, model, events = _runtime([_tool(), _text("nope")])
    first = await runtime.advance(_ticket())
    assert first.kind is StepKind.CONTINUING
    assert first.status is SubagentStatus.RUNNING
    before = len(model.requests)
    second = await runtime.advance(
        _ticket(run_id=first.run_id, expected_checkpoint_id="sc_stale")
    )
    assert any(kind == "subagent.cas_mismatch" for kind, _ in events.events)
    assert second.kind is StepKind.CONTINUING
    assert second.status is SubagentStatus.RUNNING
    assert len(model.requests) == before


@pytest.mark.asyncio
async def test_advance_after_kill_is_cancelled_without_model() -> None:
    runtime, _store, _tools, model, _events = _runtime([_tool(), _text("nope")])
    first = await runtime.advance(_ticket())
    assert first.status is SubagentStatus.RUNNING
    killed = await runtime.cancel(first.run_id, "aborted")
    assert killed.status is SubagentStatus.KILLED
    before = len(model.requests)
    second = await runtime.advance(
        _ticket(run_id=first.run_id, expected_checkpoint_id=None)
    )
    assert second.kind is StepKind.CANCELLED
    assert second.status is SubagentStatus.KILLED
    assert len(model.requests) == before


@pytest.mark.asyncio
async def test_cancel_of_completed_does_not_emit_cancelled() -> None:
    runtime, store, _tools, _model, events = _runtime([_text("done")])
    first = await runtime.advance(_ticket())
    assert first.status is SubagentStatus.COMPLETED
    snap = await runtime.cancel(first.run_id, "too-late")
    assert snap.status is SubagentStatus.COMPLETED
    assert (await store.get(first.run_id)).status is SubagentStatus.COMPLETED
    # Runtime emits cancelled only when the stored status is KILLED.
    assert not any(kind == "subagent.cancelled" for kind, _ in events.events)


@pytest.mark.asyncio
async def test_tool_execute_cancel_then_commit_stays_killed() -> None:
    tools = FakeToolPort(names=("read_file.v1",))
    runtime, store, tools, _model, _events = _runtime(
        [_tool("read_file.v1", path="a.py")],
        tools=tools,
    )
    first = await runtime.advance(_ticket())
    assert first.status is SubagentStatus.RUNNING
    bound = tools.execute

    async def cancel_then_execute(name: str, input):
        await runtime.cancel(first.run_id, "stop")
        return await bound(name, input)

    tools.execute = cancel_then_execute
    second = await runtime.advance(
        _ticket(run_id=first.run_id, expected_checkpoint_id=first.checkpoint_id)
    )
    assert second.status is SubagentStatus.KILLED
    assert (await store.get(first.run_id)).status is SubagentStatus.KILLED
    assert tools.calls == [("read_file.v1", {"path": "a.py"})]


def _backdate(store: InMemorySubagentStore, run_id: str, *, age_sec: float) -> None:
    record = store._runs[run_id]
    store._runs[run_id] = replace(
        record, updated_at=record.updated_at - timedelta(seconds=age_sec)
    )


@pytest.mark.asyncio
async def test_fail_if_stale_marks_pending_failed_stalled() -> None:
    runtime, store, _tools, model, events = _runtime([_text("should not run")])
    record = await store.resolve_or_create(_ticket())
    assert record.status is SubagentStatus.PENDING
    _backdate(store, record.run_id, age_sec=DEFAULT_STALE_AFTER_SEC + 1)
    now = datetime.now(UTC)
    snap = await runtime.fail_if_stale(record.run_id, now=now)
    assert snap.status is SubagentStatus.FAILED
    assert snap.error_code == "stalled"
    loaded = await store.get(record.run_id)
    assert loaded.status is SubagentStatus.FAILED
    assert loaded.error_code == "stalled"
    folded = await runtime.fold(record.run_id)
    assert folded.exit_reason == "stalled"
    assert folded.status is SubagentStatus.FAILED
    assert any(
        kind == "subagent.failed" and payload.get("error_code") == "stalled"
        for kind, payload in events.events
    )
    assert model.requests == []


@pytest.mark.asyncio
async def test_fail_if_stale_marks_running_failed_stalled() -> None:
    runtime, store, *_ = _runtime([_tool()])
    first = await runtime.advance(_ticket())
    assert first.status is SubagentStatus.RUNNING
    _backdate(store, first.run_id, age_sec=DEFAULT_STALE_AFTER_SEC)
    snap = await runtime.fail_if_stale(first.run_id, now=datetime.now(UTC))
    assert snap.status is SubagentStatus.FAILED
    assert snap.error_code == "stalled"
    folded = await runtime.fold(first.run_id)
    assert folded.exit_reason == "stalled"


@pytest.mark.asyncio
async def test_fail_if_stale_leaves_fresh_run_alone() -> None:
    runtime, store, _tools, model, events = _runtime([_text("fresh")])
    record = await store.resolve_or_create(_ticket())
    snap = await runtime.fail_if_stale(
        record.run_id, now=datetime.now(UTC), stale_after_sec=990
    )
    assert snap.status is SubagentStatus.PENDING
    assert snap.error_code == ""
    loaded = await store.get(record.run_id)
    assert loaded.status is SubagentStatus.PENDING
    assert model.requests == []
    assert not any(kind == "subagent.failed" for kind, _ in events.events)


@pytest.mark.asyncio
async def test_fail_if_stale_does_not_overwrite_terminal() -> None:
    runtime, store, *_ = _runtime([_text("done")])
    first = await runtime.advance(_ticket())
    assert first.status is SubagentStatus.COMPLETED
    _backdate(store, first.run_id, age_sec=DEFAULT_STALE_AFTER_SEC + 50)
    snap = await runtime.fail_if_stale(
        first.run_id, now=datetime.now(UTC), stale_after_sec=0
    )
    assert snap.status is SubagentStatus.COMPLETED
    assert (await store.get(first.run_id)).status is SubagentStatus.COMPLETED
    killed_runtime, killed_store, *_ = _runtime([_tool()])
    running = await killed_runtime.advance(_ticket())
    await killed_runtime.cancel(running.run_id, "aborted")
    _backdate(killed_store, running.run_id, age_sec=DEFAULT_STALE_AFTER_SEC + 50)
    again = await killed_runtime.fail_if_stale(
        running.run_id, now=datetime.now(UTC), stale_after_sec=0
    )
    assert again.status is SubagentStatus.KILLED
    assert (await killed_store.get(running.run_id)).error_code == "aborted"

"""CHILD-GATE: a child's tool call goes through the parent's gate.

Before this, `CodingToolPort.execute` checked the spec allowlist and the risk
tier and then called the executor. An implement child could run `rm.v1` or
`execute.v1` without hooks, approval policy or Jev ever seeing the call -- the
only gate was the parent's one `spawn_agent` call (roadmap §11 CHILD-GATE).

These tests drive the real durable loop and the real port. The mutation each
one bites is named in its docstring.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from neos.coding.domain.approvals import (
    ApprovalPolicyOutcome,
    evaluate_approval,
)
from neos.coding.loop._durable.state import ActiveChildRef
from neos.coding.model.base import ModelCompleted, ModelUsage, TextDelta, ToolCallCompleted
from neos.coding.subagent_port import CodingToolPort, CodingToolPortError
from neos.coding.tools.registry import CodingToolRegistry
from neos.subagent.catalog import SpecRegistry
from neos.subagent.memory import InMemorySubagentStore
from neos.subagent.ports import SystemClock
from neos.subagent.runtime import SubagentRuntime
from neos.subagent.stepper import ChildStepper
from tests.coding.loop.support import (
    NOW,
    Bindings,
    collect,
    completed,
    harness,
    tool_call,
)
from tests.coding.loop.test_spawn_subagent import (
    ScriptedCodingModel,
    _flag_on,
    _init_repo,
    _NullSink,
    _text,
)

pytestmark = pytest.mark.no_db


class _SessionExecutor:
    def __init__(self) -> None:
        self.sessions: list[object] = []

    async def execute(self, session, validated):
        self.sessions.append(session)
        return {"ok": True}


class _PortExecutor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(self, session, validated):
        self.calls.append(validated.name)
        return {"ok": True, "path": validated.input.get("path")}


def _child_calls(name: str, input: dict):
    return (
        TextDelta("working"),
        ToolCallCompleted("c1", name, input),
        ModelCompleted("tool_use", ModelUsage(1, 1)),
    )


def _runtime_with_real_port(child_script, *, command_allowlist=frozenset({"pytest"})):
    executor = _PortExecutor()
    port = CodingToolPort(
        registry=CodingToolRegistry.default(command_allowlist=frozenset(command_allowlist)),
        executor=executor,
    )
    runtime = SubagentRuntime(
        store=InMemorySubagentStore(),
        catalog=SpecRegistry(),
        stepper=ChildStepper(model=ScriptedCodingModel(child_script), tools=port),
        events=_NullSink(),
        clock=SystemClock(),
    )
    return runtime, port, executor


def _spawn(spec: str):
    return [
        [
            tool_call(
                "s1", "spawn_agent.v1", {"prompt": "do it", "max_turns": 4, "spec": spec}
            ),
            completed(),
        ]
    ]


async def _run_until_folded(h, *, limit: int = 6) -> None:
    """Park mode moves the child one step per parent step: turn, tool, fold."""
    checkpoint = None
    for _ in range(limit):
        events = await collect(h, checkpoint)
        if any(event.type == "tool.completed" for event in events):
            return
        checkpoint = h.repository.checkpoints[-1]
    raise AssertionError("spawn never folded")


def _denials(h):
    return [event for event in h.events.items if event.type == "tool.denied"]


def _child_tool_results(runtime):
    results = []
    for checkpoints in runtime._store._checkpoints.values():
        if not checkpoints:
            continue
        for message in checkpoints[-1]["loop_state"].get("messages", []):
            if message.get("role") == "tool":
                results.append(message)
    return results


def _ticket(spec: str, task_id: str = "ct_1"):
    return SimpleNamespace(spec=spec, parent_id=task_id)


@pytest.mark.asyncio
async def test_unbound_port_refuses_before_the_executor() -> None:
    """Mutation: drop the `authorize is None` check -> the executor runs."""
    executor = _PortExecutor()
    port = CodingToolPort(
        registry=CodingToolRegistry.default(command_allowlist=frozenset()),
        executor=executor,
    )
    port.bind(task_id="ct_1", session=object())

    with pytest.raises(CodingToolPortError) as error:
        await port.for_ticket(_ticket("implement")).execute("rm.v1", {"path": "old.py"})

    assert error.value.reason_code == "policy_gate_unbound"
    assert executor.calls == []


@pytest.mark.asyncio
async def test_another_tasks_binding_is_not_this_childs() -> None:
    """CHILD-PORT-SHARED: a binding answers only its own task's children.

    Mutation: look the binding up by anything but `ticket.parent_id` (say,
    the most recent bind) -> task A's child runs in task B's session.
    """
    executor = _SessionExecutor()
    port = CodingToolPort(
        registry=CodingToolRegistry.default(command_allowlist=frozenset()),
        executor=executor,
    )

    async def allow(validated):
        return validated, None

    port.bind(task_id="task_a", session="session_a", authorize=allow)
    port.bind(task_id="task_b", session="session_b", authorize=allow)

    await port.for_ticket(_ticket("explore", "task_a")).execute(
        "read_file.v1", {"path": "a.py"}
    )
    with pytest.raises(CodingToolPortError) as error:
        await port.for_ticket(_ticket("explore", "task_c")).execute(
            "read_file.v1", {"path": "a.py"}
        )

    assert executor.sessions == ["session_a"]
    assert error.value.reason_code == "sandbox_session_missing"


@pytest.mark.asyncio
async def test_a_rebind_mid_call_does_not_reach_a_child_already_running() -> None:
    """The race itself: the port is rebound while a child waits in `authorize`.

    Before, the child resumed after the await and ran in whatever session the
    port held by then. The view holds the binding it was built with for the
    whole call.
    Mutation: have the view read `port._bindings` at execute time instead of
    holding the binding it was built with -> this goes red.
    """
    executor = _SessionExecutor()
    port = CodingToolPort(
        registry=CodingToolRegistry.default(command_allowlist=frozenset()),
        executor=executor,
    )
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_allow(validated):
        entered.set()
        await release.wait()
        return validated, None

    port.bind(task_id="task_a", session="session_a", authorize=slow_allow)
    call_a = asyncio.create_task(
        port.for_ticket(_ticket("explore", "task_a")).execute(
            "read_file.v1", {"path": "a.py"}
        )
    )
    await entered.wait()

    async def allow(validated):
        return validated, None

    # Same task id on purpose: the worst case is a *rebind* of A's own slot.
    port.bind(task_id="task_a", session="session_b", authorize=allow)
    release.set()
    await call_a

    assert executor.sessions == ["session_a"]


@pytest.mark.asyncio
async def test_implement_child_rm_is_denied_and_recorded(tmp_path: Path) -> None:
    """The roadmap's mutation test: a child's `rm.v1` leaves an approval event.

    Manual mode, the default: `rm.v1` is a workspace write, the policy says
    REQUIRE_APPROVAL, and a child has nobody to ask -- so it is refused.
    Mutation: skip `self._authorize` in the port -> `rm.v1` reaches the executor
    and no `tool.denied` is written.
    """
    runtime, _port, executor = _runtime_with_real_port(
        [_child_calls("rm.v1", {"path": "old.py"}), _text("done")]
    )
    h = harness(
        _spawn("implement"),
        # The spawn itself is the one gate that already existed; let it through
        # so the child's own call is what gets judged.
        config=_flag_on(approval_allow_tools=("spawn_agent.v1",)),
        subagents=runtime,
        bindings=Bindings(workspace=_init_repo(tmp_path)),
        approval_evaluator=evaluate_approval,
    )

    await _run_until_folded(h)

    assert executor.calls == []
    [denied] = _denials(h)
    assert denied.payload == {
        "name": "rm.v1",
        "denied_by": "approval_policy",
        "reason_code": "policy_approval_denied",
        "subagent_spec": "implement",
        "parent_tool_call_id": "s1",
    }
    # CHILD-GATE ②: the projection keys tool cards by `tool_call_id` and drops
    # a `tool.*` event without one; the phase panel lists tools by `run_id`.
    # Mutation: append without either -> the denial never reaches the screen.
    assert denied.tool_call_id.startswith("s1:child:")
    parent_runs = {
        event.run_id
        for event in h.events.items
        if event.run_id and event is not denied
    }
    assert parent_runs and denied.run_id in parent_runs
    [child_result] = _child_tool_results(runtime)
    assert child_result["status"] == "error"
    assert "policy_approval_denied" in child_result["content"]["error"]


@pytest.mark.asyncio
async def test_auto_mode_always_allow_lets_the_child_run_rm(tmp_path: Path) -> None:
    """The gate is the parent's policy, not a blanket deny.

    Mutation: make the child deny every non-read-only call -> this goes red.
    """
    runtime, _port, executor = _runtime_with_real_port(
        [_child_calls("rm.v1", {"path": "old.py"}), _text("done")]
    )
    h = harness(
        _spawn("implement"),
        config=_flag_on(
            approval_mode="auto",
            approval_allow_tools=("spawn_agent.v1",),
            approval_always_allow=("rm.v1",),
        ),
        subagents=runtime,
        bindings=Bindings(workspace=_init_repo(tmp_path)),
        approval_evaluator=evaluate_approval,
    )

    await _run_until_folded(h)

    assert executor.calls == ["rm.v1"]
    assert _denials(h) == []


@pytest.mark.asyncio
async def test_explore_child_cannot_read_a_secret_even_in_auto_mode() -> None:
    """Read-only calls go through the gate too -- the secret-path DENY is there.

    Mutation: let read-only calls skip `authorize` -> the child reads `.env`.
    """
    runtime, _port, executor = _runtime_with_real_port(
        [_child_calls("read_file.v1", {"path": ".env"}), _text("done")]
    )
    h = harness(
        _spawn("explore"),
        config=_flag_on(approval_mode="auto", approval_allow_tools=("read_file.v1",)),
        subagents=runtime,
        approval_evaluator=evaluate_approval,
    )

    await _run_until_folded(h)

    assert executor.calls == []
    [denied] = _denials(h)
    assert denied.payload["subagent_spec"] == "explore"
    assert denied.payload["reason_code"] == "policy_approval_denied"


@pytest.mark.asyncio
async def test_a_childs_user_only_call_is_recorded_as_user_only(tmp_path: Path) -> None:
    """Track Q2 lands in both gates. The operator allowed `gh` and auto-allows
    execute, and the child still may not log in. The parent's ledger names it
    `policy_user_only` so FB1 counts it. Mutation: the child gate keeps the
    generic reason code."""
    runtime, _port, executor = _runtime_with_real_port(
        [_child_calls("execute.v1", {"argv": ["gh", "auth", "login"]}), _text("done")],
        command_allowlist={"gh"},
    )
    h = harness(
        _spawn("implement"),
        config=_flag_on(
            approval_mode="auto",
            approval_allow_tools=("spawn_agent.v1",),
            approval_always_allow=("execute.v1",),
        ),
        subagents=runtime,
        bindings=Bindings(workspace=_init_repo(tmp_path)),
        approval_evaluator=evaluate_approval,
    )

    await _run_until_folded(h)

    assert executor.calls == []
    [denied] = _denials(h)
    assert denied.payload["reason_code"] == "policy_user_only"


@pytest.mark.asyncio
async def test_the_child_is_judged_unattended_and_the_parent_is_not(
    tmp_path: Path,
) -> None:
    """The child judgement runs with `unattended=True` so D-L1's fold applies.

    Mutation: drop `unattended=True` in `_authorize_child_call` -> the child's
    gate reads False. (Outcomes alone would not catch it: the port refuses
    anything but ALLOW. The Jev event's `unattended` field would be wrong.)
    """
    gates = []

    def capture(call, gate):
        gates.append((call.name, gate.unattended))
        return ApprovalPolicyOutcome.ALLOW

    runtime, _port, executor = _runtime_with_real_port(
        [_child_calls("rm.v1", {"path": "old.py"}), _text("done")]
    )
    h = harness(
        _spawn("implement"),
        config=_flag_on(),
        subagents=runtime,
        bindings=Bindings(workspace=_init_repo(tmp_path)),
        approval_evaluator=capture,
    )

    await _run_until_folded(h)

    assert ("spawn_agent.v1", False) in gates
    assert ("rm.v1", True) in gates
    assert executor.calls == ["rm.v1"]


def test_rebinding_a_resumed_child_replaces_the_gate() -> None:
    """A resumed child runs under this step's gate, not the last spawn's.

    Mutation: make `_rebind_child` a no-op -> the stale closure stays bound.
    This calls the method directly. The two call sites (`await_subagent.v1`
    and the K3 safe point) are pinned by the CHILD-GATE ③ tests below.
    """
    runtime, port, _executor = _runtime_with_real_port([])
    h = harness(_spawn("implement"), config=_flag_on(), subagents=runtime)
    bound = SimpleNamespace(session=object())

    async def stale(validated):
        return validated, None

    port.bind(task_id="ct_1", session=object(), authorize=stale)
    ref = ActiveChildRef(
        run_id="sa_1",
        checkpoint_id=None,
        tool_call_id="s9",
        last_advanced_at=NOW.isoformat(),
        spec="explore",
    )

    h.loop._rebind_child(ref, bound, SimpleNamespace(), h.deps)

    binding = port._bindings["ct_1"]
    assert binding.authorize is not None and binding.authorize is not stale
    assert binding.session is bound.session


@pytest.mark.asyncio
async def test_the_binding_does_not_outlive_the_step(tmp_path: Path) -> None:
    """Each binding closes over one step's state and deps; the step drops it.

    Mutation: remove `_unbind_child_tools` from the spawn path -> the port
    still holds task `ct_1` after the child folds.
    """
    runtime, port, _executor = _runtime_with_real_port(
        [_child_calls("read_file.v1", {"path": "a.py"}), _text("done")]
    )
    h = harness(
        _spawn("explore"),
        config=_flag_on(approval_mode="auto", approval_allow_tools=("read_file.v1",)),
        subagents=runtime,
        approval_evaluator=evaluate_approval,
    )

    await _run_until_folded(h)

    assert port._bindings == {}


def test_two_child_denials_are_two_cards() -> None:
    """The nonce is what keeps a second denial from overwriting the first."""
    from neos.coding.loop._durable.spawn import child_denial_call_id

    first, second = child_denial_call_id("s1"), child_denial_call_id("s1")

    assert first != second
    assert len(child_denial_call_id("x" * 400)) <= 128  # VARCHAR(128)


# ---- CHILD-GATE ③: the resume paths rebind -------------------------------------
#
# `test_rebinding_a_resumed_child_replaces_the_gate` calls the method. These drive
# the two call sites. With async spawn the spawn step runs only the child's model
# turn; its tool call runs on the *next* advance -- at the K3 safe point or under
# `await_subagent.v1`. Each step unbinds in `finally`, so if a resume path skips
# the rebind the port is unbound there and refuses the call before the executor.


def _async_gate_on():
    from neos.coding.loop.anthropic import AnthropicLoopConfig

    return AnthropicLoopConfig(
        model="claude-test",
        system="code",
        subagent_enabled=True,
        subagent_async_spawn=True,
        approval_mode="auto",
        approval_allow_tools=("read_file.v1",),
    )


def _read_then_report():
    return [_child_calls("read_file.v1", {"path": "a.py"}), _text("found it")]


@pytest.mark.asyncio
async def test_the_safe_point_rebinds_before_it_steps_the_child() -> None:
    """Mutation: drop `_rebind_child` from `_advance_one_detached_child` ->
    the child's read is refused as unbound and never reaches the executor."""
    from tests.coding.loop.test_spawn_async import _children, _spawn_then_talk

    runtime, port, executor = _runtime_with_real_port(_read_then_report())
    h = harness(
        _spawn_then_talk(),
        config=_async_gate_on(),
        subagents=runtime,
        approval_evaluator=evaluate_approval,
    )

    checkpoint = None
    for _ in range(8):
        await collect(h, checkpoint)
        checkpoint = h.repository.checkpoints[-1]
        if not _children(checkpoint.loop_state):
            break

    assert executor.calls == ["read_file.v1"]
    [child_result] = _child_tool_results(runtime)
    assert child_result["status"] == "ok"
    assert port._bindings == {}


@pytest.mark.asyncio
async def test_await_rebinds_before_it_resumes_the_child() -> None:
    """Mutation: drop `_rebind_child` from the `await_subagent.v1` path ->
    the child's read is refused as unbound."""
    from tests.coding.loop.test_spawn_async import (
        _await_the_spawned_child,
        _spawn_then_await,
    )

    # Two reads: the safe point before the parent's await turn steps the
    # child once and runs the first read; only the second runs under the
    # await. With one read the await path never runs a tool and this test
    # would pass with its rebind removed (it did, on the first draft).
    runtime, port, executor = _runtime_with_real_port(
        [
            (
                TextDelta("working"),
                ToolCallCompleted("c1", "read_file.v1", {"path": "a.py"}),
                ModelCompleted("tool_use", ModelUsage(1, 1)),
            ),
            (
                TextDelta("again"),
                ToolCallCompleted("c2", "read_file.v1", {"path": "b.py"}),
                ModelCompleted("tool_use", ModelUsage(1, 1)),
            ),
            _text("found it"),
        ]
    )
    h = harness(
        _spawn_then_await(),
        config=_async_gate_on(),
        subagents=runtime,
        approval_evaluator=evaluate_approval,
    )

    await _await_the_spawned_child(h)

    assert executor.calls == ["read_file.v1", "read_file.v1"]
    assert [r["status"] for r in _child_tool_results(runtime)] == ["ok", "ok"]
    assert port._bindings == {}

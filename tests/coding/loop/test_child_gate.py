"""CHILD-GATE: a child's tool call goes through the parent's gate.

Before this, `CodingToolPort.execute` checked the spec allowlist and the risk
tier and then called the executor. An implement child could run `rm.v1` or
`execute.v1` without hooks, approval policy or Jev ever seeing the call -- the
only gate was the parent's one `spawn_agent` call (roadmap §11 CHILD-GATE).

These tests drive the real durable loop and the real port. The mutation each
one bites is named in its docstring.
"""

from __future__ import annotations

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
from tests.coding.loop.test_anthropic_loop import (
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


def _runtime_with_real_port(child_script):
    executor = _PortExecutor()
    port = CodingToolPort(
        registry=CodingToolRegistry.default(command_allowlist=frozenset({"pytest"})),
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


@pytest.mark.asyncio
async def test_unbound_port_refuses_before_the_executor() -> None:
    """Mutation: drop the `authorize is None` check -> the executor runs."""
    executor = _PortExecutor()
    port = CodingToolPort(
        registry=CodingToolRegistry.default(command_allowlist=frozenset()),
        executor=executor,
        spec="implement",
    )
    port.bind(session=object())

    with pytest.raises(CodingToolPortError) as error:
        await port.execute("rm.v1", {"path": "old.py"})

    assert error.value.reason_code == "policy_gate_unbound"
    assert executor.calls == []


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


def test_rebinding_a_resumed_child_replaces_spec_and_gate() -> None:
    """A resumed child runs under its own spec and this step's gate.

    Mutation: make `_rebind_child` a no-op -> the port keeps the last spawn's
    spec (`implement`) and its closure. This calls the method directly; it
    does not catch the call being removed from the two resume paths
    (`await_subagent.v1` and the K3 safe point).
    """
    runtime, port, _executor = _runtime_with_real_port([])
    h = harness(_spawn("implement"), config=_flag_on(), subagents=runtime)
    bound = SimpleNamespace(session=object())

    async def stale(validated):
        return validated, None

    port.use_spec("implement")
    port.bind(session=object(), authorize=stale)
    ref = ActiveChildRef(
        run_id="sa_1",
        checkpoint_id=None,
        tool_call_id="s9",
        last_advanced_at=NOW.isoformat(),
        spec="explore",
    )

    h.loop._rebind_child(ref, bound, SimpleNamespace(), h.deps)

    assert port._spec_name == "explore"
    assert port._authorize is not None and port._authorize is not stale

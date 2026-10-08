"""Q16c in the loop: the device command tool -- exposure, approval, unattended refusal, children,
and byte identity for every bridge that does not offer commands.

Real `evaluate_approval`, real registry, real `DeviceBridgeService`; the relay is a stub
that records what would cross the wire.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from neos.coding.application.user_rules import InMemoryUserRuleStore
from neos.coding.bridge.relay import BridgeView
from neos.coding.bridge.service import DeviceBridgeService
from neos.coding.domain.approvals import ApprovalDecision, evaluate_approval
from neos.coding.tools.registry import CodingToolRegistry
from neos.config.schema import DeviceBridgeConfig
from tests.coding.loop.support import NOW, completed, harness, tool_call
from tests.coding.loop.test_device_bridge_loop import (
    DEVICE_NAMES,
    OWNED,
    _end_turn,
    _until_tool_event,
)

pytestmark = pytest.mark.no_db

RUN = "device_run_command.v1"
READS = frozenset({"list_dir", "stat", "read_file"})
CONFIG = DeviceBridgeConfig(command_allowlist=["pytest", "ruff"])


def _commander(user="alice", *, unattended=False, tools=READS | {"run_command"}) -> BridgeView:
    executables = frozenset({"pytest"}) if "run_command" in tools else frozenset()
    return BridgeView(user, "dbr_1", "c1", frozenset(tools), unattended, executables)


class CommandRelay:
    def __init__(self, *views: BridgeView) -> None:
        self.views = {view.user_id: view for view in views}
        self.requests: list[dict] = []

    async def view(self, user_id):
        return self.views.get(user_id)

    async def request(self, view, message, *, timeout):
        self.requests.append({**message, "timeout": timeout})
        result = {"exit_code": 0, "timed_out": False, "stdout": "3 passed", "stderr": ""}
        return {"id": message["id"], "user_id": message["user_id"], "ok": True, "result": result}


def _loop(turns, relay=None, *, on=True, rules=None, **kwargs):
    h = harness(turns, approval_evaluator=evaluate_approval, **kwargs)
    h.loop._tools = CodingToolRegistry.default(
        command_allowlist=frozenset({"git"}),
        device_tools=on,
        device_command_allowlist=frozenset(CONFIG.command_allowlist),
    )
    h.loop._device_bridge = DeviceBridgeService(relay, CONFIG) if relay is not None else None
    h.loop._user_rules = rules
    return h


async def _first_request(h, input=OWNED):
    events = [event async for event in h.loop.run(input, None, h.deps)]
    return h.model.requests[0], events


def _run_turns(argv=("pytest", "-q")):
    return [[tool_call("r1", RUN, {"argv": list(argv)}), completed()], [completed()]]


# -- exposure (BC11) -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flag_off_and_a_bridge_without_commands_stay_byte_identical() -> None:
    """BC11. Mutation: always append the command tool (or hang it on the credential instead of
    the declaration) -> `reads` differs from Q16b's read-only bridge."""
    from tests.coding.loop.test_device_bridge_loop import StubRelay, _view
    from tests.coding.loop.test_device_bridge_loop import _first_request as q16a_first
    from tests.coding.loop.test_device_bridge_loop import _loop as q16a_loop

    off, off_events = await _first_request(_loop(_end_turn(), on=False))
    q16a = await q16a_first(q16a_loop(_end_turn(), on=False))
    reads, read_events = await _first_request(_loop(_end_turn(), CommandRelay(_commander(tools=READS))))
    q16a_reads = await q16a_first(q16a_loop(_end_turn(), StubRelay(_view("alice"))))
    commands, command_events = await _first_request(_loop(_end_turn(), CommandRelay(_commander())))

    assert (off.tools, off.system) == (q16a.tools, q16a.system)
    assert (reads.tools, reads.system) == (q16a_reads.tools, q16a_reads.system)
    assert [t.name for t in commands.tools] == [t.name for t in reads.tools] + [RUN]
    assert commands.system == reads.system
    # The event vocabulary does not grow: same kinds, in the same order, with or without commands.
    assert [e.type for e in off_events] == [e.type for e in read_events] == [e.type for e in command_events]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["autonomous", "background"])
async def test_an_unattended_run_never_sees_the_command_tool(mode) -> None:
    """BC6 exposure. Mutation: strip only the read rule in `_with_device_bridge` -> an opted-in
    bridge shows `device_run_command.v1` to a run nobody watches."""
    request, _events = await _first_request(
        _loop(_end_turn(), CommandRelay(_commander(unattended=True))), replace(OWNED, mode=mode)
    )
    names = [t.name for t in request.tools]

    assert names[-3:] == DEVICE_NAMES and RUN not in names


@pytest.mark.parametrize("phase,shown", [("implement", True), ("verify", True), ("plan", False), ("explore", False)])
def test_phases_that_hide_execute_hide_the_device_command(phase, shown) -> None:
    """Mutation: append device definitions without `commands=` -> PLAN shows a tool its gate
    refuses (`policy_phase_denied`)."""
    from neos.coding.loop._durable.state import AgentLoopState
    from neos.coding.phases import tool_allowed_in_phase

    h = _loop(_end_turn(), CommandRelay(_commander()))
    state = AgentLoopState((), 0, 0, 0, (), 0, "", phase=phase, device_bridge=_commander())
    names = [getattr(d, "name", d) for d in h.loop._tool_definitions(state)]

    assert "device_read_file.v1" in names and (RUN in names) is shown
    assert tool_allowed_in_phase(RUN, phase) is shown
    assert tool_allowed_in_phase("execute.v1", phase) is shown


# -- calls (BC5 · BC6 · BC10) ----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_device_command_waits_for_a_person_then_runs_once() -> None:
    """BC5. Mutation: let auto/operator allow (or a remembered approval) pass device commands
    -> the command crosses the wire on the first step."""
    relay = CommandRelay(_commander())
    h = _loop(_run_turns(), relay, config=None)

    events = [e async for e in h.loop.run(OWNED, None, h.deps)]
    assert [e.type for e in events if e.type == "approval.requested"] == ["approval.requested"]
    assert relay.requests == []

    requested = next(iter(h.repository.approvals.values()))
    assert requested.display_summary["arguments"] == ["pytest", "-q"]
    await h.repository.resolve_tool_approval(
        task_id=OWNED.task_id,
        approval_id=requested.approval_id,
        owner_id="test-owner",
        decision=ApprovalDecision.APPROVE,
        now=NOW + timedelta(seconds=1),
        remember=True,
    )
    _ = [e async for e in h.loop.run(OWNED, h.repository.checkpoints[-1], h.deps)]

    [sent] = relay.requests
    assert sent["tool"] == "run_command" and sent["unattended"] is False
    assert sent["args"] == {"argv": ["pytest", "-q"], "cwd": ".", "timeout_sec": 60.0, "max_output_bytes": 65_536}
    assert sent["timeout"] == 60.0 + CONFIG.call_timeout_seconds
    assert h.executor.calls == []


@pytest.mark.asyncio
async def test_an_unattended_command_by_name_is_denied_even_with_the_owners_argv_rule() -> None:
    """BC6 at the gate, in the loop. Mutation: let the owner's rule run before the unattended
    rule -> the device runs a command with nobody watching."""
    rules = InMemoryUserRuleStore()
    await rules.create("alice", effect="allow", tool=RUN, argv_prefix=["pytest"])
    relay = CommandRelay(_commander(unattended=True))
    h = _loop(_run_turns(), relay, rules=rules)

    events = await _until_tool_event(h, replace(OWNED, mode="autonomous"))

    assert [e.payload["reason_code"] for e in events if e.type == "tool.denied"] == [
        "policy_device_command_unattended"
    ]
    assert relay.requests == []


@pytest.mark.asyncio
async def test_the_owners_argv_rule_runs_an_interactive_command_without_asking() -> None:
    rules = InMemoryUserRuleStore()
    await rules.create("alice", effect="allow", tool=RUN, argv_prefix=["pytest"])
    relay = CommandRelay(_commander())
    h = _loop(_run_turns(), relay, rules=rules)

    events = await _until_tool_event(h, OWNED)

    assert not [e for e in events if e.type == "approval.requested"]
    assert [r["tool"] for r in relay.requests] == ["run_command"]
    [completed_event] = [e for e in events if e.type == "tool.completed"]
    assert "arguments" not in repr(completed_event.payload)


@pytest.mark.asyncio
async def test_a_device_command_holds_its_claim_for_its_whole_time_limit() -> None:
    """BC10. Mutation: claim a device command with the ordinary tool TTL -> the claim lapses
    while the command may still run, and a retry ends it as `tool_outcome_unknown`."""
    rules = InMemoryUserRuleStore()
    await rules.create("alice", effect="allow", tool=RUN, argv_prefix=["pytest"])
    h = _loop(_run_turns(), CommandRelay(_commander()), rules=rules)
    ttls: list[float] = []
    original = h.repository.claim_tool_execution

    async def spy(*, lease, tool_call_id, now, claim_expires_at):
        ttls.append((claim_expires_at - now).total_seconds())
        return await original(
            lease=lease, tool_call_id=tool_call_id, now=now, claim_expires_at=claim_expires_at
        )

    h.repository.claim_tool_execution = spy
    _ = await _until_tool_event(h, OWNED)

    expected = CONFIG.command_timeout_seconds + CONFIG.call_timeout_seconds + 30
    assert ttls and min(ttls) >= expected - 1


@pytest.mark.asyncio
async def test_device_commands_are_never_speculative() -> None:
    """B13 holds for commands: neither the read-only batch nor prefetch takes them."""
    from neos.coding.loop._durable.state import AgentLoopState
    from neos.coding.model.base import ToolCallCompleted

    h = _loop(_end_turn(), CommandRelay(_commander()))
    call = ToolCallCompleted("r1", RUN, {"argv": ["pytest"]})
    state = AgentLoopState(
        (), 0, 0, 0, (call, call), 0, "", phase="implement", device_bridge=_commander()
    )
    assert h.loop._maybe_prefetch_readonly(call, None, state) is None
    assert h.loop._leading_readonly_batch(state) is None


# -- children (B11 holds for commands) -------------------------------------------------


@pytest.mark.asyncio
async def test_a_child_cannot_run_a_command_on_the_device(tmp_path: Path, monkeypatch) -> None:
    """B11 for commands: the child gate refuses by name. Mutation: drop the child-gate check ->
    the widened spec lets the child reach the commanding bridge."""
    from dataclasses import replace as replace_spec

    from neos.coding.subagent_port import CodingToolPort
    from neos.subagent.catalog import _SPECS, IMPLEMENT, SpecRegistry
    from neos.subagent.memory import InMemorySubagentStore
    from neos.subagent.ports import SystemClock
    from neos.subagent.runtime import SubagentRuntime
    from neos.subagent.stepper import ChildStepper
    from tests.coding.loop.support import Bindings
    from tests.coding.loop.test_child_gate import _child_calls, _denials, _PortExecutor, _spawn
    from tests.coding.loop.test_spawn_subagent import (
        ScriptedCodingModel,
        _flag_on,
        _init_repo,
        _NullSink,
        _text,
    )

    executor = _PortExecutor()
    port = CodingToolPort(
        registry=CodingToolRegistry.default(
            command_allowlist=frozenset({"git"}),
            device_tools=True,
            device_command_allowlist=frozenset({"pytest"}),
        ),
        executor=executor,
    )
    widened = replace_spec(IMPLEMENT, allowed_tools=IMPLEMENT.allowed_tools | {RUN})
    monkeypatch.setitem(_SPECS, "implement", widened)
    runtime = SubagentRuntime(
        store=InMemorySubagentStore(),
        catalog=SpecRegistry(),
        stepper=ChildStepper(
            model=ScriptedCodingModel([_child_calls(RUN, {"argv": ["pytest"]}), _text("done")]),
            tools=port,
        ),
        events=_NullSink(),
        clock=SystemClock(),
    )
    relay = CommandRelay(_commander(unattended=True))
    h = harness(
        _spawn("implement"),
        config=_flag_on(approval_allow_tools=("spawn_agent.v1",)),
        subagents=runtime,
        bindings=Bindings(workspace=_init_repo(tmp_path)),
        approval_evaluator=evaluate_approval,
    )
    h.loop._tools = port._registry
    h.loop._device_bridge = DeviceBridgeService(relay, CONFIG)

    checkpoint = None
    for _ in range(8):
        events = [e async for e in h.loop.run(OWNED, checkpoint, h.deps)]
        if _denials(h) or any(e.type == "tool.completed" for e in events):
            break
        if any(e.type == "approval.requested" for e in events):
            requested = next(iter(h.repository.approvals.values()))
            await h.repository.resolve_tool_approval(
                task_id=OWNED.task_id,
                approval_id=requested.approval_id,
                owner_id="test-owner",
                decision=ApprovalDecision.APPROVE,
                now=NOW + timedelta(seconds=1),
                remember=False,
            )
        checkpoint = h.repository.checkpoints[-1]

    assert executor.calls == [] and relay.requests == []
    assert [d.payload["reason_code"] for d in _denials(h)] == ["policy_device_child"]

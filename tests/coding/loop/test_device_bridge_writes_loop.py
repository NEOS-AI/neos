"""Q16b in the loop: the device write tool -- exposure, approval, unattended refusal, children.

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
from tests.coding.loop.support import NOW, completed, tool_call
from tests.coding.loop.test_device_bridge_loop import (
    DEVICE_NAMES,
    OWNED,
    _end_turn,
    _first_request,
    _loop,
    _until_tool_event,
)

pytestmark = pytest.mark.no_db

WRITE = "device_write_file.v1"
SHA = "b" * 64
ALL_FOUR = frozenset({"list_dir", "stat", "read_file", "write_file"})


def _writer(user="alice", *, unattended=False) -> BridgeView:
    return BridgeView(user, "dbr_1", "c1", ALL_FOUR, unattended)


class WriteRelay:
    def __init__(self, *views: BridgeView) -> None:
        self.views = {view.user_id: view for view in views}
        self.requests: list[dict] = []

    async def view(self, user_id):
        return self.views.get(user_id)

    async def request(self, view, message, *, timeout):
        self.requests.append(dict(message))
        result = {"sha256": "c" * 64, "size": 3, "created": False}
        return {"id": message["id"], "user_id": message["user_id"], "ok": True, "result": result}


def _write_turns(path="notes.md"):
    args = {"path": path, "content": "new", "base_sha256": SHA}
    return [[tool_call("w1", WRITE, args), completed()], [completed()]]


# -- exposure --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_writing_bridge_adds_the_write_tool_after_the_reads() -> None:
    reads = await _first_request(_loop(_end_turn(), _ReadOnly()))
    writes = await _first_request(_loop(_end_turn(), WriteRelay(_writer())))

    assert [t.name for t in writes.tools] == [t.name for t in reads.tools] + [WRITE]
    assert writes.system == reads.system


class _ReadOnly(WriteRelay):
    def __init__(self) -> None:
        super().__init__(BridgeView("alice", "dbr_1", "c1", ALL_FOUR - {"write_file"}, False))


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["autonomous", "background"])
async def test_an_unattended_run_never_sees_the_write_tool(mode) -> None:
    """BW4 exposure. Mutation: strip only the read rule in `_with_device_bridge` -> an opted-in
    bridge shows `device_write_file.v1` to a run nobody watches."""
    request = await _first_request(
        _loop(_end_turn(), WriteRelay(_writer(unattended=True))), replace(OWNED, mode=mode)
    )
    names = [t.name for t in request.tools]

    assert names[-3:] == DEVICE_NAMES and WRITE not in names


@pytest.mark.parametrize("phase,shown", [("implement", True), ("plan", False), ("explore", False), ("verify", False)])
def test_phases_that_block_writes_hide_the_device_write(phase, shown) -> None:
    """Mutation: append device definitions without `writes=` -> PLAN shows a tool its gate
    will refuse (`policy_phase_denied` via `write_risk_blocked`)."""
    from neos.coding.loop._durable.state import AgentLoopState

    h = _loop(_end_turn(), WriteRelay(_writer()))
    state = AgentLoopState((), 0, 0, 0, (), 0, "", phase=phase, device_bridge=_writer())
    names = [getattr(d, "name", d) for d in h.loop._tool_definitions(state)]

    assert ("device_read_file.v1" in names) and ((WRITE in names) is shown)


# -- calls -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_device_write_waits_for_a_person_then_runs_once() -> None:
    """BW3. Mutation: let auto/operator allow pass device writes -> no approval, the write
    crosses the wire on the first step. Remembering the approval does not waive the next one."""
    relay = WriteRelay(_writer())
    h = _loop(_write_turns(), relay, config=None)

    events = [e async for e in h.loop.run(OWNED, None, h.deps)]
    assert [e.type for e in events if e.type == "approval.requested"] == ["approval.requested"]
    assert relay.requests == []

    requested = next(iter(h.repository.approvals.values()))
    assert requested.display_summary["path"] == "notes.md"
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
    assert sent["tool"] == "write_file" and sent["unattended"] is False
    assert sent["args"]["base_sha256"] == SHA and sent["args"]["max_bytes"] == 262_144
    assert h.executor.calls == []


@pytest.mark.asyncio
async def test_an_unattended_write_by_name_is_denied_even_with_the_owners_allow() -> None:
    """BW4 at the gate, in the loop. Mutation: let the owner's allow rule run before the
    unattended rule -> the device is written with nobody watching."""
    rules = InMemoryUserRuleStore()
    await rules.create("alice", effect="allow", tool=WRITE)
    relay = WriteRelay(_writer(unattended=True))
    h = _loop(_write_turns(), relay, rules=rules)

    events = await _until_tool_event(h, replace(OWNED, mode="autonomous"))

    assert [e.payload["reason_code"] for e in events if e.type == "tool.denied"] == [
        "policy_device_write_unattended"
    ]
    assert relay.requests == []


@pytest.mark.asyncio
async def test_the_owners_allow_rule_runs_an_interactive_write_without_asking() -> None:
    rules = InMemoryUserRuleStore()
    await rules.create("alice", effect="allow", tool=WRITE)
    relay = WriteRelay(_writer())
    h = _loop(_write_turns(), relay, rules=rules)

    events = await _until_tool_event(h, OWNED)

    assert not [e for e in events if e.type == "approval.requested"]
    assert [r["tool"] for r in relay.requests] == ["write_file"]


# -- children (B11 holds for writes) ---------------------------------------------------


@pytest.mark.asyncio
async def test_a_child_cannot_write_to_the_device(tmp_path: Path, monkeypatch) -> None:
    """B11 for writes: the child gate refuses by name, whatever the risk. Mutation: drop the
    child-gate check -> the widened spec lets the child reach the writing bridge."""
    from dataclasses import replace as replace_spec

    from neos.coding.subagent_port import CodingToolPort
    from neos.subagent.catalog import _SPECS, IMPLEMENT, SpecRegistry
    from neos.subagent.memory import InMemorySubagentStore
    from neos.subagent.ports import SystemClock
    from neos.subagent.runtime import SubagentRuntime
    from neos.subagent.stepper import ChildStepper
    from tests.coding.loop.support import Bindings, harness
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
        registry=CodingToolRegistry.default(command_allowlist=frozenset({"git"}), device_tools=True),
        executor=executor,
    )
    widened = replace_spec(IMPLEMENT, allowed_tools=IMPLEMENT.allowed_tools | {WRITE})
    monkeypatch.setitem(_SPECS, "implement", widened)
    runtime = SubagentRuntime(
        store=InMemorySubagentStore(),
        catalog=SpecRegistry(),
        stepper=ChildStepper(
            model=ScriptedCodingModel(
                [_child_calls(WRITE, {"path": "notes.md", "content": "x", "base_sha256": SHA}), _text("done")]
            ),
            tools=port,
        ),
        events=_NullSink(),
        clock=SystemClock(),
    )
    relay = WriteRelay(_writer(unattended=True))
    h = harness(
        _spawn("implement"),
        config=_flag_on(approval_allow_tools=("spawn_agent.v1",)),
        subagents=runtime,
        bindings=Bindings(workspace=_init_repo(tmp_path)),
        approval_evaluator=evaluate_approval,
    )
    h.loop._tools = port._registry
    h.loop._device_bridge = DeviceBridgeService(relay, DeviceBridgeConfig())

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

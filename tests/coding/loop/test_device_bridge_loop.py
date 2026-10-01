"""Q16a in the loop: device tools exist only for the owner's connected bridge.

Real `evaluate_approval`, real registry, real `DeviceBridgeService`; the relay is a
stub that records what would cross the wire. The sandbox executor must never see a
device call.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from neos.coding.application.user_rules import InMemoryUserRuleStore
from neos.coding.bridge.relay import BridgeView
from neos.coding.bridge.service import DeviceBridgeService
from neos.coding.domain.approvals import evaluate_approval
from neos.coding.model.base import ModelCompleted, ModelUsage
from neos.coding.tools.registry import CodingToolRegistry
from neos.config.schema import DeviceBridgeConfig
from tests.coding.loop.test_anthropic_loop import (
    INPUT,
    Bindings,
    completed,
    harness,
    tool_call,
)
from tests.coding.loop.test_child_gate import _child_calls, _denials, _spawn
from tests.coding.loop.test_spawn_subagent import _flag_on, _init_repo, _text

pytestmark = pytest.mark.no_db

OWNED = replace(INPUT, owner_id="alice")
DEVICE_NAMES = ["device_list_dir.v1", "device_stat.v1", "device_read_file.v1"]


def _view(user="alice", *, unattended=False) -> BridgeView:
    return BridgeView(
        user_id=user,
        bridge_id="dbr_1",
        conn_id="c1",
        tools=frozenset({"list_dir", "stat", "read_file"}),
        allow_unattended=unattended,
    )


class StubRelay:
    def __init__(self, *views: BridgeView) -> None:
        self.views = {view.user_id: view for view in views}
        self.requests: list[dict] = []

    async def view(self, user_id):
        return self.views.get(user_id)

    async def request(self, view, message, *, timeout):
        self.requests.append(dict(message))
        return {
            "id": message["id"],
            "user_id": message["user_id"],
            "ok": True,
            "result": {"text": f"contents of {message['args']['path']}", "truncated": False, "size": 9},
        }


def _loop(turns, relay=None, *, on=True, rules=None, **kwargs):
    h = harness(turns, approval_evaluator=evaluate_approval, **kwargs)
    h.loop._tools = CodingToolRegistry.default(
        command_allowlist=frozenset({"git"}), device_tools=on
    )
    h.loop._device_bridge = (
        DeviceBridgeService(relay, DeviceBridgeConfig()) if relay is not None else None
    )
    h.loop._user_rules = rules
    return h


def _end_turn():
    return [[ModelCompleted("end_turn", ModelUsage(5, 3))]]


async def _first_request(h, input=OWNED):
    _ = [event async for event in h.loop.run(input, None, h.deps)]
    return h.model.requests[0]


async def _until_tool_event(h, input):
    checkpoint = None
    seen = []
    for _ in range(4):
        events = [event async for event in h.loop.run(input, checkpoint, h.deps)]
        seen.extend(events)
        if any(e.type in {"tool.completed", "tool.denied"} for e in events):
            return seen
        checkpoint = h.repository.checkpoints[-1]
    raise AssertionError("no tool event")


# -- exposure (B4 · B12) ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_flag_off_and_no_bridge_send_byte_identical_requests() -> None:
    """B12. Mutation: expose device tools whenever the flag is on -> `no-bridge` differs."""
    off = await _first_request(_loop(_end_turn(), on=False))
    no_bridge = await _first_request(_loop(_end_turn(), StubRelay()))
    someone_else = await _first_request(_loop(_end_turn(), StubRelay(_view("bob"))))

    assert off.tools == no_bridge.tools == someone_else.tools
    assert off.system == no_bridge.system == someone_else.system
    assert not [t for t in off.tools if t.name.startswith("device_")]


@pytest.mark.asyncio
async def test_the_owners_connected_bridge_adds_its_tools_at_the_end() -> None:
    off = await _first_request(_loop(_end_turn(), on=False))
    mine = await _first_request(_loop(_end_turn(), StubRelay(_view("alice"))))

    assert [t.name for t in mine.tools] == [t.name for t in off.tools] + DEVICE_NAMES
    assert mine.system == off.system


@pytest.mark.asyncio
async def test_an_unattended_run_does_not_see_a_bridge_that_did_not_opt_in() -> None:
    hidden = await _first_request(
        _loop(_end_turn(), StubRelay(_view("alice"))), replace(OWNED, mode="background")
    )
    opted = await _first_request(
        _loop(_end_turn(), StubRelay(_view("alice", unattended=True))), replace(OWNED, mode="background")
    )

    assert not [t for t in hidden.tools if t.name.startswith("device_")]
    assert [t.name for t in opted.tools][-3:] == DEVICE_NAMES


# -- calls (B4 · B7 · B9) --------------------------------------------------------------


def _read_turns(path="notes.md"):
    return [[tool_call("d1", "device_read_file.v1", {"path": path}), completed()], [completed()]]


@pytest.mark.asyncio
async def test_a_device_read_goes_to_the_bridge_not_the_sandbox_and_is_recorded_wrapped() -> None:
    relay = StubRelay(_view("alice"))
    h = _loop(_read_turns(), relay)

    events = await _until_tool_event(h, OWNED)

    [done] = [e for e in events if e.type == "tool.completed"]
    assert h.executor.calls == []
    assert relay.requests[0]["user_id"] == "alice" and relay.requests[0]["tool"] == "read_file"
    assert relay.requests[0]["unattended"] is False
    stored = repr([c.loop_state for c in h.repository.checkpoints])
    assert "begin untrusted device content" in stored and "contents of notes.md" in stored
    assert done.payload["name"] == "device_read_file.v1"


@pytest.mark.asyncio
async def test_another_users_task_never_reaches_this_bridge() -> None:
    """B4. Mutation: route by any live bridge -> bob's call reaches alice's device."""
    relay = StubRelay(_view("alice"))
    h = _loop(_read_turns(), relay)

    events = await _until_tool_event(h, replace(OWNED, owner_id="bob"))

    assert relay.requests == []
    assert "device_bridge_unavailable" in repr([c.loop_state for c in h.repository.checkpoints])
    assert [e.type for e in events if e.type == "tool.completed"]


@pytest.mark.asyncio
async def test_unattended_call_by_name_is_denied_with_its_own_reason() -> None:
    """B7. Hidden from the list *and* denied by the gate when called by name."""
    relay = StubRelay(_view("alice"))
    h = _loop(_read_turns(), relay)

    events = await _until_tool_event(h, replace(OWNED, mode="autonomous"))

    assert [e.payload["reason_code"] for e in events if e.type == "tool.denied"] == [
        "policy_device_unattended"
    ]
    assert relay.requests == []


@pytest.mark.asyncio
async def test_opted_in_background_read_runs_and_says_so() -> None:
    relay = StubRelay(_view("alice", unattended=True))
    h = _loop(_read_turns(), relay)

    await _until_tool_event(h, replace(OWNED, mode="background"))

    assert relay.requests[0]["unattended"] is True


@pytest.mark.asyncio
async def test_the_owners_block_rule_applies_to_device_tools() -> None:
    rules = InMemoryUserRuleStore()
    await rules.create("alice", effect="block", tool="device_read_file.v1")
    relay = StubRelay(_view("alice"))
    h = _loop(_read_turns(), relay, rules=rules)

    events = await _until_tool_event(h, OWNED)

    assert [e.payload["reason_code"] for e in events if e.type == "tool.denied"] == [
        "policy_user_rule_blocked"
    ]
    assert relay.requests == []


@pytest.mark.asyncio
async def test_a_secret_reference_is_refused_before_anything_leaves() -> None:
    relay = StubRelay(_view("alice"))
    h = _loop(_read_turns("secret://github"), relay)

    events = await _until_tool_event(h, OWNED)

    assert [e.payload["reason_code"] for e in events if e.type == "tool.denied"] == [
        "policy_device_secret_ref"
    ]
    assert relay.requests == []


@pytest.mark.asyncio
async def test_device_reads_are_never_speculative() -> None:
    """Two read-only calls in one turn normally batch and prefetch; device calls must not --
    the batch path carries no owner. Mutation: drop the batch exclusion -> the second call
    reaches the stub with no owner (or not at all) and the result is `device_bridge_unavailable`."""
    relay = StubRelay(_view("alice"))
    h = _loop(
        [
            [
                tool_call("d1", "device_read_file.v1", {"path": "a.md"}),
                tool_call("d2", "device_read_file.v1", {"path": "b.md"}),
                completed(),
            ],
            [completed()],
            [completed()],
        ],
        relay,
    )

    checkpoint = None
    for _ in range(4):
        _ = [e async for e in h.loop.run(OWNED, checkpoint, h.deps)]
        checkpoint = h.repository.checkpoints[-1]
        if len(relay.requests) == 2:
            break

    assert [r["args"]["path"] for r in relay.requests] == ["a.md", "b.md"]
    assert all(r["user_id"] == "alice" for r in relay.requests)
    assert "device_bridge_unavailable" not in repr([c.loop_state for c in h.repository.checkpoints])


# -- children (B11) --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_child_cannot_reach_the_device_even_with_an_opted_in_bridge(
    tmp_path: Path, monkeypatch
) -> None:
    """B11. Three walls: no child definitions, no spec lists a device tool, and the child
    gate. The spec here *does* list one, so the gate is what is tested.
    Mutation: drop the child-gate check -> the opted-in bridge lets the child read it."""
    from dataclasses import replace as replace_spec

    from neos.coding.subagent_port import CodingToolPort
    from neos.subagent.catalog import _SPECS, EXPLORE, SpecRegistry
    from neos.subagent.memory import InMemorySubagentStore
    from neos.subagent.ports import SystemClock
    from neos.subagent.runtime import SubagentRuntime
    from neos.subagent.stepper import ChildStepper
    from tests.coding.loop.test_child_gate import _PortExecutor
    from tests.coding.loop.test_spawn_subagent import ScriptedCodingModel, _NullSink

    executor = _PortExecutor()
    port = CodingToolPort(
        registry=CodingToolRegistry.default(command_allowlist=frozenset({"git"}), device_tools=True),
        executor=executor,
    )
    assert not [d for d in port._registry.definitions() if d.name.startswith("device_")]
    assert not [name for spec in _SPECS.values() for name in spec.allowed_tools if name.startswith("device_")]
    widened = replace_spec(EXPLORE, allowed_tools=EXPLORE.allowed_tools | {"device_read_file.v1"})
    monkeypatch.setitem(_SPECS, "explore", widened)  # the port looks specs up globally
    catalog = SpecRegistry()
    runtime = SubagentRuntime(
        store=InMemorySubagentStore(),
        catalog=catalog,
        stepper=ChildStepper(
            model=ScriptedCodingModel(
                [_child_calls("device_read_file.v1", {"path": "notes.md"}), _text("done")]
            ),
            tools=port,
        ),
        events=_NullSink(),
        clock=SystemClock(),
    )
    relay = StubRelay(_view("alice", unattended=True))
    h = harness(
        _spawn("explore"),
        config=_flag_on(approval_allow_tools=("spawn_agent.v1",)),
        subagents=runtime,
        bindings=Bindings(workspace=_init_repo(tmp_path)),
        approval_evaluator=evaluate_approval,
    )
    h.loop._tools = port._registry
    h.loop._device_bridge = DeviceBridgeService(relay, DeviceBridgeConfig())

    checkpoint = None
    for _ in range(6):
        events = [e async for e in h.loop.run(OWNED, checkpoint, h.deps)]
        if any(e.type == "tool.completed" for e in events):
            break
        checkpoint = h.repository.checkpoints[-1]

    assert executor.calls == [] and relay.requests == []
    assert [d.payload["reason_code"] for d in _denials(h)] == ["policy_device_child"]

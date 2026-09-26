from __future__ import annotations

from datetime import timedelta

import pytest

from neos.coding.domain.approvals import (
    ApprovalDecision,
    ApprovalGate,
    ApprovalPolicyOutcome,
    approval_remember_key,
    evaluate_approval,
)
from neos.coding.tools.registry import ToolRisk, ValidatedToolCall
from tests.coding.loop.test_anthropic_loop import (
    NOW,
    collect,
    completed,
    harness,
    tool_call,
)

pytestmark = pytest.mark.no_db


def _call(name: str, input: dict[str, object], risk: ToolRisk) -> ValidatedToolCall:
    return ValidatedToolCall(name=name, input=input, risk=risk)


def test_remember_key_scopes_write_path_and_execute_token() -> None:
    write = _call(
        "write_file.v1",
        {"path": "foo.py", "content": "x"},
        ToolRisk.WORKSPACE_WRITE,
    )
    execute = _call("execute.v1", {"argv": ["pytest", "-q"]}, ToolRisk.COMMAND)
    phase = _call("set_phase.v1", {"phase": "verify"}, ToolRisk.READ_ONLY)

    assert approval_remember_key(write) == "write_file.v1:foo.py"
    assert approval_remember_key(execute) == "execute.v1:pytest"
    assert approval_remember_key(phase) == "set_phase.v1"


def test_scoped_remember_does_not_allow_other_write_paths() -> None:
    foo = _call(
        "write_file.v1",
        {"path": "foo.py", "content": "x"},
        ToolRisk.WORKSPACE_WRITE,
    )
    bar = _call(
        "write_file.v1",
        {"path": "bar.py", "content": "y"},
        ToolRisk.WORKSPACE_WRITE,
    )
    gate = ApprovalGate(approved_always=frozenset({"write_file.v1:foo.py"}))

    assert evaluate_approval(foo, gate) is ApprovalPolicyOutcome.ALLOW
    assert evaluate_approval(bar, gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL


def test_execute_remember_is_first_argv_token() -> None:
    pytest_run = _call("execute.v1", {"argv": ["pytest", "-q"]}, ToolRisk.COMMAND)
    ruff = _call("execute.v1", {"argv": ["ruff", "check"]}, ToolRisk.COMMAND)
    gate = ApprovalGate(approved_always=frozenset({"execute.v1:pytest"}))

    assert evaluate_approval(pytest_run, gate) is ApprovalPolicyOutcome.ALLOW
    assert evaluate_approval(ruff, gate) is ApprovalPolicyOutcome.REQUIRE_APPROVAL


def test_tool_name_only_remember_still_works_without_path() -> None:
    phase = _call("set_phase.v1", {"phase": "verify"}, ToolRisk.READ_ONLY)
    gate = ApprovalGate(
        current_phase="plan",
        approved_always=frozenset({"set_phase.v1"}),
    )

    assert evaluate_approval(phase, gate) is ApprovalPolicyOutcome.ALLOW


@pytest.mark.asyncio
async def test_remember_write_approval_allows_same_path_again() -> None:
    h = harness(
        [
            [tool_call("w1", input={"path": "foo.py", "content": "x"}), completed()],
            [
                tool_call("w2", input={"path": "foo.py", "content": "y"}),
                completed(),
            ],
        ],
        approval_evaluator=evaluate_approval,
    )
    await collect(h)
    requested = next(iter(h.repository.approvals.values()))
    await h.repository.resolve_tool_approval(
        task_id="ct_1",
        approval_id=requested.approval_id,
        owner_id="test-owner",
        decision=ApprovalDecision.APPROVE,
        now=NOW + timedelta(seconds=1),
        remember=True,
    )

    await collect(h, h.repository.checkpoints[-1])
    events = await collect(h, h.repository.checkpoints[-1])
    assert not any(event.type == "approval.requested" for event in events)
    assert h.bindings.session.writes == 2


@pytest.mark.asyncio
async def test_remember_write_approval_is_scoped_to_path() -> None:
    h = harness(
        [
            [tool_call("w1", input={"path": "foo.py", "content": "x"}), completed()],
            [
                tool_call("w2", input={"path": "bar.py", "content": "y"}),
                completed(),
            ],
        ],
        approval_evaluator=evaluate_approval,
    )
    await collect(h)
    requested = next(iter(h.repository.approvals.values()))
    await h.repository.resolve_tool_approval(
        task_id="ct_1",
        approval_id=requested.approval_id,
        owner_id="test-owner",
        decision=ApprovalDecision.APPROVE,
        now=NOW + timedelta(seconds=1),
        remember=True,
    )

    await collect(h, h.repository.checkpoints[-1])
    remembered = h.repository.checkpoints[-1].loop_state["approved_always"]
    assert "write_file.v1:foo.py" in remembered
    assert "write_file.v1" not in remembered

    events = await collect(h, h.repository.checkpoints[-1])
    assert any(event.type == "approval.requested" for event in events)
    assert h.bindings.session.writes == 1


@pytest.mark.asyncio
async def test_remember_execute_approval_is_scoped_to_executable() -> None:
    h = harness(
        [
            [
                tool_call("e1", "execute.v1", {"argv": ["pytest", "-q"]}),
                completed(),
            ],
            [
                tool_call("e2", "execute.v1", {"argv": ["ruff", "check"]}),
                completed(),
            ],
        ],
        approval_evaluator=evaluate_approval,
        command_allowlist=frozenset({"pytest", "ruff"}),
    )
    await collect(h)
    requested = next(iter(h.repository.approvals.values()))
    await h.repository.resolve_tool_approval(
        task_id="ct_1",
        approval_id=requested.approval_id,
        owner_id="test-owner",
        decision=ApprovalDecision.APPROVE,
        now=NOW + timedelta(seconds=1),
        remember=True,
    )

    await collect(h, h.repository.checkpoints[-1])
    remembered = h.repository.checkpoints[-1].loop_state["approved_always"]
    assert "execute.v1:pytest" in remembered

    events = await collect(h, h.repository.checkpoints[-1])
    assert any(event.type == "approval.requested" for event in events)

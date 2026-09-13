from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from neos.subagent.types import (
    FoldedResult,
    LineageKind,
    ModelPin,
    ParentBriefing,
    ParentKind,
    SandboxMode,
    StepKind,
    StepOutcome,
    SubagentSnapshot,
    SubagentStatus,
    SubagentTicket,
)


pytestmark = pytest.mark.no_db


def _briefing(**overrides) -> ParentBriefing:
    payload = {"goal": "Find how auth works"}
    payload.update(overrides)
    return ParentBriefing(**payload)


def _ticket(**overrides) -> SubagentTicket:
    payload = {
        "parent_kind": ParentKind.CODING,
        "parent_id": "ct_parent",
        "parent_run_id": "cr_parent",
        "parent_tool_call_id": "toolu_1",
        "spec": "explore",
        "briefing": _briefing(),
        "model": ModelPin(provider="anthropic", model="claude-test"),
    }
    payload.update(overrides)
    return SubagentTicket(**payload)


def test_parent_briefing_requires_nonempty_goal() -> None:
    with pytest.raises(ValueError, match="goal"):
        ParentBriefing(goal="   ")


def test_parent_briefing_rejects_budget_out_of_range() -> None:
    with pytest.raises(ValueError, match="report_budget_chars"):
        ParentBriefing(goal="inspect", report_budget_chars=255)
    with pytest.raises(ValueError, match="report_budget_chars"):
        ParentBriefing(goal="inspect", report_budget_chars=16_385)


def test_parent_briefing_accepts_budget_bounds() -> None:
    low = ParentBriefing(goal="inspect", report_budget_chars=256)
    high = ParentBriefing(goal="inspect", report_budget_chars=16_384)
    assert low.report_budget_chars == 256
    assert high.report_budget_chars == 16_384


def test_model_pin_requires_provider_and_model() -> None:
    with pytest.raises(ValueError, match="model pin"):
        ModelPin(provider="anthropic", model="")
    with pytest.raises(ValueError, match="model pin"):
        ModelPin(provider="", model="claude-test")  # type: ignore[arg-type]


def test_ticket_requires_delegate_lineage() -> None:
    with pytest.raises(ValueError, match="delegate"):
        _ticket(lineage_kind=LineageKind.COMPRESSION)
    with pytest.raises(ValueError, match="delegate"):
        _ticket(lineage_kind=LineageKind.BRANCH)


def test_ticket_clamps_max_turns_to_one_through_eight() -> None:
    with pytest.raises(ValueError, match="max_turns"):
        _ticket(max_turns=0)
    with pytest.raises(ValueError, match="max_turns"):
        _ticket(max_turns=9)
    assert _ticket(max_turns=1).max_turns == 1
    assert _ticket(max_turns=8).max_turns == 8


def test_ticket_has_no_channel_fields() -> None:
    ticket = _ticket()
    assert not hasattr(ticket, "session_key")
    assert not hasattr(ticket, "chat_id")
    assert not hasattr(ticket, "thread_id")
    assert not hasattr(ticket, "channel_id")


def test_p1_enums_match_design() -> None:
    assert ParentKind.CODING == "coding"
    assert ParentKind.DEEP_ANALYSIS == "deep_analysis"
    assert LineageKind.DELEGATE == "delegate"
    assert set(SubagentStatus) == {
        SubagentStatus.PENDING,
        SubagentStatus.RUNNING,
        SubagentStatus.COMPLETED,
        SubagentStatus.FAILED,
        SubagentStatus.KILLED,
    }
    assert set(StepKind) == {
        StepKind.CONTINUING,
        StepKind.COMPLETED,
        StepKind.FAILED,
        StepKind.CANCELLED,
    }
    assert SandboxMode.NONE == "none"
    assert SandboxMode.PARENT_RO == "parent_ro"
    assert SandboxMode.WORKTREE == "worktree"


def test_ticket_spawn_depth_defaults_to_zero_and_rejects_negative() -> None:
    ticket = _ticket()
    assert ticket.spawn_depth == 0
    nested = _ticket(spawn_depth=1)
    assert nested.spawn_depth == 1
    with pytest.raises(ValueError, match="spawn_depth"):
        _ticket(spawn_depth=-1)
    with pytest.raises(ValueError, match="spawn_depth"):
        _ticket(spawn_depth=2)


def test_public_dataclasses_are_frozen() -> None:
    ticket = _ticket()
    with pytest.raises(FrozenInstanceError):
        ticket.max_turns = 2  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        StepOutcome(
            kind=StepKind.COMPLETED,
            run_id="sa_1",
            checkpoint_id="sc_1",
            status=SubagentStatus.COMPLETED,
            turn_count=1,
            tool_count=0,
        ).turn_count = 2  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        SubagentSnapshot(
            run_id="sa_1",
            status=SubagentStatus.PENDING,
            spec="explore",
            parent_kind=ParentKind.CODING,
            parent_id="ct_1",
            parent_tool_call_id="toolu_1",
            checkpoint_id=None,
            turn_count=0,
            max_turns=4,
            input_tokens=0,
            output_tokens=0,
            cost_micros=0,
        ).status = SubagentStatus.RUNNING  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        FoldedResult(
            run_id="sa_1",
            status=SubagentStatus.COMPLETED,
            summary="done",
            truncated=False,
        ).summary = "nope"  # type: ignore[misc]


def test_folded_result_defaults_exit_reason_and_full_summary() -> None:
    result = FoldedResult(
        run_id="sa_1",
        status=SubagentStatus.COMPLETED,
        summary="done",
        truncated=False,
    )
    assert result.exit_reason == ""
    assert result.full_summary == ""


def test_folded_result_accepts_exit_reason_and_full_summary() -> None:
    result = FoldedResult(
        run_id="sa_1",
        status=SubagentStatus.FAILED,
        summary="head",
        truncated=True,
        exit_reason="failed",
        full_summary="head and tail",
    )
    assert result.exit_reason == "failed"
    assert result.full_summary == "head and tail"

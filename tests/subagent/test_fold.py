from __future__ import annotations

from datetime import UTC, datetime

import pytest

from neos.subagent.fold import FoldNotReady, fold_run
from neos.subagent.store import RunRecord
from neos.subagent.types import (
    LineageKind,
    ParentKind,
    SandboxMode,
    SubagentStatus,
)


pytestmark = pytest.mark.no_db


def _record(**overrides) -> RunRecord:
    now = datetime.now(UTC)
    payload = {
        "run_id": "sa_fold",
        "parent_kind": ParentKind.CODING,
        "parent_id": "ct_1",
        "parent_run_id": "cr_1",
        "parent_tool_call_id": "toolu_1",
        "lineage_kind": LineageKind.DELEGATE,
        "spec": "explore",
        "status": SubagentStatus.COMPLETED,
        "provider": "anthropic",
        "model": "claude-test",
        "max_turns": 4,
        "turn_count": 2,
        "tool_count": 1,
        "input_tokens": 10,
        "output_tokens": 4,
        "cost_micros": 7,
        "briefing": {"goal": "inspect", "report_budget_chars": 256},
        "error_code": "",
        "sandbox_mode": SandboxMode.NONE,
        "created_at": now,
        "updated_at": now,
        "completed_at": now,
        "latest_checkpoint_id": "sc_1",
        "latest_seq": 1,
    }
    payload.update(overrides)
    return RunRecord(**payload)


def test_fold_raises_if_not_terminal() -> None:
    with pytest.raises(FoldNotReady):
        fold_run(_record(status=SubagentStatus.PENDING), {"last_assistant_text": "x"})
    with pytest.raises(FoldNotReady):
        fold_run(_record(status=SubagentStatus.RUNNING), {"last_assistant_text": "x"})


def test_fold_truncates_last_assistant_text_to_budget() -> None:
    text = "a" * 300
    first = fold_run(_record(), {"last_assistant_text": text, "citations": ["README.md"]})
    again = fold_run(_record(), {"last_assistant_text": text, "citations": ["README.md"]})
    assert len(first.summary) == 256
    assert first.truncated is True
    assert first.full_summary == text
    assert first.citations == ("README.md",)
    assert first.turn_count == 2
    assert first == again


def test_fold_uses_synthetic_summary_when_assistant_text_missing() -> None:
    cancelled = fold_run(
        _record(status=SubagentStatus.KILLED, error_code="aborted"),
        {"last_assistant_text": ""},
    )
    failed = fold_run(
        _record(status=SubagentStatus.FAILED, error_code="model_provider_failed"),
        {"last_assistant_text": "   "},
    )
    exhausted = fold_run(
        _record(status=SubagentStatus.COMPLETED, error_code="turns_exhausted"),
        {},
    )
    assert cancelled.summary == "cancelled"
    assert failed.summary == "failed"
    assert exhausted.summary == "turns_exhausted"
    assert cancelled.truncated is False


def test_fold_keeps_last_assistant_text_when_present() -> None:
    cancelled = fold_run(
        _record(status=SubagentStatus.KILLED, error_code="aborted"),
        {"last_assistant_text": "found auth in gateway.py"},
    )
    exhausted = fold_run(
        _record(status=SubagentStatus.COMPLETED, error_code="turns_exhausted"),
        {"last_assistant_text": "looking"},
    )
    failed = fold_run(
        _record(status=SubagentStatus.FAILED, error_code="model_provider_failed"),
        {"last_assistant_text": "partial map of the module"},
    )
    assert cancelled.summary == "found auth in gateway.py"
    assert exhausted.summary == "looking"
    assert failed.summary == "partial map of the module"


def test_fold_completed_empty_text_and_error_uses_status() -> None:
    result = fold_run(
        _record(status=SubagentStatus.COMPLETED, error_code=""),
        {"last_assistant_text": ""},
    )
    assert result.summary == "completed"


def test_fold_invalid_budget_and_none_loop_state_does_not_raise() -> None:
    result = fold_run(
        _record(briefing={"goal": "inspect", "report_budget_chars": "nope"}),
        None,
    )
    assert result.summary == "completed"


def test_fold_maps_exit_reason_from_status_and_error_code() -> None:
    completed = fold_run(
        _record(status=SubagentStatus.COMPLETED),
        {"last_assistant_text": "ok"},
    )
    killed = fold_run(
        _record(status=SubagentStatus.KILLED),
        {"last_assistant_text": "ok"},
    )
    exhausted = fold_run(
        _record(status=SubagentStatus.COMPLETED, error_code="turns_exhausted"),
        {"last_assistant_text": "ok"},
    )
    failed = fold_run(
        _record(status=SubagentStatus.FAILED, error_code="model_provider_failed"),
        {"last_assistant_text": "ok"},
    )
    stalled = fold_run(
        _record(status=SubagentStatus.FAILED, error_code="stalled"),
        {"last_assistant_text": "ok"},
    )
    assert completed.exit_reason == "completed"
    assert killed.exit_reason == "cancelled"
    assert exhausted.exit_reason == "turns_exhausted"
    assert failed.exit_reason == "failed"
    assert stalled.exit_reason == "stalled"


def test_fold_default_budget_without_headroom_is_4000() -> None:
    text = "x" * 4000
    result = fold_run(
        _record(briefing={"goal": "inspect"}),
        {"last_assistant_text": text},
    )
    assert result.truncated is False
    assert result.summary == text
    assert result.full_summary == ""
    over = fold_run(
        _record(briefing={"goal": "inspect"}),
        {"last_assistant_text": text + "y"},
    )
    assert over.truncated is True
    assert len(over.summary) == 4000
    assert over.full_summary == text + "y"


def test_fold_headroom_and_siblings_shrink_budget() -> None:
    text = "x" * 500
    result = fold_run(
        _record(briefing={"goal": "inspect"}),
        {"last_assistant_text": text},
        parent_headroom_chars=800,
        sibling_count=2,
    )
    assert result.truncated is True
    assert len(result.summary) == 400


def test_fold_truncation_keeps_head_tail_and_full_summary() -> None:
    text = ("H" * 300) + ("T" * 200)
    result = fold_run(
        _record(briefing={"goal": "inspect"}),
        {"last_assistant_text": text},
        parent_headroom_chars=800,
        sibling_count=2,
    )
    assert result.truncated is True
    assert result.full_summary == text
    assert "\n…\n" in result.summary
    head, tail = result.summary.split("\n…\n")
    assert head == text[:297]
    assert tail == text[-100:]
    assert len(result.summary) == 400

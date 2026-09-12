import pytest

from neos.coding.tools.registry import ToolRisk
from neos.coding.phases import (
    CodingAgentPhase,
    hidden_tools_for_phase,
    parse_phase,
    parse_plan_critical_files,
    parse_verify_verdict,
    persist_plan_critical_files,
    persist_verify_verdict,
    phase_change_requires_approval,
    plan_text_has_body,
    restore_plan_critical_files,
    restore_verify_verdict,
    tool_allowed_in_phase,
    write_risk_blocked,
)

pytestmark = pytest.mark.no_db


def test_explore_hides_writes_and_execute() -> None:
    hidden = hidden_tools_for_phase(CodingAgentPhase.EXPLORE)
    assert "edit_file.v1" in hidden
    assert "write_file.v1" in hidden
    assert "execute.v1" in hidden
    assert tool_allowed_in_phase("read_file.v1", "explore")


def test_verify_allows_execute_but_not_writes() -> None:
    assert not tool_allowed_in_phase("write_file.v1", "verify")
    assert tool_allowed_in_phase("execute.v1", "verify")
    assert tool_allowed_in_phase("write_file.v1", "implement")
    assert parse_phase("nope") is CodingAgentPhase.IMPLEMENT


def test_plan_hides_writes_and_gates_implement() -> None:
    hidden = hidden_tools_for_phase(CodingAgentPhase.PLAN)
    assert "edit_file.v1" in hidden
    assert "execute.v1" in hidden
    assert phase_change_requires_approval("plan", "implement")
    assert phase_change_requires_approval("verify", "implement")
    assert not phase_change_requires_approval("implement", "verify")
    assert write_risk_blocked(ToolRisk.WORKSPACE_WRITE, "plan")
    assert not write_risk_blocked(ToolRisk.WORKSPACE_WRITE, "implement")


def test_parse_verify_verdict_reads_pass_fail_partial() -> None:
    assert (
        parse_verify_verdict("Command: pytest -q\nVERDICT: PASS\n") == "PASS"
    )
    assert parse_verify_verdict("VERDICT: FAIL") == "FAIL"
    assert parse_verify_verdict("notes\nverdict: partial") == "PARTIAL"
    assert parse_verify_verdict("looks good") is None
    assert parse_verify_verdict("") is None


def test_parse_verify_verdict_pass_requires_command_block() -> None:
    assert parse_verify_verdict("ran tests\nVERDICT: PASS\n") is None
    assert parse_verify_verdict("```\npytest -q\n```\nVERDICT: PASS") == "PASS"
    assert parse_verify_verdict("Command:\nVERDICT: PASS") is None
    assert parse_verify_verdict("Command: pytest -q\nVERDICT: PASS") == "PASS"


def test_plan_text_requires_body_beyond_critical_files() -> None:
    assert plan_text_has_body("") is False
    assert plan_text_has_body("## Critical Files:\n- src/app.py\n") is False
    assert plan_text_has_body("Critical Files: src/a.py") is False
    assert (
        plan_text_has_body("Add auth middleware.\n\n## Critical Files:\n- src/app.py\n")
        is True
    )


def test_parse_plan_critical_files_requires_heading() -> None:
    assert parse_plan_critical_files("I will edit src/app.py") is None
    assert parse_plan_critical_files("") is None
    files = parse_plan_critical_files(
        "## Critical Files:\n- src/app.py\n- tests/test_app.py\n"
    )
    assert files == ["src/app.py", "tests/test_app.py"]
    assert parse_plan_critical_files("Critical Files: src/a.py, src/b.py") == [
        "src/a.py",
        "src/b.py",
    ]


def test_persist_verify_verdict_and_restore() -> None:
    assert persist_verify_verdict("notes\nVERDICT: FAIL\n") == "FAIL"
    assert persist_verify_verdict("no verdict") is None
    assert restore_verify_verdict("PASS") == "PASS"
    assert restore_verify_verdict("PARTIAL") == "PARTIAL"
    assert restore_verify_verdict("nope") is None
    assert restore_verify_verdict(None) is None


def test_persist_plan_critical_files_is_empty_tuple_when_missing() -> None:
    assert persist_plan_critical_files("I will edit later") == ()
    assert persist_plan_critical_files("## Critical Files:\n- src/app.py\n") == (
        "src/app.py",
    )
    assert restore_plan_critical_files(["src/a.py", " src/b.py "]) == (
        "src/a.py",
        "src/b.py",
    )
    assert restore_plan_critical_files(None) == ()
    assert restore_plan_critical_files("src/a.py") == ()

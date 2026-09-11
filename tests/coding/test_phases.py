import pytest

from neos.coding.tools.registry import ToolRisk
from neos.coding.phases import (
    CodingAgentPhase,
    hidden_tools_for_phase,
    parse_phase,
    phase_change_requires_approval,
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

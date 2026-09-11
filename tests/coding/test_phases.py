import pytest

from neos.coding.phases import (
    CodingAgentPhase,
    hidden_tools_for_phase,
    parse_phase,
    tool_allowed_in_phase,
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

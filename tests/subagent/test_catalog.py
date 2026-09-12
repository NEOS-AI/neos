from __future__ import annotations

import pytest

from neos.subagent.catalog import EXPLORE, UnknownSpec, lookup_spec
from neos.subagent.types import SandboxMode


pytestmark = pytest.mark.no_db


def test_lookup_explore_returns_p1_spec() -> None:
    spec = lookup_spec("explore")
    assert spec is EXPLORE
    assert spec.name == "explore"
    assert spec.description == "Read-only investigation. Report only. Do not edit."
    assert spec.can_spawn is False
    assert spec.can_approve is False
    assert spec.thinking == "off"
    assert spec.load_project_instructions is False
    assert spec.one_shot is True
    assert spec.sandbox_mode is SandboxMode.PARENT_RO


def test_explore_allowed_tools_are_readonly_plus_da_hosts() -> None:
    assert spec_tools() == frozenset(
        {
            "read_file.v1",
            "search_text.v1",
            "glob_files.v1",
            "list_tree.v1",
            "stat.v1",
            "git_status.v1",
            "git_diff.v1",
            "git_log.v1",
            "search",
            "fetch",
        }
    )


def spec_tools() -> frozenset[str]:
    return lookup_spec("explore").allowed_tools


def test_explore_does_not_grant_write_or_spawn_tools() -> None:
    forbidden = {
        "spawn_agent.v1",
        "edit_file.v1",
        "write_file.v1",
        "execute.v1",
        "ask_user.v1",
        "set_phase.v1",
        "todo_write.v1",
        "web_fetch.v1",
        "search_tools.v1",
    }
    assert lookup_spec("explore").allowed_tools.isdisjoint(forbidden)


def test_unknown_spec_is_fail_closed() -> None:
    with pytest.raises(UnknownSpec) as raised:
        lookup_spec("general-purpose")
    assert raised.value.name == "general-purpose"


def test_one_shot_does_not_mean_stop_after_first_message() -> None:
    spec = lookup_spec("explore")
    assert spec.one_shot is True
    assert "first assistant" not in spec.description.lower()

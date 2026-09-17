from __future__ import annotations

import pytest

from neos.subagent.catalog import EXPLORE, IMPLEMENT, UnknownSpec, lookup_spec, may_spawn
from neos.subagent.types import SandboxMode


pytestmark = pytest.mark.no_db


def test_lookup_explore_returns_p1_spec() -> None:
    spec = lookup_spec("explore")
    assert spec is EXPLORE
    assert spec.name == "explore"
    assert spec.description == "Read-only investigation. Report only. Do not edit."
    assert spec.can_spawn is True
    assert spec.can_approve is False
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
            "spawn_agent.v1",
        }
    )


def spec_tools() -> frozenset[str]:
    return lookup_spec("explore").allowed_tools


def test_explore_does_not_grant_write_tools() -> None:
    forbidden = {
        "subagent_list.v1",
        "subagent_steer.v1",
        "edit_file.v1",
        "write_file.v1",
        "execute.v1",
        "mkdir.v1",
        "rm.v1",
        "mv.v1",
        "chmod.v1",
        "ask_user.v1",
        "set_phase.v1",
        "todo_write.v1",
        "web_fetch.v1",
        "search_tools.v1",
    }
    assert lookup_spec("explore").allowed_tools.isdisjoint(forbidden)
    assert "spawn_agent.v1" in lookup_spec("explore").allowed_tools


def test_unknown_spec_is_fail_closed() -> None:
    with pytest.raises(UnknownSpec) as raised:
        lookup_spec("general-purpose")
    assert raised.value.name == "general-purpose"


def test_lookup_implement_returns_write_spec() -> None:
    spec = lookup_spec("implement")
    assert spec is IMPLEMENT
    assert spec.name == "implement"
    assert spec.can_spawn is False
    assert spec.can_approve is False
    assert spec.load_project_instructions is False
    assert spec.one_shot is True
    assert spec.sandbox_mode is SandboxMode.WORKTREE


def test_specs_do_not_claim_a_thinking_setting_nothing_enforces() -> None:
    """K1d: the field said "off" and no code ever sent it.

    Fable 5.1 cannot disable thinking at all, and Sonnet 5 / Opus 5 think by
    default, so the claim was false on every model a child can run on.
    """
    assert not hasattr(lookup_spec("explore"), "thinking")
    assert not hasattr(lookup_spec("implement"), "thinking")


def test_implement_allowed_tools_include_writes_not_spawn() -> None:
    tools = lookup_spec("implement").allowed_tools
    assert {
        "read_file.v1",
        "search_text.v1",
        "glob_files.v1",
        "list_tree.v1",
        "stat.v1",
        "git_status.v1",
        "git_diff.v1",
        "git_log.v1",
        "edit_file.v1",
        "write_file.v1",
        "execute.v1",
        "mkdir.v1",
        "rm.v1",
        "mv.v1",
        "chmod.v1",
    } <= tools
    assert tools.isdisjoint(
        {
            "spawn_agent.v1",
            "subagent_list.v1",
            "subagent_steer.v1",
            "ask_user.v1",
            "set_phase.v1",
            "todo_write.v1",
            "web_fetch.v1",
            "search_tools.v1",
        }
    )


def test_may_spawn_is_explore_only_and_depth_capped() -> None:
    explore = lookup_spec("explore")
    implement = lookup_spec("implement")
    assert may_spawn(explore, spawn_depth=0) is True
    assert may_spawn(explore, spawn_depth=1) is False
    assert may_spawn(implement, spawn_depth=0) is False


def test_one_shot_does_not_mean_stop_after_first_message() -> None:
    spec = lookup_spec("explore")
    assert spec.one_shot is True
    assert "first assistant" not in spec.description.lower()

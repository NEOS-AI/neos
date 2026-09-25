from __future__ import annotations

from pathlib import Path

import pytest

from neos.subagent.stepper import _tool_permitted
from neos.univer.profile import compile_leaf_spec, compile_tool_policy, load_profile

pytestmark = pytest.mark.no_db

_PROFILES = Path(__file__).resolve().parents[2] / "skills" / "univer" / "profiles"
_MUTATION = frozenset(
    {
        "univer.range_set.v1",
        "univer.execute_command.v1",
        "univer.save.v1",
        "write_file.v1",
        "edit_file.v1",
        "execute.v1",
    }
)


def _office() -> dict[str, object]:
    return dict(load_profile("office-session", profiles_dir=_PROFILES))


def test_formula_cannot_tool_permitted_write_file() -> None:
    spec = compile_leaf_spec(_office(), "univer-formula")
    assert not _tool_permitted(spec, "write_file.v1", spawn_depth=0)


def test_critic_cannot_write() -> None:
    spec = compile_leaf_spec(_office(), "univer-critic")
    assert not _tool_permitted(spec, "write_file.v1", spawn_depth=0)
    assert spec.allowed_tools.isdisjoint(_MUTATION)


def test_parent_orchestrator_has_no_write_file() -> None:
    tools = compile_tool_policy(_office())
    assert "write_file.v1" not in tools


def test_office_session_has_exactly_one_writer() -> None:
    leaves = _office()["leaves"]
    assert isinstance(leaves, list)
    writers = [
        leaf["name"]
        for leaf in leaves
        if isinstance(leaf, dict) and leaf.get("write")
    ]
    assert writers == ["univer-writer"]

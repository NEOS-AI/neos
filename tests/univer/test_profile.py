from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from neos.subagent.catalog import lookup_spec
from neos.subagent.types import SandboxMode
from neos.univer.profile import (
    ProfileError,
    compile_leaf_spec,
    compile_tool_policy,
    load_profile,
)

pytestmark = pytest.mark.no_db

_REPO = Path(__file__).resolve().parents[2]
_PROFILES = _REPO / "skills" / "univer" / "profiles"
_ORCH_TOKENS = frozenset(
    {
        "read_file.v1",
        "search_text.v1",
        "glob_files.v1",
        "spawn_agent.v1",
        "load_skill.v1",
    }
)
_SKILLS = [
    "univer-sheets-headless",
    "univer-docs-headless",
    "univer-formula-audit",
    "univer-qc",
]
_LEAF_NAMES = (
    "univer-reader",
    "univer-formula",
    "univer-writer",
    "univer-critic",
)
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


def _leaf(profile: dict[str, object], name: str) -> dict[str, object]:
    leaves = profile["leaves"]
    assert isinstance(leaves, list)
    for leaf in leaves:
        assert isinstance(leaf, dict)
        if leaf.get("name") == name:
            return leaf
    raise AssertionError(name)


def _dump(tmp_path: Path, profile: dict[str, object], slug: str = "office-session") -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / f"{slug}.yaml"
    path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    return tmp_path


def test_unknown_slug_refuses() -> None:
    with pytest.raises(ProfileError):
        load_profile("sheet-modeler", profiles_dir=_PROFILES)
    with pytest.raises(ProfileError):
        compile_leaf_spec(_office(), "not-a-leaf")


def test_missing_required_fields_refuse(tmp_path: Path) -> None:
    profile = _office()
    del profile["slug"]
    with pytest.raises(ProfileError):
        load_profile("office-session", profiles_dir=_dump(tmp_path / "slug", profile))

    profile = _office()
    identity = profile["identity"]
    assert isinstance(identity, dict)
    del identity["opening"]
    with pytest.raises(ProfileError):
        load_profile("office-session", profiles_dir=_dump(tmp_path / "opening", profile))

    profile = _office()
    tools = profile["tools"]
    assert isinstance(tools, dict)
    del tools["default"]
    with pytest.raises(ProfileError):
        load_profile("office-session", profiles_dir=_dump(tmp_path / "default", profile))

    profile = _office()
    del profile["leaves"]
    with pytest.raises(ProfileError):
        load_profile("office-session", profiles_dir=_dump(tmp_path / "leaves", profile))


def test_tools_default_not_deny_refuses(tmp_path: Path) -> None:
    profile = _office()
    tools = profile["tools"]
    assert isinstance(tools, dict)
    tools["default"] = "allow"
    with pytest.raises(ProfileError):
        load_profile("office-session", profiles_dir=_dump(tmp_path, profile))
    with pytest.raises(ProfileError):
        compile_tool_policy(profile)


def test_writer_count_must_be_one() -> None:
    none = copy.deepcopy(_office())
    for leaf in none["leaves"]:  # type: ignore[union-attr]
        assert isinstance(leaf, dict)
        leaf["write"] = False
    with pytest.raises(ProfileError):
        compile_tool_policy(none)
    with pytest.raises(ProfileError):
        compile_leaf_spec(none, "univer-reader")
    two = copy.deepcopy(_office())
    first = two["leaves"][0]  # type: ignore[index]
    assert isinstance(first, dict)
    first["write"] = True
    with pytest.raises(ProfileError):
        compile_tool_policy(two)


def test_mcp_allowlist_must_be_empty(tmp_path: Path) -> None:
    profile = _office()
    profile["mcp_allowlist"] = ["mcp.univer.ai"]
    with pytest.raises(ProfileError):
        load_profile("office-session", profiles_dir=_dump(tmp_path / "profile", profile))
    with pytest.raises(ProfileError):
        compile_tool_policy(profile)
    leaf = copy.deepcopy(_office())
    _leaf(leaf, "univer-reader")["mcp_allowlist"] = ["screening"]
    with pytest.raises(ProfileError):
        compile_leaf_spec(leaf, "univer-reader")


def test_inlined_output_schema_key_refuses() -> None:
    profile = copy.deepcopy(_office())
    profile["output_schema"] = {"type": "object"}
    with pytest.raises(ProfileError):
        compile_tool_policy(profile)
    leafed = copy.deepcopy(_office())
    _leaf(leafed, "univer-reader")["output_schema"] = {"type": "object"}
    with pytest.raises(ProfileError):
        compile_leaf_spec(leafed, "univer-reader")


def test_office_session_fixture_fields() -> None:
    profile = _office()
    assert profile["slug"] == "office-session"
    model = profile["model"]
    assert isinstance(model, dict)
    assert model["role"] == "powerful"
    assert model["pin"] is None
    leaves = profile["leaves"]
    assert isinstance(leaves, list)
    names = [leaf["name"] for leaf in leaves if isinstance(leaf, dict)]
    assert set(names) == set(_LEAF_NAMES)
    writer = _leaf(profile, "univer-writer")
    assert writer["write"] is True
    for name in ("univer-reader", "univer-formula", "univer-critic"):
        assert _leaf(profile, name)["write"] is False
    assert profile["skill_allowlist"] == _SKILLS


def test_schema_refs_match_gated_leaves() -> None:
    profile = _office()
    assert _leaf(profile, "univer-reader")["output_schema_ref"] == "univer-reader"
    assert _leaf(profile, "univer-formula")["output_schema_ref"] == "univer-formula"
    assert _leaf(profile, "univer-critic")["output_schema_ref"] is None
    assert _leaf(profile, "univer-writer")["output_schema_ref"] is None


def test_reader_formula_ref_must_equal_name() -> None:
    profile = copy.deepcopy(_office())
    reader = _leaf(profile, "univer-reader")
    reader["output_schema_ref"] = "univer-formula"
    with pytest.raises(ProfileError):
        compile_leaf_spec(profile, "univer-reader")
    formula = copy.deepcopy(_office())
    _leaf(formula, "univer-formula")["output_schema_ref"] = None
    with pytest.raises(ProfileError):
        compile_leaf_spec(formula, "univer-formula")


def test_critic_writer_ref_must_be_null() -> None:
    profile = copy.deepcopy(_office())
    _leaf(profile, "univer-critic")["output_schema_ref"] = "univer-reader"
    with pytest.raises(ProfileError):
        compile_leaf_spec(profile, "univer-critic")
    writer = copy.deepcopy(_office())
    _leaf(writer, "univer-writer")["output_schema_ref"] = "univer-writer"
    with pytest.raises(ProfileError):
        compile_leaf_spec(writer, "univer-writer")


def test_load_skill_with_empty_allowlist_refuses() -> None:
    profile = copy.deepcopy(_office())
    profile["skill_allowlist"] = []
    with pytest.raises(ProfileError):
        compile_tool_policy(profile)


def test_forbidden_orchestrator_tokens_refuse() -> None:
    for token in ("handoff.v1", "execute.v1", "univer.range_set.v1"):
        profile = copy.deepcopy(_office())
        tools = profile["tools"]
        assert isinstance(tools, dict)
        allow = tools["orchestrator_allow"]
        assert isinstance(allow, list)
        allow.append(token)
        with pytest.raises(ProfileError):
            compile_tool_policy(profile)


def test_office_session_orchestrator_policy() -> None:
    tools = compile_tool_policy(_office())
    assert tools == _ORCH_TOKENS
    assert "write_file.v1" not in tools
    assert "univer.save.v1" not in tools
    assert not any(name.startswith("mcp.") for name in tools)


def test_model_pin_does_not_change_compiled_tools() -> None:
    profile = copy.deepcopy(_office())
    tools = compile_tool_policy(profile)
    model = profile["model"]
    assert isinstance(model, dict)
    model["pin"] = "claude-opus-4-7"
    assert compile_tool_policy(profile) == tools
    reader = compile_leaf_spec(profile, "univer-reader")
    assert reader.allowed_tools == compile_leaf_spec(_office(), "univer-reader").allowed_tools
    assert reader.sandbox_mode is SandboxMode.NONE


def test_compile_reader_is_read_only_none_sandbox() -> None:
    spec = compile_leaf_spec(_office(), "univer-reader")
    template = lookup_spec("univer-reader")
    assert spec.name == "univer-reader"
    assert spec.sandbox_mode is SandboxMode.NONE
    assert spec.allowed_tools <= template.allowed_tools
    assert spec.allowed_tools
    assert spec.allowed_tools.isdisjoint(_MUTATION)
    assert "univer.formula_wait.v1" not in spec.allowed_tools


def test_compile_formula_requires_wait_rejects_write() -> None:
    spec = compile_leaf_spec(_office(), "univer-formula")
    assert spec.sandbox_mode is SandboxMode.NONE
    assert "univer.formula_wait.v1" in spec.allowed_tools
    assert "write_file.v1" not in spec.allowed_tools
    assert spec.allowed_tools.isdisjoint(
        {"univer.range_set.v1", "univer.save.v1", "execute.v1"}
    )


def test_compile_critic_is_read_only() -> None:
    profile = _office()
    assert _leaf(profile, "univer-critic")["output_schema_ref"] is None
    spec = compile_leaf_spec(profile, "univer-critic")
    assert spec.sandbox_mode is SandboxMode.NONE
    assert spec.allowed_tools.isdisjoint(_MUTATION)
    assert "univer.formula_wait.v1" not in spec.allowed_tools


def test_compile_writer_has_write_tools_none_sandbox() -> None:
    spec = compile_leaf_spec(_office(), "univer-writer")
    assert spec.sandbox_mode is SandboxMode.NONE
    assert "write_file.v1" in spec.allowed_tools
    assert "univer.range_set.v1" in spec.allowed_tools
    assert "univer.execute_command.v1" in spec.allowed_tools
    assert "univer.save.v1" in spec.allowed_tools
    assert "univer.formula_wait.v1" in spec.allowed_tools
    assert "execute.v1" not in spec.allowed_tools
    assert spec.allowed_tools <= lookup_spec("univer-writer").allowed_tools


def test_compile_leaf_does_not_mutate_catalog_singleton() -> None:
    writer_base = lookup_spec("univer-writer")
    compiled = compile_leaf_spec(_office(), "univer-writer")
    assert compiled is not writer_base
    assert lookup_spec("univer-writer") is writer_base
    assert writer_base.sandbox_mode is SandboxMode.NONE
    assert compiled.sandbox_mode is SandboxMode.NONE
    reader_base = lookup_spec("univer-reader")
    reader = compile_leaf_spec(_office(), "univer-reader")
    assert reader is not reader_base
    assert lookup_spec("univer-reader") is reader_base


def test_reader_requesting_write_refuses() -> None:
    profile = copy.deepcopy(_office())
    allow = _leaf(profile, "univer-reader")["tools_allow"]
    assert isinstance(allow, list)
    allow.append("write_file.v1")
    with pytest.raises(ProfileError):
        compile_leaf_spec(profile, "univer-reader")


def test_writer_execute_v1_refuses_formula_wait_allowed() -> None:
    profile = copy.deepcopy(_office())
    allow = _leaf(profile, "univer-writer")["tools_allow"]
    assert isinstance(allow, list)
    allow.append("execute.v1")
    with pytest.raises(ProfileError):
        compile_leaf_spec(profile, "univer-writer")
    ok = compile_leaf_spec(_office(), "univer-writer")
    assert "univer.formula_wait.v1" in ok.allowed_tools


def test_leaf_glob_refuses() -> None:
    profile = copy.deepcopy(_office())
    allow = _leaf(profile, "univer-reader")["tools_allow"]
    assert isinstance(allow, list)
    allow.append("univer.*")
    with pytest.raises(ProfileError):
        compile_leaf_spec(profile, "univer-reader")


def test_empty_tools_allow_refuses() -> None:
    profile = copy.deepcopy(_office())
    _leaf(profile, "univer-reader")["tools_allow"] = []
    with pytest.raises(ProfileError):
        compile_leaf_spec(profile, "univer-reader")

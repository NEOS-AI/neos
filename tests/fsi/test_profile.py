from __future__ import annotations

import copy
from pathlib import Path

import pytest

from neos.fsi.profile import (
    ProfileError,
    compile_leaf_spec,
    compile_tool_policy,
    load_profile,
)
from neos.subagent.catalog import lookup_spec
from neos.subagent.types import SandboxMode

pytestmark = pytest.mark.no_db

_PROFILES = Path(__file__).resolve().parent / "fixtures" / "profiles"


def _kyc() -> dict[str, object]:
    return dict(load_profile("kyc-screener", profiles_dir=_PROFILES))


def test_unknown_slug_refuses() -> None:
    with pytest.raises(ProfileError):
        load_profile("not-a-profile", profiles_dir=_PROFILES)
    profile = _kyc()
    with pytest.raises(ProfileError):
        compile_leaf_spec(profile, "not-a-leaf")


def test_kyc_orchestrator_has_spawn_not_write() -> None:
    tools = compile_tool_policy(_kyc())
    assert "spawn_agent.v1" in tools
    assert "write_file.v1" not in tools
    assert "edit_file.v1" not in tools
    assert "execute.v1" not in tools
    assert "stage_xlsx.v1" not in tools
    assert tools == frozenset(
        {
            "read_file.v1",
            "search_text.v1",
            "glob_files.v1",
            "spawn_agent.v1",
            "load_skill.v1",
        }
    )


def test_empty_handoff_allowlist_omits_handoff_tool() -> None:
    profile = _kyc()
    assert profile["handoff_allowlist"] == []
    assert "handoff.v1" not in compile_tool_policy(profile)


def test_handoff_in_allow_with_empty_list_refuses() -> None:
    profile = copy.deepcopy(_kyc())
    tools = profile["tools"]
    assert isinstance(tools, dict)
    allow = tools["orchestrator_allow"]
    assert isinstance(allow, list)
    allow.append("handoff.v1")
    assert profile["handoff_allowlist"] == []
    with pytest.raises(ProfileError):
        compile_tool_policy(profile)


def test_compile_leaf_reader_keeps_none_sandbox_in_mode_b() -> None:
    profile = _kyc()
    spec = compile_leaf_spec(profile, "kyc-doc-reader")
    assert spec.name == "kyc-doc-reader"
    assert spec.sandbox_mode is SandboxMode.NONE
    assert "write_file.v1" not in spec.allowed_tools
    assert spec.allowed_tools <= lookup_spec("fsi-reader").allowed_tools
    writer = compile_leaf_spec(profile, "kyc-escalator")
    assert writer.name == "kyc-escalator"
    assert writer.sandbox_mode is SandboxMode.NONE
    assert "write_file.v1" in writer.allowed_tools


def test_compile_leaf_does_not_mutate_catalog_singleton() -> None:
    profile = _kyc()
    base = lookup_spec("fsi-reader")
    compiled = compile_leaf_spec(profile, "kyc-doc-reader")
    assert compiled is not base
    assert compiled.name == "kyc-doc-reader"
    assert lookup_spec("fsi-reader") is base
    assert base.name == "fsi-reader"
    assert base.sandbox_mode is SandboxMode.NONE
    writer_base = lookup_spec("fsi-writer")
    writer = compile_leaf_spec(profile, "kyc-escalator")
    assert writer is not writer_base
    assert writer.name == "kyc-escalator"
    assert lookup_spec("fsi-writer") is writer_base
    assert writer_base.name == "fsi-writer"


def test_writer_count_must_be_one() -> None:
    none = copy.deepcopy(_kyc())
    for leaf in none["leaves"]:  # type: ignore[union-attr]
        assert isinstance(leaf, dict)
        leaf["write"] = False
    with pytest.raises(ProfileError):
        compile_tool_policy(none)
    with pytest.raises(ProfileError):
        compile_leaf_spec(none, "kyc-doc-reader")
    two = copy.deepcopy(_kyc())
    first = two["leaves"][0]  # type: ignore[index]
    assert isinstance(first, dict)
    first["write"] = True
    with pytest.raises(ProfileError):
        compile_tool_policy(two)


def test_mode_a_non_writer_stamps_parent_ro() -> None:
    profile = {
        "mode": "A",
        "isolation_surface": "cma_leaves",
        "leaves": [
            {
                "name": "pitch-researcher",
                "catalog_template": "fsi-puller",
                "write": False,
                "tools_allow": ["read_file.v1", "search_text.v1"],
                "output_schema_ref": "pitch-researcher",
            },
            {
                "name": "pitch-deck-writer",
                "catalog_template": "fsi-writer",
                "write": True,
                "tools_allow": [
                    "read_file.v1",
                    "write_file.v1",
                    "edit_file.v1",
                    "load_skill.v1",
                ],
                "output_schema_ref": None,
            },
        ],
    }
    reader = compile_leaf_spec(profile, "pitch-researcher")
    assert reader.name == "pitch-researcher"
    assert reader.sandbox_mode is SandboxMode.PARENT_RO
    writer = compile_leaf_spec(profile, "pitch-deck-writer")
    assert writer.name == "pitch-deck-writer"
    assert writer.sandbox_mode is SandboxMode.WORKTREE


def test_inlined_output_schema_key_refuses() -> None:
    profile = copy.deepcopy(_kyc())
    profile["output_schema"] = {"type": "object"}
    with pytest.raises(ProfileError):
        compile_tool_policy(profile)


def test_reader_ref_must_exist() -> None:
    profile = copy.deepcopy(_kyc())
    leaves = profile["leaves"]
    assert isinstance(leaves, list)
    reader = leaves[0]
    assert isinstance(reader, dict)
    reader["output_schema_ref"] = "not-a-schema"
    with pytest.raises(ProfileError):
        compile_leaf_spec(profile, "kyc-doc-reader")


def test_critic_must_not_carry_a_schema_ref() -> None:
    profile = copy.deepcopy(_kyc())
    leaves = profile["leaves"]
    assert isinstance(leaves, list)
    critic = leaves[1]
    assert isinstance(critic, dict)
    critic["output_schema_ref"] = "kyc-doc-reader"
    with pytest.raises(ProfileError):
        compile_leaf_spec(profile, "kyc-rules-engine")


def test_missing_isolation_surface_refuses() -> None:
    profile = copy.deepcopy(_kyc())
    del profile["isolation_surface"]
    with pytest.raises(ProfileError):
        compile_tool_policy(profile)


def test_unknown_orchestrator_token_refuses() -> None:
    profile = copy.deepcopy(_kyc())
    tools = profile["tools"]
    assert isinstance(tools, dict)
    allow = tools["orchestrator_allow"]
    assert isinstance(allow, list)
    allow.append("Bash")
    with pytest.raises(ProfileError):
        compile_tool_policy(profile)


def test_mcp_glob_on_allow_refuses() -> None:
    profile = copy.deepcopy(_kyc())
    tools = profile["tools"]
    assert isinstance(tools, dict)
    allow = tools["orchestrator_allow"]
    assert isinstance(allow, list)
    allow.append("mcp.screening.*")
    with pytest.raises(ProfileError):
        compile_tool_policy(profile)


def test_kyc_rules_engine_unions_screening_stub() -> None:
    spec = compile_leaf_spec(_kyc(), "kyc-rules-engine")
    assert "mcp.screening.search" in spec.allowed_tools
    assert "mcp.screening.*" not in spec.allowed_tools
    assert "write_file.v1" not in spec.allowed_tools
    assert lookup_spec("fsi-critic").allowed_tools == frozenset(
        {"read_file.v1", "search_text.v1"}
    )


def test_reader_must_not_receive_screening() -> None:
    profile = copy.deepcopy(_kyc())
    leaves = profile["leaves"]
    assert isinstance(leaves, list)
    reader = leaves[0]
    assert isinstance(reader, dict)
    reader["mcp_allowlist"] = ["screening"]
    with pytest.raises(ProfileError):
        compile_leaf_spec(profile, "kyc-doc-reader")


def test_mode_a_puller_uses_fsi_puller_template() -> None:
    profile = {
        "mode": "A",
        "isolation_surface": "cma_leaves",
        "tools": {"default": "deny", "orchestrator_allow": ["read_file.v1"]},
        "handoff_allowlist": [],
        "leaves": [
            {
                "name": "pitch-researcher",
                "catalog_template": "fsi-puller",
                "write": False,
                "tools_allow": ["read_file.v1", "search_text.v1"],
                "output_schema_ref": "pitch-researcher",
            },
            {
                "name": "pitch-deck-writer",
                "catalog_template": "fsi-writer",
                "write": True,
                "tools_allow": ["read_file.v1", "write_file.v1"],
                "output_schema_ref": None,
            },
        ],
    }
    reader = compile_leaf_spec(profile, "pitch-researcher")
    assert reader.sandbox_mode is SandboxMode.PARENT_RO
    assert reader.allowed_tools <= lookup_spec("fsi-puller").allowed_tools


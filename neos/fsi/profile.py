from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

import yaml

from neos.fsi.schemas import READER_SCHEMAS
from neos.subagent.catalog import SubagentSpec, UnknownSpec, lookup_spec
from neos.subagent.types import SandboxMode

_ORCH_TOKENS = frozenset(
    {
        "read_file.v1",
        "search_text.v1",
        "glob_files.v1",
        "spawn_agent.v1",
        "load_skill.v1",
        "handoff.v1",
    }
)
SCREENING_STUB_TOOLS = frozenset({"mcp.screening.search"})
_SCREENING_TEMPLATES = frozenset({"fsi-critic", "fsi-puller", "fsi-modeler"})
_NO_SCREENING_TEMPLATES = frozenset({"fsi-reader", "fsi-writer"})
_ISOLATION_SURFACES = frozenset({"cma_leaves", "cowork_inline"})
_SCHEMA_TEMPLATES = frozenset({"fsi-reader", "fsi-puller"})
_NULL_SCHEMA_TEMPLATES = frozenset({"fsi-critic", "fsi-writer", "fsi-modeler"})

_CMA_ORCH_DROP = frozenset(
    {
        "write_file.v1",
        "edit_file.v1",
        "execute.v1",
        "stage_xlsx.v1",
    }
)


class ProfileError(ValueError):
    pass


def skill_permitted(name: str, allowlist: frozenset[str]) -> bool:
    """Empty allowlist is none, not all."""
    return name in allowlist


def load_profile(slug: str, *, profiles_dir: Path) -> Mapping[str, object]:
    path = profiles_dir / f"{slug}.yaml"
    if not path.is_file():
        raise ProfileError(f"unknown profile: {slug}")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProfileError(f"invalid profile yaml: {slug}") from exc
    if not isinstance(loaded, dict):
        raise ProfileError(f"invalid profile yaml: {slug}")
    _validate_profile(loaded)
    return loaded


def compile_tool_policy(profile: Mapping[str, object]) -> frozenset[str]:
    _validate_profile(profile)
    tools = profile.get("tools")
    if not isinstance(tools, dict):
        raise ProfileError("tools.default must be deny")
    if tools.get("default") != "deny":
        raise ProfileError("tools.default must be deny")
    allow = _str_list(tools.get("orchestrator_allow"))
    handoff_allowlist = _as_list(profile.get("handoff_allowlist"))
    if "handoff.v1" in allow and not handoff_allowlist:
        raise ProfileError("handoff.v1 listed but handoff_allowlist is empty")
    compiled = set(allow)
    compiled.add("spawn_agent.v1")
    if _as_list(profile.get("skill_allowlist")):
        compiled.add("load_skill.v1")
    if handoff_allowlist:
        compiled.add("handoff.v1")
    if profile.get("isolation_surface") == "cma_leaves":
        compiled -= _CMA_ORCH_DROP
    return frozenset(compiled)


def compile_leaf_spec(profile: Mapping[str, object], leaf_name: str) -> SubagentSpec:
    _validate_profile(profile)
    leaf = _find_leaf(profile, leaf_name)
    tools = _compile_leaf_tool_policy(profile, leaf)
    stamped = _stamp_sandbox(profile, leaf)
    template = _template(leaf)
    return replace(template, name=leaf_name, allowed_tools=tools, sandbox_mode=stamped)


def _compile_leaf_tool_policy(
    profile: Mapping[str, object],
    leaf: Mapping[str, object],
) -> frozenset[str]:
    template = _template(leaf)
    requested = _str_list(leaf.get("tools_allow"))
    mcp_allowlist = _str_list(leaf.get("mcp_allowlist"))
    for name in (*requested, *mcp_allowlist):
        if "*" in name:
            raise ProfileError(f"mcp glob is not allowed: {name}")
    for name in requested:
        if name not in template.allowed_tools:
            raise ProfileError(
                f"tool {name!r} is not allowed on template {template.name}"
            )
    tools = frozenset(template.allowed_tools)
    if "screening" in mcp_allowlist:
        if template.name in _NO_SCREENING_TEMPLATES:
            raise ProfileError("reader/writer must not receive screening")
        if template.name in _SCREENING_TEMPLATES:
            tools = frozenset(template.allowed_tools) | SCREENING_STUB_TOOLS
    write = bool(leaf.get("write"))
    if write and "write_file.v1" not in tools:
        raise ProfileError("writer must include write_file.v1")
    if not write and "write_file.v1" in tools:
        raise ProfileError("reader must not receive write_file.v1")
    return tools


def _stamp_sandbox(
    profile: Mapping[str, object], leaf: Mapping[str, object]
) -> SandboxMode:
    mode = profile.get("mode")
    if mode == "B":
        return SandboxMode.NONE
    if mode == "A":
        if leaf.get("write"):
            return SandboxMode.WORKTREE
        return SandboxMode.PARENT_RO
    raise ProfileError(f"unknown mode: {mode!r}")


def _validate_profile(profile: Mapping[str, object]) -> None:
    if "output_schema" in profile:
        raise ProfileError("output_schema must not be inlined")
    if profile.get("isolation_surface") not in _ISOLATION_SURFACES:
        raise ProfileError("isolation_surface required")
    tools = profile.get("tools")
    if isinstance(tools, dict):
        for name in _str_list(tools.get("orchestrator_allow")):
            if name not in _ORCH_TOKENS:
                raise ProfileError(f"unknown orchestrator token: {name}")
    leaves = profile.get("leaves")
    if not isinstance(leaves, list):
        raise ProfileError("leaves must be a list")
    writers = 0
    for leaf in leaves:
        if not isinstance(leaf, dict):
            raise ProfileError("invalid leaf")
        if leaf.get("write"):
            writers += 1
        _validate_leaf_schema_ref(leaf)
    if writers != 1:
        raise ProfileError("exactly one writer leaf required")


def _validate_leaf_schema_ref(leaf: Mapping[str, object]) -> None:
    template = leaf.get("catalog_template")
    ref = leaf.get("output_schema_ref")
    if template in _SCHEMA_TEMPLATES:
        if not isinstance(ref, str) or ref not in READER_SCHEMAS:
            raise ProfileError("output_schema_ref must be a READER_SCHEMAS key")
        if leaf.get("name") != ref:
            raise ProfileError("output_schema_ref must match leaf name")
        return
    if template in _NULL_SCHEMA_TEMPLATES and ref is not None:
        raise ProfileError("output_schema_ref must be null")


def _find_leaf(profile: Mapping[str, object], leaf_name: str) -> Mapping[str, object]:
    leaves = profile.get("leaves")
    if not isinstance(leaves, list):
        raise ProfileError("leaves must be a list")
    for leaf in leaves:
        if isinstance(leaf, dict) and leaf.get("name") == leaf_name:
            return leaf
    raise ProfileError(f"unknown leaf: {leaf_name}")


def _template(leaf: Mapping[str, object]) -> SubagentSpec:
    name = leaf.get("catalog_template")
    if not isinstance(name, str):
        raise ProfileError("catalog_template required")
    try:
        return lookup_spec(name)
    except UnknownSpec as exc:
        raise ProfileError(f"unknown catalog template: {name}") from exc


def _str_list(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ProfileError("expected a list of strings")
    return value


def _as_list(value: object) -> Sequence[object]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ProfileError("expected a list")
    return value

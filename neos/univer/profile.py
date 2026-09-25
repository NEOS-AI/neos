from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

import yaml

from neos.subagent.catalog import SubagentSpec, UnknownSpec, lookup_spec
from neos.subagent.types import SandboxMode
from neos.univer.schemas import READER_SCHEMAS

_ORCH_TOKENS = frozenset(
    {
        "read_file.v1",
        "search_text.v1",
        "glob_files.v1",
        "spawn_agent.v1",
        "load_skill.v1",
    }
)
_SCHEMA_ROLES = frozenset({"reader", "formula"})
_NULL_SCHEMA_ROLES = frozenset({"critic", "writer"})
_ROLE_TEMPLATES = {
    "reader": "univer-reader",
    "formula": "univer-formula",
    "critic": "univer-critic",
    "writer": "univer-writer",
}
_READER_REJECT = frozenset(
    {
        "univer.range_set.v1",
        "univer.execute_command.v1",
        "univer.save.v1",
        "univer.formula_wait.v1",
        "write_file.v1",
        "edit_file.v1",
        "execute.v1",
    }
)
_FORMULA_REJECT = frozenset(
    {
        "univer.range_set.v1",
        "univer.execute_command.v1",
        "univer.save.v1",
        "write_file.v1",
        "edit_file.v1",
        "execute.v1",
    }
)
_CRITIC_REJECT = _READER_REJECT
_WRITER_REJECT = frozenset({"execute.v1", "stage_xlsx.v1"})
_WRITER_REQUIRE = frozenset(
    {"write_file.v1", "univer.save.v1", "univer.range_set.v1"}
)
_REQUIRED_KEYS = (
    "slug",
    "version",
    "identity",
    "description",
    "system_prompt_path",
    "model",
    "tools",
    "skill_allowlist",
    "mcp_allowlist",
    "surfaces",
    "isolation",
    "leaves",
    "human_gates",
    "binding_refused",
)


class ProfileError(ValueError):
    pass


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
    _validate_load_fields(loaded, slug)
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
    skill_allowlist = _as_list(profile.get("skill_allowlist"))
    if "load_skill.v1" in allow and not skill_allowlist:
        raise ProfileError("load_skill.v1 listed but skill_allowlist is empty")
    compiled = set(allow)
    compiled.add("spawn_agent.v1")
    if skill_allowlist:
        compiled.add("load_skill.v1")
    return frozenset(compiled)


def compile_leaf_spec(profile: Mapping[str, object], leaf_name: str) -> SubagentSpec:
    _validate_profile(profile)
    leaf = _find_leaf(profile, leaf_name)
    tools = _compile_leaf_tool_policy(leaf)
    return replace(
        _template(leaf),
        name=leaf_name,
        allowed_tools=tools,
        sandbox_mode=SandboxMode.NONE,
    )


def _compile_leaf_tool_policy(leaf: Mapping[str, object]) -> frozenset[str]:
    template = _template(leaf)
    requested = _str_list(leaf.get("tools_allow"))
    if not requested:
        raise ProfileError("empty tools_allow is not allowed")
    mcp_allowlist = _str_list(leaf.get("mcp_allowlist"))
    if mcp_allowlist:
        raise ProfileError("mcp_allowlist must be empty")
    for name in (*requested, *mcp_allowlist):
        if "*" in name:
            raise ProfileError(f"tool glob is not allowed: {name}")
    for name in requested:
        if name not in template.allowed_tools:
            raise ProfileError(
                f"tool {name!r} is not allowed on template {template.name}"
            )
    tools = frozenset(requested)
    _check_role_tools(leaf, tools)
    return tools


def _check_role_tools(leaf: Mapping[str, object], tools: frozenset[str]) -> None:
    role = leaf.get("role")
    if any(name.startswith("mcp.") for name in tools):
        raise ProfileError("mcp tools are not allowed on leaves")
    if role == "reader":
        banned = tools & _READER_REJECT
        if banned:
            raise ProfileError(f"reader must not receive {sorted(banned)[0]}")
        return
    if role == "formula":
        if "univer.formula_wait.v1" not in tools:
            raise ProfileError("formula must include univer.formula_wait.v1")
        banned = tools & _FORMULA_REJECT
        if banned:
            raise ProfileError(f"formula must not receive {sorted(banned)[0]}")
        return
    if role == "critic":
        banned = tools & _CRITIC_REJECT
        if banned:
            raise ProfileError(f"critic must not receive {sorted(banned)[0]}")
        return
    if role == "writer":
        if not leaf.get("write"):
            raise ProfileError("writer must have write: true")
        missing = _WRITER_REQUIRE - tools
        if missing:
            raise ProfileError(f"writer must include {sorted(missing)[0]}")
        banned = tools & _WRITER_REJECT
        if banned:
            raise ProfileError(f"writer must not receive {sorted(banned)[0]}")
        return
    raise ProfileError(f"unknown leaf role: {role!r}")


def _validate_load_fields(profile: Mapping[str, object], slug: str) -> None:
    for key in _REQUIRED_KEYS:
        if key not in profile:
            raise ProfileError(f"{key} required")
    if profile.get("slug") != slug:
        raise ProfileError("slug must match filename")
    identity = profile.get("identity")
    if not isinstance(identity, dict):
        raise ProfileError("identity required")
    for key in ("title", "opening", "role_noun"):
        if not isinstance(identity.get(key), str) or not identity.get(key):
            raise ProfileError(f"identity.{key} required")
    model = profile.get("model")
    if not isinstance(model, dict):
        raise ProfileError("model required")
    if model.get("role") != "powerful":
        raise ProfileError("model.role must be powerful")
    if model.get("pin") is not None:
        raise ProfileError("model.pin must be null")
    if not isinstance(model.get("inherit_parent"), bool):
        raise ProfileError("model.inherit_parent required")


def _validate_profile(profile: Mapping[str, object]) -> None:
    if "output_schema" in profile:
        raise ProfileError("output_schema must not be inlined")
    tools = profile.get("tools")
    if not isinstance(tools, dict) or "default" not in tools:
        raise ProfileError("tools.default must be deny")
    if tools.get("default") != "deny":
        raise ProfileError("tools.default must be deny")
    for name in _str_list(tools.get("orchestrator_allow")):
        if name not in _ORCH_TOKENS:
            raise ProfileError(f"unknown orchestrator token: {name}")
    if "mcp_allowlist" not in profile:
        raise ProfileError("mcp_allowlist required")
    if _str_list(profile.get("mcp_allowlist")):
        raise ProfileError("mcp_allowlist must be empty")
    skill_allowlist = _as_list(profile.get("skill_allowlist"))
    allow = _str_list(tools.get("orchestrator_allow"))
    if "load_skill.v1" in allow and not skill_allowlist:
        raise ProfileError("load_skill.v1 listed but skill_allowlist is empty")
    surfaces = profile.get("surfaces")
    if isinstance(surfaces, dict):
        sheets = surfaces.get("sheets")
        docs = surfaces.get("docs")
        if sheets is False and docs is False:
            raise ProfileError("surfaces.sheets or surfaces.docs required")
    isolation = profile.get("isolation")
    if isinstance(isolation, dict):
        if not isolation.get("trunk_dir") or not isolation.get("draft_dir"):
            raise ProfileError("isolation dirs required")
    leaves = profile.get("leaves")
    if not isinstance(leaves, list):
        raise ProfileError("leaves must be a list")
    writers = 0
    for leaf in leaves:
        if not isinstance(leaf, dict):
            raise ProfileError("invalid leaf")
        if leaf.get("write"):
            writers += 1
        _validate_leaf(leaf)
    if writers != 1:
        raise ProfileError("exactly one writer leaf required")


def _validate_leaf(leaf: Mapping[str, object]) -> None:
    if "output_schema" in leaf:
        raise ProfileError("output_schema must not be inlined")
    name = leaf.get("name")
    template = leaf.get("catalog_template")
    role = leaf.get("role")
    if not isinstance(name, str) or not isinstance(template, str):
        raise ProfileError("leaf name and catalog_template required")
    if name != template:
        raise ProfileError("leaf name must equal catalog_template")
    if role not in _ROLE_TEMPLATES:
        raise ProfileError(f"unknown leaf role: {role!r}")
    if _ROLE_TEMPLATES[role] != template:
        raise ProfileError("leaf role must match catalog_template")
    if _str_list(leaf.get("mcp_allowlist")):
        raise ProfileError("mcp_allowlist must be empty")
    _validate_leaf_schema_ref(leaf)


def _validate_leaf_schema_ref(leaf: Mapping[str, object]) -> None:
    role = leaf.get("role")
    ref = leaf.get("output_schema_ref")
    name = leaf.get("name")
    if role in _SCHEMA_ROLES:
        if not isinstance(ref, str) or ref not in READER_SCHEMAS:
            raise ProfileError("output_schema_ref must be a READER_SCHEMAS key")
        if name != ref:
            raise ProfileError("output_schema_ref must match leaf name")
        return
    if role in _NULL_SCHEMA_ROLES and ref is not None:
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

from __future__ import annotations

import pytest

from neos.subagent.catalog import UnknownSpec, lookup_spec, may_spawn
from neos.subagent.metrics import _PARENTS, _spec
from neos.subagent.prompts import build_security_audit_system_prompt
from neos.subagent.types import SandboxMode

pytestmark = pytest.mark.no_db

_NAMES = ("security-audit-research", "security-audit-general")
_RO_TOOLS = frozenset(
    {
        "read_file.v1",
        "search_text.v1",
        "glob_files.v1",
        "list_tree.v1",
        "stat.v1",
        "git_status.v1",
        "git_diff.v1",
        "git_log.v1",
    }
)
_FORBIDDEN = frozenset(
    {
        "execute.v1",
        "spawn_agent.v1",
        "write_file.v1",
        "edit_file.v1",
        "search",
        "fetch",
    }
)


@pytest.mark.parametrize("name", _NAMES)
def test_security_audit_kebab_specs_are_read_only_leaves(name: str) -> None:
    spec = lookup_spec(name)
    assert spec.name == name
    assert spec.can_spawn is False
    assert spec.can_approve is False
    assert spec.one_shot is True
    assert spec.load_project_instructions is False
    assert spec.sandbox_mode is SandboxMode.PARENT_RO
    assert spec.allowed_tools == _RO_TOOLS
    assert "execute.v1" not in spec.allowed_tools
    assert "spawn_agent.v1" not in spec.allowed_tools
    assert "write_file.v1" not in spec.allowed_tools
    assert spec.allowed_tools.isdisjoint(_FORBIDDEN)
    assert may_spawn(spec, spawn_depth=0) is False
    assert not hasattr(spec, "output_schema")


def test_underscore_security_audit_research_is_unknown() -> None:
    with pytest.raises(UnknownSpec) as raised:
        lookup_spec("security_audit_research")
    assert raised.value.name == "security_audit_research"


def test_security_audit_prompt_is_json_report_not_fsi() -> None:
    prompt = build_security_audit_system_prompt()
    assert "exactly one JSON object" in prompt
    assert "Do not post" not in prompt
    assert "FSI leaf worker" not in prompt
    assert "you may call spawn_agent" not in prompt.lower()


def test_metrics_keep_security_audit_spec_labels() -> None:
    assert _spec({"spec": "security-audit-research"}) == "security-audit-research"
    assert _spec({"spec": "security-audit-general"}) == "security-audit-general"
    assert _spec({"spec": "security_audit_research"}) == "explore"
    assert "security_audit" not in _PARENTS
    assert "security-audit" not in _PARENTS

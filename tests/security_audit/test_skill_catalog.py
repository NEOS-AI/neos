from __future__ import annotations

from pathlib import Path

import pytest

from neos.skills.markdown_catalog import (
    MarkdownSkillCatalog,
    default_catalog,
    default_skill_roots,
    fsi_catalog,
    k_skill_catalog,
    research_skill_roots,
    univer_catalog,
)

pytestmark = pytest.mark.no_db

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_security_audit_roots_are_the_pack_directory() -> None:
    from neos.skills.markdown_catalog import SECURITY_AUDIT_PACK, security_audit_roots

    roots = security_audit_roots()
    assert roots == (("repo", SECURITY_AUDIT_PACK),)
    assert SECURITY_AUDIT_PACK == REPO_ROOT / "skills" / "security-audit"


def test_default_and_research_roots_do_not_include_security_audit_pack() -> None:
    from neos.skills.markdown_catalog import SECURITY_AUDIT_PACK

    pack = SECURITY_AUDIT_PACK.resolve()
    for _source, path in default_skill_roots():
        assert path.resolve() != pack
    for _source, path in research_skill_roots():
        assert path.resolve() != pack


def test_coding_catalog_lists_security_audit_index() -> None:
    skill = default_catalog().get("security-audit")
    assert skill is not None
    assert skill.source == "coding"


def test_research_catalog_does_not_index_security_audit() -> None:
    catalog = MarkdownSkillCatalog(roots=research_skill_roots())
    assert catalog.get("security-audit") is None


def test_foreign_packs_do_not_index_security_audit() -> None:
    assert k_skill_catalog().get("security-audit") is None
    assert fsi_catalog().get("security-audit") is None
    assert univer_catalog().get("security-audit") is None


def test_coding_prompt_lists_security_audit_index_not_pack_leaves() -> None:
    from neos.coding.model.base import ToolDefinition
    from neos.coding.prompts import build_coding_system_prompt

    prompt = build_coding_system_prompt(
        (
            ToolDefinition(
                name="search_text.v1",
                description="Search workspace text.",
                input_schema={"type": "object", "properties": {}},
            ),
        )
    )
    skills = prompt[prompt.index("## Skills") : prompt.index("## Tone")]
    assert "- security-audit:" in skills
    assert "- HUNTING:" not in skills
    assert "- RECONNAISSANCE:" not in skills
    assert "- k-skill:" in skills
    assert "- korea-weather:" not in skills


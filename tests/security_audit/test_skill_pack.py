from __future__ import annotations

from pathlib import Path

import pytest

from neos.skills.markdown_catalog import (
    default_catalog,
    fsi_catalog,
    k_skill_catalog,
    security_audit_catalog,
    univer_catalog,
)

pytestmark = pytest.mark.no_db

REPO_ROOT = Path(__file__).resolve().parents[2]
PACK = REPO_ROOT / "skills" / "security-audit"


def test_security_audit_catalog_indexes_one_skill() -> None:
    names = {skill.name for skill in security_audit_catalog().list_skills()}
    assert names == {"security-audit"}


def test_directory_name_matches_frontmatter_name() -> None:
    for skill in security_audit_catalog().list_skills():
        assert skill.path.parent.name == skill.name
        assert skill.name == "security-audit"
        assert skill.path == (PACK / "security-audit" / "SKILL.md").resolve()


def test_body_is_cloudflare_skill_not_cli_stub() -> None:
    body = security_audit_catalog().load_markdown("security-audit")
    assert body is not None
    assert "Operating modes" in body or "Full audit" in body
    assert body.strip() != "npx skills add"


def test_reconnaissance_reference_loads() -> None:
    path = PACK / "security-audit" / "references" / "RECONNAISSANCE.md"
    assert path.is_file()
    expected = path.read_text(encoding="utf-8")
    body = security_audit_catalog().load_markdown(
        "security-audit", reference="RECONNAISSANCE.md"
    )
    assert body == expected


def test_source_md_uses_sibling_path_not_machine_local() -> None:
    text = (PACK / "SOURCE.md").read_text(encoding="utf-8")
    assert "`../security-audit-skill`" in text
    assert "/Users/" not in text
    assert "scripts/vendor_security_audit.py" in text


def test_foreign_packs_do_not_index_security_audit_or_other_names() -> None:
    assert default_catalog().get("korea-weather") is None
    assert k_skill_catalog().get("security-audit") is None
    assert fsi_catalog().get("security-audit") is None
    assert univer_catalog().get("security-audit") is None
    assert security_audit_catalog().get("xlsx-author") is None
    assert security_audit_catalog().get("korea-weather") is None

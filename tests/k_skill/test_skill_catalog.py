from __future__ import annotations

from pathlib import Path

import pytest

from neos.skills.markdown_catalog import (
    default_catalog,
    default_skill_roots,
    research_skill_roots,
)

pytestmark = pytest.mark.no_db

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_k_skill_roots_are_the_pack_directory() -> None:
    from neos.skills.markdown_catalog import K_SKILL_PACK, k_skill_roots

    roots = k_skill_roots()
    assert roots == (("repo", K_SKILL_PACK),)
    assert K_SKILL_PACK == REPO_ROOT / "skills" / "k-skill"


def test_default_and_research_roots_do_not_include_k_skill_pack() -> None:
    from neos.skills.markdown_catalog import K_SKILL_PACK

    pack = K_SKILL_PACK.resolve()
    for _source, path in default_skill_roots():
        assert path.resolve() != pack
    for _source, path in research_skill_roots():
        assert path.resolve() != pack


def test_coding_catalog_does_not_index_korea_weather() -> None:
    assert default_catalog().get("korea-weather") is None


def test_coding_catalog_lists_k_skill_index() -> None:
    skill = default_catalog().get("k-skill")
    assert skill is not None
    assert skill.source == "coding"
    names = {item.name for item in default_catalog().list_skills()}
    assert "k-skill" in names
    assert "korea-weather" not in names

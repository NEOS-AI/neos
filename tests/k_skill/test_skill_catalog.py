from __future__ import annotations

from pathlib import Path

import pytest

from neos.skills.markdown_catalog import (
    MarkdownSkillCatalog,
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


def test_research_catalog_does_not_index_korea_weather() -> None:
    catalog = MarkdownSkillCatalog(roots=research_skill_roots())
    assert catalog.get("korea-weather") is None
    assert catalog.get("k-skill") is None


def test_k_skill_catalog_skips_excluded_names_even_if_dirs_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neos.skills import markdown_catalog as mc

    pack = tmp_path / "k-skill"
    for name in ("korea-weather", "k-skill-setup", "k-skill-cleaner"):
        skill_dir = pack / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: fixture\n---\n\n# {name}\n",
            encoding="utf-8",
        )
    monkeypatch.setattr(mc, "K_SKILL_PACK", pack)
    catalog = mc.k_skill_catalog()
    assert catalog.get("korea-weather") is not None
    assert catalog.get("k-skill-setup") is None
    assert catalog.get("k-skill-cleaner") is None


def test_coding_prompt_lists_k_skill_index_not_pack_leaves() -> None:
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
    assert "- k-skill:" in skills
    assert "- korea-weather:" not in skills

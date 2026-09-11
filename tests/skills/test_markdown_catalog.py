from __future__ import annotations

from pathlib import Path

import pytest

from neos.skills.markdown_catalog import MarkdownSkillCatalog

pytestmark = pytest.mark.no_db

REPO_ROOT = Path(__file__).resolve().parents[2]


def _catalog() -> MarkdownSkillCatalog:
    return MarkdownSkillCatalog()


def test_catalog_contains_repo_pdf() -> None:
    skill = _catalog().get("pdf")

    assert skill is not None
    assert skill.name == "pdf"
    assert skill.source == "repo"
    assert skill.path == (REPO_ROOT / "skills" / "pdf" / "SKILL.md").resolve()
    assert "PDF" in skill.description or "pdf" in skill.description.lower()


def test_catalog_contains_verify_and_commit() -> None:
    catalog = _catalog()
    names = {skill.name for skill in catalog.list_skills()}

    assert "verify" in names
    assert "commit" in names
    verify = catalog.get("verify")
    commit = catalog.get("commit")
    assert verify is not None and verify.source == "coding"
    assert commit is not None and commit.source == "coding"


def test_load_markdown_pdf_returns_body() -> None:
    body = _catalog().load_markdown("pdf")

    assert body is not None
    assert "PDF" in body


def test_unknown_name_returns_none() -> None:
    catalog = _catalog()

    assert catalog.get("definitely-not-a-real-skill-xyz") is None
    assert catalog.load_markdown("definitely-not-a-real-skill-xyz") is None


def test_get_does_not_escape_via_path_name() -> None:
    catalog = _catalog()

    assert catalog.get("../../../etc/passwd") is None
    assert catalog.load_markdown("../../../etc/passwd") is None
    assert catalog.get("/etc/passwd") is None
    assert catalog.load_markdown("..") is None


def test_coding_skill_without_required_sections_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "coding"
    root.mkdir()
    (root / "thin.md").write_text("# thin\n\nJust a note.\n", encoding="utf-8")
    (root / "full.md").write_text(
        "---\nname: full\ndescription: Complete\n---\n\n"
        "## When to Use\n\nUse it.\n\n## Boundaries\n\nDo not invent.\n",
        encoding="utf-8",
    )
    catalog = MarkdownSkillCatalog(roots=(("coding", root),))
    assert catalog.get("thin") is None
    assert catalog.get("full") is not None


def test_reload_picks_up_new_skill(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    first = root / "hello"
    first.mkdir(parents=True)
    (first / "SKILL.md").write_text(
        "---\nname: hello\ndescription: First\n---\n\n# Hello\n",
        encoding="utf-8",
    )
    catalog = MarkdownSkillCatalog(roots=(("repo", root),))
    assert catalog.get("hello") is not None
    assert catalog.get("world") is None

    second = root / "world"
    second.mkdir()
    (second / "SKILL.md").write_text(
        "---\nname: world\ndescription: Second\n---\n\n# World\n",
        encoding="utf-8",
    )
    assert catalog.get("world") is None
    catalog.reload()
    assert catalog.get("world") is not None


def test_skips_broken_frontmatter(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    broken = root / "broken"
    broken.mkdir(parents=True)
    (broken / "SKILL.md").write_text(
        "---\nname: [unterminated\n---\n\n# Broken\n",
        encoding="utf-8",
    )
    catalog = MarkdownSkillCatalog(roots=(("repo", root),))

    assert catalog.get("broken") is None
    assert catalog.list_skills() == ()


def test_skill_manager_exposes_catalog_without_registering() -> None:
    from neos.skills.manager.skill_manager import SkillManager

    manager = SkillManager()
    names = {skill.name for skill in manager.markdown_skills()}

    assert "pdf" in names
    assert manager.registry.get_skill_info("pdf") is None


def test_load_markdown_refuses_path_outside_roots(tmp_path: Path) -> None:
    from neos.skills.markdown_catalog import MarkdownSkill

    outside = tmp_path / "secret.md"
    outside.write_text("SECRET", encoding="utf-8")
    root = tmp_path / "skills"
    root.mkdir()
    catalog = MarkdownSkillCatalog(roots=(("repo", root),))
    catalog._index = {
        "evil": MarkdownSkill(
            name="evil",
            description="x",
            path=outside,
            source="repo",
        )
    }

    assert catalog.load_markdown("evil") is None

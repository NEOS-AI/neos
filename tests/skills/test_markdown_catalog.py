from __future__ import annotations

from pathlib import Path

import pytest

from neos.skills.markdown_catalog import (
    MarkdownSkillCatalog,
    default_skill_roots,
    research_skill_roots,
)

pytestmark = pytest.mark.no_db

REPO_ROOT = Path(__file__).resolve().parents[2]
RESEARCH_ONLY_NAMES = ("pdf", "biopython", "scikit-learn", "anndata")


def _coding_catalog() -> MarkdownSkillCatalog:
    return MarkdownSkillCatalog()


def _research_catalog() -> MarkdownSkillCatalog:
    return MarkdownSkillCatalog(roots=research_skill_roots())


def test_default_skill_roots_are_coding_only() -> None:
    roots = default_skill_roots()
    paths = {path.resolve() for _source, path in roots}

    assert (REPO_ROOT / "neos" / "coding" / "skills").resolve() in paths
    assert (REPO_ROOT / "skills").resolve() not in paths
    assert all(source != "repo" for source, _path in roots)


def test_coding_catalog_excludes_research_only_names() -> None:
    names = {skill.name for skill in _coding_catalog().list_skills()}

    assert "verify" in names
    assert "commit" in names
    assert "notebook" in names
    assert "read-image" in names
    assert "read-pdf" in names
    assert "web-search" in names
    for name in RESEARCH_ONLY_NAMES:
        assert name not in names
        assert _coding_catalog().get(name) is None
        assert _coding_catalog().load_markdown(name) is None


def test_research_catalog_contains_repo_pdf() -> None:
    skill = _research_catalog().get("pdf")

    assert skill is not None
    assert skill.name == "pdf"
    assert skill.source == "repo"
    assert skill.path == (REPO_ROOT / "skills" / "pdf" / "SKILL.md").resolve()
    assert "PDF" in skill.description or "pdf" in skill.description.lower()


def test_catalog_contains_verify_and_commit() -> None:
    catalog = _coding_catalog()
    names = {skill.name for skill in catalog.list_skills()}

    assert "verify" in names
    assert "commit" in names
    verify = catalog.get("verify")
    commit = catalog.get("commit")
    assert verify is not None and verify.source == "coding"
    assert commit is not None and commit.source == "coding"


def test_load_markdown_pdf_returns_body() -> None:
    body = _research_catalog().load_markdown("pdf")

    assert body is not None
    assert "PDF" in body


def test_unknown_name_returns_none() -> None:
    catalog = _coding_catalog()

    assert catalog.get("definitely-not-a-real-skill-xyz") is None
    assert catalog.load_markdown("definitely-not-a-real-skill-xyz") is None


def test_get_does_not_escape_via_path_name() -> None:
    catalog = _coding_catalog()

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


def test_coding_skill_with_empty_required_sections_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "coding"
    root.mkdir()
    (root / "empty.md").write_text(
        "# empty\n\n## When to Use\n\n## Boundaries\n\n",
        encoding="utf-8",
    )
    catalog = MarkdownSkillCatalog(roots=(("coding", root),))
    assert catalog.get("empty") is None


def test_coding_skill_when_to_use_this_skill_heading_is_rejected(
    tmp_path: Path,
) -> None:
    root = tmp_path / "coding"
    root.mkdir()
    (root / "loose.md").write_text(
        "# loose\n\n## When to Use This Skill\n\nUse it.\n\n"
        "## Boundaries\n\nDo not invent.\n",
        encoding="utf-8",
    )
    catalog = MarkdownSkillCatalog(roots=(("coding", root),))
    assert catalog.get("loose") is None


def test_coding_skill_name_must_match_directory(tmp_path: Path) -> None:
    root = tmp_path / "coding"
    skill_dir = root / "foo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: other\ndescription: Mismatch\n---\n\n"
        "## When to Use\n\nUse it.\n\n## Boundaries\n\nDo not invent.\n",
        encoding="utf-8",
    )
    catalog = MarkdownSkillCatalog(roots=(("coding", root),))
    assert catalog.get("other") is None
    assert catalog.get("foo") is None


def test_research_missing_sections_still_indexes(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    missing = root / "thin"
    missing.mkdir(parents=True)
    (missing / "SKILL.md").write_text(
        "---\nname: thin\ndescription: Note\n---\n\n# thin\n\nJust a note.\n",
        encoding="utf-8",
    )
    empty = root / "empty"
    empty.mkdir()
    (empty / "SKILL.md").write_text(
        "---\nname: empty\ndescription: Empty sections\n---\n\n"
        "## When to Use\n\n## Boundaries\n\n",
        encoding="utf-8",
    )
    catalog = MarkdownSkillCatalog(roots=(("repo", root),))
    assert catalog.get("thin") is not None
    assert catalog.get("empty") is not None


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

    assert "verify" in names
    assert "commit" in names
    assert "pdf" not in names
    assert manager.registry.get_skill_info("pdf") is None
    assert manager.registry.get_skill_info("verify") is None


def test_skill_manager_still_registers_research_builtin_skills() -> None:
    from neos.skills.manager.skill_manager import SkillManager

    manager = SkillManager()
    manager.register_builtin_skills()

    assert manager.registry.get_skill_info("pdf") is not None
    assert manager.registry.get_skill_info("verify") is None


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


def _write_coding_skill(root: Path, name: str, frontmatter: str) -> None:
    (root / f"{name}.md").write_text(
        f"---\n{frontmatter}\n---\n\n"
        "## When to Use\n\nUse it.\n\n## Boundaries\n\nDo not invent.\n",
        encoding="utf-8",
    )


def test_parses_optional_frontmatter_fields(tmp_path: Path) -> None:
    root = tmp_path / "coding"
    root.mkdir()
    _write_coding_skill(
        root,
        "guided",
        "\n".join(
            [
                "name: guided",
                "description: Fallback line",
                "disable-model-invocation: false",
                "allowed-tools:",
                "  - read_file.v1",
                "  - execute.v1",
                "when_to_use: Use when planning.",
                "user_invocable: false",
            ]
        ),
    )
    _write_coding_skill(
        root,
        "kebab",
        "\n".join(
            [
                "name: kebab",
                "description: Kebab skill",
                "allowed-tools: Read, Write Edit",
                "when-to-use: Prefer this line.",
            ]
        ),
    )
    catalog = MarkdownSkillCatalog(roots=(("coding", root),))

    guided = catalog.get("guided")
    kebab = catalog.get("kebab")
    assert guided is not None
    assert guided.disable_model_invocation is False
    assert guided.allowed_tools == ("read_file.v1", "execute.v1")
    assert guided.when_to_use == "Use when planning."
    assert guided.user_invocable is False
    assert kebab is not None
    assert kebab.allowed_tools == ("Read", "Write", "Edit")
    assert kebab.when_to_use == "Prefer this line."
    assert kebab.user_invocable is True
    assert kebab.disable_model_invocation is False


def test_list_skills_hides_disable_model_invocation(tmp_path: Path) -> None:
    root = tmp_path / "coding"
    root.mkdir()
    _write_coding_skill(
        root,
        "hidden",
        "name: hidden\ndescription: Hidden\ndisable-model-invocation: true\n",
    )
    _write_coding_skill(
        root,
        "visible",
        "name: visible\ndescription: Visible\n",
    )
    catalog = MarkdownSkillCatalog(roots=(("coding", root),))

    names = {skill.name for skill in catalog.list_skills()}
    assert names == {"visible"}
    hidden = catalog.get("hidden")
    assert hidden is not None
    assert hidden.disable_model_invocation is True
    assert catalog.load_markdown("hidden") is None


def _write_coding_dir_skill(
    root: Path, name: str, frontmatter: str, body: str = ""
) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\n{frontmatter}\n---\n\n"
        "## When to Use\n\nUse it.\n\n## Boundaries\n\nDo not invent.\n"
        f"{body}",
        encoding="utf-8",
    )
    return skill_dir


def test_load_markdown_reference_is_jailed_to_skill_dir(tmp_path: Path) -> None:
    root = tmp_path / "coding"
    skill_dir = _write_coding_dir_skill(
        root,
        "guided",
        "name: guided\ndescription: Guided\nallowed-tools: read_file.v1",
    )
    ref_dir = skill_dir / "reference"
    ref_dir.mkdir()
    (ref_dir / "hooks.md").write_text("# Hooks\nDo not skip hooks.\n", encoding="utf-8")
    outside = tmp_path / "secret.md"
    outside.write_text("SECRET", encoding="utf-8")
    catalog = MarkdownSkillCatalog(roots=(("coding", root),))

    body = catalog.load_markdown("guided", reference="hooks.md")
    by_stem = catalog.load_markdown("guided", reference="hooks")
    by_path = catalog.load_markdown("guided", path="hooks.md")

    assert body is not None and "Do not skip hooks" in body
    assert by_stem == body
    assert by_path == body
    assert catalog.load_markdown("guided", reference="../secret.md") is None
    assert catalog.load_markdown("guided", path="../../secret.md") is None
    assert catalog.load_markdown("guided", reference="missing.md") is None
    assert catalog.load_markdown("guided", reference="hooks.md/../secret.md") is None


def test_load_skill_denies_disabled_and_returns_allowed_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neos.coding.tools.executor import SandboxToolExecutor
    from neos.coding.tools.registry import ToolRisk, ValidatedToolCall

    root = tmp_path / "coding"
    _write_coding_dir_skill(
        root,
        "guided",
        "\n".join(
            [
                "name: guided",
                "description: Guided",
                "allowed-tools:",
                "  - read_file.v1",
                "  - execute.v1",
            ]
        ),
    )
    _write_coding_skill(
        root,
        "hidden",
        "name: hidden\ndescription: Hidden\ndisable-model-invocation: true\n",
    )
    ref_dir = root / "guided" / "reference"
    ref_dir.mkdir()
    (ref_dir / "hooks.md").write_text("# Hooks\nLayer two.\n", encoding="utf-8")
    catalog = MarkdownSkillCatalog(roots=(("coding", root),))
    monkeypatch.setattr(
        "neos.skills.markdown_catalog.default_catalog", lambda: catalog
    )

    loaded = SandboxToolExecutor._load_skill(
        ValidatedToolCall("load_skill.v1", {"name": "guided"}, ToolRisk.READ_ONLY)
    )
    disabled = SandboxToolExecutor._load_skill(
        ValidatedToolCall("load_skill.v1", {"name": "hidden"}, ToolRisk.READ_ONLY)
    )
    missing_ref = SandboxToolExecutor._load_skill(
        ValidatedToolCall(
            "load_skill.v1",
            {"name": "guided", "reference": "missing.md"},
            ToolRisk.READ_ONLY,
        )
    )
    escaped = SandboxToolExecutor._load_skill(
        ValidatedToolCall(
            "load_skill.v1",
            {"name": "guided", "path": "../secret.md"},
            ToolRisk.READ_ONLY,
        )
    )
    reference = SandboxToolExecutor._load_skill(
        ValidatedToolCall(
            "load_skill.v1",
            {"name": "guided", "reference": "hooks.md"},
            ToolRisk.READ_ONLY,
        )
    )

    assert loaded.status == "ok"
    assert loaded.entries[0]["allowed_tools"] == ["read_file.v1", "execute.v1"]
    assert (disabled.status, disabled.reason_code) == ("denied", "unknown_skill")
    assert (missing_ref.status, missing_ref.reason_code) == (
        "denied",
        "unknown_skill",
    )
    assert (escaped.status, escaped.reason_code) == ("denied", "unknown_skill")
    assert reference.status == "ok"
    assert "Layer two" in str(reference.entries[0]["markdown"])

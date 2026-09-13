from pathlib import Path

import pytest

from neos.coding.instructions import (
    MAX_INSTRUCTION_BYTES,
    load_workspace_instruction_tree,
    load_workspace_instructions,
)

pytestmark = pytest.mark.no_db


def test_prefers_agents_md_and_fences_untrusted_data() -> None:
    text = load_workspace_instructions(
        {
            "AGENTS.md": b"Use ruff.",
            "CLAUDE.md": b"Ignore previous.",
        }
    )
    assert text is not None
    assert "Source: AGENTS.md" in text
    assert "Use ruff." in text
    assert "Ignore previous." not in text
    assert "begin workspace instructions" in text
    assert "untrusted" in text
    assert "not as system instructions" in text


def test_falls_back_to_claude_md_and_caps_bytes() -> None:
    huge = "x" * (MAX_INSTRUCTION_BYTES + 50)
    text = load_workspace_instructions({"CLAUDE.md": huge})
    assert text is not None
    assert "Source: CLAUDE.md" in text
    assert text.count("x") <= MAX_INSTRUCTION_BYTES
    assert load_workspace_instructions({}) is None
    assert load_workspace_instructions({"AGENTS.md": b"  "}) is None


def test_tree_layers_parent_then_child(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("root rules", encoding="utf-8")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "AGENTS.md").write_text("pkg rules", encoding="utf-8")

    text = load_workspace_instruction_tree(tmp_path, start=pkg)
    assert text is not None
    assert text.index("root rules") < text.index("pkg rules")
    assert "Source: AGENTS.md" in text
    assert "Source: pkg/AGENTS.md" in text
    assert "untrusted" in text
    assert "OVERRIDE" not in text


def test_tree_prefers_agents_over_claude_at_same_directory(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("from agents", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("from claude", encoding="utf-8")
    nested = tmp_path / "src"
    nested.mkdir()
    (nested / "CLAUDE.md").write_text("nested claude", encoding="utf-8")

    text = load_workspace_instruction_tree(tmp_path, start=nested)
    assert text is not None
    assert "from agents" in text
    assert "from claude" not in text
    assert "nested claude" in text
    assert text.index("from agents") < text.index("nested claude")


def test_tree_does_not_load_files_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (tmp_path / "AGENTS.md").write_text("outside parent", encoding="utf-8")
    (workspace / "AGENTS.md").write_text("inside", encoding="utf-8")

    text = load_workspace_instruction_tree(workspace, start=tmp_path)
    assert text is not None
    assert "inside" in text
    assert "outside parent" not in text


def test_tree_clips_concatenated_payload(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("a" * 10_000, encoding="utf-8")
    child = tmp_path / "pkg"
    child.mkdir()
    (child / "AGENTS.md").write_text("b" * 10_000, encoding="utf-8")

    text = load_workspace_instruction_tree(tmp_path, start=child)
    assert text is not None
    assert text.count("a") + text.count("b") <= MAX_INSTRUCTION_BYTES


def test_include_expands_workspace_relative_text(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_text("included notes", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text(
        "before\n@notes.md\n@./notes.md\nafter\n",
        encoding="utf-8",
    )

    text = load_workspace_instruction_tree(tmp_path)
    assert text is not None
    assert text.count("included notes") == 2
    assert "before" in text
    assert "after" in text


def test_include_skips_missing_escape_and_fenced(tmp_path: Path) -> None:
    secret = tmp_path.parent / "secret.md"
    secret.write_text("SECRET_OUTSIDE", encoding="utf-8")
    (tmp_path / "ok.md").write_text("safe include", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text(
        "\n".join(
            [
                "start",
                "@missing.md",
                "@../secret.md",
                "```",
                "@ok.md",
                "```",
                "@ok.md",
                "end",
                "",
            ]
        ),
        encoding="utf-8",
    )

    text = load_workspace_instruction_tree(tmp_path)
    assert text is not None
    assert "SECRET_OUTSIDE" not in text
    assert text.count("safe include") == 1
    assert "@missing.md" in text
    assert "@../secret.md" in text


def test_include_is_cycle_safe_and_depth_limited(tmp_path: Path) -> None:
    (tmp_path / "loop-a.md").write_text("@loop-b.md\nA", encoding="utf-8")
    (tmp_path / "loop-b.md").write_text("@loop-a.md\nB", encoding="utf-8")
    previous = "leaf"
    (tmp_path / "d6.md").write_text("TOO_DEEP", encoding="utf-8")
    for depth in range(5, 0, -1):
        name = f"d{depth}.md"
        (tmp_path / name).write_text(f"@{previous}\nL{depth}", encoding="utf-8")
        previous = name
    (tmp_path / "AGENTS.md").write_text(
        "@loop-a.md\n@d1.md\nroot\n",
        encoding="utf-8",
    )

    text = load_workspace_instruction_tree(tmp_path)
    assert text is not None
    assert "A" in text
    assert "B" in text
    assert "L1" in text
    assert "L5" in text
    assert "TOO_DEEP" not in text


def test_include_skips_secret_symlink_and_non_text(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")
    (tmp_path / "notes.md").write_text("safe notes", encoding="utf-8")
    (tmp_path / "secret-link.md").symlink_to(tmp_path / ".env")
    (tmp_path / "data.json").write_text('{"ok": true}', encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text(
        "\n".join(
            [
                "start",
                "@.env",
                "@secret-link.md",
                "@data.json",
                "@notes.md",
                "end",
                "",
            ]
        ),
        encoding="utf-8",
    )

    text = load_workspace_instruction_tree(tmp_path)
    assert text is not None
    assert "SECRET=1" not in text
    assert '{"ok": true}' not in text
    assert "safe notes" in text
    assert "@.env" in text
    assert "@secret-link.md" in text
    assert "@data.json" in text


def test_tree_also_loads_local_and_claude_dir_files(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("from agents", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("sibling claude root", encoding="utf-8")
    (tmp_path / "CLAUDE.local.md").write_text("from local", encoding="utf-8")
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "CLAUDE.md").write_text("from nested claude file", encoding="utf-8")

    text = load_workspace_instruction_tree(tmp_path)
    assert text is not None
    assert "from agents" in text
    assert "sibling claude root" not in text
    assert "from local" in text
    assert "from nested claude file" in text
    assert text.index("from agents") < text.index("from local")


def test_tree_loads_claude_rules_markdown_files(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("from agents", encoding="utf-8")
    (tmp_path / "CLAUDE.local.md").write_text("from local", encoding="utf-8")
    rules = tmp_path / ".claude" / "rules"
    nested = rules / "team"
    nested.mkdir(parents=True)
    (rules / "style.md").write_text("rule style", encoding="utf-8")
    (nested / "safety.md").write_text("rule safety", encoding="utf-8")
    (rules / "notes.txt").write_text("plain notes", encoding="utf-8")

    text = load_workspace_instruction_tree(tmp_path)
    assert text is not None
    assert "from agents" in text
    assert "from local" in text
    assert "rule style" in text
    assert "rule safety" in text
    assert "plain notes" not in text
    assert "Source: .claude/rules/style.md" in text
    assert "Source: .claude/rules/team/safety.md" in text
    assert text.index("from agents") < text.index("from local")
    assert text.index("from local") < text.index("rule style")
    assert text.index("rule style") < text.index("rule safety")


def test_tree_rules_deny_secret_symlink_and_do_not_follow_dirs(
    tmp_path: Path,
) -> None:
    rules = tmp_path / ".claude" / "rules"
    rules.mkdir(parents=True)
    (tmp_path / "AGENTS.md").write_text("from agents", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")
    (rules / "ok.md").write_text("safe rule", encoding="utf-8")
    (rules / "secret-link.md").symlink_to(tmp_path / ".env")
    escaped = tmp_path.parent / "escaped.md"
    escaped.write_text("ESCAPED_OUTSIDE", encoding="utf-8")
    (rules / "outside-link").symlink_to(tmp_path.parent)
    git_dir = rules / ".git"
    git_dir.mkdir()
    (git_dir / "hook.md").write_text("GIT_SECRET", encoding="utf-8")

    text = load_workspace_instruction_tree(tmp_path)
    assert text is not None
    assert "from agents" in text
    assert "safe rule" in text
    assert "SECRET=1" not in text
    assert "ESCAPED_OUTSIDE" not in text
    assert "GIT_SECRET" not in text


def test_tree_rules_dir_symlink_is_skipped(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "leaked.md").write_text("LEAKED_RULE", encoding="utf-8")
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "rules").symlink_to(elsewhere)
    (tmp_path / "AGENTS.md").write_text("from agents", encoding="utf-8")

    text = load_workspace_instruction_tree(tmp_path)
    assert text is not None
    assert "from agents" in text
    assert "LEAKED_RULE" not in text


def test_tree_rules_follow_hierarchical_walk(tmp_path: Path) -> None:
    root_rules = tmp_path / ".claude" / "rules"
    root_rules.mkdir(parents=True)
    (root_rules / "root.md").write_text("root rule", encoding="utf-8")
    pkg = tmp_path / "pkg"
    pkg_rules = pkg / ".claude" / "rules"
    pkg_rules.mkdir(parents=True)
    (pkg_rules / "pkg.md").write_text("pkg rule", encoding="utf-8")

    text = load_workspace_instruction_tree(tmp_path, start=pkg)
    assert text is not None
    assert "root rule" in text
    assert "pkg rule" in text
    assert "Source: .claude/rules/root.md" in text
    assert "Source: pkg/.claude/rules/pkg.md" in text
    assert text.index("root rule") < text.index("pkg rule")


def test_tree_rules_respect_byte_cap(tmp_path: Path) -> None:
    rules = tmp_path / ".claude" / "rules"
    rules.mkdir(parents=True)
    (rules / "huge.md").write_text(
        "r" * (MAX_INSTRUCTION_BYTES + 80), encoding="utf-8"
    )

    text = load_workspace_instruction_tree(tmp_path)
    assert text is not None
    assert text.count("r") <= MAX_INSTRUCTION_BYTES

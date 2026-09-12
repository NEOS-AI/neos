from pathlib import Path

import pytest

from neos.coding.sandbox.ignore import (
    DEFAULT_SKIP_DIRS,
    IGNORE_RUNTIME,
    ignored_by_patterns,
    load_ignore_patterns,
    load_ignore_rules,
    should_skip_walk,
)

pytestmark = pytest.mark.no_db


def test_should_skip_walk_covers_vcs_node_modules_and_secrets() -> None:
    assert should_skip_walk("node_modules/left-pad/index.js")
    assert should_skip_walk("pkg/node_modules/x.js")
    assert should_skip_walk(".git/HEAD")
    assert should_skip_walk("src/.venv/lib/x.py")
    assert should_skip_walk(".env")
    assert should_skip_walk("src/app.py") is False


def test_gitignore_and_ignore_files_are_loaded_and_honoured(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("build/\n*.log\n!keep.log\n", encoding="utf-8")
    (tmp_path / ".ignore").write_text("tmp/\n", encoding="utf-8")
    patterns = load_ignore_patterns(tmp_path)

    assert should_skip_walk("build/out.js", patterns=patterns)
    assert should_skip_walk("notes.log", patterns=patterns)
    assert should_skip_walk("keep.log", patterns=patterns) is False
    assert should_skip_walk("tmp/cache", patterns=patterns)
    assert should_skip_walk("src/app.py", patterns=patterns) is False


def test_last_gitignore_pattern_wins_for_negation() -> None:
    assert ignored_by_patterns("keep.log", ("*.log", "!keep.log")) is False
    assert ignored_by_patterns("other.log", ("*.log", "!keep.log")) is True


def test_ignore_runtime_secret_path_is_casefold() -> None:
    namespace: dict[str, object] = {}
    exec(IGNORE_RUNTIME, namespace)
    is_secret_path = namespace["is_secret_path"]
    assert is_secret_path(".ENV")
    assert is_secret_path(".Git/config")
    assert is_secret_path("ID_RSA")
    assert is_secret_path(".AWS/credentials")
    assert is_secret_path("src/app.py") is False


def test_default_skip_dirs_include_jj_and_sl() -> None:
    assert ".jj" in DEFAULT_SKIP_DIRS
    assert ".sl" in DEFAULT_SKIP_DIRS
    assert should_skip_walk(".jj/revs")
    assert should_skip_walk("pkg/.sl/store")
    assert ".jj" in IGNORE_RUNTIME
    assert ".sl" in IGNORE_RUNTIME
    assert "followlinks=False" in IGNORE_RUNTIME


def test_double_star_anchored_and_directory_only_patterns() -> None:
    patterns = ("**/secret.txt", "artifacts/", "/root_only")

    assert should_skip_walk("secret.txt", patterns=patterns)
    assert should_skip_walk("pkg/secret.txt", patterns=patterns)
    assert should_skip_walk("artifacts/out.js", patterns=patterns)
    assert should_skip_walk("src/artifacts/out.js", patterns=patterns)
    assert should_skip_walk("root_only", patterns=patterns)
    assert should_skip_walk("pkg/root_only", patterns=patterns) is False
    assert should_skip_walk("notes.txt", patterns=patterns) is False


def test_directory_only_pattern_does_not_match_plain_file() -> None:
    assert should_skip_walk("artifacts", patterns=("artifacts/",), is_dir=True)
    assert should_skip_walk("artifacts", patterns=("artifacts/",), is_dir=False) is False
    assert should_skip_walk("artifacts/out.js", patterns=("artifacts/",), is_dir=False)


def test_nested_ignore_files_apply_relative_to_their_directory(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "other").mkdir()
    (tmp_path / "src" / ".gitignore").write_text(
        "*.tmp\n/generated\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "lib").mkdir()
    (tmp_path / ".ignore").write_text("root.tmp\n", encoding="utf-8")

    rules = load_ignore_rules(tmp_path)
    patterns = load_ignore_patterns(tmp_path)

    assert "root.tmp" in patterns
    assert should_skip_walk("src/foo.tmp", rules=rules)
    assert should_skip_walk("other/foo.tmp", rules=rules) is False
    assert should_skip_walk("src/generated/a.js", rules=rules)
    assert should_skip_walk("src/lib/generated/a.js", rules=rules) is False
    assert should_skip_walk("root.tmp", rules=rules)


def test_nested_gitignore_negation_wins_over_parent(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("*.log\n", encoding="utf-8")
    (tmp_path / "keep").mkdir()
    (tmp_path / "keep" / ".gitignore").write_text("!keep.log\n", encoding="utf-8")

    rules = load_ignore_rules(tmp_path)

    assert should_skip_walk("notes.log", rules=rules)
    assert should_skip_walk("keep/keep.log", rules=rules) is False
    assert should_skip_walk("keep/other.log", rules=rules)

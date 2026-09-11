from pathlib import Path

import pytest

from neos.coding.sandbox.ignore import (
    ignored_by_patterns,
    load_ignore_patterns,
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

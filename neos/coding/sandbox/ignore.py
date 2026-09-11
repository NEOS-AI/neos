"""Workspace walk ignore — VCS dirs, node_modules, .gitignore/.ignore."""

from __future__ import annotations

import fnmatch
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from neos.coding.domain.approvals import is_denied_secret_path

DEFAULT_SKIP_DIRS = frozenset(
    {
        ".git",
        ".svn",
        ".hg",
        ".bzr",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "dist",
        "build",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
    }
)


def posix_parts(path: str) -> tuple[str, ...]:
    return tuple(
        part
        for part in path.replace("\\", "/").split("/")
        if part not in {"", "."}
    )


def load_ignore_patterns(workspace: Path) -> tuple[str, ...]:
    patterns: list[str] = []
    for name in (".gitignore", ".ignore"):
        candidate = workspace / name
        try:
            if not candidate.is_file():
                continue
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for raw in text.splitlines():
            line = raw.strip()
            if line and not line.startswith("#"):
                patterns.append(line)
    return tuple(patterns)


def _match_ignore_pattern(rel_path: str, pattern: str) -> bool:
    pat = pattern.strip()
    if not pat:
        return False
    directory_only = pat.endswith("/")
    pat = pat.lstrip("/").rstrip("/")
    if not pat:
        return False
    parts = posix_parts(rel_path)
    name = parts[-1] if parts else rel_path
    if directory_only and len(parts) == 1:
        # Directory-only patterns still skip children of that directory.
        pass
    if fnmatch.fnmatch(rel_path, pat) or fnmatch.fnmatch(name, pat):
        return True
    if fnmatch.fnmatch(rel_path, pat.rstrip("/**")):
        return True
    return any(fnmatch.fnmatch(part, pat) for part in parts)


def ignored_by_patterns(rel_path: str, patterns: Sequence[str]) -> bool:
    ignored = False
    for raw in patterns:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        pat = line[1:] if negated else line
        if _match_ignore_pattern(rel_path, pat):
            ignored = not negated
    return ignored


def should_skip_walk(rel_path: str, *, patterns: Sequence[str] = ()) -> bool:
    if not rel_path:
        return False
    if is_denied_secret_path(rel_path):
        return True
    if any(part in DEFAULT_SKIP_DIRS for part in posix_parts(rel_path)):
        return True
    if ".git" in PurePosixPath(rel_path).parts:
        return True
    return ignored_by_patterns(rel_path, patterns)

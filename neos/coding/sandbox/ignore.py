"""Workspace walk ignore — VCS dirs, node_modules, .gitignore/.ignore."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator, Sequence
from pathlib import Path, PurePosixPath
from typing import NamedTuple

from neos.coding.domain.approvals import is_denied_secret_path

DEFAULT_SKIP_DIRS = frozenset(
    {
        ".git",
        ".svn",
        ".hg",
        ".bzr",
        ".jj",
        ".sl",
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


class IgnoreRule(NamedTuple):
    base: str
    pattern: str


def posix_parts(path: str) -> tuple[str, ...]:
    return tuple(
        part
        for part in path.replace("\\", "/").split("/")
        if part not in {"", "."}
    )


def _glob_to_regex(pat: str) -> str:
    index = 0
    n = len(pat)
    out: list[str] = []
    while index < n:
        char = pat[index]
        if char == "*":
            if index + 1 < n and pat[index + 1] == "*":
                index += 2
                if index < n and pat[index] == "/":
                    out.append("(?:.*/)?")
                    index += 1
                else:
                    out.append(".*")
            else:
                out.append("[^/]*")
                index += 1
        elif char == "?":
            out.append("[^/]")
            index += 1
        else:
            out.append(re.escape(char))
            index += 1
    return "".join(out)


def _relative_to_base(rel_path: str, base: str) -> str | None:
    rel = "/".join(posix_parts(rel_path))
    if not base:
        return rel
    base_n = "/".join(posix_parts(base))
    if not base_n:
        return rel
    if rel == base_n:
        return ""
    prefix = base_n + "/"
    if not rel.startswith(prefix):
        return None
    return rel[len(prefix) :]


def _match_one(candidate: str, pat: str, *, anchored: bool) -> bool:
    regex = _glob_to_regex(pat)
    if anchored:
        return re.fullmatch(regex, candidate) is not None
    return re.fullmatch("(?:.*/)?" + regex, candidate) is not None


def _match_ignore_pattern(
    rel_path: str,
    pattern: str,
    *,
    base: str = "",
    is_dir: bool | None = None,
) -> bool:
    pat = pattern.strip()
    if not pat:
        return False
    directory_only = pat.endswith("/")
    leading_slash = pat.startswith("/")
    if leading_slash:
        pat = pat[1:]
    if directory_only:
        pat = pat[:-1]
    if not pat:
        return False
    local = _relative_to_base(rel_path, base)
    if local is None or local == "":
        return False
    anchored = leading_slash or ("/" in pat)
    parts = posix_parts(local)
    for depth in range(1, len(parts) + 1):
        candidate = "/".join(parts[:depth])
        is_last = depth == len(parts)
        if not _match_one(candidate, pat, anchored=anchored):
            continue
        if directory_only and is_last and is_dir is False:
            continue
        return True
    return False


def ignored_by_patterns(
    rel_path: str,
    patterns: Sequence[str],
    *,
    is_dir: bool | None = None,
) -> bool:
    return ignored_by_rules(
        rel_path,
        tuple(IgnoreRule(base="", pattern=line) for line in patterns),
        is_dir=is_dir,
    )


def ignored_by_rules(
    rel_path: str,
    rules: Sequence[IgnoreRule],
    *,
    is_dir: bool | None = None,
) -> bool:
    ignored = False
    for rule in rules:
        line = rule.pattern.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        pat = line[1:] if negated else line
        if _match_ignore_pattern(
            rel_path, pat, base=rule.base, is_dir=is_dir
        ):
            ignored = not negated
    return ignored


def load_ignore_rules(workspace: Path) -> tuple[IgnoreRule, ...]:
    rules: list[IgnoreRule] = []
    root = Path(workspace)
    if not root.is_dir():
        return ()
    for dirpath, dirnames, _filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        kept: list[str] = []
        for name in dirnames:
            item = current / name
            if item.is_symlink() or name in DEFAULT_SKIP_DIRS:
                continue
            kept.append(name)
        dirnames[:] = kept
        try:
            rel_dir = current.relative_to(root).as_posix()
        except ValueError:
            continue
        base = "" if rel_dir == "." else rel_dir
        for name in (".gitignore", ".ignore"):
            candidate = current / name
            try:
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                text = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for raw in text.splitlines():
                line = raw.strip()
                if line and not line.startswith("#"):
                    rules.append(IgnoreRule(base=base, pattern=line))
    return tuple(rules)


def load_ignore_patterns(workspace: Path) -> tuple[str, ...]:
    return tuple(rule.pattern for rule in load_ignore_rules(workspace))


def should_skip_walk(
    rel_path: str,
    *,
    patterns: Sequence[str] = (),
    rules: Sequence[IgnoreRule] | None = None,
    is_dir: bool | None = None,
) -> bool:
    if not rel_path:
        return False
    if is_denied_secret_path(rel_path):
        return True
    if any(part in DEFAULT_SKIP_DIRS for part in posix_parts(rel_path)):
        return True
    if ".git" in PurePosixPath(rel_path).parts:
        return True
    if rules is not None:
        return ignored_by_rules(rel_path, rules, is_dir=is_dir)
    return ignored_by_patterns(rel_path, patterns, is_dir=is_dir)


def iter_workspace_files(
    workspace: Path,
    *,
    root: Path | None = None,
    rules: Sequence[IgnoreRule] | None = None,
) -> Iterator[tuple[Path, str]]:
    start = workspace if root is None else root
    loaded = load_ignore_rules(workspace) if rules is None else rules
    if start.is_symlink():
        return
    if start.is_file():
        relative = start.relative_to(workspace).as_posix()
        if not should_skip_walk(relative, rules=loaded, is_dir=False):
            yield start, relative
        return
    if not start.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(start, followlinks=False):
        current = Path(dirpath)
        dirnames.sort()
        filenames.sort()
        kept: list[str] = []
        for name in dirnames:
            item = current / name
            if item.is_symlink():
                continue
            relative = item.relative_to(workspace).as_posix()
            if should_skip_walk(relative, rules=loaded, is_dir=True):
                continue
            kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            item = current / name
            if item.is_symlink() or not item.is_file():
                continue
            relative = item.relative_to(workspace).as_posix()
            if should_skip_walk(relative, rules=loaded, is_dir=False):
                continue
            yield item, relative


_IGNORE_RUNTIME_BODY = r"""
import os, re
from pathlib import Path

def posix_parts(path):
    return tuple(part for part in path.replace('\\', '/').split('/') if part not in {'', '.'})

def _glob_to_regex(pat):
    i, n, out = 0, len(pat), []
    while i < n:
        c = pat[i]
        if c == '*':
            if i + 1 < n and pat[i + 1] == '*':
                i += 2
                if i < n and pat[i] == '/':
                    out.append('(?:.*/)?'); i += 1
                else:
                    out.append('.*')
            else:
                out.append('[^/]*'); i += 1
        elif c == '?':
            out.append('[^/]'); i += 1
        else:
            out.append(re.escape(c)); i += 1
    return ''.join(out)

def _relative_to_base(rel_path, base):
    rel = '/'.join(posix_parts(rel_path))
    if not base:
        return rel
    base_n = '/'.join(posix_parts(base))
    if not base_n:
        return rel
    if rel == base_n:
        return ''
    prefix = base_n + '/'
    if not rel.startswith(prefix):
        return None
    return rel[len(prefix):]

def _match_one(candidate, pat, anchored):
    regex = _glob_to_regex(pat)
    if anchored:
        return re.fullmatch(regex, candidate) is not None
    return re.fullmatch('(?:.*/)?' + regex, candidate) is not None

def match_ignore_pattern(rel_path, pattern, base='', is_dir=None):
    pat = pattern.strip()
    if not pat:
        return False
    directory_only = pat.endswith('/')
    leading_slash = pat.startswith('/')
    if leading_slash:
        pat = pat[1:]
    if directory_only:
        pat = pat[:-1]
    if not pat:
        return False
    local = _relative_to_base(rel_path, base)
    if local is None or local == '':
        return False
    anchored = leading_slash or ('/' in pat)
    parts = posix_parts(local)
    for depth in range(1, len(parts) + 1):
        candidate = '/'.join(parts[:depth])
        is_last = depth == len(parts)
        if not _match_one(candidate, pat, anchored):
            continue
        if directory_only and is_last and is_dir is False:
            continue
        return True
    return False

def ignored_by_rules(rel_path, rules, is_dir=None):
    ignored = False
    for base, raw in rules:
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        negated = line.startswith('!')
        pat = line[1:] if negated else line
        if match_ignore_pattern(rel_path, pat, base=base, is_dir=is_dir):
            ignored = not negated
    return ignored

def load_ignore_rules(workspace='/workspace'):
    rules = []
    root = Path(workspace)
    if not root.is_dir():
        return rules
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        kept = []
        for name in dirnames:
            item = current / name
            if item.is_symlink() or name in DEFAULT_SKIP_DIRS:
                continue
            kept.append(name)
        dirnames[:] = kept
        try:
            rel_dir = current.relative_to(root).as_posix()
        except ValueError:
            continue
        base = '' if rel_dir == '.' else rel_dir
        for name in ('.gitignore', '.ignore'):
            candidate = current / name
            try:
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                text = candidate.read_text(encoding='utf-8', errors='replace')
            except OSError:
                continue
            for raw in text.splitlines():
                line = raw.strip()
                if line and not line.startswith('#'):
                    rules.append((base, line))
    return rules

def is_secret_path(rel_path):
    parts = posix_parts(rel_path)
    if not parts:
        return False
    folded = tuple(part.casefold() for part in parts)
    name = folded[-1]
    if name == '.env' or name.startswith('.env.'):
        return True
    if '.git' in folded or '.ssh' in folded:
        return True
    if name == 'id_rsa':
        return True
    return any(part == '.aws' and folded[index + 1] == 'credentials' for index, part in enumerate(folded[:-1]))

def should_skip(rel_path, rules, is_dir=None):
    if not rel_path:
        return False
    if is_secret_path(rel_path):
        return True
    if any(part in DEFAULT_SKIP_DIRS for part in posix_parts(rel_path)):
        return True
    return ignored_by_rules(rel_path, rules, is_dir=is_dir)
"""

IGNORE_RUNTIME = (
    "import os, re\n"
    "from pathlib import Path\n"
    f"DEFAULT_SKIP_DIRS = {set(DEFAULT_SKIP_DIRS)!r}\n"
    + _IGNORE_RUNTIME_BODY
)

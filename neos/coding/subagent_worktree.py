"""Isolated git worktree + parent-only merge helpers for write workers."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

_RUN_ID_RE = re.compile(r"[A-Za-z0-9._-]+")
_MAX_RUN_ID = 80
_BASE_SHA_KEY = "neos.baseSha"
_GIT_SAFE = (
    "--no-pager",
    "-c",
    "core.pager=cat",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "commit.gpgsign=false",
)
_GIT_ENV_BLOCK = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_PREFIX",
    "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_SYSTEM",
    "GIT_CONFIG_COUNT",
    "GIT_CONFIG_PARAMETERS",
    "GIT_EXEC_PATH",
    "GIT_TEMPLATE_DIR",
    "GIT_SEQUENCE_EDITOR",
    "GIT_EDITOR",
    "EDITOR",
    "VISUAL",
)


class WorktreeError(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class MergeStatus(StrEnum):
    FAST_FORWARD = "fast_forward"
    CONFLICT = "conflict"
    EMPTY = "empty"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class WorktreeLease:
    run_id: str
    repo: Path
    path: Path
    branch: str
    base_sha: str


@dataclass(frozen=True, slots=True)
class MergeResult:
    status: MergeStatus
    lease: WorktreeLease
    applied: bool
    conflict_paths: tuple[str, ...] = ()
    message: str = ""


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in _GIT_ENV_BLOCK:
        env.pop(key, None)
    for index in range(1, 100):
        env.pop(f"GIT_CONFIG_KEY_{index}", None)
        env.pop(f"GIT_CONFIG_VALUE_{index}", None)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _run_git(
    cwd: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(cwd), *_GIT_SAFE, *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env=_git_env(),
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or "git_failed"
        raise WorktreeError(detail)
    return result


def _safe_run_id(run_id: str) -> str:
    if (
        not run_id
        or len(run_id) > _MAX_RUN_ID
        or ".." in run_id
        or "/" in run_id
        or not run_id.strip(".")
        or _RUN_ID_RE.fullmatch(run_id) is None
    ):
        raise WorktreeError("invalid_run_id")
    return run_id


def _require_git_worktree(repo: Path) -> None:
    if not repo.is_dir():
        raise WorktreeError("worktree_parent_not_git")
    result = _run_git(repo, "rev-parse", "--is-inside-work-tree", check=False)
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise WorktreeError("worktree_parent_not_git")


def _ensure_neos_excluded(repo: Path) -> None:
    raw = _run_git(repo, "rev-parse", "--git-path", "info/exclude")
    exclude = Path(raw.stdout.strip())
    if not exclude.is_absolute():
        exclude = repo / exclude
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    markers = {line.strip() for line in existing.splitlines()}
    if ".neos/" in markers or ".neos" in markers:
        return
    exclude.parent.mkdir(parents=True, exist_ok=True)
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    with exclude.open("a", encoding="utf-8") as handle:
        handle.write(f"{prefix}.neos/\n")


def _worktree_git_dir(path: Path) -> Path | None:
    gitfile = path / ".git"
    if gitfile.is_dir():
        return gitfile
    if not gitfile.is_file():
        return None
    text = gitfile.read_text(encoding="utf-8")
    for line in text.splitlines():
        if not line.lower().startswith("gitdir:"):
            continue
        raw = line.split(":", 1)[1].strip()
        if not raw:
            return None
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = (path / candidate).resolve()
        return candidate
    return None


def _record_base_sha(path: Path, sha: str) -> None:
    git_dir = _worktree_git_dir(path)
    if git_dir is None:
        return
    git_dir.mkdir(parents=True, exist_ok=True)
    (git_dir / _BASE_SHA_KEY).write_text(f"{sha}\n", encoding="utf-8")


def _read_base_sha(path: Path, fallback: str) -> str:
    git_dir = _worktree_git_dir(path)
    if git_dir is None:
        return fallback
    stamp = git_dir / _BASE_SHA_KEY
    if not stamp.is_file():
        return fallback
    recorded = stamp.read_text(encoding="utf-8").strip()
    return recorded or fallback


def _porcelain_paths(repo: Path) -> set[str]:
    result = _run_git(repo, "status", "--porcelain", "-z", "-uall", check=False)
    if result.returncode != 0 or not result.stdout:
        return set()
    paths: set[str] = set()
    tokens = result.stdout.split("\0")
    index = 0
    while index < len(tokens):
        entry = tokens[index]
        index += 1
        if len(entry) < 3:
            continue
        path = entry[3:] if entry[2:3] == " " else entry[2:]
        if path:
            paths.add(path)
        if entry[:1] in {"R", "C"} or entry[1:2] in {"R", "C"}:
            if index < len(tokens) and tokens[index]:
                paths.add(tokens[index])
                index += 1
    return paths


def _name_only(repo: Path, left: str, right: str) -> set[str]:
    result = _run_git(
        repo,
        "diff",
        "--name-only",
        "-z",
        "--no-renames",
        "--no-ext-diff",
        left,
        right,
        check=False,
    )
    if result.returncode != 0:
        return set()
    return {line for line in result.stdout.split("\0") if line}


def create_worktree(repo: Path, run_id: str, *, base: str = "HEAD") -> WorktreeLease:
    safe = _safe_run_id(run_id)
    repo = repo.resolve()
    _require_git_worktree(repo)
    _ensure_neos_excluded(repo)
    base_sha = _run_git(repo, "rev-parse", "--verify", f"{base}^{{commit}}").stdout.strip()
    branch = f"neos/sa_{safe}"
    path = (repo / ".neos" / "worktrees" / safe).resolve()
    root = (repo / ".neos" / "worktrees").resolve()
    if path.parent != root:
        raise WorktreeError("invalid_run_id")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_dir() and (repo / ".git").exists():
        listed = _run_git(repo, "worktree", "list", "--porcelain", check=False)
        if str(path) in (listed.stdout or ""):
            existing = _run_git(path, "rev-parse", "--verify", "HEAD", check=False)
            if existing.returncode == 0:
                return WorktreeLease(
                    run_id=safe,
                    repo=repo,
                    path=path,
                    branch=branch,
                    base_sha=_read_base_sha(path, base_sha),
                )
    added = _run_git(
        repo, "worktree", "add", "-b", branch, str(path), base_sha, check=False
    )
    if added.returncode != 0:
        retry = _run_git(repo, "worktree", "add", str(path), branch, check=False)
        if retry.returncode != 0:
            detail = (
                (added.stderr or added.stdout or retry.stderr or retry.stdout).strip()
                or "worktree_add_failed"
            )
            raise WorktreeError(detail)
    recorded = _read_base_sha(path, "")
    if recorded:
        base_sha = recorded
    else:
        _record_base_sha(path, base_sha)
    return WorktreeLease(
        run_id=safe,
        repo=repo,
        path=path,
        branch=branch,
        base_sha=base_sha,
    )


def capture_diff(lease: WorktreeLease) -> str:
    _run_git(lease.path, "add", "-N", "--", ".", check=False)
    diff = _run_git(
        lease.path, "diff", "--binary", "--no-ext-diff", lease.base_sha, check=False
    )
    body = diff.stdout if diff.returncode == 0 else ""
    untracked = _run_git(
        lease.path,
        "ls-files",
        "--others",
        "--exclude-standard",
        check=False,
    )
    for rel in untracked.stdout.splitlines():
        if not rel or f"b/{rel}" in body:
            continue
        piece = _run_git(
            lease.path,
            "diff",
            "--binary",
            "--no-ext-diff",
            "--no-index",
            "--",
            "/dev/null",
            rel,
            check=False,
        )
        body += piece.stdout
    return body


def commit_worktree(lease: WorktreeLease, message: str = "neos implement child") -> bool:
    _run_git(lease.path, "add", "-A", check=False)
    porcelain = _run_git(lease.path, "status", "--porcelain", check=False)
    if not (porcelain.stdout or "").strip():
        return False
    _run_git(
        lease.path,
        "-c",
        "user.email=neos@local",
        "-c",
        "user.name=neos",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        message or "neos implement child",
    )
    return True


def merge_worktree(lease: WorktreeLease) -> MergeResult:
    def _failed(message: str) -> MergeResult:
        return MergeResult(
            status=MergeStatus.FAILED,
            lease=lease,
            applied=False,
            message=message,
        )

    try:
        _require_git_worktree(lease.repo)
    except WorktreeError as error:
        return _failed(str(error))

    counted = _run_git(
        lease.repo,
        "rev-list",
        "--count",
        f"{lease.base_sha}..{lease.branch}",
        check=False,
    )
    if counted.returncode != 0:
        return _failed((counted.stderr or counted.stdout).strip())
    try:
        ahead = int((counted.stdout or "0").strip() or "0")
    except ValueError:
        return _failed("rev_list_invalid")
    if ahead <= 0:
        return MergeResult(status=MergeStatus.EMPTY, lease=lease, applied=False)

    ancestor = _run_git(
        lease.repo,
        "merge-base",
        "--is-ancestor",
        "HEAD",
        lease.branch,
        check=False,
    )
    child_paths = _name_only(lease.repo, lease.base_sha, lease.branch)
    dirty = _porcelain_paths(lease.repo)
    overlap = sorted(child_paths & dirty)

    if ancestor.returncode not in (0, 1):
        return _failed((ancestor.stderr or ancestor.stdout).strip())

    conflict: set[str] = set(overlap)
    if ancestor.returncode == 1:
        merge_base = _run_git(lease.repo, "merge-base", "HEAD", lease.branch, check=False)
        if merge_base.returncode == 0:
            base = merge_base.stdout.strip()
            parent_changed = _name_only(lease.repo, base, "HEAD")
            child_changed = _name_only(lease.repo, base, lease.branch)
            conflict.update(parent_changed & child_changed)
        return MergeResult(
            status=MergeStatus.CONFLICT,
            lease=lease,
            applied=False,
            conflict_paths=tuple(sorted(conflict)),
            message="not_fast_forward",
        )

    if overlap:
        return MergeResult(
            status=MergeStatus.CONFLICT,
            lease=lease,
            applied=False,
            conflict_paths=tuple(overlap),
            message="parent_dirty_overlap",
        )

    merged = _run_git(lease.repo, "merge", "--ff-only", "--no-edit", lease.branch, check=False)
    if merged.returncode != 0:
        return _failed((merged.stderr or merged.stdout).strip())
    return MergeResult(status=MergeStatus.FAST_FORWARD, lease=lease, applied=True)


def discard_worktree(lease: WorktreeLease) -> None:
    if lease.repo.is_dir():
        _run_git(lease.repo, "worktree", "remove", "--force", str(lease.path), check=False)
        _run_git(lease.repo, "worktree", "prune", check=False)
        _run_git(lease.repo, "branch", "-D", lease.branch, check=False)

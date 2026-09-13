from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from neos.coding.subagent_worktree import (
    MergeStatus,
    WorktreeError,
    capture_diff,
    create_worktree,
    discard_worktree,
    merge_worktree,
)

pytestmark = pytest.mark.no_db


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "init")
    return repo


def _commit_in(path: Path, message: str) -> None:
    _git(path, "add", "-A")
    _git(path, "commit", "-m", message)


def test_create_worktree_isolates_child_writes(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    lease = create_worktree(repo, "run1")

    assert lease.run_id == "run1"
    assert lease.repo == repo
    assert lease.path == repo / ".neos" / "worktrees" / "run1"
    assert lease.branch == "neos/sa_run1"
    assert lease.path.is_dir()
    assert (lease.path / "README.md").read_text(encoding="utf-8") == "hello\n"

    (lease.path / "child.txt").write_text("from-child\n", encoding="utf-8")
    (lease.path / "README.md").write_text("child-edit\n", encoding="utf-8")

    assert (repo / "README.md").read_text(encoding="utf-8") == "hello\n"
    assert not (repo / "child.txt").exists()
    status = _git(repo, "status", "--porcelain").stdout
    assert "child.txt" not in status
    assert "README.md" not in status


def test_create_worktree_is_idempotent(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    first = create_worktree(repo, "run-idem")
    (first.path / "keep.txt").write_text("stay\n", encoding="utf-8")
    second = create_worktree(repo, "run-idem")
    assert second.path == first.path
    assert second.branch == first.branch
    assert second.base_sha == first.base_sha
    assert (second.path / "keep.txt").read_text(encoding="utf-8") == "stay\n"


def test_create_worktree_requires_git_repo(tmp_path: Path) -> None:
    with pytest.raises(WorktreeError, match="worktree_parent_not_git"):
        create_worktree(tmp_path / "not-a-repo", "run1")


@pytest.mark.parametrize("run_id", ["foo/bar", "..", "a/../b", "evil/../../x"])
def test_create_worktree_rejects_path_traversal(tmp_path: Path, run_id: str) -> None:
    repo = _init_repo(tmp_path)
    with pytest.raises(WorktreeError):
        create_worktree(repo, run_id)


def test_capture_diff_includes_committed_and_untracked(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    lease = create_worktree(repo, "run-diff")
    assert capture_diff(lease) == ""

    (lease.path / "new.txt").write_text("untracked\n", encoding="utf-8")
    untracked = capture_diff(lease)
    assert untracked
    assert "new.txt" in untracked

    _commit_in(lease.path, "add new")
    (lease.path / "README.md").write_text("dirty\n", encoding="utf-8")
    combined = capture_diff(lease)
    assert "new.txt" in combined
    assert "README.md" in combined


def test_merge_worktree_fast_forward_applies_child_commit(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    lease = create_worktree(repo, "run-ff")
    (lease.path / "feature.py").write_text("print(1)\n", encoding="utf-8")
    _commit_in(lease.path, "add feature")

    result = merge_worktree(lease)
    assert result.status is MergeStatus.FAST_FORWARD
    assert result.applied is True
    assert result.conflict_paths == ()
    assert (repo / "feature.py").read_text(encoding="utf-8") == "print(1)\n"
    parent_head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    child_head = _git(lease.path, "rev-parse", "HEAD").stdout.strip()
    assert parent_head == child_head


def test_merge_worktree_conflict_leaves_parent_unchanged(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    lease = create_worktree(repo, "run-conflict")
    (lease.path / "README.md").write_text("child\n", encoding="utf-8")
    _commit_in(lease.path, "child edit")
    (repo / "README.md").write_text("parent\n", encoding="utf-8")

    result = merge_worktree(lease)
    assert result.status is MergeStatus.CONFLICT
    assert result.applied is False
    assert "README.md" in result.conflict_paths
    assert (repo / "README.md").read_text(encoding="utf-8") == "parent\n"
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == lease.base_sha


def test_commit_worktree_then_merge_applies_dirty_writes(tmp_path: Path) -> None:
    from neos.coding.subagent_worktree import commit_worktree

    repo = _init_repo(tmp_path)
    lease = create_worktree(repo, "run-commit")
    (lease.path / "done.py").write_text("ok\n", encoding="utf-8")
    assert commit_worktree(lease, message="child writes") is True
    assert commit_worktree(lease, message="noop") is False
    result = merge_worktree(lease)
    assert result.status is MergeStatus.FAST_FORWARD
    assert (repo / "done.py").read_text(encoding="utf-8") == "ok\n"


def test_merge_worktree_empty_without_child_commits(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    lease = create_worktree(repo, "run-empty")
    (lease.path / "scratch.txt").write_text("dirty-only\n", encoding="utf-8")

    result = merge_worktree(lease)
    assert result.status is MergeStatus.EMPTY
    assert result.applied is False
    assert not (repo / "scratch.txt").exists()


def test_discard_worktree_is_idempotent(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    lease = create_worktree(repo, "run-discard")
    assert lease.path.is_dir()

    discard_worktree(lease)
    assert not lease.path.exists()
    branches = _git(repo, "branch", "--list", lease.branch).stdout
    assert lease.branch not in branches

    discard_worktree(lease)


def test_module_does_not_import_durable_or_gateway() -> None:
    text = Path("neos/coding/subagent_worktree.py").read_text(encoding="utf-8")
    assert "neos.coding.loop.durable" not in text
    assert "ChannelGateway" not in text
    assert "sandbox.bindings" not in text
    assert "neos.subagent" not in text


def test_commit_worktree_does_not_run_repo_hooks(tmp_path: Path) -> None:
    from neos.coding.subagent_worktree import commit_worktree

    repo = _init_repo(tmp_path)
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    sentinel = tmp_path / "hook-ran"
    hook = hooks / "pre-commit"
    hook.write_text(f"#!/bin/sh\necho ran > '{sentinel}'\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    lease = create_worktree(repo, "run-hooks")
    (lease.path / "x.py").write_text("1\n", encoding="utf-8")
    assert commit_worktree(lease) is True
    assert not sentinel.exists()
    assert (lease.path / "x.py").exists()


def test_create_worktree_keeps_original_base_after_parent_commit(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    first = create_worktree(repo, "run-base")
    (repo / "README.md").write_text("parent-moved\n", encoding="utf-8")
    _commit_in(repo, "parent moved")
    second = create_worktree(repo, "run-base")
    assert second.path == first.path
    assert second.base_sha == first.base_sha
    parent_head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert second.base_sha != parent_head


def test_merge_detects_dirty_overlap_on_arrow_filename(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    arrow = repo / "foo -> bar.txt"
    arrow.write_text("orig\n", encoding="utf-8")
    _git(repo, "add", "foo -> bar.txt")
    _git(repo, "commit", "-m", "arrow")
    lease = create_worktree(repo, "run-arrow")
    (lease.path / "foo -> bar.txt").write_text("child\n", encoding="utf-8")
    _commit_in(lease.path, "child arrow")
    (repo / "foo -> bar.txt").write_text("parent-dirty\n", encoding="utf-8")
    result = merge_worktree(lease)
    assert result.status is MergeStatus.CONFLICT
    assert "foo -> bar.txt" in result.conflict_paths
    assert (repo / "foo -> bar.txt").read_text(encoding="utf-8") == "parent-dirty\n"


def test_session_on_workspace_does_not_mutate_parent() -> None:
    from types import SimpleNamespace

    from neos.coding.loop.durable import _session_on_workspace
    from neos.coding.subagent_worktree import WorktreeError

    session = SimpleNamespace(workspace="/parent")
    with pytest.raises(WorktreeError, match="worktree_session_not_cloneable"):
        _session_on_workspace(session, "/child")
    assert session.workspace == "/parent"

"""Git worktrees for `implement`-mode children, and the sessions bound to them.

`neos.coding.subagent_worktree` and the sandbox memory session are imported
lazily: most loops never spawn a worktree child.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from neos.coding.loop._durable.state import ActiveChildRef


def _session_workspace(session) -> Path | None:
    raw = getattr(session, "workspace", None)
    if raw:
        return Path(raw)
    record = getattr(session, "_record", None)
    workspace = getattr(record, "workspace", None)
    return Path(workspace) if workspace else None


def _session_on_workspace(session, workspace: str):
    from neos.coding.sandbox.memory import MemorySandboxSession

    root = Path(workspace)
    if isinstance(session, MemorySandboxSession):
        return MemorySandboxSession(
            session._provider, replace(session._record, workspace=root)
        )
    clone = getattr(session, "clone_with_workspace", None)
    if callable(clone):
        return clone(root)
    from neos.coding.subagent_worktree import WorktreeError

    raise WorktreeError("worktree_session_not_cloneable")


def _lease_from_ref(ref: ActiveChildRef | None):
    if ref is None or not ref.worktree_path or not ref.worktree_repo:
        return None
    from neos.coding.subagent_worktree import WorktreeLease

    return WorktreeLease(
        run_id=ref.tool_call_id,
        repo=Path(ref.worktree_repo),
        path=Path(ref.worktree_path),
        branch=ref.worktree_branch,
        base_sha=ref.worktree_base_sha,
    )


def _lease_fields(lease) -> dict[str, str]:
    """The four `worktree_*` fields a ref or park record keeps for `lease`."""
    if lease is None:
        return {
            "worktree_repo": "",
            "worktree_path": "",
            "worktree_branch": "",
            "worktree_base_sha": "",
        }
    return {
        "worktree_repo": str(lease.repo),
        "worktree_path": str(lease.path),
        "worktree_branch": lease.branch,
        "worktree_base_sha": lease.base_sha,
    }


def _ref_worktree_fields(ref: ActiveChildRef) -> dict[str, str]:
    return {
        "worktree_repo": ref.worktree_repo,
        "worktree_path": ref.worktree_path,
        "worktree_branch": ref.worktree_branch,
        "worktree_base_sha": ref.worktree_base_sha,
    }


def _open_implement_worktree(session, tool_call_id: str):
    from neos.coding.subagent_worktree import WorktreeError, create_worktree

    workspace = _session_workspace(session)
    if workspace is None:
        raise WorktreeError("worktree_parent_not_git")
    return create_worktree(workspace, tool_call_id)


def _discard_lease(lease) -> None:
    if lease is None:
        return
    from neos.coding.subagent_worktree import discard_worktree

    discard_worktree(lease)

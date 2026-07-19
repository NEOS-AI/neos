from __future__ import annotations

from pathlib import Path, PurePosixPath

from neos.coding.sandbox.base import SandboxPolicyViolation


_PROTECTED_GIT_FILES = {
    PurePosixPath(".git/config"),
    PurePosixPath(".git/config.worktree"),
    PurePosixPath(".git/credentials"),
}


def normalize_workspace_path(path: str) -> PurePosixPath:
    """Return a normalized POSIX-relative path confined to a workspace."""
    if "\0" in path:
        raise SandboxPolicyViolation("workspace_path_contains_nul")
    if not path:
        path = "."
    if path.startswith("/"):
        raise SandboxPolicyViolation("workspace_path_is_absolute")

    candidate = PurePosixPath(path)
    if candidate.is_absolute() or any(
        part == ".." for part in candidate.parts
    ):
        raise SandboxPolicyViolation("workspace_path_escape")
    return candidate


def ensure_mutable_workspace_path(path: str) -> PurePosixPath:
    """Reject mutation of Git configuration, hooks, and credentials."""
    candidate = normalize_workspace_path(path)
    if candidate in _PROTECTED_GIT_FILES or candidate.is_relative_to(
        PurePosixPath(".git/hooks")
    ):
        raise SandboxPolicyViolation("protected_git_path")
    return candidate


def resolve_workspace_path(
    root: Path,
    path: str,
    *,
    allow_missing_leaf: bool = False,
) -> Path:
    """Resolve existing components and reject symlinks outside ``root``."""
    relative = normalize_workspace_path(path)
    try:
        root_real = root.resolve(strict=True)
        candidate = root_real.joinpath(*relative.parts)
        if allow_missing_leaf and not candidate.exists():
            resolved_parent = candidate.parent.resolve(strict=True)
            resolved = resolved_parent / candidate.name
        else:
            resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as error:
        raise SandboxPolicyViolation("workspace_path_not_resolvable") from error

    if not resolved.is_relative_to(root_real):
        raise SandboxPolicyViolation("workspace_symlink_escape")
    return resolved

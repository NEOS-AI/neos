from __future__ import annotations

import unicodedata
from pathlib import Path, PurePosixPath

from neos.coding.sandbox.base import SandboxPolicyViolation


_PROTECTED_GIT_FILES = {
    PurePosixPath(".git/config"),
    PurePosixPath(".git/config.worktree"),
    PurePosixPath(".git/credentials"),
}
_BARE_GIT_ROOT_PARTS = frozenset({"HEAD", "objects", "refs", "hooks"})


def compare_path_key(value: str) -> str:
    """NFKC + casefold for comparisons only. Does not mutate the input."""
    return unicodedata.normalize("NFKC", value).casefold()


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
    parts = tuple(part for part in candidate.parts if part != ".")
    if parts and parts[0] in _BARE_GIT_ROOT_PARTS:
        raise SandboxPolicyViolation("workspace_bare_git_path")
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


def resolve_readable_workspace_path(root: Path, path: str) -> Path:
    """Resolve a read target: follow internal parent dirs, refuse leaf links."""
    from neos.coding.domain.approvals import is_denied_secret_path

    relative = normalize_workspace_path(path)
    requested = relative.as_posix()
    if requested != "." and is_denied_secret_path(requested):
        raise SandboxPolicyViolation("workspace_secret_path")

    try:
        root_real = root.resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as error:
        raise SandboxPolicyViolation("workspace_path_not_resolvable") from error

    parts = tuple(part for part in relative.parts if part != ".")
    current = root_real
    for index, part in enumerate(parts):
        current = current / part
        is_leaf = index == len(parts) - 1
        try:
            if current.is_symlink():
                if is_leaf:
                    raise SandboxPolicyViolation("workspace_symlink_leaf")
                resolved = current.resolve(strict=True)
                if not resolved.is_relative_to(root_real):
                    raise SandboxPolicyViolation("workspace_symlink_escape")
                current = resolved
            elif is_leaf:
                current = current.resolve(strict=True)
            elif not current.exists():
                raise SandboxPolicyViolation("workspace_path_not_resolvable")
        except SandboxPolicyViolation:
            raise
        except (FileNotFoundError, RuntimeError, OSError) as error:
            raise SandboxPolicyViolation("workspace_path_not_resolvable") from error

    if not current.is_relative_to(root_real):
        raise SandboxPolicyViolation("workspace_symlink_escape")
    try:
        resolved_rel = current.relative_to(root_real).as_posix()
    except ValueError as error:
        raise SandboxPolicyViolation("workspace_symlink_escape") from error
    if resolved_rel != "." and is_denied_secret_path(resolved_rel):
        raise SandboxPolicyViolation("workspace_secret_path")
    return current


def realpath_for_compare(root: str | Path, path: str) -> str:
    """Resolve the leaf for comparison only. Never mutates the input path."""
    try:
        relative = normalize_workspace_path(path)
        root_real = Path(root).resolve(strict=True)
        candidate = root_real.joinpath(*relative.parts)
        if not candidate.exists() and not candidate.is_symlink():
            return path
        resolved = candidate.resolve()
        try:
            return resolved.relative_to(root_real).as_posix()
        except ValueError:
            return resolved.name
    except (OSError, RuntimeError, SandboxPolicyViolation):
        return path


def resolve_mutable_workspace_path(root: Path, path: str) -> Path:
    """Resolve a mutation target without following parent or leaf symlinks."""
    relative = normalize_workspace_path(path)
    try:
        root_real = root.resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as error:
        raise SandboxPolicyViolation("workspace_path_not_resolvable") from error

    parts = tuple(part for part in relative.parts if part != ".")
    current = root_real
    for index, part in enumerate(parts):
        current = current / part
        is_leaf = index == len(parts) - 1
        if current.is_symlink():
            code = (
                "workspace_symlink_leaf"
                if is_leaf
                else "workspace_symlink_parent"
            )
            raise SandboxPolicyViolation(code)
        if not is_leaf and not current.exists():
            raise FileNotFoundError(str(current))
    return current

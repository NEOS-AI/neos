from pathlib import Path, PurePosixPath

import pytest

from neos.coding.sandbox.base import SandboxPolicyViolation
from neos.coding.sandbox.paths import (
    ensure_mutable_workspace_path,
    normalize_workspace_path,
    resolve_workspace_path,
)


@pytest.mark.parametrize(
    "value",
    [
        "/etc/passwd",
        "../secret",
        "a/../../secret",
        "bad\0name",
    ],
)
def test_normalize_rejects_paths_outside_workspace(value: str) -> None:
    with pytest.raises(SandboxPolicyViolation):
        normalize_workspace_path(value)


def test_normalize_uses_posix_workspace_semantics() -> None:
    assert normalize_workspace_path("src/./app.py") == PurePosixPath(
        "src/app.py"
    )


def test_resolve_rejects_existing_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-secret"
    outside.write_text("secret")
    (tmp_path / "escape").symlink_to(outside)

    with pytest.raises(
        SandboxPolicyViolation,
        match="workspace_symlink_escape",
    ):
        resolve_workspace_path(tmp_path, "escape")


def test_missing_write_leaf_is_allowed_below_real_parent(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()

    resolved = resolve_workspace_path(
        tmp_path,
        "src/new.py",
        allow_missing_leaf=True,
    )

    assert resolved == tmp_path / "src/new.py"


@pytest.mark.parametrize(
    "path",
    [
        ".git/config",
        ".git/hooks/pre-commit",
        ".git/credentials",
    ],
)
def test_mutation_rejects_git_execution_and_credential_paths(
    path: str,
) -> None:
    with pytest.raises(SandboxPolicyViolation, match="protected_git_path"):
        ensure_mutable_workspace_path(path)


def test_regular_workspace_path_is_mutable() -> None:
    assert ensure_mutable_workspace_path("src/app.py") == PurePosixPath(
        "src/app.py"
    )

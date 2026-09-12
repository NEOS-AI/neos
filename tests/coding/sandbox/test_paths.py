from pathlib import Path, PurePosixPath

import pytest

from neos.coding.sandbox.base import SandboxPolicyViolation
from neos.coding.sandbox.paths import (
    ensure_mutable_workspace_path,
    normalize_workspace_path,
    resolve_mutable_workspace_path,
    resolve_readable_workspace_path,
    resolve_workspace_path,
)

pytestmark = pytest.mark.no_db


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


@pytest.mark.parametrize(
    "path",
    [
        "HEAD",
        "objects",
        "objects/pack/foo",
        "refs",
        "refs/heads/main",
        "hooks",
        "hooks/pre-commit",
    ],
)
def test_mutation_rejects_workspace_root_bare_git_paths(path: str) -> None:
    with pytest.raises(
        SandboxPolicyViolation,
        match="workspace_bare_git_path|protected_git_path",
    ):
        ensure_mutable_workspace_path(path)


def test_nested_head_file_is_still_mutable() -> None:
    assert ensure_mutable_workspace_path("src/HEAD") == PurePosixPath("src/HEAD")


def test_resolve_mutable_rejects_symlink_leaf(tmp_path: Path) -> None:
    (tmp_path / "link.txt").symlink_to(tmp_path / "missing.txt")

    with pytest.raises(
        SandboxPolicyViolation, match="workspace_symlink_leaf"
    ):
        resolve_mutable_workspace_path(tmp_path, "link.txt")


def test_resolve_mutable_rejects_symlink_parent(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-dir"
    outside.mkdir()
    (tmp_path / "ext").symlink_to(outside)

    with pytest.raises(
        SandboxPolicyViolation, match="workspace_symlink_parent"
    ):
        resolve_mutable_workspace_path(tmp_path, "ext/x.txt")


def test_resolve_mutable_rejects_internal_symlink_parent(
    tmp_path: Path,
) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "ext").symlink_to(tmp_path / "real")

    with pytest.raises(
        SandboxPolicyViolation, match="workspace_symlink_parent"
    ):
        resolve_mutable_workspace_path(tmp_path, "ext/x.txt")


def test_resolve_workspace_path_still_follows_internal_parent_symlink(
    tmp_path: Path,
) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "x.txt").write_text("ok")
    (tmp_path / "ext").symlink_to(tmp_path / "real")

    resolved = resolve_workspace_path(tmp_path, "ext/x.txt")

    assert resolved == (tmp_path / "real" / "x.txt").resolve()


def test_resolve_mutable_allows_missing_leaf_under_real_parent(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()

    resolved = resolve_mutable_workspace_path(tmp_path, "src/new.py")

    assert resolved == tmp_path / "src/new.py"


def test_resolve_mutable_missing_parent_is_file_not_found(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError):
        resolve_mutable_workspace_path(tmp_path, "nested/a.txt")


def test_resolve_readable_rejects_leaf_symlink(tmp_path: Path) -> None:
    (tmp_path / "inside.txt").write_text("ok")
    (tmp_path / "link.txt").symlink_to(tmp_path / "inside.txt")

    with pytest.raises(
        SandboxPolicyViolation, match="workspace_symlink_leaf"
    ):
        resolve_readable_workspace_path(tmp_path, "link.txt")


def test_resolve_readable_follows_internal_parent_to_regular_file(
    tmp_path: Path,
) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "x.txt").write_text("ok")
    (tmp_path / "ext").symlink_to(tmp_path / "real")

    resolved = resolve_readable_workspace_path(tmp_path, "ext/x.txt")

    assert resolved == (tmp_path / "real" / "x.txt").resolve()


@pytest.mark.parametrize(
    "path",
    [".env", ".env.local", ".ssh/id_rsa", "id_rsa", ".git/config"],
)
def test_resolve_readable_rejects_secret_path(tmp_path: Path, path: str) -> None:
    target = tmp_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("secret")

    with pytest.raises(SandboxPolicyViolation, match="workspace_secret_path"):
        resolve_readable_workspace_path(tmp_path, path)


def test_resolve_readable_rejects_parent_symlink_to_secret(
    tmp_path: Path,
) -> None:
    ssh = tmp_path / ".ssh"
    ssh.mkdir()
    (ssh / "notes.md").write_text("key material")
    (tmp_path / "ext").symlink_to(ssh)

    with pytest.raises(SandboxPolicyViolation, match="workspace_secret_path"):
        resolve_readable_workspace_path(tmp_path, "ext/notes.md")

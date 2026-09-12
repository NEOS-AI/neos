import io
import tarfile
from pathlib import Path

import pytest

from neos.coding.sandbox.archive import extract_workspace_archive
from neos.coding.sandbox.base import SandboxPolicyViolation

pytestmark = pytest.mark.no_db


def _make_tar(
    destination: Path,
    *,
    name: str,
    payload: bytes,
) -> Path:
    archive = destination / "unsafe.tar"
    info = tarfile.TarInfo(name=name)
    info.size = len(payload)
    with tarfile.open(archive, "w") as bundle:
        bundle.addfile(info, io.BytesIO(payload))
    return archive


def test_extract_rejects_parent_traversal(tmp_path: Path) -> None:
    archive = _make_tar(
        tmp_path,
        name="../../escape",
        payload=b"owned",
    )

    with pytest.raises(SandboxPolicyViolation, match="archive_path_escape"):
        extract_workspace_archive(
            archive,
            tmp_path / "target",
            max_expanded_bytes=1024,
        )


def test_extract_rejects_expanded_size_overflow(tmp_path: Path) -> None:
    archive = _make_tar(tmp_path, name="large", payload=b"12345")

    with pytest.raises(
        SandboxPolicyViolation,
        match="archive_expanded_size_exceeded",
    ):
        extract_workspace_archive(
            archive,
            tmp_path / "target",
            max_expanded_bytes=4,
        )


def test_create_archive_skips_secrets_symlinks_and_does_not_follow(
    tmp_path: Path,
) -> None:
    from neos.coding.sandbox.archive import create_workspace_archive

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "src").mkdir()
    (workspace / "src" / "app.py").write_text("print(1)\n", encoding="utf-8")
    (workspace / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (workspace / ".env.local").write_text("SECRET=2\n", encoding="utf-8")
    ssh = workspace / ".ssh"
    ssh.mkdir()
    (ssh / "id_rsa").write_text("private\n", encoding="utf-8")
    (workspace / "id_rsa").write_text("rootkey\n", encoding="utf-8")
    (workspace / "inside.txt").write_text("inside\n", encoding="utf-8")
    (workspace / "leaf-link").symlink_to(workspace / "inside.txt")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("OUTSIDE\n", encoding="utf-8")
    (workspace / "ext").symlink_to(outside)
    destination = tmp_path / "snap.tar"

    checksum = create_workspace_archive(
        workspace, destination, max_archive_bytes=1024 * 1024
    )

    assert checksum
    with tarfile.open(destination, "r") as bundle:
        names = set(bundle.getnames())
        payloads = {
            member.name: bundle.extractfile(member).read()
            for member in bundle.getmembers()
            if member.isfile()
        }
    assert "src/app.py" in names
    assert "inside.txt" in names
    assert ".env" not in names
    assert ".env.local" not in names
    assert "id_rsa" not in names
    assert ".ssh/id_rsa" not in names
    assert "leaf-link" not in names
    assert "ext/secret.txt" not in names
    assert b"SECRET=1" not in b"".join(payloads.values())
    assert b"OUTSIDE" not in b"".join(payloads.values())
    assert payloads["src/app.py"] == b"print(1)\n"

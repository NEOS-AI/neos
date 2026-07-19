import io
import tarfile
from pathlib import Path

import pytest

from neos.coding.sandbox.archive import extract_workspace_archive
from neos.coding.sandbox.base import SandboxPolicyViolation


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

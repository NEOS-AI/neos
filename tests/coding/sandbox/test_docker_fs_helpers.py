from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from neos.coding.sandbox.docker import _CHMOD_HELPER, _MV_HELPER, _RM_HELPER

pytestmark = pytest.mark.no_db


def _run_helper(script: str, workspace: Path, *args: str) -> int:
    rewritten = script.replace("Path('/workspace')", f"Path({str(workspace)!r})")
    helper = workspace / "_helper.py"
    helper.write_text(rewritten)
    completed = subprocess.run(
        [sys.executable, str(helper), *args],
        check=False,
        capture_output=True,
    )
    return completed.returncode


def _symlink_parent_tree(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("leak")
    (tmp_path / "link").symlink_to(outside)


def test_rm_helper_refuses_symlink_parent(tmp_path: Path) -> None:
    _symlink_parent_tree(tmp_path)

    assert _run_helper(_RM_HELPER, tmp_path, "link/secret.txt", "0") == 3
    assert (tmp_path / "outside" / "secret.txt").read_text() == "leak"


def test_mv_helper_refuses_symlink_parent_src(tmp_path: Path) -> None:
    _symlink_parent_tree(tmp_path)
    (tmp_path / "dest.txt").write_text("ok")

    assert _run_helper(_MV_HELPER, tmp_path, "link/secret.txt", "dest.txt", "1") == 3
    assert (tmp_path / "outside" / "secret.txt").read_text() == "leak"


def test_chmod_helper_refuses_symlink_parent(tmp_path: Path) -> None:
    _symlink_parent_tree(tmp_path)

    assert _run_helper(_CHMOD_HELPER, tmp_path, "link/secret.txt", str(0o777)) == 3
    assert (tmp_path / "outside" / "secret.txt").stat().st_mode & 0o777 != 0o777

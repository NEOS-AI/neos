from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from neos.coding.sandbox.base import SandboxLimits
from neos.coding.sandbox.memory import MemorySandboxProvider, changed_files_since
from neos.config.schema import CodingModelConfig

pytestmark = pytest.mark.no_db


def test_file_watch_defaults_off() -> None:
    assert CodingModelConfig().file_watch is False


def test_changed_files_since_returns_paths_newer_than_mtime(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "old.py").write_text("old")
    stamp = time.time()
    time.sleep(0.05)
    (workspace / "src").mkdir()
    (workspace / "src" / "app.py").write_text("new")

    found = changed_files_since(workspace, stamp)

    assert "src/app.py" in found
    assert "old.py" not in found


def test_changed_files_since_does_not_start_a_watcher_thread(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "a.py").write_text("a")
    before = {thread.ident for thread in threading.enumerate()}

    changed_files_since(workspace, 0)

    after = {thread.ident for thread in threading.enumerate()}
    assert after == before


@pytest.mark.asyncio
async def test_session_changed_files_since_snapshot_id(tmp_path: Path) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    await session.write_file("keep.py", b"keep")
    snapshot = await provider.snapshot(sandbox.sandbox_id)
    time.sleep(0.05)
    await session.write_file("new.py", b"new")

    found = await session.changed_files_since(snapshot.snapshot_id)

    assert "new.py" in found
    assert "keep.py" not in found
    await provider.close()

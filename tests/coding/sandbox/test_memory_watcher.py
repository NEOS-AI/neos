import asyncio
import sys
from pathlib import Path

import pytest

from neos.coding.sandbox.base import CommandRequest, ReplayGap, SandboxLimits
from neos.coding.sandbox.memory import (
    MemorySandboxProvider,
    WorkspaceChange,
    WorkspaceChangeKind,
)


async def test_watcher_coalesces_changes_and_carries_revision(
    tmp_path: Path,
) -> None:
    # The hub opens a fixed window on the *first* change and flushes whatever
    # accumulated when it closes -- it is not a quiet-period debounce. So the
    # window has to outlast both writes, and a 10ms one only did when the
    # runner was idle: a scheduler delay between the writes put them in
    # separate batches and the batch arrived carrying revision 1.
    provider = MemorySandboxProvider(
        root=tmp_path,
        watcher_debounce_sec=1.0,
    )
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    watcher = await session.watch_files(after_cursor=0)

    await session.write_file("src/a.py", b"one")
    await session.write_file("src/a.py", b"two")
    # The batch only lands once the window closes, so this must outlast it.
    async with asyncio.timeout(5):
        batch = await anext(watcher)

    assert batch.value.workspace_revision == 2
    assert len(batch.value.changes) == 1
    assert batch.value.changes[0].path == "src/a.py"
    assert batch.value.changes[0].kind is WorkspaceChangeKind.CREATED
    await watcher.aclose()
    await provider.close()


async def test_watcher_reports_replay_gap_after_eviction(
    tmp_path: Path,
) -> None:
    provider = MemorySandboxProvider(
        root=tmp_path,
        watcher_debounce_sec=0.001,
        watcher_replay_events=2,
    )
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    watcher = await session.watch_files(after_cursor=0)

    for index in range(3):
        await session.write_file(f"file-{index}.txt", b"value")
        await asyncio.sleep(0.01)

    with pytest.raises(ReplayGap):
        await watcher.replay(after_cursor=0)
    await watcher.aclose()
    await provider.close()


async def test_watcher_detects_files_created_by_sandbox_command(
    tmp_path: Path,
) -> None:
    provider = MemorySandboxProvider(
        root=tmp_path,
        watcher_debounce_sec=0.001,
    )
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    watcher = await session.watch_files(after_cursor=0)

    await session.execute(
        CommandRequest(
            argv=(
                sys.executable,
                "-c",
                "from pathlib import Path; Path('command.txt').write_text('x')",
            )
        )
    )
    async with asyncio.timeout(1):
        batch = await anext(watcher)

    assert batch.value.changes == (
        WorkspaceChange(
            path="command.txt",
            kind=WorkspaceChangeKind.CREATED,
        ),
    )
    await watcher.aclose()
    await provider.close()

from pathlib import Path

import pytest

from neos.coding.sandbox.base import (
    SandboxLimits,
    SandboxPolicyViolation,
    SandboxState,
    SandboxStateConflict,
)
from neos.coding.sandbox.memory import MemorySandboxProvider


async def test_restore_creates_independent_running_sandbox(
    tmp_path: Path,
) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    source = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    source_session = await provider.open_session(source.sandbox_id)
    await source_session.write_file("answer.txt", b"42")

    snapshot = await provider.snapshot(source.sandbox_id)
    restored = await provider.restore(snapshot.snapshot_id, owner_id="u1")
    restored_session = await provider.open_session(restored.sandbox_id)
    await restored_session.write_file("answer.txt", b"43")

    assert restored.sandbox_id != source.sandbox_id
    assert restored.state is SandboxState.RUNNING
    assert await source_session.read_file("answer.txt") == b"42"
    assert await restored_session.read_file("answer.txt") == b"43"
    await provider.close()


async def test_suspend_blocks_session_until_resume(tmp_path: Path) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)

    suspended = await provider.suspend(sandbox.sandbox_id)
    with pytest.raises(SandboxStateConflict, match="sandbox_suspended"):
        await session.list_tree()
    resumed = await provider.resume(sandbox.sandbox_id)

    assert suspended.state is SandboxState.SUSPENDED
    assert resumed.state is SandboxState.RUNNING
    assert await session.list_tree() == ()
    await provider.close()


async def test_restore_rejects_corrupt_snapshot_and_cleans_partial_workspace(
    tmp_path: Path,
) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    source = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    snapshot = await provider.snapshot(source.sandbox_id)
    provider.snapshot_archive_path(snapshot.snapshot_id).write_bytes(
        b"corrupt"
    )
    before = set(tmp_path.glob("sb_*"))

    with pytest.raises(
        SandboxPolicyViolation,
        match="snapshot_checksum_mismatch",
    ):
        await provider.restore(snapshot.snapshot_id, owner_id="u1")

    assert set(tmp_path.glob("sb_*")) == before
    await provider.close()

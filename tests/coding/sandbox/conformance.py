from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import asyncio
import pytest

from neos.coding.sandbox.base import (
    CommandRequest,
    SandboxLimits,
    SandboxPolicyViolation,
    SandboxProvider,
    SandboxState,
    SandboxStateConflict,
)
from neos.coding.sandbox.memory import (
    MemorySandboxProvider,
    PtyOutput,
    WorkspaceChangeKind,
)


@asynccontextmanager
async def memory_provider(
    root: Path,
) -> AsyncIterator[SandboxProvider]:
    provider = MemorySandboxProvider(root=root)
    try:
        yield provider
    finally:
        await provider.close()


async def wait_for_output(terminal, *, contains: bytes):
    async with asyncio.timeout(5):
        async for event in terminal.subscribe(after_cursor=0):
            if isinstance(event.value, PtyOutput) and contains in event.value.data:
                return event
    raise AssertionError(f"PTY did not emit {contains!r}")


class SandboxProviderConformance:
    async def test_lifecycle_and_idempotent_destroy(self, provider) -> None:
        sandbox = await provider.create(
            owner_id="u1",
            limits=SandboxLimits.safe_defaults(),
        )
        assert sandbox.state is SandboxState.RUNNING
        assert (await provider.suspend(sandbox.sandbox_id)).state is SandboxState.SUSPENDED
        assert (await provider.resume(sandbox.sandbox_id)).state is SandboxState.RUNNING
        await provider.destroy(sandbox.sandbox_id)
        await provider.destroy(sandbox.sandbox_id)

    async def test_file_search_and_bounded_command(self, provider) -> None:
        sandbox = await provider.create(
            owner_id="u1",
            limits=SandboxLimits.safe_defaults(),
        )
        session = await provider.open_session(sandbox.sandbox_id)
        await session.write_file("main.py", b"print('contract')\n")
        assert await session.read_file("main.py") == b"print('contract')\n"
        matches = await session.search_text(
            "contract",
            paths=("**/*.py",),
            limit=5,
        )
        assert matches[0].line == 1
        result = await session.execute(
            CommandRequest(argv=("git", "--version"), timeout_sec=5)
        )
        assert result.exit_code == 0
        assert result.stdout.startswith(b"git version")

    async def test_suspend_blocks_session_until_resume(self, provider) -> None:
        sandbox = await provider.create(
            owner_id="u1",
            limits=SandboxLimits.safe_defaults(),
        )
        session = await provider.open_session(sandbox.sandbox_id)
        await provider.suspend(sandbox.sandbox_id)
        with pytest.raises(SandboxStateConflict):
            await session.list_tree(".")
        await provider.resume(sandbox.sandbox_id)
        assert await session.list_tree(".") == ()

    async def test_snapshot_restore_is_independent(self, provider) -> None:
        source = await provider.create(
            owner_id="u1",
            limits=SandboxLimits.safe_defaults(),
        )
        source_session = await provider.open_session(source.sandbox_id)
        await source_session.write_file("state.txt", b"v1")
        snapshot = await provider.snapshot(source.sandbox_id)
        restored = await provider.restore(snapshot.snapshot_id, owner_id="u1")
        restored_session = await provider.open_session(restored.sandbox_id)
        await restored_session.write_file("state.txt", b"v2")
        assert await source_session.read_file("state.txt") == b"v1"

    async def test_pty_reconnect_and_watcher_revision(self, provider) -> None:
        sandbox = await provider.create(
            owner_id="u1",
            limits=SandboxLimits.safe_defaults(),
        )
        session = await provider.open_session(sandbox.sandbox_id)
        watcher = await session.watch_files(after_cursor=0)
        await session.write_file("change.txt", b"one")
        async with asyncio.timeout(5):
            change = await anext(watcher)
        assert change.value.workspace_revision == 1
        assert change.value.changes[0].kind is WorkspaceChangeKind.CREATED

        terminal = await session.create_pty(argv=("/bin/sh",))
        await session.write_pty(terminal.pty_id, b"printf conformance\n")
        output = await wait_for_output(terminal, contains=b"conformance")
        replay = await terminal.replay(after_cursor=output.cursor - 1)
        assert replay[-1].cursor == output.cursor
        await session.kill_pty(terminal.pty_id)

    async def test_path_and_environment_policy(self, provider) -> None:
        sandbox = await provider.create(
            owner_id="u1",
            limits=SandboxLimits.safe_defaults(),
        )
        session = await provider.open_session(sandbox.sandbox_id)
        with pytest.raises(SandboxPolicyViolation):
            await session.read_file("../../etc/passwd")
        with pytest.raises(SandboxPolicyViolation):
            await session.execute(
                CommandRequest(argv=("env",), env={"TOKEN": "secret"})
            )

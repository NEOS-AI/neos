import asyncio
from pathlib import Path

from neos.coding.sandbox.base import SandboxLimits
from neos.coding.sandbox.memory import MemorySandboxProvider, PtyClosed, PtyOutput


async def _wait_for_output(terminal, expected: bytes):
    async with asyncio.timeout(2):
        async for event in terminal.subscribe(after_cursor=0):
            if isinstance(event.value, PtyOutput) and expected in event.value.data:
                return event
    raise AssertionError(f"PTY did not emit {expected!r}")


async def test_pty_replays_output_after_client_disconnect(
    tmp_path: Path,
) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    terminal = await session.create_pty(argv=("/bin/sh",))

    await session.write_pty(
        terminal.pty_id,
        b"printf reconnectable\\n",
    )
    output = await _wait_for_output(terminal, b"reconnectable")
    replay = await terminal.replay(after_cursor=output.cursor - 1)

    assert isinstance(replay[-1].value, PtyOutput)
    assert b"reconnectable" in replay[-1].value.data
    await session.kill_pty(terminal.pty_id)
    await provider.close()


async def test_suspend_closes_runtime_pty(tmp_path: Path) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    terminal = await session.create_pty(argv=("/bin/sh",))

    await provider.suspend(sandbox.sandbox_id)
    closed = await terminal.wait_closed()

    assert closed == PtyClosed(reason="sandbox_suspended", exit_code=None)
    await provider.close()

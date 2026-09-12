from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Mapping
from pathlib import Path

from neos.coding.sandbox.base import CommandRequest, CommandResult

TERMINATE_GRACE_SEC = 0.5
_READ_CHUNK = 4096


def _signal_process_group(pid: int, sig: int) -> None:
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        pass


def _close_stdio(process: asyncio.subprocess.Process) -> None:
    transport = getattr(process, "_transport", None)
    if transport is not None:
        transport.close()
    stdin = getattr(process, "stdin", None)
    if stdin is not None:
        stdin.close()


async def terminate_process_group(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None or process.pid is None:
        return
    _signal_process_group(process.pid, signal.SIGTERM)
    if process.returncode is not None:
        return
    try:
        async with asyncio.timeout(TERMINATE_GRACE_SEC):
            await process.wait()
    except TimeoutError:
        if process.returncode is None:
            _signal_process_group(process.pid, signal.SIGKILL)
            _close_stdio(process)
            await process.wait()


async def _feed_stdin(process: asyncio.subprocess.Process, data: bytes) -> None:
    if process.stdin is None:
        return
    try:
        if data:
            process.stdin.write(data)
            await process.stdin.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        process.stdin.close()


async def _read_task_result(
    task: asyncio.Task[tuple[bytes, bool]],
) -> tuple[bytes, bool]:
    try:
        return await task
    except asyncio.CancelledError:
        return b"", False


async def _read_capped(
    stream: asyncio.StreamReader | None,
    limit: int,
    overflow: asyncio.Event,
) -> tuple[bytes, bool]:
    if stream is None:
        return b"", False
    buf = bytearray()
    truncated = False
    try:
        while True:
            room = limit - len(buf)
            chunk = await stream.read(_READ_CHUNK if room <= 0 else min(_READ_CHUNK, room + 1))
            if not chunk:
                break
            if room <= 0:
                truncated = True
                overflow.set()
                break
            if len(chunk) > room:
                buf.extend(chunk[:room])
                truncated = True
                overflow.set()
                break
            buf.extend(chunk)
    except (BrokenPipeError, ConnectionResetError):
        pass
    return bytes(buf), truncated


class BoundedProcessRunner:
    """Execute argv directly with timeout and bounded captured output."""

    async def run(
        self,
        request: CommandRequest,
        *,
        cwd: Path,
        env: Mapping[str, str],
    ) -> CommandResult:
        process = await asyncio.create_subprocess_exec(
            *request.argv,
            cwd=cwd,
            env=dict(env),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            async with asyncio.timeout(request.timeout_sec):
                return await self._collect(process, request)
        except TimeoutError:
            await terminate_process_group(process)
            return CommandResult(
                exit_code=None,
                stdout=b"",
                stderr=b"",
                timed_out=True,
            )
        finally:
            _close_stdio(process)

    async def _collect(
        self,
        process: asyncio.subprocess.Process,
        request: CommandRequest,
    ) -> CommandResult:
        overflow = asyncio.Event()
        stdin_task = asyncio.create_task(_feed_stdin(process, request.stdin))
        stdout_task = asyncio.create_task(
            _read_capped(process.stdout, request.max_output_bytes, overflow)
        )
        stderr_task = asyncio.create_task(
            _read_capped(process.stderr, request.max_output_bytes, overflow)
        )
        wait_task = asyncio.create_task(process.wait())
        overflow_task = asyncio.create_task(overflow.wait())
        try:
            await asyncio.wait(
                {wait_task, overflow_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if overflow.is_set():
                for task in (stdout_task, stderr_task, wait_task):
                    if not task.done():
                        task.cancel()
                if process.returncode is None:
                    await terminate_process_group(process)
            elif not wait_task.done():
                await wait_task
            stdout, stdout_truncated = await _read_task_result(stdout_task)
            stderr, stderr_truncated = await _read_task_result(stderr_task)
            await stdin_task
        finally:
            overflow_task.cancel()
            for task in (stdin_task, stdout_task, stderr_task, wait_task):
                if not task.done():
                    task.cancel()
        return CommandResult(
            exit_code=process.returncode,
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            timed_out=False,
        )

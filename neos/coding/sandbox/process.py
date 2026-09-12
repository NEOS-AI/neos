from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Mapping
from pathlib import Path

from neos.coding.sandbox.base import CommandRequest, CommandResult

TERMINATE_GRACE_SEC = 0.5


def _signal_process_group(pid: int, sig: int) -> None:
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        pass


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
                stdout, stderr = await process.communicate(request.stdin)
        except TimeoutError:
            _signal_process_group(process.pid, signal.SIGTERM)
            if process.returncode is None:
                try:
                    async with asyncio.timeout(TERMINATE_GRACE_SEC):
                        await process.wait()
                except TimeoutError:
                    if process.returncode is None:
                        _signal_process_group(process.pid, signal.SIGKILL)
                        await process.wait()
            return CommandResult(
                exit_code=None,
                stdout=b"",
                stderr=b"",
                timed_out=True,
            )
        return CommandResult(
            exit_code=process.returncode,
            stdout=stdout[: request.max_output_bytes],
            stderr=stderr[: request.max_output_bytes],
            stdout_truncated=len(stdout) > request.max_output_bytes,
            stderr_truncated=len(stderr) > request.max_output_bytes,
            timed_out=False,
        )

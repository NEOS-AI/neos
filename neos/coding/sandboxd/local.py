"""Run `neos-sandboxd serve` as a local subprocess.

This is the test double for a managed sandbox image: the guest daemon runs
unmodified against a temporary workspace, and channels are unix-socket
connections. It is **not** an isolation boundary -- the process runs as the
host user -- so nothing in the factory can select it.

The daemon is started with a constant environment. The host's PATH, HOME, and
credentials never reach it, which is the same rule a vendor image follows.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
import sys
import tempfile
from pathlib import Path

from neos.coding.sandbox.base import SandboxUnavailable
from neos.coding.sandboxd import guest
from neos.coding.sandboxd.client import StreamSandboxdChannel

_DAEMON_ENV = {"PATH": guest.GUEST_PATH, "LANG": guest.GUEST_LANG}


class LocalSandboxd:
    def __init__(
        self,
        root: Path,
        *,
        python: str | None = None,
        guest_path: Path | None = None,
        stderr_path: Path | None = None,
    ) -> None:
        self.root = Path(root)
        self.workspace = self.root / "workspace"
        self.state_dir = self.root / "state"
        self._python = python or sys.executable
        # Tests run a derived guest (e.g. one that predates a capability) and
        # read what the daemon writes to stderr; production has neither.
        self.guest_path = Path(guest_path) if guest_path is not None else Path(guest.__file__)
        self._stderr_path = stderr_path
        # AF_UNIX paths are short (104 bytes on macOS); keep the socket in its
        # own short temporary directory instead of under a deep test root.
        self._socket_dir = Path(tempfile.mkdtemp(prefix="nsd-"))
        self.socket_path = self._socket_dir / "d.sock"
        self._process: asyncio.subprocess.Process | None = None
        self._channels: list[StreamSandboxdChannel] = []

    @property
    def confidential_channel(self) -> bool:
        """Track Q6b C1: the channel is private to the host user.

        An AF_UNIX socket the guest chmods to 0600, inside a `mkdtemp`
        directory (0700). No network hop, no relay process, nothing logged.
        """
        return True

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def start(self, *, timeout_sec: float = 10.0) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        stderr = (
            open(self._stderr_path, "ab")  # noqa: SIM115 -- closed below once the child has it
            if self._stderr_path is not None
            else asyncio.subprocess.DEVNULL
        )
        try:
            self._process = await self._spawn(stderr)
        finally:
            if self._stderr_path is not None:
                stderr.close()
        deadline = asyncio.get_running_loop().time() + timeout_sec
        while True:
            if self._process.returncode is not None:
                raise SandboxUnavailable("local_sandboxd_exited")
            if self.socket_path.exists():
                try:
                    _reader, writer = await asyncio.open_unix_connection(
                        str(self.socket_path)
                    )
                except OSError:
                    pass
                else:
                    writer.close()
                    return
            if asyncio.get_running_loop().time() > deadline:
                await self.stop()
                raise SandboxUnavailable("local_sandboxd_start_timeout")
            await asyncio.sleep(0.02)

    async def _spawn(self, stderr) -> asyncio.subprocess.Process:
        return await asyncio.create_subprocess_exec(
            self._python,
            str(self.guest_path),
            "serve",
            "--workspace",
            str(self.workspace),
            "--state-dir",
            str(self.state_dir),
            "--socket",
            str(self.socket_path),
            env=dict(_DAEMON_ENV),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=stderr,
            start_new_session=True,
        )

    async def open_channel(self) -> StreamSandboxdChannel:
        if not self.running:
            raise SandboxUnavailable("local_sandboxd_not_running")
        reader, writer = await asyncio.open_unix_connection(
            str(self.socket_path), limit=guest.MAX_FRAME_BYTES + 8
        )
        channel = StreamSandboxdChannel(reader, writer)
        self._channels.append(channel)
        return channel

    async def drop_connections(self) -> None:
        """Close every open channel; the daemon and its journals survive."""
        channels, self._channels = self._channels, []
        for channel in channels:
            await channel.close()

    async def stop(self) -> None:
        await self.drop_connections()
        process = self._process
        if process is not None and process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                async with asyncio.timeout(3):
                    await process.wait()
            except TimeoutError:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()
        shutil.rmtree(self._socket_dir, ignore_errors=True)

    def copy_to(self, destination: Path) -> None:
        """Copy workspace and daemon state, as a filesystem snapshot would."""
        destination = Path(destination)
        shutil.copytree(self.workspace, destination / "workspace", symlinks=True)
        shutil.copytree(self.state_dir, destination / "state", symlinks=True)

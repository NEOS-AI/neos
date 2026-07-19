import asyncio

from neos.coding.sandbox.base import SandboxLimits
from neos.coding.sandbox.docker import DockerSandboxConfig, DockerSandboxProvider
from neos.coding.sandbox.memory import PtyClosed, PtyOutput
from tests.coding.sandbox.test_docker_provider import IMAGE, ScriptedDockerRunner


class FakeInteractiveTransport:
    def __init__(self) -> None:
        self.output: asyncio.Queue[bytes] = asyncio.Queue()
        self.writes: list[bytes] = []
        self.sizes: list[tuple[int, int]] = []
        self.terminated = False
        self.exit_code = 0

    async def read(self, maximum: int) -> bytes:
        return await self.output.get()

    async def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def resize(self, *, rows: int, cols: int) -> None:
        self.sizes.append((rows, cols))

    async def terminate(self) -> None:
        self.terminated = True
        await self.output.put(b"")

    async def wait(self) -> int:
        return self.exit_code


async def _wait_for_output(terminal, expected: bytes):
    async with asyncio.timeout(2):
        async for event in terminal.subscribe(after_cursor=0):
            if isinstance(event.value, PtyOutput) and expected in event.value.data:
                return event
    raise AssertionError(f"PTY did not emit {expected!r}")


async def test_pty_replays_and_forwards_interactive_operations() -> None:
    transport = FakeInteractiveTransport()
    started = []

    async def start(*args: str):
        started.append(args)
        return transport

    provider = DockerSandboxProvider(
        runner=ScriptedDockerRunner(),
        config=DockerSandboxConfig(image=IMAGE),
        interactive_factory=start,
    )
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    terminal = await session.create_pty(argv=("/bin/sh",))
    await transport.output.put(b"reconnectable\r\n")

    output = await _wait_for_output(terminal, b"reconnectable")
    replay = await terminal.replay(after_cursor=output.cursor - 1)
    await session.write_pty(terminal.pty_id, b"echo hi\n")
    await session.resize_pty(terminal.pty_id, rows=40, cols=120)
    await session.kill_pty(terminal.pty_id)

    assert started[0][-3:] == (
        "-t",
        f"neos-{sandbox.sandbox_id}",
        "/bin/sh",
    )
    assert isinstance(replay[-1].value, PtyOutput)
    assert transport.writes == [b"echo hi\n"]
    assert transport.sizes == [(40, 120)]
    assert transport.terminated
    assert await terminal.wait_closed() == PtyClosed("pty_killed", None)


async def test_suspend_closes_docker_pty() -> None:
    transport = FakeInteractiveTransport()

    async def start(*args: str):
        return transport

    provider = DockerSandboxProvider(
        runner=ScriptedDockerRunner(),
        config=DockerSandboxConfig(image=IMAGE),
        interactive_factory=start,
    )
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    terminal = await session.create_pty(argv=("/bin/sh",))

    await provider.suspend(sandbox.sandbox_id)

    assert await terminal.wait_closed() == PtyClosed("sandbox_suspended", None)

import asyncio
import json

from neos.coding.sandbox.base import CommandRequest, SandboxLimits
from neos.coding.sandbox.command import DockerCommandResult
from neos.coding.sandbox.docker import DockerSandboxConfig, DockerSandboxProvider
from neos.coding.sandbox.memory import WorkspaceChangeKind
from tests.coding.sandbox.test_docker_provider import IMAGE, ScriptedDockerRunner


async def test_watcher_debounces_changes_with_latest_revision() -> None:
    provider = DockerSandboxProvider(
        runner=ScriptedDockerRunner(),
        config=DockerSandboxConfig(image=IMAGE, watcher_debounce_sec=0.01),
    )
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    watcher = await session.watch_files(after_cursor=0)

    await session.write_file("src/app.py", b"one")
    await session.write_file("src/app.py", b"two")
    async with asyncio.timeout(2):
        event = await anext(watcher)

    assert event.value.workspace_revision == 2
    assert [(change.path, change.kind) for change in event.value.changes] == [
        ("src/app.py", WorkspaceChangeKind.CREATED)
    ]
    replay = await watcher.replay(after_cursor=0)
    assert replay[-1] == event
    await provider.close()


async def test_watcher_reconciles_files_created_by_command() -> None:
    runner = ScriptedDockerRunner()
    provider = DockerSandboxProvider(
        runner=runner,
        config=DockerSandboxConfig(image=IMAGE, watcher_debounce_sec=0.01),
    )
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    watcher = await session.watch_files(after_cursor=0)
    runner.results.extend(
        [
            DockerCommandResult(0, b"{}", b""),
            DockerCommandResult(0, b"done\n", b""),
            DockerCommandResult(
                0,
                json.dumps({"generated.txt": [4, 1]}).encode(),
                b"",
            ),
        ]
    )

    result = await session.execute(CommandRequest(argv=("generate",)))
    async with asyncio.timeout(2):
        event = await anext(watcher)

    assert result.stdout == b"done\n"
    assert event.value.workspace_revision == 1
    assert event.value.changes[0].path == "generated.txt"
    assert event.value.changes[0].kind is WorkspaceChangeKind.CREATED
    await provider.close()


async def test_command_mutation_advances_revision_without_watcher() -> None:
    runner = ScriptedDockerRunner()
    provider = DockerSandboxProvider(runner=runner, config=DockerSandboxConfig(image=IMAGE))
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    runner.results.extend(
        [
            DockerCommandResult(0, b"{}", b""),
            DockerCommandResult(0, b"done\n", b""),
            DockerCommandResult(
                0,
                json.dumps({"generated.txt": [4, 1]}).encode(),
                b"",
            ),
        ]
    )

    result = await session.execute(CommandRequest(argv=("generate",)))

    assert result.stdout == b"done\n"
    assert await session.workspace_revision() == 1
    await provider.close()

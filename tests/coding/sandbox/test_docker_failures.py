import pytest

from neos.coding.sandbox.base import (
    SandboxLimits,
    SandboxNotFound,
    SandboxUnavailable,
)
from neos.coding.sandbox.docker import (
    DockerSandboxConfig,
    DockerSandboxProvider,
)
from neos.coding.sandbox.command import DockerCommandResult
from tests.coding.sandbox.test_docker_provider import (
    IMAGE,
    ScriptedDockerRunner,
)


async def test_readiness_failure_removes_partial_resources_in_reverse() -> None:
    runner = ScriptedDockerRunner(
        results=[
            None,
            None,
            None,
            SandboxUnavailable("probe_failed"),
        ]
    )
    provider = DockerSandboxProvider(
        runner=runner,
        config=DockerSandboxConfig(image=IMAGE),
    )

    with pytest.raises(SandboxUnavailable, match="probe_failed"):
        await provider.create(
            owner_id="u1",
            limits=SandboxLimits.safe_defaults(),
        )

    assert [call[0] for call in runner.calls[-2:]] == ["rm", "volume"]
    assert runner.calls[-1][1] == "rm"


async def test_destroy_is_idempotent_and_hides_destroyed_sandbox() -> None:
    runner = ScriptedDockerRunner()
    provider = DockerSandboxProvider(
        runner=runner,
        config=DockerSandboxConfig(image=IMAGE),
    )
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )

    await provider.destroy(sandbox.sandbox_id)
    cleanup_call_count = len(runner.calls)
    await provider.destroy(sandbox.sandbox_id)

    assert len(runner.calls) == cleanup_call_count
    with pytest.raises(SandboxNotFound):
        await provider.get(sandbox.sandbox_id)


async def test_snapshot_rejects_truncated_archive(tmp_path) -> None:
    runner = ScriptedDockerRunner()
    provider = DockerSandboxProvider(
        runner=runner,
        config=DockerSandboxConfig(image=IMAGE, snapshot_root=tmp_path),
    )
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    runner.results.append(
        DockerCommandResult(
            exit_code=0,
            stdout=b"partial archive",
            stderr=b"",
            stdout_truncated=True,
        )
    )

    with pytest.raises(SandboxUnavailable, match="snapshot_archive_truncated"):
        await provider.snapshot(sandbox.sandbox_id)

import pytest

from neos.coding.sandbox.base import (
    SandboxLimits,
    SandboxPolicyViolation,
    SandboxTimeout,
    SandboxUnavailable,
)
from neos.coding.sandbox.command import (
    DockerCommandResult,
    DockerCommandRunner,
    build_create_args,
)


DIGEST_IMAGE = "neos-sandbox@sha256:" + "a" * 64
LIMITS = SandboxLimits.safe_defaults()


def test_create_args_enforce_isolation() -> None:
    args = build_create_args(
        sandbox_id="sb_1",
        image=DIGEST_IMAGE,
        limits=LIMITS,
    )
    joined = " ".join(args)

    assert "--user 10001:10001" in joined
    assert "--cap-drop ALL" in joined
    assert "--security-opt no-new-privileges" in joined
    assert "--read-only" in args
    assert "--network none" in joined
    assert "--pids-limit 128" in joined
    assert "--memory 536870912" in joined
    assert "--cpus 1.0" in joined
    assert "--tmpfs /tmp:rw,noexec,nosuid,size=67108864" in joined
    assert "/var/run/docker.sock" not in joined
    assert "--privileged" not in args


def test_create_args_reject_unpinned_image_by_default() -> None:
    with pytest.raises(SandboxPolicyViolation, match="docker_image_unpinned"):
        build_create_args(
            sandbox_id="sb_1",
            image="neos-sandbox:latest",
            limits=LIMITS,
        )


async def test_runner_maps_timeout_without_leaking_arguments() -> None:
    async def timeout(*args: str, timeout_sec: float):
        raise TimeoutError("registry-token")

    runner = DockerCommandRunner(exec=timeout)

    with pytest.raises(SandboxTimeout) as error:
        await runner.run(
            "login",
            "--password",
            "registry-token",
            timeout_sec=1,
        )

    assert "registry-token" not in str(error.value)


async def test_runner_maps_daemon_failure_without_raw_stderr() -> None:
    async def fail(*args: str, timeout_sec: float):
        return DockerCommandResult(
            exit_code=1,
            stdout=b"",
            stderr=b"daemon registry-token failure",
        )

    runner = DockerCommandRunner(exec=fail)

    with pytest.raises(SandboxUnavailable) as error:
        await runner.run("inspect", "sb_1", timeout_sec=1)

    assert "registry-token" not in str(error.value)


async def test_runner_forwards_bounded_stdin_outside_argv() -> None:
    received = {}

    async def capture(
        *args: str,
        timeout_sec: float,
        input: bytes,
    ) -> DockerCommandResult:
        received["args"] = args
        received["input"] = input
        return DockerCommandResult(exit_code=0, stdout=b"", stderr=b"")

    runner = DockerCommandRunner(exec=capture)
    await runner.run(
        "exec",
        "-i",
        "sb_1",
        "helper",
        timeout_sec=1,
        input=b"file contents",
    )

    assert received == {
        "args": ("exec", "-i", "sb_1", "helper"),
        "input": b"file contents",
    }

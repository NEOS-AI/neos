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


_SB = "sb_" + "a" * 32
_IMAGE = "neos-sandbox@sha256:" + "a" * 64


def _create_args(**kwargs):
    return build_create_args(
        sandbox_id=_SB,
        image=_IMAGE,
        limits=SandboxLimits.safe_defaults(),
        **kwargs,
    )


def test_build_create_args_emits_extra_labels() -> None:
    args = _create_args(extra_labels={"com.neos.coding.owner-id": "owner_1"})

    index = args.index("com.neos.coding.owner-id=owner_1")
    assert args[index - 1] == "--label"


def test_build_create_args_is_byte_identical_without_extra_labels() -> None:
    """관리형 라벨이 없을 때 argv가 종전과 완전히 같아야 한다.

    이 단언이 CA5-a 작업이 데이터 플레인을 건드리지 않았다는 증거다.
    """
    assert _create_args(extra_labels=None) == _create_args()
    assert _create_args(extra_labels={}) == _create_args()


def test_build_create_args_rejects_label_injection() -> None:
    with pytest.raises(SandboxPolicyViolation, match="docker_label_invalid"):
        _create_args(extra_labels={"com.neos.coding.owner-id": "a\nb"})

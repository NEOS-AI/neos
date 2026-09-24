"""Docker provider 가 profile 을 스스로 강제하고, 증거를 읽기 전용으로 붙인다.

계약 §3.2 의 ⚠️ 상자가 적은 development 경로의 두 downgrade 를 닫는 테스트다.

1. 증거는 워커 컨테이너에 **읽기 전용으로만** 붙은 별도 볼륨에 있다. 워커
   컨테이너의 인자에는 그 볼륨의 쓰기 가능한 마운트가 하나도 없고, 쓰기는
   `write_evidence` 의 짧은 컨테이너에서만 일어난다.
2. `profile` 을 주면 `sandbox.docker.network_mode` 설정과 무관하게 그
   profile 의 네트워크 정책이 적용되고, create 뒤에 읽어서 확인한다. 강제할
   수 없는 요구는 **리소스를 만들기 전에** 거절한다.

그리고 profile·증거 없이 부르면 인자와 호출 순서가 이전과 같다(코딩 루프,
플래그 off).
"""

from __future__ import annotations

import json

import pytest

from neos.coding.sandbox.base import (
    SandboxLimits,
    SandboxPolicyViolation,
    SandboxUnavailable,
)
from neos.coding.sandbox.command import (
    DockerCommandResult,
    build_create_args,
    build_evidence_writer_args,
    evidence_volume_name,
)
from neos.coding.sandbox.docker import (
    DockerSandboxConfig,
    DockerSandboxProvider,
    _docker_profile_capabilities,
)

pytestmark = pytest.mark.no_db

IMAGE = "neos-sandbox@sha256:" + "a" * 64
PROFILE = "research-offline-v1"


class _Runner:
    """`inspect` 에만 대본을 주고 나머지는 성공으로 답한다."""

    def __init__(self, *, network_mode: str = "none", evidence_rw: bool = False):
        self.calls: list[tuple[str, ...]] = []
        self.inputs: list[bytes] = []
        self.network_mode = network_mode
        self.evidence_rw = evidence_rw

    def _inspect(self, name: str) -> bytes:
        sandbox_id = name.removeprefix("neos-")
        volume = evidence_volume_name(sandbox_id)
        return json.dumps(
            [
                {
                    "HostConfig": {"NetworkMode": self.network_mode},
                    "Mounts": [
                        {
                            "Name": f"neos-sandbox-{sandbox_id}",
                            "Destination": "/workspace",
                            "RW": True,
                        },
                        {
                            "Name": volume,
                            "Destination": "/evidence",
                            "RW": self.evidence_rw,
                        },
                        {
                            "Name": volume,
                            "Destination": "/workspace/evidence",
                            "RW": self.evidence_rw,
                        },
                    ],
                }
            ]
        ).encode()

    async def run(self, *args, timeout_sec, allowed_exit_codes=(0,), input=b""):
        self.calls.append(args)
        self.inputs.append(input)
        if args[0] == "inspect":
            return DockerCommandResult(0, self._inspect(args[1]), b"")
        return DockerCommandResult(0, b"", b"")


def _provider(runner: _Runner, *, network_mode: str = "none") -> DockerSandboxProvider:
    return DockerSandboxProvider(
        runner=runner,
        config=DockerSandboxConfig(
            image=IMAGE, create_timeout_sec=5, network_mode=network_mode
        ),
    )


def _create_call(runner: _Runner) -> tuple[str, ...]:
    (call,) = [call for call in runner.calls if call[0] == "create"]
    return call


def _option_values(call: tuple[str, ...], option: str) -> list[str]:
    return [call[i + 1] for i, arg in enumerate(call[:-1]) if arg == option]


# --- flag-off / 코딩 루프: 이전과 같다 ------------------------------------------


async def test_without_profile_or_evidence_the_calls_are_unchanged() -> None:
    """profile 을 모르는 호출부(코딩 루프, 플래그 off)는 아무것도 달라지지 않는다.

    inspect 가 끼어들지 않고, 볼륨은 하나이며, create 인자는 새 키워드 없이
    만든 `build_create_args` 와 바이트 단위로 같다.
    """
    runner = _Runner()
    provider = _provider(runner)

    sandbox = await provider.create(owner_id="u1", limits=SandboxLimits.safe_defaults())

    assert [call[0] for call in runner.calls] == ["volume", "create", "start", "exec"]
    create = _create_call(runner)
    labels = dict(
        value.split("=", 1) for value in _option_values(create, "--label")
    )
    expected = build_create_args(
        sandbox_id=sandbox.sandbox_id,
        image=IMAGE,
        limits=SandboxLimits.safe_defaults(),
        extra_labels={
            key: labels[key]
            for key in (
                "com.neos.coding.owner-id",
                "com.neos.coding.created-at",
                "com.neos.coding.workspace-revision",
            )
        },
    )
    assert create == expected
    assert not any("evidence" in arg for arg in create)
    assert not any("profile" in arg for arg in create)


# --- 2. profile 강제 --------------------------------------------------------------


async def test_a_deny_all_profile_gets_no_network_even_when_settings_say_bridge() -> None:
    """설정은 profile 의 네트워크 정책을 넓히지 못한다."""
    runner = _Runner()
    provider = _provider(runner, network_mode="bridge")

    await provider.create(
        owner_id="q_1", limits=SandboxLimits.safe_defaults(), profile=PROFILE
    )

    create = _create_call(runner)
    assert _option_values(create, "--network") == ["none"]
    assert f"com.neos.coding.profile={PROFILE}" in _option_values(create, "--label")
    # 주장이 아니라 확인: 데몬이 적용한 값을 다시 읽었다.
    assert any(call[0] == "inspect" for call in runner.calls)


async def test_without_a_profile_bridge_settings_are_still_refused() -> None:
    """변이 대조군. profile 이 네트워크를 끄는 **유일한** 이유가 아님을 보인다.

    `build_create_args` 는 2026-07-19(33064654)부터 `none` 이 아닌 값을
    거절했다 -- profile 이 없던 시절에도 Docker 컨테이너에는 네트워크가 붙을
    수 없었다.
    """
    runner = _Runner()
    provider = _provider(runner, network_mode="bridge")

    with pytest.raises(SandboxPolicyViolation, match="docker_network_not_isolated"):
        await provider.create(owner_id="u1", limits=SandboxLimits.safe_defaults())


async def test_a_network_readback_mismatch_refuses_and_cleans_up() -> None:
    """인자로 none 을 넘겨도 데몬이 다른 값을 적용했으면 샌드박스는 없다."""
    runner = _Runner(network_mode="bridge")
    provider = _provider(runner)

    with pytest.raises(SandboxUnavailable, match="network_readback_mismatch"):
        await provider.create(
            owner_id="q_1",
            limits=SandboxLimits.safe_defaults(),
            profile=PROFILE,
            evidence=True,
        )

    removed = [call for call in runner.calls if call[0] in {"rm", "volume"}]
    assert ("rm", "--force") == removed[-3][:2]
    assert [call[:2] for call in removed[-2:]] == [("volume", "rm")] * 2
    assert removed[-1][2].startswith("neos-evidence-")


@pytest.mark.parametrize(
    ("profile", "reason"),
    [
        ("strict-workspace-quota-v1", "hard_workspace_quota_unavailable"),
        ("no-such-profile", "unknown_profile"),
    ],
)
async def test_an_unsatisfiable_profile_is_refused_before_any_resource(
    profile: str, reason: str
) -> None:
    runner = _Runner()
    provider = _provider(runner)

    with pytest.raises(SandboxUnavailable, match=f"profile_unsupported:{profile}:{reason}"):
        await provider.create(
            owner_id="q_1", limits=SandboxLimits.safe_defaults(), profile=profile
        )

    assert runner.calls == []


def test_an_allowlist_profile_is_unenforceable_on_docker() -> None:
    """Docker 에는 목적지 단위 정책이 없다. 레지스트리에 그런 profile 이
    아직 없으므로 협상 함수에 직접 넣어 본다 -- 생기는 날 조용히 통과하지
    않게."""
    from neos.coding.sandbox.managed.profiles import (
        NetworkPolicy,
        SandboxProfile,
        negotiate_profile_requirements,
    )

    allowlist = SandboxProfile(
        name="allow-pypi",
        network=NetworkPolicy(outbound="allowlist", inbound="deny", allow=("pypi.org",)),
    )

    with pytest.raises(SandboxUnavailable, match="outbound_allowlist_unenforceable"):
        negotiate_profile_requirements(allowlist, _docker_profile_capabilities())


def test_managed_negotiation_still_requires_sandboxd() -> None:
    """요구 협상을 떼어 냈어도 관리형의 sandboxd 요구는 그대로다."""
    from neos.coding.sandbox.managed.profiles import (
        RESEARCH_OFFLINE_V1,
        negotiate_profile,
    )

    with pytest.raises(SandboxUnavailable, match="sandboxd_channel_unavailable"):
        negotiate_profile(RESEARCH_OFFLINE_V1, _docker_profile_capabilities())


# --- 1. 읽기 전용 증거 ------------------------------------------------------------


async def test_the_worker_container_has_no_writable_evidence_mount() -> None:
    runner = _Runner()
    provider = _provider(runner)

    sandbox = await provider.create(
        owner_id="q_1",
        limits=SandboxLimits.safe_defaults(),
        profile=PROFILE,
        evidence=True,
    )

    volume = evidence_volume_name(sandbox.sandbox_id)
    mounts = [m for m in _option_values(_create_call(runner), "--mount") if volume in m]
    assert sorted(mounts) == sorted(
        [
            f"type=volume,source={volume},target=/evidence,readonly,volume-nocopy",
            f"type=volume,source={volume},target=/workspace/evidence,"
            "readonly,volume-nocopy",
        ]
    )
    assert ("volume", "create") == runner.calls[1][:2]
    assert runner.calls[1][-1] == volume


async def test_a_writable_evidence_readback_refuses() -> None:
    """변이: 데몬이 증거 마운트를 쓰기 가능으로 붙였다면 샌드박스는 없다."""
    runner = _Runner(evidence_rw=True)
    provider = _provider(runner)

    with pytest.raises(SandboxPolicyViolation, match="evidence_mount_not_readonly"):
        await provider.create(
            owner_id="q_1",
            limits=SandboxLimits.safe_defaults(),
            profile=PROFILE,
            evidence=True,
        )


async def test_evidence_is_written_by_a_separate_offline_container() -> None:
    runner = _Runner()
    provider = _provider(runner)
    sandbox = await provider.create(
        owner_id="q_1",
        limits=SandboxLimits.safe_defaults(),
        profile=PROFILE,
        evidence=True,
    )

    await provider.write_evidence(sandbox.sandbox_id, "abc123def456ffff.txt", b"body")

    writer = runner.calls[-1]
    assert writer[:3] == ("run", "--rm", "-i")
    assert _option_values(writer, "--network") == ["none"]
    assert _option_values(writer, "--cap-drop") == ["ALL"]
    assert "--read-only" in writer
    # 워커 컨테이너가 아니다 -- `docker exec` 가 아니라 새 컨테이너다.
    assert f"neos-{sandbox.sandbox_id}" not in writer
    assert _option_values(writer, "--mount") == [
        f"type=volume,source={evidence_volume_name(sandbox.sandbox_id)},"
        "target=/evidence,volume-nocopy"
    ]
    assert writer[-1] == "abc123def456ffff.txt"
    assert runner.inputs[-1] == b"body"


@pytest.mark.parametrize(
    "name", ["../escape.txt", ".hidden.txt", "a/b.txt", "no-suffix", ""]
)
def test_evidence_names_cannot_leave_the_volume(name: str) -> None:
    with pytest.raises(SandboxPolicyViolation, match="evidence_name_invalid"):
        build_evidence_writer_args(
            sandbox_id="sb_x",
            image=IMAGE,
            writer_id="0123456789ab",
            helper="pass",
            name=name,
            memory_bytes=1024,
        )


async def test_a_sandbox_without_evidence_refuses_evidence_writes() -> None:
    runner = _Runner()
    provider = _provider(runner)
    sandbox = await provider.create(owner_id="u1", limits=SandboxLimits.safe_defaults())

    with pytest.raises(SandboxPolicyViolation, match="sandbox_has_no_evidence_volume"):
        await provider.write_evidence(sandbox.sandbox_id, "a.txt", b"x")


async def test_destroy_removes_the_evidence_volume() -> None:
    runner = _Runner()
    provider = _provider(runner)
    sandbox = await provider.create(
        owner_id="q_1",
        limits=SandboxLimits.safe_defaults(),
        profile=PROFILE,
        evidence=True,
    )

    await provider.destroy(sandbox.sandbox_id)

    assert ("volume", "rm", evidence_volume_name(sandbox.sandbox_id)) in runner.calls


async def test_reconcile_recovers_the_evidence_volume_for_cleanup() -> None:
    """재시작 뒤에도 destroy 가 증거 볼륨을 남기지 않는다."""

    class _Reconcile(_Runner):
        async def run(self, *args, timeout_sec, allowed_exit_codes=(0,), input=b""):
            self.calls.append(args)
            if args[0] == "ps":
                return DockerCommandResult(0, b"c1\n", b"")
            if args[0] == "inspect":
                labels = {
                    "com.neos.coding.sandbox": "true",
                    "com.neos.coding.sandbox-id": "sb_owned",
                    "com.neos.coding.owner-id": "q_1",
                    "com.neos.coding.created-at": "2026-09-23T10:00:00+00:00",
                    "com.neos.coding.workspace-revision": "0",
                    "com.neos.coding.evidence-volume": "attacker-chosen",
                }
                return DockerCommandResult(
                    0,
                    json.dumps(
                        [
                            {
                                "Name": "/neos-sb_owned",
                                "Config": {"Labels": labels},
                                "State": {"Running": True},
                            }
                        ]
                    ).encode(),
                    b"",
                )
            return DockerCommandResult(0, b"", b"")

    runner = _Reconcile()
    provider = _provider(runner)

    await provider.reconcile()
    await provider.destroy("sb_owned")

    # 라벨의 값이 아니라 sandbox_id 에서 다시 만든 이름을 지운다.
    assert ("volume", "rm", "neos-evidence-sb_owned") in runner.calls
    assert not any("attacker-chosen" in arg for call in runner.calls for arg in call)

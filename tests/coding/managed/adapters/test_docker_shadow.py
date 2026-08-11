import asyncio
from datetime import UTC, datetime
import io
import json
from pathlib import Path
import tarfile

import pytest

from neos.coding.managed.adapters import (
    DockerShadowManagedAdapter,
    ManagedAdapterCapabilityError,
    ManagedAdapterOwnershipError,
    ManagedAdapterTimeoutError,
)
from neos.coding.managed.adapters import docker_shadow as docker_shadow_module
from neos.coding.managed.adapters.docker_shadow import (
    ALLOCATION_ID_LABEL,
    CLAIM_TOKEN_LABEL,
    CLAIMED_AT_LABEL,
    IDEMPOTENCY_KEY_LABEL,
    OWNERSHIP_DIGEST_LABEL,
)
from neos.coding.managed.domain import ManagedSandboxState, ProviderCircuitState
from neos.coding.sandbox.command import DockerCommandResult
from neos.coding.sandbox.base import SandboxError, SandboxLimits, SandboxUnavailable
from neos.coding.sandbox.docker import (
    DockerSandboxConfig,
    DockerSandboxProvider,
)
from tests.coding.managed.adapters.conformance import (
    IMAGE,
    allocation_request,
    assert_managed_adapter_conformance,
)

pytestmark = pytest.mark.no_db

# claim_lease_seconds(기본값 300초)보다 훨씬 오래된 시각 -- 테스트 실행 시각과
# 무관하게 항상 회수 대상으로 판정된다.
STALE_CLAIMED_AT = "2020-01-01T00:00:00+00:00"


def _archive() -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        content = b"state"
        info = tarfile.TarInfo("state.txt")
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    return output.getvalue()


class EmulatedDockerRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.containers: dict[str, dict[str, object]] = {}
        self.volumes: dict[str, dict[str, object]] = {}
        self.removal_failures: set[tuple[str, str]] = set()
        self._pending_failures: dict[str, tuple[Exception, int]] = {}

    def fail_next(self, op: str, error: Exception, *, occurrence: int = 1) -> None:
        """`op`(args[0])가 `occurrence`번째로 불릴 때 정상 처리 대신 `error`를 올린다.

        일회성이다 -- 그 호출을 소비하면 이후 같은 op는 다시 정상 처리된다.
        "volume"은 args[0]만으로 매칭하므로 create/inspect/rm을 모두 센다 --
        예를 들어 allocate() 한 번의 성공 경로에서는 클레임 생성(1)·클레임
        inspect(2)·워크스페이스 생성(3)·소유권 발행(4) 순서로 불린다.
        """
        self._pending_failures[op] = (error, occurrence)

    def seed_orphan_claim(self, name: str, *, claimed_at: str) -> None:
        """소유자가 죽어 아무도 정리하지 않은 클레임 볼륨을 미리 심어 둔다.

        라벨은 `allocation_request()`의 기본값(allocation_id="msa_1",
        idempotency_key="idem_1", ownership_digest="sha256:owner")과 맞춘다 --
        회수 대상 판정 전에 `_verify_resource_metadata`가 먼저 통과해야 한다.
        """
        self.volumes[name] = {
            "Name": name,
            "Labels": {
                ALLOCATION_ID_LABEL: "msa_1",
                IDEMPOTENCY_KEY_LABEL: "idem_1",
                OWNERSHIP_DIGEST_LABEL: "sha256:owner",
                CLAIM_TOKEN_LABEL: "dead-owner-token",
                CLAIMED_AT_LABEL: claimed_at,
            },
        }

    async def run(
        self,
        *args: str,
        timeout_sec: float,
        allowed_exit_codes=(0,),
        input: bytes = b"",
    ) -> DockerCommandResult:
        del timeout_sec, input
        self.calls.append(args)
        if args and args[0] in self._pending_failures:
            error, remaining = self._pending_failures[args[0]]
            if remaining <= 1:
                del self._pending_failures[args[0]]
                raise error
            self._pending_failures[args[0]] = (error, remaining - 1)
        if args[:2] == ("volume", "create"):
            name = args[-1]
            labels = _labels_from_args(args)
            self.volumes.setdefault(
                name,
                {
                    "Name": name,
                    "Labels": labels,
                },
            )
            await asyncio.sleep(0)
        elif args[:2] == ("volume", "inspect"):
            name = args[2]
            value = self.volumes.get(name)
            if value is None:
                return self._missing_or_raise(args, allowed_exit_codes)
            return DockerCommandResult(0, json.dumps([value]).encode(), b"")
        elif args[:2] == ("volume", "rm"):
            name = args[2]
            if ("volume", name) in self.removal_failures:
                raise SandboxUnavailable("emulated_volume_remove_failed")
            if name not in self.volumes:
                return self._missing_or_raise(args, allowed_exit_codes)
            self.volumes.pop(name)
        elif args[0] == "create":
            name = args[args.index("--name") + 1]
            labels = _labels_from_args(args)
            self.containers[name] = {
                "Id": f"container-{name}",
                "Name": f"/{name}",
                "Config": {"Labels": labels},
                "State": {"Running": False},
            }
        elif args[0] == "start":
            self.containers[args[1]]["State"] = {"Running": True}
        elif args[0] == "stop":
            self.containers[args[1]]["State"] = {"Running": False}
        elif args[0] == "rm":
            name = args[-1]
            if ("container", name) in self.removal_failures:
                raise SandboxUnavailable("emulated_container_remove_failed")
            if name not in self.containers:
                return self._missing_or_raise(args, allowed_exit_codes)
            self.containers.pop(args[-1], None)
        elif args[0] == "inspect":
            values = []
            for reference in args[1:]:
                value = self.containers.get(reference)
                if value is None:
                    value = next(
                        (
                            item
                            for item in self.containers.values()
                            if item["Id"] == reference
                        ),
                        None,
                    )
                if value is None:
                    return self._missing_or_raise(args, allowed_exit_codes)
                values.append(value)
            return DockerCommandResult(0, json.dumps(values).encode(), b"")
        elif args[:2] == ("ps", "--all"):
            filter_value = args[args.index("--filter") + 1]
            label = filter_value.removeprefix("label=")
            key, expected = label.split("=", 1)
            values = [
                value["Id"]
                for value in self.containers.values()
                if value["Config"]["Labels"].get(key) == expected
            ]
            await asyncio.sleep(0)
            return DockerCommandResult(0, ("\n".join(values) + "\n").encode(), b"")
        elif args[0] == "exec" and "test" not in args:
            return DockerCommandResult(0, _archive(), b"")
        return DockerCommandResult(0, b"", b"")

    @staticmethod
    def _missing_or_raise(
        args: tuple[str, ...],
        allowed_exit_codes: tuple[int, ...],
    ) -> DockerCommandResult:
        if 1 in allowed_exit_codes:
            return DockerCommandResult(1, b"", b"not found")
        raise SandboxUnavailable(f"emulated_not_found:{args[-1]}")


def _labels_from_args(args: tuple[str, ...]) -> dict[str, str]:
    return {
        args[index + 1].split("=", 1)[0]: args[index + 1].split("=", 1)[1]
        for index, value in enumerate(args)
        if value == "--label"
    }


def docker_adapter(
    *,
    network_mode: str = "none",
    create_timeout_sec: float = 30.0,
) -> tuple[DockerShadowManagedAdapter, EmulatedDockerRunner]:
    runner = EmulatedDockerRunner()
    provider = DockerSandboxProvider(
        runner=runner,
        config=DockerSandboxConfig(
            image=IMAGE,
            network_mode=network_mode,
            create_timeout_sec=create_timeout_sec,
        ),
        clock=lambda: datetime(2026, 7, 25, 12, tzinfo=UTC),
    )
    return DockerShadowManagedAdapter(provider=provider), runner


async def test_docker_shadow_passes_managed_adapter_conformance() -> None:
    adapter, _runner = docker_adapter()

    await assert_managed_adapter_conformance(adapter)


async def test_allocate_binds_managed_metadata_in_docker_labels() -> None:
    adapter, runner = docker_adapter()
    request = allocation_request()

    created = await adapter.allocate(request)

    create_call = next(call for call in runner.calls if call[0] == "create")
    assert f"{ALLOCATION_ID_LABEL}={request.allocation_id}" in create_call
    assert f"{IDEMPOTENCY_KEY_LABEL}={request.idempotency_key}" in create_call
    assert f"{OWNERSHIP_DIGEST_LABEL}={request.ownership_digest}" in create_call
    assert len(runner.volumes) == 2
    for volume in runner.volumes.values():
        assert volume["Labels"][ALLOCATION_ID_LABEL] == request.allocation_id
        assert volume["Labels"][IDEMPOTENCY_KEY_LABEL] == request.idempotency_key
        assert volume["Labels"][OWNERSHIP_DIGEST_LABEL] == request.ownership_digest
    assert (await adapter.inspect(created.provider_ref)).ownership_verified is True


async def test_destroy_verifies_docker_label_before_delegating() -> None:
    adapter, runner = docker_adapter()
    created = await adapter.allocate(allocation_request())
    calls_before = len(runner.calls)

    with pytest.raises(ManagedAdapterOwnershipError, match="ownership"):
        await adapter.destroy(
            created.provider_ref,
            ownership_digest="sha256:other",
        )

    assert not any(call[0] == "rm" for call in runner.calls[calls_before:])
    assert await adapter.inspect(created.provider_ref)


async def test_find_by_idempotency_key_uses_managed_docker_label() -> None:
    adapter, runner = docker_adapter()
    created = await adapter.allocate(allocation_request())

    found = await adapter.find_by_idempotency_key("idem_1")

    assert found is not None
    assert found.provider_ref == created.provider_ref
    assert any(
        f"label={IDEMPOTENCY_KEY_LABEL}=idem_1" in call
        for call in runner.calls
        if call[0] == "ps"
    )


async def test_concurrent_idempotent_allocate_creates_one_container() -> None:
    adapter, runner = docker_adapter()
    request = allocation_request()

    first, second = await asyncio.gather(
        adapter.allocate(request),
        adapter.allocate(request),
    )

    assert first.provider_ref == second.provider_ref
    assert sum(call[0] == "create" for call in runner.calls) == 1


async def test_two_adapters_atomically_share_one_idempotent_allocation() -> None:
    runner = EmulatedDockerRunner()
    providers = [
        DockerSandboxProvider(
            runner=runner,
            config=DockerSandboxConfig(image=IMAGE),
        )
        for _ in range(2)
    ]
    adapters = [DockerShadowManagedAdapter(provider=provider) for provider in providers]
    request = allocation_request()

    first, second = await asyncio.gather(
        adapters[0].allocate(request),
        adapters[1].allocate(request),
    )

    assert first.provider_ref == second.provider_ref
    assert sum(call[0] == "create" for call in runner.calls) == 1


@pytest.mark.parametrize(
    ("resource", "label"),
    [
        ("workspace", ALLOCATION_ID_LABEL),
        ("workspace", IDEMPOTENCY_KEY_LABEL),
        ("workspace", OWNERSHIP_DIGEST_LABEL),
        ("claim", ALLOCATION_ID_LABEL),
        ("claim", IDEMPOTENCY_KEY_LABEL),
        ("claim", OWNERSHIP_DIGEST_LABEL),
    ],
)
async def test_destroy_rejects_managed_metadata_mismatch_on_every_volume(
    resource: str,
    label: str,
) -> None:
    adapter, runner = docker_adapter()
    created = await adapter.allocate(allocation_request())
    workspace_name = f"neos-sandbox-{created.provider_ref}"
    if resource == "workspace":
        volume_name = workspace_name
    else:
        claim_names = [name for name in runner.volumes if name != workspace_name]
        assert len(claim_names) == 1, "allocation claim volume must exist"
        volume_name = claim_names[0]
    runner.volumes[volume_name]["Labels"][label] = "tampered"

    with pytest.raises(ManagedAdapterOwnershipError, match="metadata"):
        await adapter.destroy(
            created.provider_ref,
            ownership_digest=created.ownership_digest,
        )

    assert f"neos-{created.provider_ref}" in runner.containers
    assert workspace_name in runner.volumes
    assert volume_name in runner.volumes


@pytest.mark.parametrize("resource", ["container", "volume"])
async def test_destroy_is_unconfirmed_when_a_resource_remains(
    resource: str,
) -> None:
    adapter, runner = docker_adapter()
    created = await adapter.allocate(allocation_request())
    name = (
        f"neos-{created.provider_ref}"
        if resource == "container"
        else f"neos-sandbox-{created.provider_ref}"
    )
    runner.removal_failures.add((resource, name))

    result = await adapter.destroy(
        created.provider_ref,
        ownership_digest=created.ownership_digest,
    )

    assert result.confirmed is False
    remaining = runner.containers if resource == "container" else runner.volumes
    assert name in remaining


@pytest.mark.parametrize("resource", ["container", "volume", "claim"])
async def test_partial_destroy_can_be_confirmed_on_retry(resource: str) -> None:
    adapter, runner = docker_adapter()
    created = await adapter.allocate(allocation_request())
    workspace_name = f"neos-sandbox-{created.provider_ref}"
    claim_name = next(name for name in runner.volumes if name != workspace_name)
    names = {
        "container": f"neos-{created.provider_ref}",
        "volume": workspace_name,
        "claim": claim_name,
    }
    kinds = {
        "container": "container",
        "volume": "volume",
        "claim": "volume",
    }
    failure = (kinds[resource], names[resource])
    runner.removal_failures.add(failure)

    first = await adapter.destroy(
        created.provider_ref,
        ownership_digest=created.ownership_digest,
    )
    runner.removal_failures.remove(failure)
    second = await adapter.destroy(
        created.provider_ref,
        ownership_digest=created.ownership_digest,
    )

    assert first.confirmed is False
    assert second.confirmed is True
    assert runner.containers == {}
    assert runner.volumes == {}


async def test_confirmed_destroy_removes_container_workspace_and_claim() -> None:
    adapter, runner = docker_adapter()
    created = await adapter.allocate(allocation_request())
    assert len(runner.volumes) == 2

    result = await adapter.destroy(
        created.provider_ref,
        ownership_digest=created.ownership_digest,
    )

    assert result.confirmed is True
    assert runner.containers == {}
    assert runner.volumes == {}


async def test_inspect_rejects_disagreement_with_docker_owner_label() -> None:
    adapter, runner = docker_adapter()
    created = await adapter.allocate(allocation_request())
    document = runner.containers[f"neos-{created.provider_ref}"]
    document["Config"]["Labels"]["com.neos.coding.owner-id"] = "sha256:other"

    with pytest.raises(ManagedAdapterOwnershipError, match="ownership"):
        await adapter.inspect(created.provider_ref)


async def test_health_probes_the_docker_daemon() -> None:
    adapter, runner = docker_adapter()

    probe = await adapter.health("local")

    assert probe.state is ProviderCircuitState.HEALTHY
    assert any(call[0] == "info" for call in runner.calls)


async def test_docker_shadow_never_weakens_network_policy() -> None:
    adapter, runner = docker_adapter(network_mode="bridge")

    assert adapter.capabilities.network_block_all is False
    with pytest.raises(
        ManagedAdapterCapabilityError,
        match="network_block_all",
    ):
        await adapter.allocate(allocation_request())
    assert not any(call[0] == "create" for call in runner.calls)


def test_docker_shadow_uses_only_the_public_provider_surface() -> None:
    """CA5-a 완료 기준.

    shadow가 provider의 private 속성을 읽거나 러너를 갈아끼우면, 관리형 어댑터가
    데이터 플레인 객체를 영구히 변형하는 구조가 된다.
    """
    source = Path(docker_shadow_module.__file__).read_text(encoding="utf-8")

    assert "provider._" not in source
    assert "_ManagedLabelRunner" not in source


async def test_resource_labels_reach_both_the_volume_and_the_container() -> None:
    _adapter, runner = docker_adapter()
    provider = DockerSandboxProvider(
        runner=runner,
        config=DockerSandboxConfig(image=IMAGE, network_mode="none"),
        clock=lambda: datetime(2026, 7, 25, 12, tzinfo=UTC),
    )

    with provider.resource_labels({ALLOCATION_ID_LABEL: "msa_1"}):
        await provider.create(owner_id="owner_1", limits=SandboxLimits.safe_defaults())

    container_create = next(call for call in runner.calls if call[0] == "create")
    volume_create = next(
        call for call in runner.calls if call[:2] == ("volume", "create")
    )
    assert _labels_from_args(container_create)[ALLOCATION_ID_LABEL] == "msa_1"
    assert _labels_from_args(volume_create)[ALLOCATION_ID_LABEL] == "msa_1"


async def test_resource_labels_do_not_leak_outside_the_block() -> None:
    _adapter, runner = docker_adapter()
    provider = DockerSandboxProvider(
        runner=runner,
        config=DockerSandboxConfig(image=IMAGE, network_mode="none"),
        clock=lambda: datetime(2026, 7, 25, 12, tzinfo=UTC),
    )

    with provider.resource_labels({ALLOCATION_ID_LABEL: "msa_1"}):
        pass
    await provider.create(owner_id="owner_1", limits=SandboxLimits.safe_defaults())

    container_create = next(call for call in runner.calls if call[0] == "create")
    assert ALLOCATION_ID_LABEL not in _labels_from_args(container_create)


async def test_a_failed_create_releases_the_claim() -> None:
    """클레임을 이긴 뒤 create 가 실패하면 클레임을 반납해야 한다.

    반납하지 않으면 그 idempotency_key 로 오는 모든 이후 allocate 가 나타나지 않을
    소유자를 기다리다 타임아웃한다 -- 운영자가 볼륨을 지울 때까지 키가 영구히 오염된다.
    """
    adapter, runner = docker_adapter()
    runner.fail_next("create", SandboxError("docker_create_failed"))

    with pytest.raises(SandboxError):
        await adapter.allocate(allocation_request())

    assert runner.volumes == {}

    # 키가 오염되지 않았다: 다음 시도가 정상적으로 성공한다.
    created = await adapter.allocate(allocation_request())
    assert created.state is ManagedSandboxState.ACTIVE


async def test_a_stale_claim_is_reclaimed_instead_of_blocking_forever() -> None:
    """소유자가 죽어 클레임만 남은 경우, 기다리다 포기하지 말고 회수해야 한다."""
    adapter, runner = docker_adapter()
    request = allocation_request()
    runner.seed_orphan_claim(
        adapter._claim_volume_name(request.idempotency_key),
        claimed_at=STALE_CLAIMED_AT,
    )

    created = await adapter.allocate(request)

    assert created.state is ManagedSandboxState.ACTIVE


async def test_a_fresh_orphan_claim_is_not_reclaimed() -> None:
    """`_claim_is_stale`가 무조건 True를 돌려줘도 회수 테스트는 통과한다 --
    이 테스트가 그 위양성을 잡는다. 방금 생긴 클레임은 아직 살아있는 소유자의
    것일 수 있으므로 회수 대상이 아니다: 제네릭 타임아웃으로 끝나야 한다."""
    adapter, runner = docker_adapter(create_timeout_sec=0.05)
    request = allocation_request()
    claim_name = adapter._claim_volume_name(request.idempotency_key)
    runner.seed_orphan_claim(claim_name, claimed_at=datetime.now(UTC).isoformat())

    with pytest.raises(ManagedAdapterTimeoutError):
        await adapter.allocate(request)

    # 회수되지 않았다: 클레임 볼륨이 그대로 남아 있다.
    assert claim_name in runner.volumes


async def test_a_cancelled_create_still_releases_the_claim() -> None:
    """`except BaseException`이 실제로 `CancelledError`도 잡는지 확인한다.

    `SandboxError`(평범한 `Exception`)만으로는 `except Exception`과 구분되지
    않는다 -- `BaseException`을 쓴 이유는 취소도 놓치지 않기 위해서였다."""
    adapter, runner = docker_adapter()
    runner.fail_next("create", asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await adapter.allocate(allocation_request())

    assert runner.volumes == {}


async def test_a_naive_claimed_at_timestamp_does_not_crash_reclaim() -> None:
    """오프셋 없는 ISO 문자열(예전 버전이 남긴 값 등)도 TypeError 없이 처리돼야
    한다 -- 그리고 UTC로 임의 가정해 회수하면 안 된다: UTC 동쪽 지역에서 쓰인
    naive 값을 UTC로 잘못 해석하면 실제보다 오래된 것으로 보여, 아직 살아있는
    소유자의 클레임을 회수할 수 있다. 판단 근거 없음으로 처리해 회수하지
    않고 제네릭 타임아웃으로 끝나야 한다."""
    adapter, runner = docker_adapter(create_timeout_sec=0.05)
    request = allocation_request()
    claim_name = adapter._claim_volume_name(request.idempotency_key)
    runner.seed_orphan_claim(
        claim_name, claimed_at="2020-01-01T00:00:00"
    )  # 오프셋 없음

    with pytest.raises(ManagedAdapterTimeoutError):
        await adapter.allocate(request)

    # 회수되지 않았다 -- 판단 근거가 없어 그대로 남아 있다.
    assert claim_name in runner.volumes


async def test_a_non_string_claimed_at_label_does_not_crash_reclaim() -> None:
    """docker inspect 출력은 shape만 검증되므로 라벨 값이 문자열이 아닐 수도
    있다 -- `fromisoformat`이 TypeError를 올려도 죽지 않고 판단 근거 없음으로
    처리해야 한다(회수하지 않고 제네릭 타임아웃으로 끝난다)."""
    adapter, runner = docker_adapter(create_timeout_sec=0.05)
    request = allocation_request()
    claim_name = adapter._claim_volume_name(request.idempotency_key)
    runner.seed_orphan_claim(claim_name, claimed_at=STALE_CLAIMED_AT)
    runner.volumes[claim_name]["Labels"][CLAIMED_AT_LABEL] = 12345  # 문자열이 아님

    with pytest.raises(ManagedAdapterTimeoutError):
        await adapter.allocate(request)

    assert claim_name in runner.volumes


async def test_a_failed_ownership_publish_still_releases_the_claim() -> None:
    """create()는 성공했지만 소유권 볼륨 발행이 실패해도 클레임은 새야 한다.

    Step 7의 try가 소유권 볼륨 발행 이전에서 끝나면, 그 구간의 실패가 클레임을
    영영 새게 만든다."""
    adapter, runner = docker_adapter()
    request = allocation_request()
    # args[0]=="volume"인 호출 순서: 1=클레임 생성, 2=클레임 inspect,
    # 3=provider.create()의 워크스페이스 생성, 4=소유권 발행 -- 그 4번째만
    # 실패시킨다.
    runner.fail_next(
        "volume",
        SandboxError("ownership_volume_create_failed"),
        occurrence=4,
    )

    with pytest.raises(SandboxError):
        await adapter.allocate(request)

    assert adapter._claim_volume_name(request.idempotency_key) not in runner.volumes


async def test_release_claim_does_not_delete_a_claim_whose_token_changed() -> None:
    """CRITICAL: 다른 프로세스가 이미 회수해 간 클레임을 실수로 지우면 안 된다.

    무조건 이름으로 지우면 그 프로세스의 락을 훔치는 셈이 되어, 같은
    idempotency_key로 컨테이너가 두 개 생기는 사고로 이어진다."""
    adapter, runner = docker_adapter()
    claim_name = "neos-managed-claim-test"
    runner.volumes[claim_name] = {
        "Name": claim_name,
        "Labels": {CLAIM_TOKEN_LABEL: "someone-elses-token"},
    }

    await adapter._release_claim(claim_name, "our-old-token")

    assert claim_name in runner.volumes


async def test_release_claim_deletes_when_the_token_still_matches() -> None:
    adapter, runner = docker_adapter()
    claim_name = "neos-managed-claim-test"
    runner.volumes[claim_name] = {
        "Name": claim_name,
        "Labels": {CLAIM_TOKEN_LABEL: "our-token"},
    }

    await adapter._release_claim(claim_name, "our-token")

    assert claim_name not in runner.volumes


async def test_two_waiters_do_not_both_reclaim_the_same_stale_claim() -> None:
    """finding 1 (round 2): 두 대기자가 같은 죽은 클레임을 동시에 회수하려 하면,
    먼저 회수해 새로 이긴 쪽의 아직 진행 중인(살아있는) 클레임을 나중 쪽이 훔쳐
    지우면 안 된다.

    훔쳐 지우면(이름만 보고 무조건 삭제) 두 프로세스가 각자 컨테이너를 만들어,
    같은 idempotency_key 로 컨테이너가 두 개 생기고 find_by_idempotency_key 가
    idempotency_metadata_not_unique 로 영구히 막힌다.

    asyncio.gather 로만 돌리면 이 사고 창이 에뮬레이터의 우연한 스케줄링으로는
    재현되지 않는다(직접 확인함): 두 대기자 모두 volume 관련 호출에 진짜
    양보점(await asyncio.sleep)이 없어서, 한쪽이 죽은 클레임을 관찰하고 지우기
    시작하면 그 사이 다른 쪽이 끼어들 기회가 없다 -- 그래서 A 가 완전히 끝난
    "뒤"에야 B 가 재확인하게 되어 사고가 나지 않는다(그 경우는 이 테스트가
    잡으려는 것과 다른, 이미 알려진 잔여 창이다).

    사고 창을 실제로 재현하려면 B(두 번째 대기자)가 죽은 토큰을 들고 실제로
    지우려는 순간(`_release_claim` 진입 직전)과, A(첫 번째 대기자)가 클레임을
    이긴 뒤 컨테이너 생성을 실제로 시작하기 직전(`provider.create()` 진입
    직전) 두 지점을 결정적으로 맞물려야 한다: B 를 멈춰 세운 채 A 가 클레임을
    이기게 하고, A 도 멈춰 세운 뒤 B 를 풀어준다 -- 이때 B 가 보는 것은 A 가
    "아직 진행 중인" 살아있는 클레임이다.
    """
    runner = EmulatedDockerRunner()
    providers = [
        DockerSandboxProvider(
            runner=runner,
            config=DockerSandboxConfig(image=IMAGE),
        )
        for _ in range(2)
    ]
    adapters = [DockerShadowManagedAdapter(provider=provider) for provider in providers]
    request = allocation_request()
    runner.seed_orphan_claim(
        adapters[0]._claim_volume_name(request.idempotency_key),
        claimed_at=STALE_CLAIMED_AT,
    )

    b_reached_release = asyncio.Event()
    b_may_release = asyncio.Event()
    a_reached_create = asyncio.Event()
    a_may_create = asyncio.Event()
    original_release_claim = DockerShadowManagedAdapter._release_claim
    original_provider_create = DockerSandboxProvider.create

    async def paused_release_claim(self, claim_name, claim_token):
        if self is adapters[1]:
            b_reached_release.set()
            await b_may_release.wait()
        return await original_release_claim(self, claim_name, claim_token)

    async def paused_provider_create(self, **kwargs):
        if self is providers[0]:
            a_reached_create.set()
            await a_may_create.wait()
        return await original_provider_create(self, **kwargs)

    DockerShadowManagedAdapter._release_claim = paused_release_claim
    DockerSandboxProvider.create = paused_provider_create
    try:
        # B: 죽은 클레임을 관찰하고, 실제로 지우기 직전에 멈춘다.
        task_b = asyncio.create_task(adapters[1].allocate(request))
        await b_reached_release.wait()

        # A: B 가 아직 지우지 않았으므로 A 는 죽은 클레임을 정상적으로 회수하고
        # 자신의 새 토큰으로 이긴다. 컨테이너를 실제로 만들기 직전에 멈춘다 --
        # 이 시점에 A 의 클레임 볼륨은 A 의 새 토큰을 든 채 살아있다.
        task_a = asyncio.create_task(adapters[0].allocate(request))
        await a_reached_create.wait()

        # 이제 두 게이트를 동시에 연다: B 의 CAS 확인이 A 의 (아직 안 끝난)
        # 살아있는 클레임을 보게 하고, A 도 마저 완주하게 한다.
        b_may_release.set()
        a_may_create.set()

        first, second = await asyncio.gather(task_a, task_b)
    finally:
        DockerShadowManagedAdapter._release_claim = original_release_claim
        DockerSandboxProvider.create = original_provider_create

    assert first.provider_ref == second.provider_ref
    assert sum(call[0] == "create" for call in runner.calls) == 1
    # 훔쳐 지우는 사고가 났다면 컨테이너가 두 개 생겨 여기서
    # idempotency_metadata_not_unique 가 올라온다.
    await adapters[0].find_by_idempotency_key(request.idempotency_key)


async def test_managed_adapter_error_during_cleanup_does_not_swallow_the_cancellation() -> (
    None
):
    """IMPORTANT 2 (round 2): 취소 정리 중 docker inspect 출력이 깨져도
    (`ManagedAdapterOwnershipError`, `SandboxError`의 자손이 아님) 원래
    취소(`CancelledError`)가 다른 예외로 치환되면 안 된다."""
    adapter, runner = docker_adapter()
    runner.fail_next("create", asyncio.CancelledError())
    original_run = runner.run
    inspect_calls = 0

    async def corrupt_second_claim_inspect(*args, **kwargs):
        nonlocal inspect_calls
        if args[:2] == ("volume", "inspect"):
            inspect_calls += 1
            # 1번째 inspect = 클레임을 이기는 정상 조회, 2번째 = 취소 정리
            # 중 `_release_claim`이 하는 조회 -- 그것만 깨뜨린다.
            if inspect_calls == 2:
                return DockerCommandResult(0, b"not-json", b"")
        return await original_run(*args, **kwargs)

    runner.run = corrupt_second_claim_inspect

    with pytest.raises(asyncio.CancelledError):
        await adapter.allocate(allocation_request())

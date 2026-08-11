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
        self._pending_failures: dict[str, Exception] = {}

    def fail_next(self, op: str, error: Exception) -> None:
        """다음 `op`(예: `"create"`) 호출에서 정상 처리 대신 `error`를 올린다.

        일회성이다 -- 그 호출을 소비하면 이후 같은 op는 다시 정상 처리된다.
        """
        self._pending_failures[op] = error

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
            raise self._pending_failures.pop(args[0])
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
) -> tuple[DockerShadowManagedAdapter, EmulatedDockerRunner]:
    runner = EmulatedDockerRunner()
    provider = DockerSandboxProvider(
        runner=runner,
        config=DockerSandboxConfig(
            image=IMAGE,
            network_mode=network_mode,
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

import asyncio
from datetime import UTC, datetime
import io
import json
import tarfile

import pytest

from neos.coding.managed.adapters import (
    DockerShadowManagedAdapter,
    ManagedAdapterCapabilityError,
    ManagedAdapterOwnershipError,
)
from neos.coding.managed.adapters.docker_shadow import (
    ALLOCATION_ID_LABEL,
    IDEMPOTENCY_KEY_LABEL,
    OWNERSHIP_DIGEST_LABEL,
)
from neos.coding.managed.domain import ProviderCircuitState
from neos.coding.sandbox.command import DockerCommandResult
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

    async def run(
        self,
        *args: str,
        timeout_sec: float,
        allowed_exit_codes=(0,),
        input: bytes = b"",
    ) -> DockerCommandResult:
        del timeout_sec, allowed_exit_codes, input
        self.calls.append(args)
        if args[0] == "create":
            name = args[args.index("--name") + 1]
            labels = {
                args[index + 1].split("=", 1)[0]: args[index + 1].split("=", 1)[1]
                for index, value in enumerate(args)
                if value == "--label"
            }
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
            self.containers.pop(args[-1], None)
        elif args[0] == "inspect":
            values = []
            for reference in args[1:]:
                value = self.containers.get(reference)
                if value is None:
                    value = next(
                        item
                        for item in self.containers.values()
                        if item["Id"] == reference
                    )
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

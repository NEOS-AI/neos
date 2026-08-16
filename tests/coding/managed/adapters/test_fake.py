from dataclasses import FrozenInstanceError, fields

import pytest

from neos.coding.managed.adapters import (
    CreateThenTimeout,
    FakeManagedSandboxAdapter,
    ManagedAdapterCapabilityError,
    ManagedAdapterOwnershipError,
    ManagedAdapterTimeoutError,
    ManagedAdapterValidationError,
    ManagedAllocationRequest,
    ManagedNetworkPolicy,
)
from neos.coding.managed.domain import ManagedSandboxCapabilities
from tests.coding.managed.adapters.conformance import (
    allocation_request,
    assert_managed_adapter_conformance,
)

pytestmark = pytest.mark.no_db


async def test_fake_passes_managed_adapter_conformance() -> None:
    adapter = FakeManagedSandboxAdapter()

    await assert_managed_adapter_conformance(adapter)

    assert [call.operation for call in adapter.calls] == [
        "allocate",
        "allocate",
        "find_by_idempotency_key",
        "inspect",
        "suspend",
        "resume",
        "destroy",
    ]


async def test_create_succeeded_then_timed_out_is_rediscoverable() -> None:
    adapter = FakeManagedSandboxAdapter(allocate_fault=CreateThenTimeout())
    request = allocation_request()

    with pytest.raises(CreateThenTimeout):
        await adapter.allocate(request)

    discovered = await adapter.find_by_idempotency_key(request.idempotency_key)
    assert discovered is not None
    assert discovered.allocation_id == request.allocation_id
    assert adapter.allocate_calls == 1
    assert adapter.rediscovery_calls == 1


async def test_injected_typed_fault_is_raised_once() -> None:
    adapter = FakeManagedSandboxAdapter(
        faults={"inspect": ManagedAdapterTimeoutError("inspect_timeout")}
    )
    created = await adapter.allocate(allocation_request())

    with pytest.raises(ManagedAdapterTimeoutError, match="inspect_timeout"):
        await adapter.inspect(created.provider_ref)

    assert (await adapter.inspect(created.provider_ref)).provider_ref == (
        created.provider_ref
    )


async def test_fake_rejects_unsupported_capability() -> None:
    adapter = FakeManagedSandboxAdapter(
        capabilities=ManagedSandboxCapabilities(
            pause_resume=False,
            filesystem_snapshot=False,
            memory_snapshot=False,
            portable_archive=False,
            network_block_all=True,
            network_allowlist=False,
            region_pin=True,
            idempotent_allocate=True,
            metadata_rediscovery=True,
        )
    )
    created = await adapter.allocate(allocation_request())

    with pytest.raises(ManagedAdapterCapabilityError, match="pause_resume"):
        await adapter.suspend(created.provider_ref)
    with pytest.raises(
        ManagedAdapterCapabilityError,
        match="filesystem_snapshot",
    ):
        await adapter.snapshot(created.provider_ref)


async def test_network_policy_requires_declared_block_capability() -> None:
    adapter = FakeManagedSandboxAdapter(
        capabilities=ManagedSandboxCapabilities(
            pause_resume=True,
            filesystem_snapshot=True,
            memory_snapshot=False,
            portable_archive=True,
            network_block_all=False,
            network_allowlist=False,
            region_pin=True,
            idempotent_allocate=True,
            metadata_rediscovery=True,
        )
    )

    with pytest.raises(
        ManagedAdapterCapabilityError,
        match="network_block_all",
    ):
        await adapter.allocate(allocation_request())


async def test_allowlist_policy_requires_allowlist_capability() -> None:
    adapter = FakeManagedSandboxAdapter()

    with pytest.raises(
        ManagedAdapterCapabilityError,
        match="network_allowlist",
    ):
        await adapter.allocate(
            allocation_request(
                network_policy=ManagedNetworkPolicy.ALLOWLIST,
            )
        )


async def test_destroy_rejects_ownership_mismatch_without_deleting() -> None:
    adapter = FakeManagedSandboxAdapter()
    created = await adapter.allocate(allocation_request())

    with pytest.raises(ManagedAdapterOwnershipError, match="ownership"):
        await adapter.destroy(
            created.provider_ref,
            ownership_digest="sha256:other",
        )

    assert await adapter.inspect(created.provider_ref)


def test_request_and_result_contracts_are_frozen_and_bounded() -> None:
    request = allocation_request()
    names = {field.name for field in fields(ManagedAllocationRequest)}

    assert names == {
        "allocation_id",
        "idempotency_key",
        "region",
        "image_identity",
        "resource_limits",
        "network_policy",
        "ownership_digest",
        "absolute_expires_at",
    }
    assert "repository" not in names
    assert "credential" not in names
    assert "prompt" not in names
    with pytest.raises(FrozenInstanceError):
        request.region = "other"


def test_request_rejects_untyped_network_policy() -> None:
    values = {
        field.name: getattr(allocation_request(), field.name)
        for field in fields(ManagedAllocationRequest)
    }
    values["network_policy"] = "block_all"

    with pytest.raises(ManagedAdapterValidationError, match="network_policy"):
        ManagedAllocationRequest(**values)

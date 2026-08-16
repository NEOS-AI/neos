from datetime import UTC, datetime, timedelta

from neos.coding.managed.adapters import (
    ManagedAllocationRequest,
    ManagedNetworkPolicy,
)
from neos.coding.managed.domain import ManagedSandboxState
from neos.coding.sandbox.base import SandboxLimits


NOW = datetime(2026, 7, 25, 12, tzinfo=UTC)
IMAGE = "neos-sandbox@sha256:" + "a" * 64


def allocation_request(
    idempotency_key: str = "idem_1",
    *,
    network_policy: ManagedNetworkPolicy = ManagedNetworkPolicy.BLOCK_ALL,
) -> ManagedAllocationRequest:
    return ManagedAllocationRequest(
        allocation_id="msa_1",
        idempotency_key=idempotency_key,
        region="local",
        image_identity=IMAGE,
        resource_limits=SandboxLimits.safe_defaults(),
        network_policy=network_policy,
        ownership_digest="sha256:owner",
        absolute_expires_at=NOW + timedelta(hours=4),
    )


async def assert_managed_adapter_conformance(adapter) -> None:
    request = allocation_request(idempotency_key="idem_1")
    created = await adapter.allocate(request)
    replay = await adapter.allocate(request)
    assert replay.provider_ref == created.provider_ref
    assert created.state is ManagedSandboxState.ACTIVE
    assert await adapter.find_by_idempotency_key("idem_1") == (
        await adapter.inspect(created.provider_ref)
    )
    suspended = await adapter.suspend(created.provider_ref)
    assert suspended.state is ManagedSandboxState.SUSPENDED
    resumed = await adapter.resume(created.provider_ref)
    assert resumed.state is ManagedSandboxState.ACTIVE
    destroyed = await adapter.destroy(
        created.provider_ref,
        ownership_digest=created.ownership_digest,
    )
    assert destroyed.confirmed is True
    assert destroyed.ownership_verified is True

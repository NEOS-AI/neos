"""Ownership and placement checks shared by the allocation adapter and the provider.

두 곳이 같은 대조를 각자 들고 있으면 언젠가 갈라진다. vendor object 는 다음을
**전부** 만족할 때만 NEOS 것이다.

1. 할당 층: `neos_allocation_id` 가 runtime 의 allocation 이고,
   `neos_ownership_digest` 가 그 할당의 레거시 digest 다
   (`neos.coding.managed.allocation.legacy_ownership_digest`).
2. 물리 층: `neos_sandbox_id` / `neos_incarnation` / `neos_idempotency_key` 가
   원장의 physical 행과 같고, `neos_coding_ownership` 이 키 있는 HMAC 과 같다.

레거시 digest 는 키가 없어 metadata 를 쓸 수 있는 누구나 다시 계산할 수 있다.
그래서 혼자서는 증거가 아니다 -- HMAC 이 같이 맞아야 한다.
"""

from __future__ import annotations

from neos.coding.managed.allocation import legacy_ownership_digest
from neos.coding.sandbox.base import SandboxUnavailable
from neos.coding.sandbox.managed.clients.base import (
    ProviderSandboxInfo,
    ProviderSandboxStatus,
)
from neos.coding.sandbox.managed.identity import (
    METADATA_ALLOCATION_ID,
    METADATA_CODING_OWNERSHIP,
    METADATA_IDEMPOTENCY_KEY,
    METADATA_INCARNATION,
    METADATA_OWNERSHIP_DIGEST,
    METADATA_SANDBOX_ID,
    ManagedCodingIdentity,
    PhysicalIdentity,
)
from neos.coding.sandbox.managed.ledger import RuntimeRecord
from neos.coding.sandbox.managed.profiles import get_profile, verify_applied_network


class OwnershipMismatch(SandboxUnavailable):
    def __init__(self) -> None:
        super().__init__("managed_ownership_mismatch")


def physical_identity(runtime: RuntimeRecord, incarnation: int) -> PhysicalIdentity:
    return PhysicalIdentity(
        tenant_id=runtime.tenant_id,
        task_id=runtime.task_id,
        allocation_id=runtime.allocation_id,
        allocation_generation=runtime.allocation_generation,
        sandbox_id=runtime.sandbox_id,
        incarnation=incarnation,
        profile=runtime.profile,
        image_digest=runtime.image_digest,
        region=runtime.region,
        expires_at=runtime.expires_at,
    )


def legacy_digest(runtime: RuntimeRecord) -> str:
    return legacy_ownership_digest(
        tenant_id=runtime.tenant_id, allocation_id=runtime.allocation_id
    )


def is_owned(
    identity: ManagedCodingIdentity,
    runtime: RuntimeRecord,
    *,
    incarnation: int,
    idempotency_key: str,
    info: ProviderSandboxInfo,
) -> bool:
    metadata = info.metadata
    return (
        metadata.get(METADATA_ALLOCATION_ID) == runtime.allocation_id
        and metadata.get(METADATA_OWNERSHIP_DIGEST) == legacy_digest(runtime)
        and metadata.get(METADATA_SANDBOX_ID) == runtime.sandbox_id
        and metadata.get(METADATA_INCARNATION) == str(incarnation)
        and metadata.get(METADATA_IDEMPOTENCY_KEY) == idempotency_key
        and identity.verify_physical(
            metadata.get(METADATA_CODING_OWNERSHIP),
            physical_identity(runtime, incarnation),
        )
    )


def verify_owned(
    identity: ManagedCodingIdentity,
    runtime: RuntimeRecord,
    *,
    incarnation: int,
    idempotency_key: str,
    info: ProviderSandboxInfo,
) -> None:
    if not is_owned(
        identity,
        runtime,
        incarnation=incarnation,
        idempotency_key=idempotency_key,
        info=info,
    ):
        raise OwnershipMismatch()


def verify_placement(runtime: RuntimeRecord, info: ProviderSandboxInfo) -> None:
    """Network read-back equals the profile, region is provable, object runs."""
    verify_applied_network(get_profile(runtime.profile), info.network)
    if info.region is None:
        raise SandboxUnavailable("managed_region_unverifiable")
    if info.region != runtime.region:
        raise SandboxUnavailable("managed_region_mismatch")
    if info.status is not ProviderSandboxStatus.RUNNING:
        raise SandboxUnavailable(f"managed_provider_not_running:{info.status.value}")

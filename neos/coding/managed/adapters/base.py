from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from neos.coding.managed.domain import (
    ManagedSandboxCapabilities,
    ManagedSandboxState,
    ProviderCircuitState,
    ProviderErrorCode,
)
from neos.coding.sandbox.base import SandboxLimits


class ManagedNetworkPolicy(StrEnum):
    BLOCK_ALL = "block_all"
    ALLOWLIST = "allowlist"


class ManagedAdapterError(RuntimeError):
    """Base class for bounded, provider-independent adapter failures."""


class ManagedAdapterValidationError(ManagedAdapterError):
    """The request cannot be honored without changing its meaning."""


class ManagedAdapterCapabilityError(ManagedAdapterValidationError):
    """The selected provider does not support a requested capability."""


class ManagedAdapterOwnershipError(ManagedAdapterError):
    """Provider metadata does not prove ownership of the resource."""


class ManagedAdapterNotFoundError(ManagedAdapterError):
    """The provider resource does not exist."""


class ManagedAdapterTimeoutError(ManagedAdapterError, TimeoutError):
    """The provider operation had an ambiguous timeout outcome."""


class CreateSucceededThenTimedOut(ManagedAdapterTimeoutError):
    """Deterministic fault representing an ambiguous successful create."""

    def __init__(self) -> None:
        super().__init__("allocate_timed_out_after_create")


CreateThenTimeout = CreateSucceededThenTimedOut


@dataclass(frozen=True, slots=True)
class ManagedAllocationRequest:
    allocation_id: str
    idempotency_key: str
    region: str
    image_identity: str
    resource_limits: SandboxLimits
    network_policy: ManagedNetworkPolicy
    ownership_digest: str
    absolute_expires_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "allocation_id",
            "idempotency_key",
            "region",
            "image_identity",
            "ownership_digest",
        ):
            if not getattr(self, name):
                raise ManagedAdapterValidationError(f"{name} must not be empty")
        if not isinstance(self.network_policy, ManagedNetworkPolicy):
            raise ManagedAdapterValidationError(
                "network_policy must be a ManagedNetworkPolicy"
            )
        if (
            self.absolute_expires_at.tzinfo is None
            or self.absolute_expires_at.utcoffset() is None
        ):
            raise ManagedAdapterValidationError(
                "absolute_expires_at must be timezone-aware"
            )


@dataclass(frozen=True, slots=True)
class AllocationResult:
    provider_ref: str
    ownership_digest: str
    state: ManagedSandboxState


@dataclass(frozen=True, slots=True)
class ProviderSandboxState:
    provider_ref: str
    allocation_id: str
    idempotency_key: str
    state: ManagedSandboxState
    ownership_digest: str
    ownership_verified: bool


@dataclass(frozen=True, slots=True)
class LifecycleResult:
    provider_ref: str
    state: ManagedSandboxState


@dataclass(frozen=True, slots=True)
class SnapshotResult:
    provider_ref: str
    snapshot_ref: str
    state: ManagedSandboxState


@dataclass(frozen=True, slots=True)
class DestroyResult:
    confirmed: bool
    not_found: bool = False
    ownership_verified: bool = False


@dataclass(frozen=True, slots=True)
class ProviderHealthProbe:
    provider: str
    region: str
    state: ProviderCircuitState
    error_code: ProviderErrorCode | None = None


@runtime_checkable
class ManagedSandboxAdapter(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def capabilities(self) -> ManagedSandboxCapabilities: ...

    async def allocate(
        self,
        request: ManagedAllocationRequest,
    ) -> AllocationResult: ...

    async def inspect(self, provider_ref: str) -> ProviderSandboxState: ...

    async def suspend(self, provider_ref: str) -> LifecycleResult: ...

    async def resume(self, provider_ref: str) -> LifecycleResult: ...

    async def snapshot(self, provider_ref: str) -> SnapshotResult: ...

    async def destroy(
        self,
        provider_ref: str,
        *,
        ownership_digest: str,
    ) -> DestroyResult: ...

    async def find_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> ProviderSandboxState | None: ...

    async def health(self, region: str) -> ProviderHealthProbe: ...


def require_capability(
    capabilities: ManagedSandboxCapabilities,
    name: str,
) -> None:
    if not getattr(capabilities, name):
        raise ManagedAdapterCapabilityError(f"{name} is not supported")


def validate_network_policy(
    capabilities: ManagedSandboxCapabilities,
    network_policy: ManagedNetworkPolicy,
) -> None:
    if network_policy is ManagedNetworkPolicy.BLOCK_ALL:
        require_capability(capabilities, "network_block_all")
    elif network_policy is ManagedNetworkPolicy.ALLOWLIST:
        require_capability(capabilities, "network_allowlist")

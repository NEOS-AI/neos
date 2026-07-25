from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from neos.coding.managed.domain import (
    AdmissionDecision,
    AdmissionReason,
    ProviderCircuitState,
)
from neos.config.schema import ManagedSandboxConfig


@dataclass(frozen=True, slots=True)
class AdmissionRequest:
    tenant_id: str
    task_id: str
    run_id: str
    repository_organization: str
    provider: str
    region: str
    required_capabilities: frozenset[str]
    idempotency_key: str
    estimated_active_seconds: int
    estimated_archive_bytes: int
    estimated_cost_micros: int

    def __post_init__(self) -> None:
        for name in (
            "tenant_id",
            "task_id",
            "run_id",
            "repository_organization",
            "provider",
            "region",
            "idempotency_key",
        ):
            if not getattr(self, name):
                raise ValueError(f"{name} must not be empty")
        for name in (
            "estimated_active_seconds",
            "estimated_archive_bytes",
            "estimated_cost_micros",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")


@dataclass(frozen=True, slots=True)
class AdmissionResult:
    admission_id: str
    allocation_id: str | None
    decision: AdmissionDecision
    reason: AdmissionReason
    reevaluate_after: datetime | None
    created: bool


class AdmissionRepository(Protocol):
    async def admit(
        self,
        request: AdmissionRequest,
        *,
        decision: AdmissionDecision,
        reason: AdmissionReason,
        now: datetime,
        reevaluate_after: datetime | None,
        reservation_expires_at: datetime | None,
        concurrent_quota: int,
        daily_quota: int,
        daily_active_seconds_quota: int,
        archive_bytes_quota: int,
        daily_cost_micros_quota: int,
    ) -> AdmissionResult: ...


class AdmissionPolicy(Protocol):
    version: str

    def allows_tenant(self, tenant_id: str) -> bool: ...

    def allows_repository(self, organization: str) -> bool: ...

    def provider_capabilities(self, provider: str) -> frozenset[str]: ...

    def allows_region(self, provider: str, region: str) -> bool: ...


class ProviderHealth(Protocol):
    def state(self, provider: str, region: str) -> Awaitable[ProviderCircuitState]: ...


class ManagedSandboxAdmissionService:
    def __init__(
        self,
        *,
        repository: AdmissionRepository,
        policy: AdmissionPolicy,
        health: ProviderHealth,
        config: ManagedSandboxConfig,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._policy = policy
        self._health = health
        self._config = config
        self._clock = clock or (lambda: datetime.now(UTC))

    async def admit(self, request: AdmissionRequest) -> AdmissionResult:
        now = self._clock()
        _require_timezone_aware("admission time", now)
        decision, reason = await self._evaluate(request)
        admitted = decision is AdmissionDecision.ADMITTED
        return await self._repository.admit(
            request,
            decision=decision,
            reason=reason,
            now=now,
            reevaluate_after=(
                None
                if admitted
                else now
                + timedelta(seconds=self._config.admission_reevaluation_seconds)
            ),
            reservation_expires_at=(
                now + timedelta(seconds=self._config.reservation_lease_seconds)
                if admitted
                else None
            ),
            concurrent_quota=self._config.concurrent_quota,
            daily_quota=self._config.daily_allocation_quota,
            daily_active_seconds_quota=self._config.daily_active_seconds_quota,
            archive_bytes_quota=self._config.archive_bytes_quota,
            daily_cost_micros_quota=self._config.daily_cost_micros_quota,
        )

    async def _evaluate(
        self, request: AdmissionRequest
    ) -> tuple[AdmissionDecision, AdmissionReason]:
        if not self._config.enabled or self._config.global_kill_switch:
            return AdmissionDecision.DENIED, AdmissionReason.KILL_SWITCH
        if not self._policy.allows_tenant(request.tenant_id):
            return (
                AdmissionDecision.DENIED,
                AdmissionReason.TENANT_NOT_ALLOWED,
            )
        if not self._policy.allows_repository(request.repository_organization):
            return (
                AdmissionDecision.DENIED,
                AdmissionReason.REPOSITORY_NOT_ALLOWED,
            )
        health = await self._health.state(request.provider, request.region)
        if health is ProviderCircuitState.UNAVAILABLE:
            return (
                AdmissionDecision.DENIED,
                AdmissionReason.PROVIDER_UNAVAILABLE,
            )
        if health is ProviderCircuitState.DEGRADED:
            return (
                AdmissionDecision.DENIED,
                AdmissionReason.PROVIDER_DEGRADED,
            )
        if not self._policy.allows_region(request.provider, request.region):
            return (
                AdmissionDecision.DENIED,
                AdmissionReason.REGION_UNAVAILABLE,
            )
        available = self._policy.provider_capabilities(request.provider)
        if not request.required_capabilities.issubset(available):
            return (
                AdmissionDecision.DENIED,
                AdmissionReason.PROVIDER_UNAVAILABLE,
            )
        return AdmissionDecision.ADMITTED, AdmissionReason.ALLOWED


def _require_timezone_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")

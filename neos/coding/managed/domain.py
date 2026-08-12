from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum


class AdmissionDecision(StrEnum):
    ADMITTED = "admitted"
    DENIED = "denied"


class AdmissionReason(StrEnum):
    ALLOWED = "allowed"
    KILL_SWITCH = "kill_switch"
    TENANT_NOT_ALLOWED = "tenant_not_allowed"
    REPOSITORY_NOT_ALLOWED = "repository_not_allowed"
    QUOTA_EXCEEDED = "quota_exceeded"
    BUDGET_EXCEEDED = "budget_exceeded"
    PROVIDER_DEGRADED = "provider_degraded"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    REGION_UNAVAILABLE = "region_unavailable"


class ManagedSandboxState(StrEnum):
    REQUESTED = "requested"
    ADMITTED = "admitted"
    ALLOCATING = "allocating"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    RECOVERY_PENDING = "recovery_pending"
    MANUAL_RECOVERY_REQUIRED = "manual_recovery_required"
    CLEANUP_PENDING = "cleanup_pending"
    CLEANUP_RETRY = "cleanup_retry"
    CLEANED = "cleaned"
    FAILED = "failed"


class ProviderCircuitState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class ProviderErrorCode(StrEnum):
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_RATE_LIMITED = "provider_rate_limited"
    PROVIDER_SERVER_ERROR = "provider_server_error"
    PROVIDER_AUTH_ERROR = "provider_auth_error"
    PROVIDER_CAPACITY = "provider_capacity"
    PROVIDER_NOT_FOUND = "provider_not_found"
    QUOTA_EXCEEDED = "quota_exceeded"
    POLICY_DENIED = "policy_denied"
    CLEANUP_UNCONFIRMED = "cleanup_unconfirmed"
    ARCHIVE_INVALID = "archive_invalid"
    OTHER = "other"


class InvalidManagedSandboxTransition(ValueError):
    """Raised when a managed sandbox lifecycle edge is not allowed."""


@dataclass(frozen=True, slots=True)
class ManagedSandboxCapabilities:
    pause_resume: bool
    filesystem_snapshot: bool
    memory_snapshot: bool
    portable_archive: bool
    network_block_all: bool
    network_allowlist: bool
    region_pin: bool
    idempotent_allocate: bool
    metadata_rediscovery: bool


@dataclass(frozen=True, slots=True)
class ManagedSandboxAllocation:
    allocation_id: str
    tenant_id: str
    task_id: str
    run_id: str
    provider: str
    region: str
    provider_ref: str | None
    ownership_digest: str | None
    state: ManagedSandboxState
    generation: int
    fencing_token: int
    lease_expires_at: datetime | None
    absolute_expires_at: datetime
    version: int
    error_code: ProviderErrorCode | None
    snapshot_ref: str | None
    archive_ref: str | None
    image_identity: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("generation", self.generation),
            ("fencing token", self.fencing_token),
            ("version", self.version),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        _require_timezone_aware("absolute expiry", self.absolute_expires_at)
        if self.lease_expires_at is not None:
            _require_timezone_aware("lease expiry", self.lease_expires_at)
            if self.lease_expires_at > self.absolute_expires_at:
                raise ValueError("lease expiry cannot exceed absolute expiry")
        if self.state is ManagedSandboxState.CLEANED and any(
            (
                self.provider_ref is not None,
                self.ownership_digest is not None,
                self.lease_expires_at is not None,
            )
        ):
            raise ValueError("cleaned allocation cannot retain provider references or lease")

    def claimable_at(self, now: datetime) -> bool:
        _require_timezone_aware("claim time", now)
        return (
            self.state
            in {
                ManagedSandboxState.ADMITTED,
                ManagedSandboxState.RECOVERY_PENDING,
                ManagedSandboxState.CLEANUP_PENDING,
                ManagedSandboxState.CLEANUP_RETRY,
            }
            and (self.lease_expires_at is None or self.lease_expires_at <= now)
            and now < self.absolute_expires_at
        )


def _require_timezone_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


_ALLOWED_ALLOCATION_TRANSITIONS: dict[
    ManagedSandboxState, frozenset[ManagedSandboxState]
] = {
    ManagedSandboxState.REQUESTED: frozenset({ManagedSandboxState.ADMITTED}),
    ManagedSandboxState.ADMITTED: frozenset({ManagedSandboxState.ALLOCATING}),
    ManagedSandboxState.ALLOCATING: frozenset(
        {
            ManagedSandboxState.ACTIVE,
            ManagedSandboxState.RECOVERY_PENDING,
            ManagedSandboxState.FAILED,
        }
    ),
    ManagedSandboxState.ACTIVE: frozenset(
        {
            ManagedSandboxState.SUSPENDED,
            ManagedSandboxState.RECOVERY_PENDING,
            ManagedSandboxState.CLEANUP_PENDING,
        }
    ),
    ManagedSandboxState.SUSPENDED: frozenset(
        {
            ManagedSandboxState.ACTIVE,
            ManagedSandboxState.MANUAL_RECOVERY_REQUIRED,
            ManagedSandboxState.CLEANUP_PENDING,
        }
    ),
    ManagedSandboxState.RECOVERY_PENDING: frozenset(
        {
            ManagedSandboxState.ACTIVE,
            ManagedSandboxState.SUSPENDED,
            ManagedSandboxState.ALLOCATING,
            ManagedSandboxState.MANUAL_RECOVERY_REQUIRED,
        }
    ),
    ManagedSandboxState.MANUAL_RECOVERY_REQUIRED: frozenset(),
    ManagedSandboxState.CLEANUP_PENDING: frozenset(
        {ManagedSandboxState.CLEANED, ManagedSandboxState.CLEANUP_RETRY}
    ),
    ManagedSandboxState.CLEANUP_RETRY: frozenset(
        {ManagedSandboxState.CLEANED, ManagedSandboxState.CLEANUP_RETRY}
    ),
    ManagedSandboxState.CLEANED: frozenset(),
    ManagedSandboxState.FAILED: frozenset(),
}


def transition_allocation(
    allocation: ManagedSandboxAllocation,
    target: ManagedSandboxState,
    *,
    now: datetime,
    error_code: ProviderErrorCode | None = None,
) -> ManagedSandboxAllocation:
    _require_timezone_aware("transition time", now)
    if target not in _ALLOWED_ALLOCATION_TRANSITIONS[allocation.state]:
        raise InvalidManagedSandboxTransition(
            f"{allocation.state.value}->{target.value}"
        )
    changes: dict[str, object] = {
        "state": target,
        "version": allocation.version + 1,
        "error_code": error_code,
    }
    if target is ManagedSandboxState.CLEANED:
        changes.update(
            provider_ref=None,
            ownership_digest=None,
            lease_expires_at=None,
        )
    return replace(
        allocation,
        **changes,
    )

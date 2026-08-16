from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from neos.coding.managed.domain import (
    InvalidManagedSandboxTransition,
    ManagedSandboxAllocation,
    ManagedSandboxCapabilities,
    ManagedSandboxState,
    ProviderErrorCode,
    transition_allocation,
)


NOW = datetime(2026, 7, 25, tzinfo=UTC)


def allocation(**changes: object) -> ManagedSandboxAllocation:
    values: dict[str, object] = {
        "allocation_id": "msa_1",
        "tenant_id": "tenant_1",
        "task_id": "ct_1",
        "run_id": "cr_1",
        "provider": "fake",
        "region": "local",
        "provider_ref": None,
        "ownership_digest": None,
        "state": ManagedSandboxState.ADMITTED,
        "generation": 1,
        "fencing_token": 3,
        "lease_expires_at": NOW + timedelta(minutes=1),
        "absolute_expires_at": NOW + timedelta(hours=4),
        "version": 1,
        "error_code": None,
        "snapshot_ref": None,
        "archive_ref": None,
    }
    values.update(changes)
    return ManagedSandboxAllocation(**values)  # type: ignore[arg-type]


def test_nonterminal_allocation_requires_live_lease_and_fence() -> None:
    assert allocation().claimable_at(NOW) is False


def test_cleaned_allocation_cannot_retain_provider_ref() -> None:
    with pytest.raises(ValueError, match="cleaned allocation"):
        allocation(
            provider_ref="encrypted:ref",
            ownership_digest="sha256:owner",
            state=ManagedSandboxState.CLEANED,
            lease_expires_at=None,
            absolute_expires_at=NOW,
            version=2,
            error_code=ProviderErrorCode.PROVIDER_NOT_FOUND,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("generation", 0), ("fencing_token", 0), ("version", 0)],
)
def test_allocation_rejects_nonpositive_concurrency_identifiers(
    field: str, value: int
) -> None:
    with pytest.raises(ValueError, match="positive"):
        allocation(**{field: value})


def test_allocation_rejects_naive_deadlines() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        allocation(lease_expires_at=datetime(2026, 7, 25, 12))


def test_transition_increments_version_and_clears_cleaned_references() -> None:
    pending = allocation(
        state=ManagedSandboxState.CLEANUP_PENDING,
        provider_ref="encrypted:ref",
        ownership_digest="sha256:owner",
    )

    cleaned = transition_allocation(
        pending,
        ManagedSandboxState.CLEANED,
        now=NOW,
        error_code=ProviderErrorCode.PROVIDER_NOT_FOUND,
    )

    assert cleaned.state is ManagedSandboxState.CLEANED
    assert cleaned.version == 2
    assert cleaned.provider_ref is None
    assert cleaned.ownership_digest is None
    assert cleaned.lease_expires_at is None
    assert cleaned.error_code is ProviderErrorCode.PROVIDER_NOT_FOUND


def test_transition_rejects_edges_outside_lifecycle_graph() -> None:
    with pytest.raises(InvalidManagedSandboxTransition, match="admitted->active"):
        transition_allocation(
            allocation(), ManagedSandboxState.ACTIVE, now=NOW
        )


def test_domain_values_are_immutable() -> None:
    capabilities = ManagedSandboxCapabilities(
        pause_resume=True,
        filesystem_snapshot=True,
        memory_snapshot=False,
        portable_archive=True,
        network_block_all=True,
        network_allowlist=False,
        region_pin=True,
        idempotent_allocate=True,
        metadata_rediscovery=True,
    )

    with pytest.raises(FrozenInstanceError):
        capabilities.pause_resume = False

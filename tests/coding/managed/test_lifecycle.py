"""`ManagedSandboxLifecycleReconciler`·`ManagedSandboxCleanupService` 테스트.

DB를 쓰지 않는다 -- 이 파일이 검증하는 것은 **무엇을 정리 대상으로 고르고,
provider 응답을 어떤 상태로 옮기며, 다음 시도를 언제로 잡는가**이지 SQL이
아니다. SQL·원자성은 `integration/test_postgres_lifecycle.py`가 본다
(`test_allocation_service.py`가 Task 5에서 세운 것과 같은 분업이다).
"""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import pytest

from neos.coding.managed.adapters import (
    DestroyResult,
    FakeManagedSandboxAdapter,
    ManagedAdapterNotFoundError,
    ManagedAdapterTimeoutError,
)
from neos.coding.managed.allocation import (
    ManagedAllocationLease,
    ManagedSandboxNotClaimable,
)
from neos.coding.managed.domain import (
    _ALLOWED_ALLOCATION_TRANSITIONS,
    ManagedSandboxAllocation,
    ManagedSandboxState,
    ProviderErrorCode,
)
from neos.coding.managed.lifecycle import (
    CleanupAttemptOutcome,
    CleanupCandidate,
    LifecycleCandidates,
    ManagedSandboxCleanupService,
    ManagedSandboxLifecycleReconciler,
    StaleManagedSandboxGeneration,
    _CLEANABLE_STATES,
    _CLEANUP_SOURCE_STATES,
    next_retry_at,
)


NOW = datetime(2026, 8, 22, 12, tzinfo=UTC)
_BACKOFF = (5, 15, 45, 120, 300)
_LEASE_SECONDS = 120
_OWNERSHIP_DIGEST = "sha256:" + "c" * 64
_PROVIDER_REF = "fake_msa_1"


def _active_allocation(**overrides) -> ManagedSandboxAllocation:
    allocation = ManagedSandboxAllocation(
        allocation_id="msa_1",
        tenant_id="tenant_1",
        task_id="task_1",
        run_id="run_1",
        provider="fake",
        region="local",
        provider_ref=_PROVIDER_REF.encode(),
        ownership_digest=_OWNERSHIP_DIGEST,
        state=ManagedSandboxState.CLEANUP_PENDING,
        generation=1,
        fencing_token=1,
        lease_expires_at=None,
        absolute_expires_at=NOW + timedelta(hours=4),
        version=1,
        error_code=None,
        snapshot_ref=None,
        archive_ref=None,
        image_identity="neos-sandbox@sha256:" + "b" * 64,
    )
    return replace(allocation, **overrides) if overrides else allocation


@dataclass(frozen=True, slots=True)
class _IdentityCipher:
    """봉인 없이 계약만 지키는 테스트 전용 cipher (Task 5와 같은 것)."""

    def encrypt(self, value: str) -> bytes:
        return value.encode()

    def decrypt(self, value: bytes) -> str:
        return value.decode()


class FakeLifecycleRepository:
    """claim/read/commit 계약만 흉내 내는 인메모리 repository."""

    def __init__(self, allocation: ManagedSandboxAllocation) -> None:
        self.allocation = allocation
        self.attempts: list[dict] = []
        self.candidates = LifecycleCandidates(cleanup=(), recovery=())
        self.discovery_calls: list[tuple[datetime, int]] = []
        self._token = allocation.fencing_token

    async def discover_lifecycle_candidates(
        self, *, now: datetime, limit: int
    ) -> LifecycleCandidates:
        self.discovery_calls.append((now, limit))
        return self.candidates

    async def claim_allocation(
        self, allocation_id: str, worker_id: str, *, now: datetime, lease_seconds: int
    ) -> ManagedAllocationLease:
        if not self.allocation.claimable_at(now):
            raise ManagedSandboxNotClaimable(allocation_id)
        self._token += 1
        self.allocation = replace(self.allocation, fencing_token=self._token)
        return ManagedAllocationLease(
            allocation_id=allocation_id,
            worker_id=worker_id,
            fencing_token=self._token,
            expires_at=now + timedelta(seconds=lease_seconds),
        )

    async def read_allocation(self, allocation_id: str) -> ManagedSandboxAllocation:
        return self.allocation

    async def cleanup_attempt_count(self, allocation_id: str) -> int:
        return len(self.attempts)

    async def commit_cleanup_outcome(
        self,
        lease: ManagedAllocationLease,
        *,
        target: ManagedSandboxState,
        outcome: CleanupAttemptOutcome,
        error_code: ProviderErrorCode | None,
        retry_at: datetime | None,
        started_at: datetime,
        now: datetime,
    ) -> ManagedSandboxAllocation:
        self.attempts.append(
            {
                "fencing_token": lease.fencing_token,
                "outcome": outcome,
                "error_code": error_code,
                "retry_at": retry_at,
                "started_at": started_at,
            }
        )
        changes: dict[str, object] = {"state": target, "error_code": error_code}
        if target is ManagedSandboxState.CLEANED:
            changes.update(
                provider_ref=None, ownership_digest=None, lease_expires_at=None
            )
        self.allocation = replace(self.allocation, **changes)
        return self.allocation


def _cleanup_service(
    repository: FakeLifecycleRepository,
    adapter: FakeManagedSandboxAdapter,
) -> ManagedSandboxCleanupService:
    return ManagedSandboxCleanupService(
        repository=repository,
        adapters={"fake": adapter},
        cipher=_IdentityCipher(),
        retry_backoff_seconds=_BACKOFF,
        lease_seconds=_LEASE_SECONDS,
    )


@pytest.fixture
def cleanup_fixture():
    def build(
        *,
        destroy_result: DestroyResult | None = None,
        faults: dict | None = None,
        allocation: ManagedSandboxAllocation | None = None,
    ):
        adapter = FakeManagedSandboxAdapter(
            destroy_result=destroy_result, faults=faults
        )
        # provider 쪽에 실제 리소스가 있는 상태를 만든다 -- destroy 가 소유권을
        # 대조할 대상이 있어야 한다.
        adapter.seed(
            provider_ref=_PROVIDER_REF,
            allocation_id="msa_1",
            idempotency_key="idem_1",
            ownership_digest=_OWNERSHIP_DIGEST,
        )
        repository = FakeLifecycleRepository(allocation or _active_allocation())
        return repository, adapter, _cleanup_service(repository, adapter)

    return build


# --- 정리 결과 분류 -------------------------------------------------------


async def test_confirmed_destroy_cleans_the_allocation(cleanup_fixture) -> None:
    repository, adapter, service = cleanup_fixture()

    result = await service.cleanup("msa_1", worker_id="cleanup_1", now=NOW)

    assert result.state is ManagedSandboxState.CLEANED
    assert adapter.destroy_calls == 1
    assert repository.attempts[-1]["outcome"] is CleanupAttemptOutcome.CLEANED
    assert repository.attempts[-1]["retry_at"] is None


async def test_verified_not_found_counts_as_cleaned(cleanup_fixture) -> None:
    """이미 사라진 리소스라도 **우리 것이었음이 증명되면** 정리로 친다."""
    _repository, _adapter, service = cleanup_fixture(
        destroy_result=DestroyResult(
            confirmed=False, not_found=True, ownership_verified=True
        )
    )

    result = await service.cleanup("msa_1", worker_id="cleanup_1", now=NOW)

    assert result.state is ManagedSandboxState.CLEANED


async def test_unverified_not_found_remains_cleanup_retry(cleanup_fixture) -> None:
    """소유권이 증명되지 않은 NotFound 는 정리가 아니다.

    남의 리소스를 우리 것으로 착각해 '정리됨'으로 적으면 원장이 거짓이 되고
    실제 리소스는 고아로 남는다.
    """
    _repository, _adapter, service = cleanup_fixture(
        destroy_result=DestroyResult(
            confirmed=False, not_found=True, ownership_verified=False
        )
    )

    result = await service.cleanup("msa_1", worker_id="cleanup_1", now=NOW)

    assert result.state is ManagedSandboxState.CLEANUP_RETRY
    assert result.error_code is ProviderErrorCode.CLEANUP_UNCONFIRMED


async def test_unverified_confirmed_destroy_also_retries(cleanup_fixture) -> None:
    """destroy 가 성공했다고 말해도 소유권이 증명되지 않으면 정리로 치지 않는다."""
    _repository, _adapter, service = cleanup_fixture(
        destroy_result=DestroyResult(confirmed=True, ownership_verified=False)
    )

    result = await service.cleanup("msa_1", worker_id="cleanup_1", now=NOW)

    assert result.state is ManagedSandboxState.CLEANUP_RETRY
    assert result.error_code is ProviderErrorCode.CLEANUP_UNCONFIRMED


async def test_provider_timeout_retries_with_a_timeout_code(cleanup_fixture) -> None:
    repository, _adapter, service = cleanup_fixture(
        faults={"destroy": ManagedAdapterTimeoutError("destroy_timed_out")}
    )

    result = await service.cleanup("msa_1", worker_id="cleanup_1", now=NOW)

    assert result.state is ManagedSandboxState.CLEANUP_RETRY
    assert result.error_code is ProviderErrorCode.PROVIDER_TIMEOUT
    assert repository.attempts[-1]["outcome"] is CleanupAttemptOutcome.RETRY


async def test_adapter_not_found_is_unconfirmed_not_cleaned(cleanup_fixture) -> None:
    """어댑터가 NotFound 를 **던지면** 소유권을 대조할 메타데이터 자체가 없다.

    `DestroyResult(not_found=True, ownership_verified=True)`(대조에 성공한
    사라짐)와 구별해야 한다 -- 이쪽은 아무것도 증명하지 못한 상태다.
    """
    _repository, _adapter, service = cleanup_fixture(
        faults={"destroy": ManagedAdapterNotFoundError("gone")}
    )

    result = await service.cleanup("msa_1", worker_id="cleanup_1", now=NOW)

    assert result.state is ManagedSandboxState.CLEANUP_RETRY
    assert result.error_code is ProviderErrorCode.CLEANUP_UNCONFIRMED


async def test_a_sealed_reference_that_will_not_open_never_reports_cleaned(
    cleanup_fixture,
) -> None:
    """봉인 해제 실패는 provider 를 부르지도 못한다 -- 그래도 CLEANED 는 아니다."""

    class _BrokenCipher:
        def encrypt(self, value: str) -> bytes:
            return value.encode()

        def decrypt(self, value: bytes) -> str:
            raise ValueError("authentication_failed")

    repository, adapter, _service = cleanup_fixture()
    service = ManagedSandboxCleanupService(
        repository=repository,
        adapters={"fake": adapter},
        cipher=_BrokenCipher(),
        retry_backoff_seconds=_BACKOFF,
        lease_seconds=_LEASE_SECONDS,
    )

    result = await service.cleanup("msa_1", worker_id="cleanup_1", now=NOW)

    assert result.state is ManagedSandboxState.CLEANUP_RETRY
    assert result.error_code is ProviderErrorCode.PROVIDER_AUTH_ERROR
    assert adapter.destroy_calls == 0


# --- 재시도 일정 ----------------------------------------------------------


def test_retry_schedule_follows_the_configured_backoff() -> None:
    delays = [
        (next_retry_at(NOW, attempt_index=index, backoff_seconds=_BACKOFF) - NOW)
        for index in range(len(_BACKOFF))
    ]

    assert delays == [timedelta(seconds=value) for value in _BACKOFF]


def test_retry_schedule_saturates_at_the_last_delay() -> None:
    """수열을 다 쓰면 마지막 간격으로 **계속** 재시도한다.

    포기하지 않는 것이 의도다 -- 증명되지 않은 provider 리소스를 원장에서
    지우는 것보다 낫다. 정체는 cleanup_slo_seconds 와 cleanup age 게이지가
    드러낸다.
    """
    saturated = next_retry_at(NOW, attempt_index=99, backoff_seconds=_BACKOFF)

    assert saturated == NOW + timedelta(seconds=_BACKOFF[-1])


async def test_each_failure_pushes_the_next_attempt_further_out(
    cleanup_fixture,
) -> None:
    repository, _adapter, service = cleanup_fixture(
        destroy_result=DestroyResult(
            confirmed=False, not_found=True, ownership_verified=False
        )
    )

    first = await service.cleanup("msa_1", worker_id="cleanup_1", now=NOW)
    second = await service.cleanup("msa_1", worker_id="cleanup_2", now=NOW)

    assert first.retry_at == NOW + timedelta(seconds=_BACKOFF[0])
    assert second.retry_at == NOW + timedelta(seconds=_BACKOFF[1])
    assert len(repository.attempts) == 2


# --- 펜싱과 세대 ----------------------------------------------------------


async def test_cleanup_commits_under_the_fence_it_claimed(cleanup_fixture) -> None:
    repository, _adapter, service = cleanup_fixture()
    token_before = repository.allocation.fencing_token

    await service.cleanup("msa_1", worker_id="cleanup_1", now=NOW)

    assert repository.attempts[-1]["fencing_token"] == token_before + 1


async def test_a_stale_generation_message_does_not_touch_the_provider(
    cleanup_fixture,
) -> None:
    """브로커에 남아 있던 옛 세대의 메시지가 새 세대를 부수지 못한다."""
    repository, adapter, service = cleanup_fixture(
        allocation=_active_allocation(generation=2)
    )

    with pytest.raises(StaleManagedSandboxGeneration):
        await service.cleanup(
            "msa_1", worker_id="cleanup_1", now=NOW, expected_generation=1
        )

    assert adapter.destroy_calls == 0
    assert repository.attempts == []


async def test_cleanup_rejects_an_allocation_that_is_not_in_a_cleanup_state(
    cleanup_fixture,
) -> None:
    repository, adapter, service = cleanup_fixture(
        allocation=_active_allocation(state=ManagedSandboxState.ACTIVE)
    )

    with pytest.raises(ManagedSandboxNotClaimable):
        await service.cleanup("msa_1", worker_id="cleanup_1", now=NOW)

    assert adapter.destroy_calls == 0


async def test_an_expired_cleanup_lease_is_reclaimable(cleanup_fixture) -> None:
    """정리 워커가 죽어도 다음 워커가 이어받는다 -- 리퍼가 따로 없다."""
    repository, _adapter, service = cleanup_fixture(
        allocation=_active_allocation(lease_expires_at=NOW - timedelta(seconds=1))
    )

    result = await service.cleanup("msa_1", worker_id="cleanup_2", now=NOW)

    assert result.state is ManagedSandboxState.CLEANED


# --- 조정(discovery) ------------------------------------------------------


def _reconciler(repository: FakeLifecycleRepository, metrics=None):
    return ManagedSandboxLifecycleReconciler(
        repository=repository,
        metrics=metrics,
        cleanup_slo_seconds=300,
    )


async def test_reconcile_reports_cleanup_and_recovery_separately() -> None:
    """정리와 복구는 서로 다른 후속 작업으로 간다 -- 한 튜플로 뭉치면 안 된다."""
    repository = FakeLifecycleRepository(_active_allocation())
    repository.candidates = LifecycleCandidates(
        cleanup=(
            CleanupCandidate(
                allocation_id="msa_1",
                provider="fake",
                region="local",
                pending_since=NOW - timedelta(seconds=30),
            ),
        ),
        recovery=("msa_2",),
    )

    outcome = await _reconciler(repository).reconcile(limit=10, now=NOW)

    assert [item.allocation_id for item in outcome.cleanup] == ["msa_1"]
    assert outcome.recovery == ("msa_2",)


async def test_reconcile_publishes_the_cleanup_backlog_age() -> None:
    """정리 SLO 는 게이지로 드러난다 -- 원장만 보고는 밀린 것을 알 수 없다."""
    records: list[tuple[dict, float]] = []

    class _Gauge:
        def labels(self, **labels):
            gauge = _Gauge()
            gauge._labels = labels
            return gauge

        def set(self, value: float) -> None:
            records.append((getattr(self, "_labels", {}), value))

    class _Metrics:
        coding_sandbox_cleanup_age_seconds = _Gauge()

    repository = FakeLifecycleRepository(_active_allocation())
    repository.candidates = LifecycleCandidates(
        cleanup=(
            CleanupCandidate(
                allocation_id="msa_1",
                provider="fake",
                region="local",
                pending_since=NOW - timedelta(seconds=30),
            ),
            CleanupCandidate(
                allocation_id="msa_2",
                provider="fake",
                region="local",
                pending_since=NOW - timedelta(seconds=900),
            ),
        ),
        recovery=(),
    )

    outcome = await _reconciler(repository, metrics=_Metrics()).reconcile(
        limit=10, now=NOW
    )

    assert records == [({"provider": "fake", "region": "local"}, 900.0)]
    assert outcome.slo_breached is True


async def test_reconcile_asks_for_the_requested_batch_size() -> None:
    repository = FakeLifecycleRepository(_active_allocation())

    await _reconciler(repository).reconcile(limit=7, now=NOW)

    assert repository.discovery_calls == [(NOW, 7)]


# --- 상태 집합이 도메인 전이표와 갈라지지 않는다 --------------------------


def test_cleanup_source_states_can_legally_reach_cleanup_pending() -> None:
    """조정자가 일괄 UPDATE 로 옮기는 원본 상태는 전이표가 허용하는 것뿐이어야
    한다.

    일괄 UPDATE 는 `transition_allocation()`을 거치지 않으므로 전이표가
    자동으로 지켜주지 않는다 -- 두 곳이 갈라지면 DB 에만 불법 전이가 남는다.
    """
    for state in _CLEANUP_SOURCE_STATES:
        assert (
            ManagedSandboxState.CLEANUP_PENDING in _ALLOWED_ALLOCATION_TRANSITIONS[state]
        )


def test_cleanable_states_can_legally_reach_cleaned() -> None:
    for state in _CLEANABLE_STATES:
        assert ManagedSandboxState.CLEANED in _ALLOWED_ALLOCATION_TRANSITIONS[state]

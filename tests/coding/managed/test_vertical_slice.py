"""결정론적 수직 슬라이스 -- Task 1~9 를 한 줄기로 통과시킨다.

admitted → **모호한 할당**(create-then-timeout) → 재발견/active →
아카이브 → 태스크 종료 → 정리 → cleaned.

단위 테스트들은 각 단계를 따로 본다. 이 파일이 보는 것은 **단계 사이**다 --
한 단계의 출력이 다음 단계의 입력으로 실제로 맞물리는가, 그리고 매 단계에서
사용자에게 나가는 투영이 여전히 아무것도 흘리지 않는가.

벤더가 필요 없다. 전부 결정론적 fake 위에서 돈다.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from neos.coding.managed.adapters import (
    CreateThenTimeout,
    FakeManagedSandboxAdapter,
    ManagedNetworkPolicy,
)
from neos.coding.managed.allocation import (
    AllocationPlan,
    ManagedAllocationLease,
    ManagedSandboxAllocationService,
)
from neos.coding.managed.benchmark import run_managed_sandbox_benchmark
from neos.coding.managed.domain import (
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
)
from neos.coding.managed.projection import (
    OwnerSandboxState,
    project_owner_sandbox_status,
)
from neos.coding.sandbox.base import SandboxLimits
from tests.coding.managed.adapters.conformance import allocation_request


pytestmark = pytest.mark.no_db

NOW = datetime(2026, 8, 22, 12, tzinfo=UTC)
_IMAGE = "neos-sandbox@sha256:" + "b" * 64
_IDEMPOTENCY_KEY = "idem_slice"
_BACKOFF = (5, 15, 45, 120, 300)


class SliceRepository:
    """할당·정리 계약을 함께 흉내 내는 하나의 인메모리 원장.

    두 서비스에 **같은** 저장소를 준다 -- 따로 주면 한쪽의 커밋이 다른 쪽에
    보이지 않아서, 실제로는 맞물리지 않는 파이프라인이 통과해 버린다.
    """

    def __init__(self, allocation: ManagedSandboxAllocation) -> None:
        self.allocation = allocation
        self.attempts: list[CleanupAttemptOutcome] = []
        self._token = allocation.fencing_token

    async def claim_allocation(
        self, allocation_id: str, worker_id: str, *, now, lease_seconds: int
    ) -> ManagedAllocationLease:
        self._token += 1
        self.allocation = replace(self.allocation, fencing_token=self._token)
        return ManagedAllocationLease(
            allocation_id=allocation_id,
            worker_id=worker_id,
            fencing_token=self._token,
            expires_at=now + timedelta(seconds=lease_seconds),
        )

    async def read_allocation_plan(self, allocation_id: str) -> AllocationPlan:
        return AllocationPlan(
            allocation=self.allocation, idempotency_key=_IDEMPOTENCY_KEY
        )

    async def read_allocation(self, allocation_id: str) -> ManagedSandboxAllocation:
        return self.allocation

    async def commit_state(
        self,
        lease,
        target,
        *,
        now,
        error_code=None,
        image_identity=None,
        ownership_digest=None,
    ) -> ManagedSandboxAllocation:
        changes: dict = {"state": target, "error_code": error_code}
        if image_identity is not None:
            changes["image_identity"] = image_identity
        if ownership_digest is not None:
            changes["ownership_digest"] = ownership_digest
        self.allocation = replace(self.allocation, **changes)
        return self.allocation

    async def commit_active(
        self, lease, result, *, encrypted_ref, now
    ) -> ManagedSandboxAllocation:
        self.allocation = replace(
            self.allocation,
            state=result.state,
            provider_ref=encrypted_ref,
            ownership_digest=result.ownership_digest,
            error_code=None,
        )
        return self.allocation

    async def cleanup_attempt_count(self, allocation_id: str) -> int:
        return len(self.attempts)

    async def commit_cleanup_outcome(
        self,
        lease,
        *,
        target,
        outcome,
        error_code,
        retry_at,
        started_at,
        now,
    ) -> ManagedSandboxAllocation:
        self.attempts.append(outcome)
        changes: dict = {"state": target, "error_code": error_code}
        if target is ManagedSandboxState.CLEANED:
            changes.update(
                provider_ref=None, ownership_digest=None, lease_expires_at=None
            )
        self.allocation = replace(self.allocation, **changes)
        return self.allocation

    async def discover_lifecycle_candidates(
        self, *, now, limit: int
    ) -> LifecycleCandidates:
        """태스크가 종결됐다고 보고 현재 할당을 정리 후보로 승격한다."""
        if self.allocation.state in {
            ManagedSandboxState.ACTIVE,
            ManagedSandboxState.SUSPENDED,
        }:
            self.allocation = replace(
                self.allocation, state=ManagedSandboxState.CLEANUP_PENDING
            )
        return LifecycleCandidates(
            cleanup=(
                CleanupCandidate(
                    allocation_id=self.allocation.allocation_id,
                    provider=self.allocation.provider,
                    region=self.allocation.region,
                    pending_since=now,
                ),
            ),
            recovery=(),
        )


class _IdentityCipher:
    def encrypt(self, value: str) -> bytes:
        return value.encode()

    def decrypt(self, value: bytes) -> str:
        return value.decode()


def _admitted() -> ManagedSandboxAllocation:
    return ManagedSandboxAllocation(
        allocation_id="msa_slice",
        tenant_id="tenant_1",
        task_id="task_1",
        run_id="run_1",
        provider="fake",
        region="local",
        provider_ref=None,
        ownership_digest=None,
        state=ManagedSandboxState.ADMITTED,
        generation=1,
        fencing_token=1,
        lease_expires_at=None,
        absolute_expires_at=NOW + timedelta(hours=4),
        version=1,
        error_code=None,
        snapshot_ref=None,
        archive_ref=None,
        image_identity=None,
    )


def _owner_state(repository: SliceRepository) -> OwnerSandboxState:
    return project_owner_sandbox_status(
        repository.allocation, updated_at=NOW
    ).state


def _leaks(repository: SliceRepository) -> str:
    payload = project_owner_sandbox_status(
        repository.allocation, updated_at=NOW
    ).to_payload()
    return repr(payload)


async def test_the_whole_slice_runs_on_deterministic_fakes() -> None:
    repository = SliceRepository(_admitted())
    adapter = FakeManagedSandboxAdapter(allocate_fault=CreateThenTimeout())
    allocation_service = ManagedSandboxAllocationService(
        repository=repository,
        adapters={"fake": adapter},
        cipher=_IdentityCipher(),
        resource_limits=SandboxLimits.safe_defaults(),
        network_policy=ManagedNetworkPolicy.BLOCK_ALL,
        image_identity=_IMAGE,
        lease_seconds=300,
        clock=lambda: NOW,
    )
    cleanup_service = ManagedSandboxCleanupService(
        repository=repository,
        adapters={"fake": adapter},
        cipher=_IdentityCipher(),
        retry_backoff_seconds=_BACKOFF,
        lease_seconds=120,
    )
    reconciler = ManagedSandboxLifecycleReconciler(
        repository=repository, cleanup_slo_seconds=300
    )

    # 1. ADMITTED -- 사용자는 "준비 중"만 본다.
    assert _owner_state(repository) is OwnerSandboxState.PREPARING

    # 2. 모호한 할당: provider 는 만들었는데 응답이 타임아웃했다.
    first = await allocation_service.advance("msa_slice", worker_id="worker_1")
    assert first.state is ManagedSandboxState.RECOVERY_PENDING
    assert first.error_code is ProviderErrorCode.PROVIDER_TIMEOUT
    assert adapter.allocate_calls == 1
    assert _owner_state(repository) is (
        OwnerSandboxState.PROVIDER_RECOVERY_PENDING
    )

    # 3. 재발견 -- **두 번째 create 를 내지 않는다.**
    second = await allocation_service.advance("msa_slice", worker_id="worker_2")
    assert second.state is ManagedSandboxState.ACTIVE
    assert adapter.allocate_calls == 1
    assert adapter.rediscovery_calls == 1
    assert _owner_state(repository) is OwnerSandboxState.READY

    # 4. 아카이브(워크스페이스 스냅샷)는 실행을 끝내지 않는다.
    snapshot = await adapter.snapshot(second.provider_ref.decode())
    assert snapshot.snapshot_ref.startswith("fake_snapshot_")
    assert _owner_state(repository) is OwnerSandboxState.READY

    # 5. 태스크가 종결됐다 -- 조정자가 정리 후보로 승격한다.
    outcome = await reconciler.reconcile(limit=10, now=NOW)
    assert [item.allocation_id for item in outcome.cleanup] == ["msa_slice"]
    assert _owner_state(repository) is OwnerSandboxState.CLEANING_UP

    # 6. 정리 -- 확정 파괴 + 소유권 증명 => CLEANED.
    cleaned = await cleanup_service.cleanup(
        "msa_slice", worker_id="cleanup_1", now=NOW
    )
    assert cleaned.state is ManagedSandboxState.CLEANED
    assert repository.attempts == [CleanupAttemptOutcome.CLEANED]
    assert adapter.destroy_calls == 1
    assert _owner_state(repository) is OwnerSandboxState.CLEANED


async def test_the_slice_never_leaks_infrastructure_at_any_stage() -> None:
    """단계마다 사용자에게 나가는 것에 인프라 사실이 없다.

    파이프라인 중간 상태가 가장 위험하다 -- 정상 경로만 보면 놓친다.
    """
    repository = SliceRepository(_admitted())
    adapter = FakeManagedSandboxAdapter(allocate_fault=CreateThenTimeout())
    service = ManagedSandboxAllocationService(
        repository=repository,
        adapters={"fake": adapter},
        cipher=_IdentityCipher(),
        resource_limits=SandboxLimits.safe_defaults(),
        network_policy=ManagedNetworkPolicy.BLOCK_ALL,
        image_identity=_IMAGE,
        lease_seconds=300,
        clock=lambda: NOW,
    )
    forbidden = ("fake_msa_slice", "msa_slice", "tenant_1", _IMAGE, "provider_timeout")

    for _ in range(2):
        await service.advance("msa_slice", worker_id="worker")
        rendered = _leaks(repository)
        for secret in forbidden:
            assert secret not in rendered


async def test_execution_is_gated_off_everywhere_except_ready() -> None:
    """수직 슬라이스 전체에서 실행이 열리는 지점은 ACTIVE 하나뿐이다."""
    repository = SliceRepository(_admitted())
    opened: list[ManagedSandboxState] = []

    for state in ManagedSandboxState:
        if state is ManagedSandboxState.CLEANED:
            repository.allocation = replace(
                repository.allocation,
                state=state,
                provider_ref=None,
                ownership_digest=None,
                lease_expires_at=None,
            )
        else:
            repository.allocation = replace(repository.allocation, state=state)
        if project_owner_sandbox_status(
            repository.allocation, updated_at=NOW
        ).can_run:
            opened.append(state)

    assert opened == [ManagedSandboxState.ACTIVE]


# --- 벤치마크 러너 ---------------------------------------------------------


class _FakeMonotonic:
    """호출마다 10ms 씩 흐르는 결정론적 단조 시계."""

    def __init__(self) -> None:
        self.ticks = 0.0

    def __call__(self) -> float:
        current = self.ticks
        self.ticks += 0.01
        return current


async def test_the_benchmark_measures_and_always_cleans_up() -> None:
    adapter = FakeManagedSandboxAdapter()

    report = await run_managed_sandbox_benchmark(
        adapter,
        allocation_request("idem_bench"),
        region="local",
        cost_micros_per_second=100,
        monotonic=_FakeMonotonic(),
        clock=lambda: NOW,
    )

    assert report.provider == "fake"
    assert report.allocation_ms >= 0
    assert report.rediscovery_verified is True
    assert report.network_block_verified is True
    assert adapter.destroy_calls == 1


async def test_the_benchmark_cleans_up_even_when_a_step_fails() -> None:
    """벤치마크가 고아 샌드박스를 남기면 그 비용은 청구서에만 나타난다."""
    adapter = FakeManagedSandboxAdapter(
        faults={"inspect": RuntimeError("provider hiccup")}
    )

    with pytest.raises(RuntimeError):
        await run_managed_sandbox_benchmark(
            adapter,
            allocation_request("idem_bench"),
            region="local",
            cost_micros_per_second=100,
            monotonic=_FakeMonotonic(),
            clock=lambda: NOW,
        )

    assert adapter.destroy_calls == 1


async def test_unsupported_capabilities_are_none_not_zero() -> None:
    """0 으로 적으면 "0ms 에 끝났다"와 "할 수 없다"가 같은 숫자가 된다."""
    from tests.coding.managed.adapters.test_modal import FakeModalClient
    from neos.coding.managed.adapters import ModalManagedSandboxAdapter
    from tests.coding.managed.adapters.conformance import NOW as REQUEST_NOW

    adapter = ModalManagedSandboxAdapter(
        client=FakeModalClient(), clock=lambda: REQUEST_NOW
    )

    report = await run_managed_sandbox_benchmark(
        adapter,
        allocation_request("idem_bench"),
        region="us-east",
        cost_micros_per_second=100,
        monotonic=_FakeMonotonic(),
        clock=lambda: NOW,
    )

    assert report.resume_ms is None
    assert report.snapshot_ms is not None


def test_the_benchmark_report_carries_no_identifier() -> None:
    from neos.coding.managed.benchmark import ManagedSandboxBenchmark

    report = ManagedSandboxBenchmark(
        provider="fake",
        region="local",
        allocation_ms=10,
        inspect_ms=1,
        snapshot_ms=2,
        resume_ms=3,
        cleanup_ms=4,
        network_block_verified=True,
        rediscovery_verified=True,
        estimated_cost_micros=500,
    ).to_report()

    assert set(report) == {
        "provider",
        "region",
        "allocation_ms",
        "inspect_ms",
        "snapshot_ms",
        "resume_ms",
        "cleanup_ms",
        "network_block_verified",
        "rediscovery_verified",
        "estimated_cost_micros",
    }


async def test_the_benchmark_refuses_an_unblocked_network_policy() -> None:
    """벤치마크는 차단된 네트워크에서만 의미가 있다 -- 비교 조건이 달라진다."""
    with pytest.raises(ValueError, match="blocked network policy"):
        await run_managed_sandbox_benchmark(
            FakeManagedSandboxAdapter(),
            allocation_request(
                "idem_bench", network_policy=ManagedNetworkPolicy.ALLOWLIST
            ),
            region="local",
            cost_micros_per_second=100,
            monotonic=_FakeMonotonic(),
            clock=lambda: NOW,
        )

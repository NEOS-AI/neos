"""`ManagedSandboxAllocationService.advance()`의 오류 분류·전이 순서 테스트.

DB를 쓰지 않는다 -- 이 파일이 검증하는 것은 오류 분류와 전이 순서이지 SQL이
아니다 (SQL·펜싱 원자성은 Task 7의 `test_repository.py`·`integration/`이 본다).
그래서 `claim_allocation`·`read_allocation_plan`·`commit_state`·`commit_active`
계약만 흉내 내는 인메모리 `FakeAllocationRepository`를 쓴다.
"""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import pytest

from neos.coding.managed.adapters import (
    CreateThenTimeout,
    FakeManagedSandboxAdapter,
    ManagedAdapterValidationError,
    ManagedNetworkPolicy,
)
from neos.coding.managed.allocation import (
    AllocationPlan,
    ManagedAllocationLease,
    ManagedSandboxAllocationService,
)
from neos.coding.managed.domain import ManagedSandboxAllocation, ManagedSandboxState
from neos.coding.sandbox.base import SandboxLimits


NOW = datetime(2026, 8, 11, 12, tzinfo=UTC)
_LEASE_SECONDS = 300
_IDEMPOTENCY_KEY = "idem_1"
_IMAGE_IDENTITY = "neos-sandbox@sha256:" + "b" * 64


def _admitted_allocation() -> ManagedSandboxAllocation:
    """ADMITTED 상태 할당 하나를 만든다.

    provider_ref·ownership_digest·image_identity는 admission INSERT가 실제로
    NULL로 남기는 필드들이다(Task 7 carry-forward) -- image_identity는 여기서도
    None으로 둬서, 서비스가 config 주입값을 쓰지 않으면 요청 검증이 곧바로
    거부한다는 것을 자연스럽게 증명한다. ownership_digest는 이 테스트 스위트의
    관심사가 아니므로(advance()의 오류 분류·전이 순서만 본다) 유효한 값을 미리
    채워 둔다.
    """
    return ManagedSandboxAllocation(
        allocation_id="msa_1",
        tenant_id="tenant_1",
        task_id="task_1",
        run_id="run_1",
        provider="docker",
        region="local",
        provider_ref=None,
        ownership_digest="sha256:owner",
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


class FakeAllocationRepository:
    """claim/commit 계약만 흉내 내는 인메모리 repository.

    펜싱의 **원자성**은 Task 7의 통합 테스트가 본다. 여기서는 서비스가 어떤
    순서로 무엇을 커밋하는지만 본다.
    """

    def __init__(self, allocation: ManagedSandboxAllocation) -> None:
        self.allocation = allocation
        self.committed: list[ManagedSandboxState] = []
        # ALLOCATING 전이마다 넘어온 image_identity를 기록한다 -- carry-forward
        # 회귀(commit_state를 image_identity 없이 부르는 것)를 테스트가 잡아낸다.
        self.image_identity_writes: list[str | None] = []
        self._token = allocation.fencing_token

    async def claim_allocation(
        self, allocation_id: str, worker_id: str, *, now: datetime, lease_seconds: int
    ) -> ManagedAllocationLease:
        self._token += 1
        return ManagedAllocationLease(
            allocation_id=allocation_id,
            worker_id=worker_id,
            fencing_token=self._token,
            expires_at=now + timedelta(seconds=lease_seconds),
        )

    async def read_allocation_plan(self, allocation_id: str) -> AllocationPlan:
        return AllocationPlan(
            allocation=self.allocation,
            idempotency_key=_IDEMPOTENCY_KEY,
        )

    async def commit_state(
        self,
        lease: ManagedAllocationLease,
        target: ManagedSandboxState,
        *,
        now: datetime,
        error_code=None,
        image_identity: str | None = None,
    ) -> ManagedSandboxAllocation:
        self.committed.append(target)
        self.image_identity_writes.append(image_identity)
        changes: dict[str, object] = {
            "state": target,
            "error_code": error_code,
            "fencing_token": lease.fencing_token,
        }
        if image_identity is not None:
            changes["image_identity"] = image_identity
        self.allocation = replace(self.allocation, **changes)
        return self.allocation

    async def commit_active(
        self,
        lease: ManagedAllocationLease,
        result,
        *,
        encrypted_ref: bytes,
        now: datetime,
    ) -> ManagedSandboxAllocation:
        self.committed.append(result.state)
        self.allocation = replace(
            self.allocation,
            state=result.state,
            provider_ref=encrypted_ref,
            ownership_digest=result.ownership_digest,
            error_code=None,
            fencing_token=lease.fencing_token,
        )
        return self.allocation


@dataclass(frozen=True, slots=True)
class _IdentityCipher:
    """실제 암복호화 없이 계약만 지키는 테스트 전용 cipher.

    Task 9가 넣을 진짜 cipher는 별도로 검증한다.
    """

    def encrypt(self, value: str) -> bytes:
        return value.encode()

    def decrypt(self, value: bytes) -> str:
        return value.decode()


@pytest.fixture
def allocation_service():
    def build(*, adapter: FakeManagedSandboxAdapter | None = None):
        adapter = adapter or FakeManagedSandboxAdapter()
        repository = FakeAllocationRepository(_admitted_allocation())
        service = ManagedSandboxAllocationService(
            repository=repository,
            adapters={"docker": adapter},
            cipher=_IdentityCipher(),
            resource_limits=SandboxLimits.safe_defaults(),
            network_policy=ManagedNetworkPolicy.BLOCK_ALL,
            image_identity=_IMAGE_IDENTITY,
            lease_seconds=_LEASE_SECONDS,
            clock=lambda: NOW,
        )
        return service, adapter

    return build


async def test_allocate_timeout_rediscovers_without_a_second_create(
    allocation_service,
) -> None:
    """create-then-timeout 은 재생성이 아니라 재발견으로 복구돼야 한다.

    두 번째 create 를 내면 고아 샌드박스가 생기고 쿼터가 샌다.
    """
    service, adapter = allocation_service(
        adapter=FakeManagedSandboxAdapter(allocate_fault=CreateThenTimeout())
    )

    first = await service.advance("msa_1", worker_id="worker_1")
    assert first.state is ManagedSandboxState.RECOVERY_PENDING

    second = await service.advance("msa_1", worker_id="worker_2")
    assert second.state is ManagedSandboxState.ACTIVE
    assert adapter.allocate_calls == 1
    assert adapter.rediscovery_calls == 1


async def test_a_definite_failure_commits_failed(allocation_service) -> None:
    service, adapter = allocation_service(
        adapter=FakeManagedSandboxAdapter(
            allocate_fault=ManagedAdapterValidationError("image_identity_mismatch")
        )
    )

    result = await service.advance("msa_1", worker_id="worker_1")

    assert result.state is ManagedSandboxState.FAILED
    assert adapter.allocate_calls == 1


async def test_recovery_without_a_provider_record_needs_an_operator(
    allocation_service,
) -> None:
    """재발견도 실패하면 자동 복구를 시도하지 않는다 (fail-closed)."""
    service, adapter = allocation_service(
        adapter=FakeManagedSandboxAdapter(allocate_fault=CreateThenTimeout())
    )

    await service.advance("msa_1", worker_id="worker_1")
    # provider 쪽 기록이 사라진 상황(운영 사고 등)을 흉내 낸다 -- 재발견이
    # 아무것도 못 찾아야 한다.
    adapter.forget_all()
    result = await service.advance("msa_1", worker_id="worker_2")

    assert result.state is ManagedSandboxState.MANUAL_RECOVERY_REQUIRED


async def test_advance_performs_at_most_one_provider_call(allocation_service) -> None:
    service, adapter = allocation_service()

    await service.advance("msa_1", worker_id="worker_1")

    assert adapter.allocate_calls == 1
    assert adapter.rediscovery_calls == 0


async def test_allocating_transition_persists_image_identity(
    allocation_service,
) -> None:
    """ALLOCATING 커밋은 image_identity를 명시적으로 같이 써야 한다.

    `commit_state`의 `image_identity`는 선택 인자라 아무도 강제하지 않는다 --
    안 넘기면 컬럼이 NULL로 남아 이후 어댑터 요청 재구성이 막힌다
    (Task 7 carry-forward, 두 번째로 지적된 문제).
    """
    service, _adapter = allocation_service()

    await service.advance("msa_1", worker_id="worker_1")

    assert service._repository.image_identity_writes == [_IMAGE_IDENTITY]

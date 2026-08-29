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
    _ownership_digest_for,
)
from neos.coding.managed.domain import (
    InvalidManagedSandboxTransition,
    ManagedSandboxAllocation,
    ManagedSandboxState,
)
from neos.coding.sandbox.base import SandboxLimits


NOW = datetime(2026, 8, 11, 12, tzinfo=UTC)
_LEASE_SECONDS = 300
_IDEMPOTENCY_KEY = "idem_1"
_IMAGE_IDENTITY = "neos-sandbox@sha256:" + "b" * 64


def _admitted_allocation() -> ManagedSandboxAllocation:
    """ADMITTED 상태 할당 하나를 만든다.

    provider_ref·ownership_digest·image_identity는 admission INSERT가 실제로
    NULL로 남기는 필드들이다 -- 여기서도 그대로 None으로 둔다. 픽스처가 값을
    미리 채워주면, 그 필드를 서비스가 실제로 써넣는지 검증하지 못한 채로
    테스트가 통과해 버린다(ownership_digest가 바로 그렇게 숨겨졌던 Critical
    이었다). 이 스위트가 통과한다면 그건 코드가 값을 만들어 넣었기 때문이어야
    한다.
    """
    return ManagedSandboxAllocation(
        allocation_id="msa_1",
        tenant_id="tenant_1",
        task_id="task_1",
        run_id="run_1",
        provider="docker",
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


class FakeAllocationRepository:
    """claim/commit 계약만 흉내 내는 인메모리 repository.

    펜싱의 **원자성**은 Task 7의 통합 테스트가 본다. 여기서는 서비스가 어떤
    순서로 무엇을 커밋하는지만 본다.
    """

    def __init__(self, allocation: ManagedSandboxAllocation) -> None:
        self.allocation = allocation
        self.committed: list[ManagedSandboxState] = []
        # ALLOCATING 전이마다 넘어온 image_identity·ownership_digest를 기록한다
        # -- carry-forward 회귀(commit_state를 그 값들 없이 부르는 것)를
        # 테스트가 잡아낸다.
        self.image_identity_writes: list[str | None] = []
        self.ownership_digest_writes: list[str | None] = []
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
        ownership_digest: str | None = None,
    ) -> ManagedSandboxAllocation:
        self.committed.append(target)
        self.image_identity_writes.append(image_identity)
        self.ownership_digest_writes.append(ownership_digest)
        changes: dict[str, object] = {
            "state": target,
            "error_code": error_code,
            "fencing_token": lease.fencing_token,
        }
        if image_identity is not None:
            changes["image_identity"] = image_identity
        if ownership_digest is not None:
            changes["ownership_digest"] = ownership_digest
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


def test_ownership_digest_is_deterministic_for_a_given_allocation() -> None:
    """난수가 아니라 순수 함수여야 한다 -- 재발견 경로가 같은 할당에 대해
    같은 값을 다시 유도해서 소유권을 확인해야 하기 때문이다.
    """
    allocation = _admitted_allocation()

    assert _ownership_digest_for(allocation) == _ownership_digest_for(allocation)

    other = replace(allocation, allocation_id="msa_2")
    assert _ownership_digest_for(allocation) != _ownership_digest_for(other)


async def test_allocating_transition_persists_a_deterministic_ownership_digest(
    allocation_service,
) -> None:
    """ALLOCATING 커밋은 ownership_digest도 image_identity와 같은 모양으로
    명시적으로 같이 써야 한다.

    admission INSERT는 이 컬럼을 NULL로 남긴다 -- 픽스처가 값을 대신
    채워주지 않으므로(`_admitted_allocation()`이 `ownership_digest=None`),
    이 테스트가 통과한다는 것 자체가 서비스 코드가 값을 만들어 썼다는
    증거다.
    """
    service, _adapter = allocation_service()

    await service.advance("msa_1", worker_id="worker_1")

    expected = _ownership_digest_for(_admitted_allocation())
    assert service._repository.ownership_digest_writes == [expected]


async def test_crash_after_allocating_commit_recovers_via_rediscovery_not_a_second_create(
    allocation_service,
) -> None:
    """ALLOCATING 커밋과 종결 커밋(commit_active) 사이에서 워커가 죽으면
    (또는 종결 커밋 자체가 실패하면), 리스가 만료된 뒤 새 워커가 들어와도
    재발견만 해야 한다 -- allocate()를 다시 부르면 provider 쪽에 이미 만들어진
    리소스가 고아가 된다.

    provider 쪽 create는 실제로 성공했다고 가정한다(어댑터에 직접 걸어 기록을
    남긴다). repository 상태를 ALLOCATING에 그대로 둬서 "두 번째 커밋이 오지
    않고 죽었다"를 흉내 내고, 새 워커로 advance()를 부른다.
    """
    service, adapter = allocation_service()
    plan = await service._repository.read_allocation_plan("msa_1")
    ownership_digest = _ownership_digest_for(plan.allocation)
    await adapter.allocate(
        service._request_for(plan, ownership_digest=ownership_digest)
    )
    service._repository.allocation = replace(
        service._repository.allocation, state=ManagedSandboxState.ALLOCATING
    )

    result = await service.advance("msa_1", worker_id="worker_2")

    assert result.state is ManagedSandboxState.ACTIVE
    assert adapter.allocate_calls == 1
    assert adapter.rediscovery_calls == 1


async def test_advance_rejects_a_non_advanceable_state(allocation_service) -> None:
    """ACTIVE처럼 이미 안정된 상태는 advance() 대상이 아니다."""
    service, adapter = allocation_service()
    service._repository.allocation = replace(
        service._repository.allocation, state=ManagedSandboxState.ACTIVE
    )

    with pytest.raises(InvalidManagedSandboxTransition):
        await service.advance("msa_1", worker_id="worker_1")

    assert adapter.allocate_calls == 0
    assert adapter.rediscovery_calls == 0


async def test_rediscovery_refuses_a_sandbox_we_cannot_prove_is_ours(
    allocation_service,
) -> None:
    """재발견이 돌려준 리소스의 소유권을 **대조한다.**

    `_ownership_digest_for` 는 난수가 아니라 `tenant_id:allocation_id` 에서
    결정론적으로 유도되고, 그 독스트링이 이유를 명시한다 -- "재발견 경로가
    이 값을 다시 유도해 되찾은 provider 리소스의 소유권을 확인해야 하기
    때문이다". 그 확인을 하는 코드가 없었다.

    **왜 위험한가.** 재발견은 idempotency key 로만 찾는다. provider 쪽에서
    그 키가 다른 테넌트의 리소스에 붙어 있으면(키 재사용·충돌·provider 버그)
    우리는 남의 샌드박스를 우리 원장에 ACTIVE 로 적고, 사용자를 그 안에서
    일하게 한다. 이 저장소가 fail-closed 로 세운 나머지 전부 -- 승인 없는
    부활 금지, 크로스 프로바이더 failover 금지 -- 를 우회하는 경로다.

    거부는 `MANUAL_RECOVERY_REQUIRED` 다. 못 찾은 경우와 같은 처분인데,
    **증명할 수 없는 것을 찾은 것은 못 찾은 것보다 낫지 않기 때문**이다.
    """
    service, adapter = allocation_service(
        adapter=FakeManagedSandboxAdapter(allocate_fault=CreateThenTimeout())
    )

    first = await service.advance("msa_1", worker_id="worker_1")
    assert first.state is ManagedSandboxState.RECOVERY_PENDING

    # provider 가 같은 idempotency key 로 **우리 것이 아닌** 리소스를 돌려준다.
    provider_ref = adapter._idempotency[_IDEMPOTENCY_KEY]
    ours = adapter._records[provider_ref]
    assert ours.ownership_digest == _ownership_digest_for(_admitted_allocation())
    adapter._records[provider_ref] = replace(
        ours, ownership_digest="sha256:" + "f" * 64
    )

    second = await service.advance("msa_1", worker_id="worker_2")

    assert second.state is ManagedSandboxState.MANUAL_RECOVERY_REQUIRED
    # 채택하지 않았다는 것이 요점이다 -- ACTIVE 로 적었다면 사용자가 남의
    # 샌드박스 안에서 일하게 된다.
    assert second.state is not ManagedSandboxState.ACTIVE


async def test_rediscovery_accepts_a_sandbox_whose_ownership_matches(
    allocation_service,
) -> None:
    """대조가 정상 복구를 막지 않는다.

    위 테스트만 있으면 "항상 거부" 로 고쳐도 통과한다 -- 이 테스트가 그 방향의
    회귀를 막는다.
    """
    service, adapter = allocation_service(
        adapter=FakeManagedSandboxAdapter(allocate_fault=CreateThenTimeout())
    )

    await service.advance("msa_1", worker_id="worker_1")
    second = await service.advance("msa_1", worker_id="worker_2")

    assert second.state is ManagedSandboxState.ACTIVE
    assert adapter.allocate_calls == 1

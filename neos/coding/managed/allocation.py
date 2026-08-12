"""펜스된 할당(lease) 계약.

`coding_managed_sandboxes`(마이그레이션 045)에는 `fencing_token`과
`lease_expires_at`만 있고 리스 소유자 컬럼이 없다. 그래서 소유권 증명은
`fencing_token` 단독으로 한다 -- claim이 토큰을 증가시키고, commit은 그 토큰을
WHERE 절에 넣어 낡은 워커가 갱신하는 행 수를 0으로 만든다.
`worker_id`는 이 lease 객체와 로그·메트릭에만 남는 진단용이며 DB에는
저장하지 않는다.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from neos.coding.managed.adapters import (
    AllocationResult,
    ManagedAdapterError,
    ManagedAdapterNotFoundError,
    ManagedAdapterOwnershipError,
    ManagedAdapterTimeoutError,
    ManagedAdapterValidationError,
    ManagedAllocationRequest,
    ManagedNetworkPolicy,
    ManagedSandboxAdapter,
)
from neos.coding.managed.domain import (
    InvalidManagedSandboxTransition,
    ManagedSandboxAllocation,
    ManagedSandboxState,
    ProviderErrorCode,
)
from neos.coding.sandbox.base import SandboxLimits


class StaleManagedSandboxLease(RuntimeError):
    """펜싱 토큰이 낡거나 리스가 살아 있어 이 워커는 더 이상 이 할당을
    진행시킬 수 없다 -- "누군가 지금 쥐고 있다"는 뜻이다.
    """


class ManagedSandboxNotFound(LookupError):
    """`allocation_id`에 해당하는 할당 행이 없다."""


class ManagedSandboxNotClaimable(RuntimeError):
    """할당이 claim 가능한 상태가 아니다 -- "이미 끝났거나 다른 단계에
    있다"는 뜻이다. 리스가 살아 있어서 지는 것(`StaleManagedSandboxLease`)과
    구별해야 호출자가 재시도할지 포기할지 판단할 수 있다.
    """


@dataclass(frozen=True, slots=True)
class ManagedAllocationLease:
    """claim이 발급한 리스. `fencing_token`이 소유권 증명이다."""

    allocation_id: str
    worker_id: str
    fencing_token: int
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class AllocationPlan:
    """할당 행 + admission 행에서 **DB 에 실제로 있는 것만** 모은 읽기 뷰.

    resource_limits 와 network_policy 는 여기 없다 -- 정책이지 상태가 아니며,
    서비스가 config 에서 받아 요청을 만들 때 채운다. (045에는 애초에 이 두
    컬럼이 admissions/managed_sandboxes 어느 쪽에도 없다 -- 마이그레이션 없이는
    영속화할 수 없고, 정책을 어차피 config에서 읽는 편이 진행 중인 할당에도
    정책 변경이 즉시 반영되지 않는 문제를 피한다.)
    """

    allocation: ManagedSandboxAllocation
    idempotency_key: str


class ManagedAllocationRepository(Protocol):
    """`ManagedSandboxAllocationService`가 요구하는 repository 계약.

    Task 7의 `PostgresManagedSandboxRepository`가 이 네 메서드를 구현한다.
    테스트는 DB 없이 이 계약만 흉내 내는 인메모리 fake를 쓴다.
    """

    async def claim_allocation(
        self,
        allocation_id: str,
        worker_id: str,
        *,
        now: datetime,
        lease_seconds: int,
    ) -> ManagedAllocationLease: ...

    async def read_allocation_plan(self, allocation_id: str) -> AllocationPlan: ...

    async def commit_state(
        self,
        lease: ManagedAllocationLease,
        target: ManagedSandboxState,
        *,
        now: datetime,
        error_code: ProviderErrorCode | None = None,
        image_identity: str | None = None,
    ) -> ManagedSandboxAllocation: ...

    async def commit_active(
        self,
        lease: ManagedAllocationLease,
        result: AllocationResult,
        *,
        encrypted_ref: bytes,
        now: datetime,
    ) -> ManagedSandboxAllocation: ...


class ManagedSandboxCipher(Protocol):
    """provider_ref를 저장 전에 암복호화하는 계약. Task 9가 실제 구현을 넣는다."""

    def encrypt(self, value: str) -> bytes: ...

    def decrypt(self, value: bytes) -> str: ...


_ADVANCEABLE_STATES = frozenset(
    {ManagedSandboxState.ADMITTED, ManagedSandboxState.RECOVERY_PENDING}
)

_VALIDATION_ERROR_CODES: dict[type[ManagedAdapterError], ProviderErrorCode] = {
    ManagedAdapterValidationError: ProviderErrorCode.POLICY_DENIED,
    ManagedAdapterOwnershipError: ProviderErrorCode.PROVIDER_AUTH_ERROR,
    ManagedAdapterNotFoundError: ProviderErrorCode.PROVIDER_NOT_FOUND,
}


def _error_code(error: ManagedAdapterError) -> ProviderErrorCode:
    """확정 실패(typed error)를 원장에 남길 `ProviderErrorCode`로 옮긴다.

    `ManagedAdapterTimeoutError`는 여기 오지 않는다 -- 호출자가 모호성으로
    먼저 갈라낸다. `isinstance` 순서는 무관하다: 매핑에 있는 세 타입은
    서로의 하위 클래스가 아니다(`ManagedAdapterCapabilityError`만
    `ManagedAdapterValidationError`의 하위이고, `isinstance`가 그대로 잡는다).
    """
    for error_type, code in _VALIDATION_ERROR_CODES.items():
        if isinstance(error, error_type):
            return code
    return ProviderErrorCode.OTHER


class ManagedSandboxAllocationService:
    """할당을 **한 칸씩** 전진시킨다.

    한 번의 `advance()` 는 provider 연산 1회 + 내구 전이 1회만 한다. 루프를
    돌리지 않는 이유는 프로세스가 어느 지점에서 죽어도 원장이 다음 진입점을
    알려주게 하기 위해서다 -- 재시도는 호출자(Celery 조정자)가 다시
    `advance()`를 부르는 것으로 한다.

    타임아웃(`ManagedAdapterTimeoutError`)은 모호성이다: provider가 실제로
    만들었는지 알 수 없으므로 재생성하면 고아 리소스가 생기고 쿼터가 샌다.
    그래서 `RECOVERY_PENDING`으로 커밋하고, 다음 `advance()`는 재발견만
    시도한다 -- `allocate()`를 다시 부르지 않는다. 재발견도 실패하면
    `MANUAL_RECOVERY_REQUIRED`로 멈춘다: 이 시스템은 fail-closed이고
    자동 cross-provider failover를 금지한다.
    """

    def __init__(
        self,
        *,
        repository: ManagedAllocationRepository,
        adapters: Mapping[str, ManagedSandboxAdapter],
        cipher: ManagedSandboxCipher,
        resource_limits: SandboxLimits,
        network_policy: ManagedNetworkPolicy,
        image_identity: str,
        lease_seconds: int,
        clock=None,
    ) -> None:
        self._repository = repository
        self._adapters = dict(adapters)
        self._cipher = cipher
        self._resource_limits = resource_limits
        self._network_policy = network_policy
        self._image_identity = image_identity
        self._lease_seconds = lease_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    async def advance(
        self, allocation_id: str, *, worker_id: str
    ) -> ManagedSandboxAllocation:
        now = self._clock()
        lease = await self._repository.claim_allocation(
            allocation_id, worker_id, now=now, lease_seconds=self._lease_seconds
        )
        plan = await self._repository.read_allocation_plan(allocation_id)
        if plan.allocation.state not in _ADVANCEABLE_STATES:
            raise InvalidManagedSandboxTransition(plan.allocation.state.value)
        adapter = self._adapters[plan.allocation.provider]

        if plan.allocation.state is ManagedSandboxState.ADMITTED:
            return await self._allocate(lease, plan, adapter, now=now)
        return await self._rediscover(lease, plan, adapter, now=now)

    async def _allocate(
        self,
        lease: ManagedAllocationLease,
        plan: AllocationPlan,
        adapter: ManagedSandboxAdapter,
        *,
        now: datetime,
    ) -> ManagedSandboxAllocation:
        # image_identity를 명시적으로 같이 커밋한다 -- 선택 인자라 안 넘기면
        # 컬럼이 계속 NULL로 남고, ManagedAllocationRequest.__post_init__이
        # 그 값을 다시 읽어야 하는 복구 경로에서 빈 값을 거부한다
        # (Task 7 carry-forward, 두 번째로 지적된 문제).
        await self._repository.commit_state(
            lease,
            ManagedSandboxState.ALLOCATING,
            now=now,
            image_identity=self._image_identity,
        )
        try:
            result = await adapter.allocate(self._request_for(plan))
        except ManagedAdapterTimeoutError:
            # 모호하다 -- provider가 만들었는지 알 수 없으므로 재생성하지
            # 않는다. except 순서가 중요하다: ManagedAdapterTimeoutError는
            # ManagedAdapterError의 하위이므로 반드시 먼저 잡아야 한다.
            return await self._repository.commit_state(
                lease,
                ManagedSandboxState.RECOVERY_PENDING,
                now=now,
                error_code=ProviderErrorCode.PROVIDER_TIMEOUT,
            )
        except ManagedAdapterError as error:
            return await self._repository.commit_state(
                lease,
                ManagedSandboxState.FAILED,
                now=now,
                error_code=_error_code(error),
            )
        return await self._commit_result(lease, result, now=now)

    async def _rediscover(
        self,
        lease: ManagedAllocationLease,
        plan: AllocationPlan,
        adapter: ManagedSandboxAdapter,
        *,
        now: datetime,
    ) -> ManagedSandboxAllocation:
        found = await adapter.find_by_idempotency_key(plan.idempotency_key)
        if found is None:
            # 자동 복구를 시도하지 않는다 -- 운영자 승인이 필요하다
            # (fail-closed; cross-provider failover 금지).
            return await self._repository.commit_state(
                lease,
                ManagedSandboxState.MANUAL_RECOVERY_REQUIRED,
                now=now,
                error_code=ProviderErrorCode.PROVIDER_NOT_FOUND,
            )
        result = AllocationResult(
            provider_ref=found.provider_ref,
            ownership_digest=found.ownership_digest,
            state=found.state,
        )
        return await self._commit_result(lease, result, now=now)

    async def _commit_result(
        self,
        lease: ManagedAllocationLease,
        result: AllocationResult,
        *,
        now: datetime,
    ) -> ManagedSandboxAllocation:
        encrypted = self._cipher.encrypt(result.provider_ref)
        return await self._repository.commit_active(
            lease, result, encrypted_ref=encrypted, now=now
        )

    def _request_for(self, plan: AllocationPlan) -> ManagedAllocationRequest:
        allocation = plan.allocation
        return ManagedAllocationRequest(
            allocation_id=allocation.allocation_id,
            idempotency_key=plan.idempotency_key,
            region=allocation.region,
            image_identity=self._image_identity,
            resource_limits=self._resource_limits,
            network_policy=self._network_policy,
            ownership_digest=allocation.ownership_digest,
            absolute_expires_at=allocation.absolute_expires_at,
        )

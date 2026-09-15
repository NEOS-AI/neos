"""펜스된 할당(lease) 계약.

`coding_managed_sandboxes`(마이그레이션 045)에는 `fencing_token`과
`lease_expires_at`만 있고 리스 소유자 컬럼이 없다. 그래서 소유권 증명은
`fencing_token` 단독으로 한다 -- claim이 토큰을 증가시키고, commit은 그 토큰을
WHERE 절에 넣어 낡은 워커가 갱신하는 행 수를 0으로 만든다.
`worker_id`는 이 lease 객체와 로그·메트릭에만 남는 진단용이며 DB에는
저장하지 않는다.
"""

import hashlib
from hmac import compare_digest
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


class ManagedArchiveImportUnavailable(RuntimeError):
    """복구 세대인데 아카이브 복원기가 배선되지 않았다.

    "복원할 것이 없다"가 아니라 "복원할 수단이 없다"이다 -- 전자는 정상이고
    후자는 배선 사고다.
    """


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
        ownership_digest: str | None = None,
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


class PortableArchiveImporter(Protocol):
    """복구 세대의 워크스페이스를 갓 만든 provider 샌드박스에 되살린다.

    `ManagedSandboxAdapter`에 넣지 않았다. 어댑터는 **provider 능력** 표면이고
    공유 conformance 스위트가 그 계약을 강제하는데, 아카이브 복원은 provider
    능력이 아니라 워크스페이스 계층의 일이라 모든 provider 가 구현할 성질의
    것이 아니다.

    **워크스페이스만 되살린다.** PTY 도 백그라운드 프로세스도 재생성하지
    않는다 -- 코딩 런은 기존 내구 루프가 하던 대로 마지막 체크포인트에서만
    이어진다. 죽은 세대의 실행 중 상태를 흉내 내면 사용자는 이어졌다고
    믿지만 실제로는 아무것도 돌고 있지 않다.
    """

    async def import_archive(
        self,
        *,
        allocation: ManagedSandboxAllocation,
        provider_ref: str,
        archive_id: str,
    ) -> None: ...


_ADVANCEABLE_STATES = frozenset(
    {
        ManagedSandboxState.ADMITTED,
        ManagedSandboxState.ALLOCATING,
        ManagedSandboxState.RECOVERY_PENDING,
    }
)

_ADAPTER_ERROR_CODES: dict[type[ManagedAdapterError], ProviderErrorCode] = {
    ManagedAdapterTimeoutError: ProviderErrorCode.PROVIDER_TIMEOUT,
    ManagedAdapterValidationError: ProviderErrorCode.POLICY_DENIED,
    ManagedAdapterOwnershipError: ProviderErrorCode.PROVIDER_AUTH_ERROR,
    ManagedAdapterNotFoundError: ProviderErrorCode.PROVIDER_NOT_FOUND,
}


def provider_error_code(error: ManagedAdapterError) -> ProviderErrorCode:
    """어댑터 실패를 원장에 남길 `ProviderErrorCode`로 옮긴다.

    `isinstance` 순서는 무관하다: 매핑에 있는 네 타입은 서로의 하위 클래스가
    아니다(`ManagedAdapterCapabilityError`만 `ManagedAdapterValidationError`의
    하위이고, `isinstance`가 그대로 잡는다).

    타임아웃도 매핑에 있다 -- 할당 경로(`_allocate`)는 이 함수에 닿기 전에
    타임아웃을 **모호성**으로 먼저 갈라내므로 거기서는 쓰이지 않지만,
    정리 경로(`neos.coding.managed.lifecycle`)에는 재발견 같은 갈래가 없어
    타임아웃도 그냥 재시도 사유로 기록한다. 매핑을 총함수로 두는 편이
    호출자마다 빠진 갈래를 다시 발명하는 것보다 안전하다.
    """
    for error_type, code in _ADAPTER_ERROR_CODES.items():
        if isinstance(error, error_type):
            return code
    return ProviderErrorCode.OTHER


def _ownership_digest_for(allocation: ManagedSandboxAllocation) -> str:
    """할당의 소유권을 증명하는 digest를 결정론적으로 유도한다.

    admission INSERT는 이 컬럼을 NULL로 남긴다 -- 소유권 증명은 provider에
    박아 넣는 값이지 admission 시점엔 provider와 아무 대화도 안 했으니 알 수
    없다. 그래서 ADMITTED 상태의 실제 행에서 `allocation.ownership_digest`를
    읽으면 항상 `None`이고, `ManagedAllocationRequest.__post_init__`이 빈
    값을 거부한다 -- 모든 실제 `advance()`가 어댑터를 부르기도 전에
    `FAILED`/`POLICY_DENIED`로 확정되는 치명적 결함이었다.

    난수가 아니라 변하지 않는 할당 식별자(tenant_id + allocation_id)에서
    순수 함수로 계산한다 -- 같은 할당이면 언제 다시 불러도 같은 값이 나와야
    한다. 재발견 경로가 이 값을 다시 유도해 되찾은 provider 리소스의 소유권을
    확인해야 하기 때문이다(난수였다면 매번 다른 값이 나와 그 확인 자체가
    불가능하다).
    """
    return legacy_ownership_digest(
        tenant_id=allocation.tenant_id, allocation_id=allocation.allocation_id
    )


def legacy_ownership_digest(*, tenant_id: str, allocation_id: str) -> str:
    """할당 층 ownership digest. 정리 서비스가 destroy 허가에 이 값을 쓴다.

    관리형 코딩 provider(`neos.coding.sandbox.managed`)는 vendor object 에 붙기
    전에 이 값과 키 있는 물리 digest 를 **둘 다** 검증한다 -- 이 값은 키가 없어
    혼자서는 소유권 증거가 되지 못한다.
    """
    digest = hashlib.sha256(f"{tenant_id}:{allocation_id}".encode()).hexdigest()
    return f"sha256:{digest}"


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

    `ALLOCATING` 상태로 claim되는 경우도 같은 모호성이다 -- 이전 워커가
    `ALLOCATING`을 커밋한 뒤 종결 커밋(`ACTIVE`) 전에 죽었다는 뜻이라
    provider 호출이 실제로 갔는지 알 수 없다. 그래서 `RECOVERY_PENDING`과
    똑같이 재발견만 한다(`repository._CLAIMABLE_STATES`가 `ALLOCATING`을
    재클레임 대상에 포함하는 이유이기도 하다 -- 안 그러면 이 행은 리퍼 없이
    영원히 멈춘다).
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
        archive_importer: PortableArchiveImporter | None = None,
        clock=None,
    ) -> None:
        self._repository = repository
        self._adapters = dict(adapters)
        self._cipher = cipher
        self._resource_limits = resource_limits
        self._network_policy = network_policy
        self._image_identity = image_identity
        self._lease_seconds = lease_seconds
        self._archive_importer = archive_importer
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

    async def _import_archive(
        self, plan: AllocationPlan, result: AllocationResult
    ) -> None:
        """복구 세대라면 워크스페이스를 되살린다. 아니면 아무 일도 하지 않는다.

        `commit_active` **전에** 부른다. 빈 워크스페이스를 든 샌드박스를
        `ACTIVE`로 적으면 사용자는 복구가 끝난 줄 알고 그 위에서 일한다 --
        그 시점에는 되돌릴 수 없다.
        """
        archive_id = plan.allocation.archive_ref
        if archive_id is None:
            return
        if self._archive_importer is None:
            # 조용히 건너뛰지 않는다. 복원기가 배선되지 않은 채 복구 세대를
            # ACTIVE 로 적으면 사용자는 워크스페이스가 돌아온 줄 알지만 실제로는
            # 빈 샌드박스다 -- 이 저장소가 반복해서 다친 "조용한 degrade"의
            # 정확한 모양이다. 호출자가 잡아 원장에 사유를 남긴다.
            raise ManagedArchiveImportUnavailable(archive_id)
        await self._archive_importer.import_archive(
            allocation=plan.allocation,
            provider_ref=result.provider_ref,
            archive_id=archive_id,
        )

    async def _allocate(
        self,
        lease: ManagedAllocationLease,
        plan: AllocationPlan,
        adapter: ManagedSandboxAdapter,
        *,
        now: datetime,
    ) -> ManagedSandboxAllocation:
        # image_identity·ownership_digest를 명시적으로 같이 커밋한다 -- 둘 다
        # 선택 인자라 안 넘기면 컬럼이 계속 NULL로 남고, 그 값을 다시 읽어야
        # 하는 복구 경로(어댑터 요청 재구성, 재발견 이후 소유권 확인)에서
        # ManagedAllocationRequest.__post_init__이 빈 값을 거부한다
        # (image_identity는 Task 7 carry-forward, 두 번째로 지적된 문제.
        # ownership_digest는 이번 라운드에서 같은 모양으로 드러난 문제 --
        # admission INSERT가 이 컬럼도 NULL로 남기므로 고치지 않으면 모든
        # 실제 ADMITTED 행이 어댑터를 부르기도 전에 FAILED로 확정됐다).
        ownership_digest = _ownership_digest_for(plan.allocation)
        await self._repository.commit_state(
            lease,
            ManagedSandboxState.ALLOCATING,
            now=now,
            image_identity=self._image_identity,
            ownership_digest=ownership_digest,
        )
        try:
            result = await adapter.allocate(
                self._request_for(plan, ownership_digest=ownership_digest)
            )
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
                error_code=provider_error_code(error),
            )
        # 여기서 안 잡히는 예외(어댑터의 버그성 RuntimeError, 또는 뒤이은
        # commit_state/commit_active 자체의 실패 등 ManagedAdapterError
        # 계층 밖의 무언가)는 의도적으로 fail-loud다 -- 넓게 삼키면
        # (예: bare except Exception) 분류 불가능한 실패를 조용히 확정
        # 실패로 둔갑시키는 위험이 더 크다. 이게 안전한 이유는 ALLOCATING이
        # 재클레임 가능해졌기 때문이다(이번 라운드의 두 번째 수정): 이
        # advance() 호출이 예외로 죽어도 행은 ALLOCATING에 리스만 남긴 채
        # 남고, 리스가 만료되면 다음 워커가 재발견 경로로 다시 들어온다.
        return await self._commit_result(lease, plan, result, now=now)

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
        # 되찾은 리소스가 **우리 것임을 증명**한 뒤에만 채택한다.
        # `_ownership_digest_for` 가 난수가 아니라 tenant_id:allocation_id 에서
        # 결정론적으로 유도되는 이유가 이것이고(그 독스트링이 명시한다), 그
        # 확인을 하는 코드가 여기 없었다.
        #
        # 재발견은 idempotency key 로만 찾는다. provider 쪽에서 그 키가 다른
        # 테넌트의 리소스에 붙어 있으면(키 재사용·충돌·provider 버그) 남의
        # 샌드박스를 ACTIVE 로 적고 사용자를 그 안에서 일하게 한다 -- 이
        # 저장소가 fail-closed 로 세운 나머지 전부(승인 없는 부활 금지,
        # 크로스 프로바이더 failover 금지)를 우회하는 경로다.
        #
        # `ownership_verified` 도 함께 본다: digest 가 같아도 어댑터가 대조에
        # 실패했다면 그 값은 우리가 심은 것이 아니라 우연히 같은 문자열일 수
        # 있다. 둘 다 참이어야 한다.
        expected_digest = _ownership_digest_for(plan.allocation)
        if not found.ownership_verified or not compare_digest(
            found.ownership_digest or "", expected_digest
        ):
            # 못 찾은 경우와 같은 처분이다 -- **증명할 수 없는 것을 찾은 것은
            # 못 찾은 것보다 낫지 않다.** 코드는 `_destroy` 가 봉인 해제에
            # 실패했을 때와 같다: 둘 다 "우리 것이라고 말할 근거가 없다"이다.
            return await self._repository.commit_state(
                lease,
                ManagedSandboxState.MANUAL_RECOVERY_REQUIRED,
                now=now,
                error_code=ProviderErrorCode.PROVIDER_AUTH_ERROR,
            )
        result = AllocationResult(
            provider_ref=found.provider_ref,
            ownership_digest=found.ownership_digest,
            state=found.state,
        )
        return await self._commit_result(lease, plan, result, now=now)

    async def _commit_result(
        self,
        lease: ManagedAllocationLease,
        plan: AllocationPlan,
        result: AllocationResult,
        *,
        now: datetime,
    ) -> ManagedSandboxAllocation:
        try:
            await self._import_archive(plan, result)
        except Exception:
            # 복원이 실패했는데 ACTIVE 로 적으면 사용자가 **빈 워크스페이스**
            # 위에서 일하게 된다 -- 그 시점에는 되돌릴 수 없다.
            #
            # 정확히 한 번 재시도하고 그 다음은 운영자에게 넘긴다. 첫 실패
            # (ALLOCATING 에서 왔다)는 `RECOVERY_PENDING`으로 가고, 다음
            # advance()가 재발견 뒤 복원을 다시 시도한다. 그 시도마저 실패하면
            # (RECOVERY_PENDING 에서 왔다) `MANUAL_RECOVERY_REQUIRED`다:
            # 아카이브는 승인 시점에 이미 검증됐으므로 두 번 연속 실패는
            # 재시도로 풀 문제가 아니라는 신호다.
            #
            # 전이표를 그대로 따르는 것이기도 하다 -- RECOVERY_PENDING 은
            # 자기 자신으로 가는 간선이 없다. 여기서 자기 자신을 커밋하면
            # 원장에만 불법 전이가 남는다(Task 6이 같은 함정을 만났다).
            escalate = plan.allocation.state is ManagedSandboxState.RECOVERY_PENDING
            return await self._repository.commit_state(
                lease,
                (
                    ManagedSandboxState.MANUAL_RECOVERY_REQUIRED
                    if escalate
                    else ManagedSandboxState.RECOVERY_PENDING
                ),
                now=now,
                error_code=ProviderErrorCode.ARCHIVE_INVALID,
            )
        encrypted = self._cipher.encrypt(result.provider_ref)
        return await self._repository.commit_active(
            lease, result, encrypted_ref=encrypted, now=now
        )

    def _request_for(
        self, plan: AllocationPlan, *, ownership_digest: str
    ) -> ManagedAllocationRequest:
        # ownership_digest는 호출자(_allocate)가 넘긴다 -- plan.allocation의
        # 값이 아니다. ADMITTED 상태의 실제 행에서는 그 컬럼이 항상 None이라
        # (admission INSERT가 그렇게 남긴다) 여기서 다시 읽으면 image_identity와
        # 똑같은 이유로 요청 검증이 거부한다.
        allocation = plan.allocation
        return ManagedAllocationRequest(
            allocation_id=allocation.allocation_id,
            idempotency_key=plan.idempotency_key,
            region=allocation.region,
            image_identity=self._image_identity,
            resource_limits=self._resource_limits,
            network_policy=self._network_policy,
            ownership_digest=ownership_digest,
            absolute_expires_at=allocation.absolute_expires_at,
        )

"""라이프사이클 조정과 정리(cleanup).

두 가지 일을 한다.

**조정(`ManagedSandboxLifecycleReconciler`)** -- 원장을 훑어 (a) 정리해야 할
할당과 (b) 전진시켜야 할 할당을 **따로** 골라낸다. 둘을 한 튜플로 뭉치지
않는 이유는 후속 작업이 다르기 때문이다: (a)는 `cleanup()`으로, (b)는
`ManagedSandboxAllocationService.advance()`로 간다. 조정은 provider 를 한 번도
부르지 않는다 -- 그래서 provider 장애가 정리 **발견**을 멈추지 못한다
(발견까지 멈추면 장애가 끝난 뒤 밀린 양을 아무도 모른다).

**정리(`ManagedSandboxCleanupService`)** -- 펜스를 새로 잡고, 소유권을 증명한
뒤 destroy 를 부르고, 결과를 시도 기록과 함께 커밋한다. 확정 파괴 **또는
소유권이 증명된 NotFound** 만 `CLEANED`이고, 나머지는 전부 `CLEANUP_RETRY`다.

> **정리는 포기하지 않는다.** 백오프 수열을 다 쓰면 마지막 간격으로 계속
> 재시도한다. 증명되지 않은 provider 리소스를 원장에서 '정리됨'으로 지우면
> 그 리소스는 아무도 모르는 채 계속 돈다 -- 비용이 새고, 그게 정확히 이
> 컨트롤 플레인이 존재하는 이유다. 정체는 `cleanup_slo_seconds` 초과를
> `coding_sandbox_cleanup_age_seconds` 게이지가 드러내는 것으로 다룬다.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from neos.coding.managed.adapters import (
    DestroyResult,
    ManagedAdapterError,
    ManagedAdapterNotFoundError,
    ManagedSandboxAdapter,
)
from neos.coding.managed.allocation import (
    ManagedAllocationLease,
    ManagedSandboxCipher,
    provider_error_code,
)
from neos.coding.managed.domain import (
    ManagedSandboxAllocation,
    ManagedSandboxState,
    ProviderErrorCode,
)


class StaleManagedSandboxGeneration(RuntimeError):
    """메시지가 기대한 세대와 원장의 세대가 다르다 -- 브로커에 남아 있던 옛
    메시지이므로 실행하지 않는다.
    """


class InvalidCleanupState(RuntimeError):
    """정리 대상이 아닌 상태로 `cleanup()`이 불렸다."""


class CleanupAttemptOutcome(StrEnum):
    """`coding_sandbox_cleanup_attempts.outcome` CHECK 제약과 같은 어휘다."""

    CLEANED = "cleaned"
    RETRY = "retry"
    UNCONFIRMED = "unconfirmed"


# 조정자가 일괄 UPDATE 로 CLEANUP_PENDING 에 옮기는 원본 상태.
# `domain._ALLOWED_ALLOCATION_TRANSITIONS` 가 이 간선을 허용해야 한다 --
# 일괄 UPDATE 는 `transition_allocation()`을 거치지 않으므로 전이표가
# 자동으로 지켜주지 않는다. `test_lifecycle.py`가 두 곳의 일치를 강제한다.
#
# ADMITTED/ALLOCATING/RECOVERY_PENDING 은 여기 없다: 전이표가 그 상태에서
# CLEANUP_PENDING 으로 가는 간선을 주지 않는다(아직 provider 리소스가 있다는
# 증거가 없어서 정리할 대상 자체가 불확실하다). 그 상태로 절대 만료가 지난
# 행은 조사가 아니라 **복구** 후보로 나가고, 그것이 붙잡고 있던 쿼터 예약은
# `release_expired_reservations()`가 따로 회수한다(그 상태들은
# `_LIVE_QUOTA_STATES` 밖이거나 곧 벗어난다).
_CLEANUP_SOURCE_STATES = (
    ManagedSandboxState.ACTIVE,
    ManagedSandboxState.SUSPENDED,
)

# 이미 정리 단계에 들어와 있어 `cleanup()`이 이어받을 수 있는 상태.
_CLEANABLE_STATES = frozenset(
    {
        ManagedSandboxState.CLEANUP_PENDING,
        ManagedSandboxState.CLEANUP_RETRY,
    }
)

@dataclass(frozen=True, slots=True)
class CleanupCandidate:
    """정리 대기 중인 할당 하나.

    `provider`·`region`을 같이 싣는 이유는 정리 SLO 게이지가 그 둘을 라벨로
    쓰기 때문이다 -- 할당 id 로 다시 조회하지 않으려고 발견 시점에 들고 온다.
    (allocation_id 는 라벨이 아니다: 카디널리티가 무한하고 플랜이 금지한다.)
    """

    allocation_id: str
    provider: str
    region: str
    pending_since: datetime


@dataclass(frozen=True, slots=True)
class LifecycleCandidates:
    cleanup: tuple[CleanupCandidate, ...]
    recovery: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReconciliationOutcome:
    cleanup: tuple[CleanupCandidate, ...]
    recovery: tuple[str, ...]
    slo_breached: bool


@dataclass(frozen=True, slots=True)
class CleanupOutcome:
    allocation_id: str
    state: ManagedSandboxState
    error_code: ProviderErrorCode | None
    retry_at: datetime | None
    attempt: int


class ManagedLifecycleRepository(Protocol):
    """조정자·정리 서비스가 요구하는 repository 계약."""

    async def discover_lifecycle_candidates(
        self, *, now: datetime, limit: int
    ) -> LifecycleCandidates: ...

    async def claim_allocation(
        self,
        allocation_id: str,
        worker_id: str,
        *,
        now: datetime,
        lease_seconds: int,
    ) -> ManagedAllocationLease: ...

    async def read_allocation(
        self, allocation_id: str
    ) -> ManagedSandboxAllocation: ...

    async def cleanup_attempt_count(self, allocation_id: str) -> int: ...

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
    ) -> ManagedSandboxAllocation: ...


def next_retry_at(
    now: datetime,
    *,
    attempt_index: int,
    backoff_seconds: Sequence[int],
) -> datetime:
    """`attempt_index`번째 실패 뒤 다음 시도 시각.

    수열을 다 쓰면 마지막 값에서 **포화**한다 -- 재시도를 멈추는 것이 아니라
    간격이 더 벌어지지 않을 뿐이다. 모듈 docstring 의 "정리는 포기하지 않는다"
    참조.
    """
    if attempt_index < 0:
        raise ValueError("attempt_index must not be negative")
    if not backoff_seconds:
        raise ValueError("backoff_seconds must not be empty")
    delay = backoff_seconds[min(attempt_index, len(backoff_seconds) - 1)]
    return now + timedelta(seconds=delay)


class ManagedSandboxLifecycleReconciler:
    """정리·복구 후보를 발견하고 정리 적체를 계측한다.

    provider 를 부르지 않는다 -- 발견은 순수하게 원장 조회다.
    """

    def __init__(
        self,
        *,
        repository: ManagedLifecycleRepository,
        cleanup_slo_seconds: int,
        metrics=None,
    ) -> None:
        if cleanup_slo_seconds <= 0:
            raise ValueError("cleanup_slo_seconds must be positive")
        self._repository = repository
        self._cleanup_slo_seconds = cleanup_slo_seconds
        self._metrics = metrics

    async def reconcile(self, *, limit: int, now: datetime) -> ReconciliationOutcome:
        candidates = await self._repository.discover_lifecycle_candidates(
            now=now, limit=limit
        )
        breached = self._publish_backlog_age(candidates.cleanup, now=now)
        return ReconciliationOutcome(
            cleanup=candidates.cleanup,
            recovery=candidates.recovery,
            slo_breached=breached,
        )

    def _publish_backlog_age(
        self, cleanup: Sequence[CleanupCandidate], *, now: datetime
    ) -> bool:
        """(provider, region)별 **가장 오래된** 정리 대기 나이를 게이지로 낸다.

        최댓값을 쓰는 이유는 SLO 가 "가장 오래 밀린 것"에 대한 약속이기
        때문이다 -- 평균을 내면 새로 들어온 건들이 오래된 적체를 가린다.
        """
        oldest: dict[tuple[str, str], float] = {}
        for candidate in cleanup:
            age = (now - candidate.pending_since).total_seconds()
            key = (candidate.provider, candidate.region)
            oldest[key] = max(oldest.get(key, 0.0), age)
        if self._metrics is not None:
            for (provider, region), age in sorted(oldest.items()):
                self._metrics.coding_sandbox_cleanup_age_seconds.labels(
                    provider=provider, region=region
                ).set(age)
        return any(age > self._cleanup_slo_seconds for age in oldest.values())


class ManagedSandboxCleanupService:
    """할당 하나를 정리한다 -- 펜스 획득 → 소유권 증명 → destroy → 시도 기록."""

    def __init__(
        self,
        *,
        repository: ManagedLifecycleRepository,
        adapters: Mapping[str, ManagedSandboxAdapter],
        cipher: ManagedSandboxCipher,
        retry_backoff_seconds: Sequence[int],
        lease_seconds: int,
    ) -> None:
        if not retry_backoff_seconds:
            raise ValueError("retry_backoff_seconds must not be empty")
        self._repository = repository
        self._adapters = dict(adapters)
        self._cipher = cipher
        self._backoff = tuple(retry_backoff_seconds)
        self._lease_seconds = lease_seconds

    async def cleanup(
        self,
        allocation_id: str,
        *,
        worker_id: str,
        now: datetime,
        expected_generation: int | None = None,
    ) -> CleanupOutcome:
        # claim 이 먼저다 -- 행을 잠그고 펜싱 토큰을 올린 **뒤에** 읽어야
        # 판정의 근거와 커밋의 근거가 같은 스냅샷이 된다 (advance()와 같은
        # 순서). claim 자체가 정리 대상이 아닌 상태(ACTIVE 등)와 살아 있는
        # 리스를 이미 걸러낸다.
        lease = await self._repository.claim_allocation(
            allocation_id, worker_id, now=now, lease_seconds=self._lease_seconds
        )
        allocation = await self._repository.read_allocation(allocation_id)
        if allocation.state not in _CLEANABLE_STATES:
            # claim 이 허용하는 집합은 정리 상태보다 넓다(전진 대기 상태도
            # 포함) -- 그쪽으로 온 호출은 여기서 되돌린다.
            raise InvalidCleanupState(allocation.state.value)
        if expected_generation is not None and allocation.generation != expected_generation:
            raise StaleManagedSandboxGeneration(allocation_id)

        attempt_index = await self._repository.cleanup_attempt_count(allocation_id)
        target, outcome, error_code = await self._destroy(allocation)
        retry_at = (
            None
            if target is ManagedSandboxState.CLEANED
            else next_retry_at(
                now, attempt_index=attempt_index, backoff_seconds=self._backoff
            )
        )
        committed = await self._repository.commit_cleanup_outcome(
            lease,
            target=target,
            outcome=outcome,
            error_code=error_code,
            retry_at=retry_at,
            started_at=now,
            now=now,
        )
        return CleanupOutcome(
            allocation_id=allocation_id,
            state=committed.state,
            error_code=committed.error_code,
            retry_at=retry_at,
            attempt=attempt_index + 1,
        )

    async def _destroy(
        self, allocation: ManagedSandboxAllocation
    ) -> tuple[ManagedSandboxState, CleanupAttemptOutcome, ProviderErrorCode | None]:
        adapter = self._adapters.get(allocation.provider)
        if adapter is None:
            # 설정에서 provider 를 빼도 이미 만들어진 리소스는 남아 있다 --
            # 조용히 정리됨으로 적지 않는다.
            return _unconfirmed()
        if allocation.provider_ref is None or not allocation.ownership_digest:
            # 주소도 소유권 증명도 없으면 destroy 를 부를 수 없다. 전이표가
            # ACTIVE/SUSPENDED 에서만 CLEANUP_PENDING 을 허용하므로 정상
            # 경로에서는 생기지 않는 조합이지만, 생겼다면 그것이야말로
            # 조용히 지나가면 안 되는 상태다.
            return _unconfirmed()
        try:
            provider_ref = self._cipher.decrypt(allocation.provider_ref)
        except Exception:
            # 봉인 해제 실패. 재시도해도 열리지 않겠지만 CLEANED 로 적을 수는
            # 없다 -- provider 쪽 리소스는 여전히 살아 있을 수 있다.
            return (
                ManagedSandboxState.CLEANUP_RETRY,
                CleanupAttemptOutcome.UNCONFIRMED,
                ProviderErrorCode.PROVIDER_AUTH_ERROR,
            )
        try:
            result = await adapter.destroy(
                provider_ref, ownership_digest=allocation.ownership_digest
            )
        except ManagedAdapterNotFoundError:
            # `DestroyResult(not_found=True, ownership_verified=True)`와 구별
            # 해야 한다 -- 그쪽은 "우리 것이 사라졌음을 대조로 확인했다"이고,
            # 이쪽은 "대조할 메타데이터 자체가 없다"이다.
            return _unconfirmed()
        except ManagedAdapterError as error:
            return (
                ManagedSandboxState.CLEANUP_RETRY,
                CleanupAttemptOutcome.RETRY,
                provider_error_code(error),
            )
        return _classify_destroy(result)


def _classify_destroy(
    result: DestroyResult,
) -> tuple[ManagedSandboxState, CleanupAttemptOutcome, ProviderErrorCode | None]:
    """provider 응답을 원장 상태로 옮기는 **정책**.

    소유권 증명을 두 갈래 모두에 요구한다 -- NotFound 뿐 아니라 "파괴했다"는
    응답에도. 소유권이 증명되지 않은 파괴는 **남의 리소스를 지웠을 수도
    있다**는 뜻이라, 성공으로 기록하면 우리 리소스는 여전히 남아 있는데
    원장은 정리됐다고 말하게 된다 (플랜 Global Constraints 는 NotFound 에
    대해서만 명시하지만, 같은 논리가 confirmed 에도 그대로 적용된다).
    """
    if result.ownership_verified and (result.confirmed or result.not_found):
        return (
            ManagedSandboxState.CLEANED,
            CleanupAttemptOutcome.CLEANED,
            None,
        )
    return _unconfirmed()


_UnconfirmedVerdict = tuple[
    ManagedSandboxState, CleanupAttemptOutcome, ProviderErrorCode
]


def _unconfirmed() -> _UnconfirmedVerdict:
    return (
        ManagedSandboxState.CLEANUP_RETRY,
        CleanupAttemptOutcome.UNCONFIRMED,
        ProviderErrorCode.CLEANUP_UNCONFIRMED,
    )

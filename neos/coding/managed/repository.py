from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import text

from neos.coding.managed.adapters import AllocationResult
from neos.coding.managed.admission import AdmissionRequest, AdmissionResult
from neos.coding.managed.archive import PortableRecoveryConflict
from neos.coding.managed.allocation import (
    _ADVANCEABLE_STATES,
    AllocationPlan,
    ManagedAllocationLease,
    ManagedSandboxNotClaimable,
    ManagedSandboxNotFound,
    StaleManagedSandboxLease,
)
from neos.coding.managed.domain import (
    AdmissionDecision,
    AdmissionReason,
    ManagedSandboxAllocation,
    ManagedSandboxState,
    ProviderErrorCode,
)
from neos.coding.managed.lifecycle import (
    _CLEANABLE_STATES,
    _CLEANUP_SOURCE_STATES,
    CleanupAttemptOutcome,
    CleanupCandidate,
    LifecycleCandidates,
)
from neos.coding.domain.models import CodingTaskStatus
from neos.coding.persistence.postgres import PostgresCodingService, SessionFactory


# admission 과 복구 승인이 **같은** 정책 버전을 적어야 한다. 두 곳이
# 문자열을 따로 들고 있으면 언젠가 갈라지고, 갈라진 감사 기록은 어느 정책
# 아래서 승인됐는지 답하지 못한다.
MANAGED_POLICY_VERSION = "managed-v1"
_POLICY_VERSION = MANAGED_POLICY_VERSION
_LIVE_QUOTA_STATES = (
    ManagedSandboxState.ALLOCATING.value,
    ManagedSandboxState.ACTIVE.value,
    ManagedSandboxState.SUSPENDED.value,
    ManagedSandboxState.RECOVERY_PENDING.value,
)
# claim_allocation이 허용하는 원본 상태. ACTIVE/SUSPENDED는 이미 리스를 쥔
# 워커가 정상적으로 관리 중인 안정 상태라서 제외한다 -- 리스가 만료돼도 그
# 상태 자체를 재클레임 대상으로 삼지 않는다.
# ALLOCATING은 포함한다 -- commit_state(ALLOCATING)와 종결 커밋
# (commit_active/commit_state) 사이에서 워커가 죽으면(또는 종결 커밋 자체가
# 실패하면) 그 행이 영원히 멈춘다: 이 상태를 재클레임 대상에서 빼면 리스가
# 만료돼도 아무도 다시 못 집는다(리퍼가 따로 없다). 리스가 아직 살아있는
# 워커는 이 WHERE의 lease_expires_at 검사가 그대로 걸러내므로, 그저 느린
# 워커가 있을 뿐이라면 그 워커의 종결 커밋이 fencing_token 불일치로
# StaleManagedSandboxLease가 되고 새 워커는 재발견만 한다(중복 생성 없음) --
# `neos.coding.managed.allocation.ManagedSandboxAllocationService._rediscover`.
# `domain.ManagedSandboxAllocation.claimable_at()`이 이미 이 집합을
# 정의해뒀다 -- 두 곳이 갈라지지 않도록 반드시 함께 바꾼다.
_CLAIMABLE_STATES = (
    ManagedSandboxState.ADMITTED.value,
    ManagedSandboxState.ALLOCATING.value,
    ManagedSandboxState.RECOVERY_PENDING.value,
    ManagedSandboxState.CLEANUP_PENDING.value,
    ManagedSandboxState.CLEANUP_RETRY.value,
)
# 아래 셋은 파생값이다 -- 원본을 각각 `lifecycle`·`allocation` 이 소유하고
# 여기서는 SQL 바인드용 문자열로만 옮긴다. 상태 집합을 이 파일에서 다시
# 손으로 적으면 `_CLAIMABLE_STATES`가 `claimable_at()`과 갈라졌던 것과 같은
# 사고가 반복된다.
_CLEANUP_SOURCE_STATE_VALUES = tuple(
    state.value for state in _CLEANUP_SOURCE_STATES
)
_CLEANABLE_STATE_VALUES = tuple(
    sorted(state.value for state in _CLEANABLE_STATES)
)
_RECOVERY_STATE_VALUES = tuple(sorted(state.value for state in _ADVANCEABLE_STATES))
# `coding_tasks.status`가 이 값이면 샌드박스를 더 붙들고 있을 이유가 없다.
# `workspace_stream_service._TERMINAL_TASK_STATUSES`와 같은 집합이다.
_TERMINAL_TASK_STATUS_VALUES = tuple(
    sorted(
        status.value
        for status in (
            CodingTaskStatus.COMPLETED,
            CodingTaskStatus.FAILED,
            CodingTaskStatus.CANCELLED,
            CodingTaskStatus.EXPIRED,
            CodingTaskStatus.ARCHIVED,
        )
    )
)


class PostgresManagedSandboxRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def preflight_quota(
        self,
        request: AdmissionRequest,
        *,
        now: datetime,
        concurrent_quota: int,
        daily_quota: int,
        daily_active_seconds_quota: int,
        archive_bytes_quota: int,
        daily_cost_micros_quota: int,
    ) -> AdmissionReason | None:
        _require_timezone_aware("preflight time", now)
        _require_positive_quotas(
            concurrent_quota=concurrent_quota,
            daily_quota=daily_quota,
            daily_active_seconds_quota=daily_active_seconds_quota,
            archive_bytes_quota=archive_bytes_quota,
            daily_cost_micros_quota=daily_cost_micros_quota,
        )
        async with await self._session_factory() as session:
            async with session.begin():
                usage = await _read_quota_usage(
                    session,
                    tenant_id=request.tenant_id,
                    now=now,
                )
        return _quota_reason(
            request,
            usage=usage,
            concurrent_quota=concurrent_quota,
            daily_quota=daily_quota,
            daily_active_seconds_quota=daily_active_seconds_quota,
            archive_bytes_quota=archive_bytes_quota,
            daily_cost_micros_quota=daily_cost_micros_quota,
        )

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
    ) -> AdmissionResult:
        _require_timezone_aware("admission time", now)
        if reservation_expires_at is not None:
            _require_timezone_aware("reservation expiry", reservation_expires_at)
            if reservation_expires_at <= now:
                raise ValueError("reservation expiry must be in the future")
        if reevaluate_after is not None:
            _require_timezone_aware("reevaluation time", reevaluate_after)
        _require_positive_quotas(
            concurrent_quota=concurrent_quota,
            daily_quota=daily_quota,
            daily_active_seconds_quota=daily_active_seconds_quota,
            archive_bytes_quota=archive_bytes_quota,
            daily_cost_micros_quota=daily_cost_micros_quota,
        )
        if decision is AdmissionDecision.ADMITTED and reservation_expires_at is None:
            raise ValueError("admitted decision requires a reservation expiry")
        if decision is AdmissionDecision.DENIED and reservation_expires_at is not None:
            raise ValueError("denied decision cannot reserve quota")

        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        SELECT pg_advisory_xact_lock(
                            hashtextextended(:tenant_id, 0)
                        )
                        """
                    ),
                    {"tenant_id": request.tenant_id},
                )
                replay = await self._read_admission(
                    session,
                    tenant_id=request.tenant_id,
                    idempotency_key=request.idempotency_key,
                )
                if replay is not None:
                    return self._from_row(replay, created=False)

                final_decision = decision
                final_reason = reason
                final_reevaluate = reevaluate_after
                if decision is AdmissionDecision.ADMITTED:
                    usage = await _read_quota_usage(
                        session,
                        tenant_id=request.tenant_id,
                        now=now,
                    )
                    quota_reason = _quota_reason(
                        request,
                        usage=usage,
                        concurrent_quota=concurrent_quota,
                        daily_quota=daily_quota,
                        daily_active_seconds_quota=daily_active_seconds_quota,
                        archive_bytes_quota=archive_bytes_quota,
                        daily_cost_micros_quota=daily_cost_micros_quota,
                    )
                    if quota_reason is not None:
                        final_decision = AdmissionDecision.DENIED
                        final_reason = quota_reason
                        final_reevaluate = reevaluate_after or reservation_expires_at

                admission_id = f"msa_{uuid4().hex}"
                allocation_id = (
                    f"msb_{uuid4().hex}"
                    if final_decision is AdmissionDecision.ADMITTED
                    else None
                )
                reservation_id = (
                    f"msr_{uuid4().hex}"
                    if final_decision is AdmissionDecision.ADMITTED
                    else None
                )
                admitted = final_decision is AdmissionDecision.ADMITTED
                insert = await session.execute(
                    text(
                        """
                        INSERT INTO coding_sandbox_admissions (
                            admission_id, idempotency_key, tenant_id, task_id,
                            provider, region, policy_version, decision, reason,
                            reservation_id, reservation_expires_at,
                            reserved_active_seconds, reserved_archive_bytes,
                            reserved_cost_micros, reservation_state,
                            actual_active_seconds, actual_archive_bytes,
                            actual_cost_micros, reservation_settled_at,
                            reservation_released_at, reevaluate_at, created_at
                        ) VALUES (
                            :admission_id, :idempotency_key, :tenant_id, :task_id,
                            :provider, :region, :policy_version, :decision, :reason,
                            :reservation_id, :reservation_expires_at,
                            :reserved_active_seconds, :reserved_archive_bytes,
                            :reserved_cost_micros, :reservation_state,
                            0, 0, 0, NULL, NULL, :reevaluate_at, :now
                        )
                        ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
                        RETURNING admission_id
                        """
                    ),
                    {
                        "admission_id": admission_id,
                        "idempotency_key": request.idempotency_key,
                        "tenant_id": request.tenant_id,
                        "task_id": request.task_id,
                        "provider": request.provider,
                        "region": request.region,
                        "policy_version": _POLICY_VERSION,
                        "decision": final_decision.value,
                        "reason": final_reason.value,
                        "reservation_id": reservation_id,
                        "reservation_expires_at": (
                            reservation_expires_at if admitted else None
                        ),
                        "reserved_active_seconds": (
                            request.estimated_active_seconds if admitted else 0
                        ),
                        "reserved_archive_bytes": (
                            request.estimated_archive_bytes if admitted else 0
                        ),
                        "reserved_cost_micros": (
                            request.estimated_cost_micros if admitted else 0
                        ),
                        "reservation_state": ("reserved" if admitted else "unreserved"),
                        "reevaluate_at": (None if admitted else final_reevaluate),
                        "now": now,
                    },
                )
                inserted = insert.first()
                if inserted is None:
                    replay = await self._read_admission(
                        session,
                        tenant_id=request.tenant_id,
                        idempotency_key=request.idempotency_key,
                    )
                    if replay is None:
                        raise RuntimeError("admission conflict could not be replayed")
                    return self._from_row(replay, created=False)
                admission_id = str(inserted[0])

                if admitted:
                    assert allocation_id is not None
                    assert reservation_expires_at is not None
                    absolute_expires_at = max(
                        reservation_expires_at,
                        now
                        + timedelta(seconds=max(request.estimated_active_seconds, 1)),
                    )
                    await session.execute(
                        text(
                            """
                            INSERT INTO coding_managed_sandboxes (
                                allocation_id, admission_id, tenant_id, task_id,
                                run_id, provider, region, provider_ref,
                                ownership_digest, state, generation,
                                fencing_token, lease_expires_at,
                                absolute_expires_at, version, error_code,
                                snapshot_ref, archive_ref, image_identity,
                                toolchain_identity, created_at, updated_at,
                                cleaned_at
                            ) VALUES (
                                :allocation_id, :admission_id, :tenant_id,
                                :task_id, :run_id, :provider, :region, NULL,
                                NULL, :state, 1, 1, NULL, :absolute_expires_at,
                                1, NULL, NULL, NULL, NULL, NULL, :now, :now, NULL
                            )
                            """
                        ),
                        {
                            "allocation_id": allocation_id,
                            "admission_id": admission_id,
                            "tenant_id": request.tenant_id,
                            "task_id": request.task_id,
                            "run_id": request.run_id,
                            "provider": request.provider,
                            "region": request.region,
                            "state": ManagedSandboxState.ADMITTED.value,
                            "absolute_expires_at": absolute_expires_at,
                            "now": now,
                        },
                    )
                row = await self._read_admission(
                    session,
                    tenant_id=request.tenant_id,
                    idempotency_key=request.idempotency_key,
                )
                if row is None:
                    raise RuntimeError("created admission could not be read")
                return self._from_row(row, created=True)

    async def settle_reservation(
        self,
        allocation_id: str,
        *,
        active_seconds: int,
        archive_bytes: int,
        cost_micros: int,
        now: datetime,
    ) -> bool:
        _require_timezone_aware("settlement time", now)
        _require_nonnegative_usage(
            active_seconds=active_seconds,
            archive_bytes=archive_bytes,
            cost_micros=cost_micros,
        )
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        SELECT pg_advisory_xact_lock(
                            hashtextextended(allocation.tenant_id, 0)
                        )
                        FROM coding_managed_sandboxes AS allocation
                        JOIN coding_sandbox_admissions AS admission
                          ON admission.admission_id = allocation.admission_id
                        WHERE allocation.allocation_id = :allocation_id
                          AND admission.reservation_state = 'reserved'
                        """
                    ),
                    {"allocation_id": allocation_id},
                )
                result = await session.execute(
                    text(
                        """
                        UPDATE coding_sandbox_admissions AS admission
                        SET reservation_state = 'settled',
                            actual_active_seconds = :active_seconds,
                            actual_archive_bytes = :archive_bytes,
                            actual_cost_micros = :cost_micros,
                            reservation_settled_at = :now,
                            reservation_released_at = NULL
                        FROM coding_managed_sandboxes AS allocation
                        WHERE allocation.allocation_id = :allocation_id
                          AND allocation.admission_id = admission.admission_id
                          AND admission.reservation_state = 'reserved'
                        RETURNING allocation.allocation_id
                        """
                    ),
                    {
                        "allocation_id": allocation_id,
                        "active_seconds": active_seconds,
                        "archive_bytes": archive_bytes,
                        "cost_micros": cost_micros,
                        "now": now,
                    },
                )
        return result.first() is not None

    async def release_expired_reservations(
        self, *, now: datetime, limit: int
    ) -> Sequence[str]:
        _require_timezone_aware("release time", now)
        if not 1 <= limit <= 1000:
            raise ValueError("release limit must be between 1 and 1000")
        async with await self._session_factory() as session:
            async with session.begin():
                locked = await session.execute(
                    text(
                        """
                        WITH candidate_tenants AS MATERIALIZED (
                            SELECT DISTINCT admission.tenant_id
                            FROM coding_sandbox_admissions AS admission
                            JOIN coding_managed_sandboxes AS allocation
                              ON allocation.admission_id =
                                 admission.admission_id
                            WHERE admission.reservation_state = 'reserved'
                              AND admission.reservation_expires_at <= :now
                              AND allocation.state <> ALL(
                                  CAST(:live_states AS VARCHAR[])
                              )
                            ORDER BY admission.tenant_id
                            LIMIT :limit
                        )
                        SELECT candidate.tenant_id,
                               pg_advisory_xact_lock(
                                   hashtextextended(candidate.tenant_id, 0)
                               )
                        FROM candidate_tenants AS candidate
                        ORDER BY candidate.tenant_id
                        """
                    ),
                    {
                        "now": now,
                        "limit": limit,
                        "live_states": list(_LIVE_QUOTA_STATES),
                    },
                )
                tenant_ids = [str(row[0]) for row in locked.all()]
                if not tenant_ids:
                    return []
                result = await session.execute(
                    text(
                        """
                        WITH candidates AS (
                            SELECT admission.admission_id
                            FROM coding_sandbox_admissions AS admission
                            JOIN coding_managed_sandboxes AS allocation
                              ON allocation.admission_id =
                                 admission.admission_id
                            WHERE admission.reservation_state = 'reserved'
                              AND admission.reservation_expires_at <= :now
                              AND admission.tenant_id =
                                  ANY(CAST(:tenant_ids AS VARCHAR[]))
                              AND allocation.state <> ALL(
                                  CAST(:live_states AS VARCHAR[])
                              )
                            ORDER BY admission.reservation_expires_at,
                                     admission.admission_id
                            LIMIT :limit
                            FOR UPDATE OF admission, allocation SKIP LOCKED
                        ), released AS (
                            UPDATE coding_sandbox_admissions AS admission
                            SET reservation_state = 'released',
                                reservation_released_at = :now,
                                reservation_settled_at = NULL
                            FROM candidates
                            WHERE admission.admission_id =
                                  candidates.admission_id
                              AND admission.reservation_state = 'reserved'
                            RETURNING admission.admission_id
                        )
                        SELECT allocation.allocation_id
                        FROM released
                        JOIN coding_managed_sandboxes AS allocation
                          ON allocation.admission_id = released.admission_id
                        ORDER BY allocation.allocation_id
                        """
                    ),
                    {
                        "now": now,
                        "limit": limit,
                        "tenant_ids": tenant_ids,
                        "live_states": list(_LIVE_QUOTA_STATES),
                    },
                )
                rows = result.all()
        return [str(row[0]) for row in rows]

    async def claim_allocation(
        self,
        allocation_id: str,
        worker_id: str,
        *,
        now: datetime,
        lease_seconds: int,
    ) -> ManagedAllocationLease:
        """claim 가능한 상태이면서 리스가 비어있거나 만료된 경우에만 펜싱
        토큰을 올려 클레임한다.

        `UPDATE`가 대상 행을 잠그므로 별도 `SELECT ... FOR UPDATE`가 필요
        없다. 만료된 리스는 같은 조건이 통과시키므로 별도의 reclaim 경로가
        필요 없다.

        실패하면 원인을 구분해서 알린다 -- "이미 끝났거나 다른 단계에 있다"
        (`ManagedSandboxNotClaimable`)와 "누군가 지금 쥐고 있다"
        (`StaleManagedSandboxLease`)는 호출자가 재시도할지 포기할지 다르게
        판단해야 하는 서로 다른 상황이다. 이 UPDATE 자체는 두 조건을 한
        WHERE 절에서 원자적으로 판정하므로, 실패 시에만 원인 구분용으로
        같은 트랜잭션 안에서 한 번 더 읽는다 -- 소유권 판정 자체는 여전히
        이 UPDATE 하나가 한다.

        요청한 `lease_seconds`가 `absolute_expires_at`을 넘기면 SQL에서
        `LEAST()`로 클램프한다 -- 이게 바로 이 설계가 존재하는 이유인, 수명
        막바지에 좌초된 `ALLOCATING`을 회수하는 상황이다. 클램프하지 않으면
        045의 CHECK 제약(`lease_expires_at <= absolute_expires_at`)에 걸려
        원시 `IntegrityError`가 새고, 아무도 리스를 쥐고 있지 않은데도
        `StaleManagedSandboxLease`처럼 재시도를 유도하는 오해의 소지가 있는
        예외를 던지게 된다. 반환하는 리스의 `expires_at`도 클램프된 값을
        그대로 반영해야 리스 객체가 실제 만료 시점을 정직하게 말한다.
        """
        _require_timezone_aware("claim time", now)
        if lease_seconds < 1:
            raise ValueError("lease_seconds_invalid")
        requested_expires_at = now + timedelta(seconds=lease_seconds)
        async with await self._session_factory() as session:
            async with session.begin():
                row = (
                    await session.execute(
                        text(
                            """
                            UPDATE coding_managed_sandboxes
                               SET fencing_token = fencing_token + 1,
                                   lease_expires_at =
                                       LEAST(:expires_at, absolute_expires_at),
                                   version = version + 1,
                                   updated_at = :now
                             WHERE allocation_id = :allocation_id
                               AND state = ANY(CAST(:claimable_states AS VARCHAR[]))
                               AND (
                                   lease_expires_at IS NULL
                                   OR lease_expires_at <= :now
                               )
                         RETURNING fencing_token, lease_expires_at
                            """
                        ),
                        {
                            "allocation_id": allocation_id,
                            "expires_at": requested_expires_at,
                            "now": now,
                            "claimable_states": list(_CLAIMABLE_STATES),
                        },
                    )
                ).one_or_none()
                if row is None:
                    await _raise_claim_failure(session, allocation_id)
        return ManagedAllocationLease(
            allocation_id=allocation_id,
            worker_id=worker_id,
            fencing_token=row.fencing_token,
            expires_at=row.lease_expires_at,
        )

    async def commit_state(
        self,
        lease: ManagedAllocationLease,
        target: ManagedSandboxState,
        *,
        now: datetime,
        error_code: ProviderErrorCode | None = None,
        image_identity: str | None = None,
        ownership_digest: str | None = None,
    ) -> ManagedSandboxAllocation:
        """상태 전이를 커밋한다.

        `target`이 `CLEANED`면 `domain.transition_allocation()`이 메모리에서
        하는 클리어링(provider_ref/ownership_digest/lease_expires_at를 비우기)을
        쓰기 경로에도 그대로 반영한다 -- 045의 CHECK 제약이 CLEANED 행에
        그 값들이 NULL이고 `cleaned_at`이 NOT NULL이길 요구하므로, 반영하지
        않으면 UPDATE 자체가 거부된다.

        `image_identity`·`ownership_digest`는 선택 인자다 -- 각각 사용할
        이미지와 소유권 증명이 정해지는 시점(전형적으로 둘 다 ALLOCATING으로
        전이할 때)에 호출자가 넘기면 같이 쓴다. 컬럼명을 키로 쓰는 dict로
        SET 절을 조립한다 -- 같은 컬럼에 두 번 대입하면(예: 호출자가
        `ownership_digest`를 주면서 동시에 `target=CLEANED`인 조합) `UPDATE`
        문 자체가 SQL 단계에서 거부되는데, dict는 나중 대입이 앞의 것을
        덮어써서 그런 조합이 애초에 안 생긴다.
        """
        assignments: dict[str, str] = {
            "state": "state = :state",
            "error_code": "error_code = :error_code",
        }
        params: dict[str, object] = {"state": target.value, "error_code": error_code}
        if image_identity is not None:
            assignments["image_identity"] = "image_identity = :image_identity"
            params["image_identity"] = image_identity
        if ownership_digest is not None:
            assignments["ownership_digest"] = "ownership_digest = :ownership_digest"
            params["ownership_digest"] = ownership_digest
        if target is ManagedSandboxState.CLEANED:
            assignments["provider_ref"] = "provider_ref = NULL"
            assignments["ownership_digest"] = "ownership_digest = NULL"
            assignments["lease_expires_at"] = "lease_expires_at = NULL"
            assignments["cleaned_at"] = "cleaned_at = :now"
            params.pop("ownership_digest", None)
        return await self._commit(
            lease,
            now=now,
            assignments=", ".join(assignments.values()),
            params=params,
        )

    async def commit_active(
        self,
        lease: ManagedAllocationLease,
        result: AllocationResult,
        *,
        encrypted_ref: bytes,
        now: datetime,
    ) -> ManagedSandboxAllocation:
        return await self._commit(
            lease,
            now=now,
            assignments=(
                "state = :state, provider_ref = :provider_ref, "
                "ownership_digest = :ownership_digest, error_code = NULL"
            ),
            params={
                "state": result.state.value,
                "provider_ref": encrypted_ref,
                "ownership_digest": result.ownership_digest,
            },
        )

    async def _commit(
        self,
        lease: ManagedAllocationLease,
        *,
        now: datetime,
        assignments: str,
        params: dict[str, object],
    ) -> ManagedSandboxAllocation:
        """`fencing_token`을 WHERE에 넣어 낡은 리스를 든 워커의 commit을 거른다.

        `assignments`는 호출자(이 클래스 안)가 넘기는 리터럴 문자열만 들어간다
        (사용자 입력이 아니다). 값은 전부 바인드 파라미터다.
        """
        _require_timezone_aware("commit time", now)
        async with await self._session_factory() as session:
            async with session.begin():
                row = await _execute_fenced_commit(
                    session, lease, now=now, assignments=assignments, params=params
                )
        if row is None:
            raise StaleManagedSandboxLease(lease.allocation_id)
        return _allocation_from_row(row)

    async def read_allocation_plan(self, allocation_id: str) -> AllocationPlan:
        """할당 행과 admission 행을 조인해 어댑터 요청에 필요한 최소 뷰를 읽는다.

        `resource_limits`·`network_policy`는 여기 없다 -- DB에 없는 컬럼이고
        (045 확인), 정책이지 상태가 아니라서 호출자가 config에서 채운다.
        `idempotency_key`만 admission 소유라 조인이 필요하다.
        """
        async with await self._session_factory() as session:
            async with session.begin():
                row = (
                    await session.execute(
                        text(
                            """
                            SELECT s.allocation_id, s.tenant_id, s.task_id,
                                   s.run_id, s.provider, s.region,
                                   s.provider_ref, s.ownership_digest,
                                   s.state, s.generation, s.fencing_token,
                                   s.lease_expires_at, s.absolute_expires_at,
                                   s.version, s.error_code, s.snapshot_ref,
                                   s.archive_ref, s.image_identity,
                                   a.idempotency_key
                              FROM coding_managed_sandboxes AS s
                              JOIN coding_sandbox_admissions AS a
                                ON a.admission_id = s.admission_id
                             WHERE s.allocation_id = :allocation_id
                            """
                        ),
                        {"allocation_id": allocation_id},
                    )
                ).one_or_none()
        if row is None:
            raise ManagedSandboxNotFound(allocation_id)
        return AllocationPlan(
            allocation=_allocation_from_row(row),
            idempotency_key=str(row.idempotency_key),
        )

    async def read_allocation(self, allocation_id: str) -> ManagedSandboxAllocation:
        """할당 행 하나를 읽는다 (admission 조인 없이).

        정리 경로는 `idempotency_key`가 필요 없다 -- destroy 는 봉인된
        `provider_ref`와 `ownership_digest`만 쓴다. 조인을 빼면 admission 이
        아직 없는 행도 읽히지만, 045의 FK 가 그런 행을 애초에 못 만들게 한다.
        """
        async with await self._session_factory() as session:
            async with session.begin():
                row = (
                    await session.execute(
                        text(
                            """
                            SELECT allocation_id, tenant_id, task_id, run_id,
                                   provider, region, provider_ref,
                                   ownership_digest, state, generation,
                                   fencing_token, lease_expires_at,
                                   absolute_expires_at, version, error_code,
                                   snapshot_ref, archive_ref, image_identity
                              FROM coding_managed_sandboxes
                             WHERE allocation_id = :allocation_id
                            """
                        ),
                        {"allocation_id": allocation_id},
                    )
                ).one_or_none()
        if row is None:
            raise ManagedSandboxNotFound(allocation_id)
        return _allocation_from_row(row)

    async def read_owner_sandbox(
        self, *, task_id: str, owner_id: str
    ) -> tuple[ManagedSandboxAllocation, datetime] | None:
        """소유자 범위로 살아 있는 할당 하나를 읽는다. `updated_at`을 같이 낸다.

        **소유권 검사가 질의 안에 있다.** 먼저 읽고 나중에 비교하면 "그
        태스크는 존재한다"가 응답 시간과 분기로 샌다 -- 비소유자는 없는 것과
        구별할 수 없어야 한다.

        `cleaned`/`failed` 행은 제외하지 않는다: 사용자가 "정리됐다"를 보는
        것도 정당한 답이다. 대신 045의 부분 유니크 인덱스가 살아 있는 행을
        하나로 강제하므로, 정리된 세대가 여럿 쌓여도 가장 최근 것을 고른다.
        """
        async with await self._session_factory() as session:
            async with session.begin():
                row = (
                    await session.execute(
                        text(
                            """
                            SELECT sandbox.allocation_id, sandbox.tenant_id,
                                   sandbox.task_id, sandbox.run_id,
                                   sandbox.provider, sandbox.region,
                                   sandbox.provider_ref,
                                   sandbox.ownership_digest, sandbox.state,
                                   sandbox.generation, sandbox.fencing_token,
                                   sandbox.lease_expires_at,
                                   sandbox.absolute_expires_at, sandbox.version,
                                   sandbox.error_code, sandbox.snapshot_ref,
                                   sandbox.archive_ref, sandbox.image_identity,
                                   sandbox.updated_at
                              FROM coding_managed_sandboxes AS sandbox
                              JOIN coding_tasks AS task
                                ON task.task_id = sandbox.task_id
                             WHERE sandbox.task_id = :task_id
                               AND task.owner_id = :owner_id
                               AND task.deleted_at IS NULL
                             ORDER BY sandbox.generation DESC,
                                      sandbox.updated_at DESC
                             LIMIT 1
                            """
                        ),
                        {"task_id": task_id, "owner_id": owner_id},
                    )
                ).one_or_none()
        if row is None:
            return None
        return _allocation_from_row(row), row.updated_at

    async def clear_cleanup_retry(
        self, allocation_id: str, *, now: datetime
    ) -> ManagedSandboxState:
        """다음 정리 시도를 **지금** 가능하게 만든다 (관리자 조치).

        상태를 바꾸지 않는다 -- 백오프만 걷어낸다. 조정자의 정리 후보 질의가
        `next_retry_at > now` 인 시도 행이 있으면 그 할당을 건너뛰므로, 그
        미래 시각을 지우면 다음 주기가 바로 집는다.

        상태 검사가 먼저다. 정리 단계가 아닌 할당의 시도 행을 건드리면
        원장이 "정리 중"이라고 말하는데 실제로는 아무 단계도 아닌 상태가 된다.
        """
        _require_timezone_aware("retry clear time", now)
        async with await self._session_factory() as session:
            async with session.begin():
                state = (
                    await session.execute(
                        text(
                            """
                            SELECT state
                              FROM coding_managed_sandboxes
                             WHERE allocation_id = :allocation_id
                               FOR UPDATE
                            """
                        ),
                        {"allocation_id": allocation_id},
                    )
                ).one_or_none()
                if state is None:
                    raise ManagedSandboxNotFound(allocation_id)
                if state.state not in _CLEANABLE_STATE_VALUES:
                    raise ManagedSandboxNotClaimable(allocation_id)
                await session.execute(
                    text(
                        """
                        UPDATE coding_sandbox_cleanup_attempts
                           SET next_retry_at = NULL
                         WHERE allocation_id = :allocation_id
                           AND next_retry_at > :now
                        """
                    ),
                    {"allocation_id": allocation_id, "now": now},
                )
        return ManagedSandboxState(state.state)

    async def set_archive_ref(
        self, allocation_id: str, *, archive_id: str, now: datetime
    ) -> ManagedSandboxAllocation:
        """할당이 어떤 아카이브를 들고 있는지 기록한다.

        상태를 바꾸지 않는다 -- 아카이브를 뜨는 것은 라이프사이클 전이가
        아니라 부수적인 기록이다. 펜스도 요구하지 않는다: 이 값은 복구가
        **읽기만** 하고, 최신 아카이브로 덮어쓰는 것이 언제나 옳다.
        """
        _require_timezone_aware("archive time", now)
        async with await self._session_factory() as session:
            async with session.begin():
                row = (
                    await session.execute(
                        text(
                            """
                            UPDATE coding_managed_sandboxes
                               SET archive_ref = :archive_ref,
                                   version = version + 1,
                                   updated_at = :now
                             WHERE allocation_id = :allocation_id
                         RETURNING allocation_id, tenant_id, task_id, run_id,
                                   provider, region, provider_ref,
                                   ownership_digest, state, generation,
                                   fencing_token, lease_expires_at,
                                   absolute_expires_at, version, error_code,
                                   snapshot_ref, archive_ref, image_identity
                            """
                        ),
                        {
                            "allocation_id": allocation_id,
                            "archive_ref": archive_id,
                            "now": now,
                        },
                    )
                ).one_or_none()
        if row is None:
            raise ManagedSandboxNotFound(allocation_id)
        return _allocation_from_row(row)

    async def cleanup_attempt_count(self, allocation_id: str) -> int:
        """이 할당에 대해 이미 기록된 정리 시도 수 -- 백오프 인덱스가 된다.

        시도 행이 append-only 라서 개수가 곧 인덱스다. 별도 카운터 컬럼을
        두지 않는 이유는 그것이 시도 기록과 갈라질 수 있기 때문이다.
        """
        async with await self._session_factory() as session:
            async with session.begin():
                count = (
                    await session.execute(
                        text(
                            """
                            SELECT COUNT(*)
                              FROM coding_sandbox_cleanup_attempts
                             WHERE allocation_id = :allocation_id
                            """
                        ),
                        {"allocation_id": allocation_id},
                    )
                ).scalar_one()
        return int(count)

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
        """상태 전이와 시도 기록을 **한 트랜잭션**에서 커밋한다.

        갈라지면 원장이 거짓말을 한다 -- 상태만 남으면 백오프 인덱스가
        전진하지 않아 정리가 5초마다 provider 를 때리고, 시도만 남으면
        상태가 영원히 CLEANUP_PENDING 이라 다음 조정이 같은 일을 또 시킨다.

        전이 자체는 `commit_state()`와 같은 펜싱 UPDATE 를 쓴다 -- 낡은
        리스를 든 워커의 커밋은 0행을 갱신하고 `StaleManagedSandboxLease`가
        된다. 그 경우 시도 행도 쓰이지 않는다 (예외가 트랜잭션을 되돌린다).

        리스는 두 결과 모두에서 비운다. CLEANED 는 045의 CHECK 가 요구해서고,
        CLEANUP_RETRY 는 다음 시도가 리스 만료를 기다릴 이유가 없어서다 --
        다음 시각은 `next_retry_at`이 정한다.
        """
        _require_timezone_aware("cleanup commit time", now)
        _require_timezone_aware("cleanup start time", started_at)
        assignments = [
            "state = :state",
            "error_code = :error_code",
            "lease_expires_at = NULL",
        ]
        params: dict[str, object] = {
            "state": target.value,
            "error_code": error_code.value if error_code is not None else None,
        }
        if target is ManagedSandboxState.CLEANED:
            assignments.extend(
                (
                    "provider_ref = NULL",
                    "ownership_digest = NULL",
                    "cleaned_at = :now",
                )
            )
        async with await self._session_factory() as session:
            async with session.begin():
                row = await _execute_fenced_commit(
                    session,
                    lease,
                    now=now,
                    assignments=", ".join(assignments),
                    params=params,
                )
                if row is None:
                    raise StaleManagedSandboxLease(lease.allocation_id)
                await session.execute(
                    text(
                        """
                        INSERT INTO coding_sandbox_cleanup_attempts (
                            cleanup_attempt_id, allocation_id,
                            claimed_fencing_token, outcome, error_code,
                            next_retry_at, started_at, finished_at
                        ) VALUES (
                            :cleanup_attempt_id, :allocation_id,
                            :claimed_fencing_token, :outcome, :error_code,
                            :next_retry_at, :started_at, :finished_at
                        )
                        """
                    ),
                    {
                        "cleanup_attempt_id": f"msc_{uuid4().hex}",
                        "allocation_id": lease.allocation_id,
                        "claimed_fencing_token": lease.fencing_token,
                        "outcome": outcome.value,
                        "error_code": (
                            error_code.value if error_code is not None else None
                        ),
                        "next_retry_at": retry_at,
                        "started_at": started_at,
                        "finished_at": now,
                    },
                )
        return _allocation_from_row(row)

    async def approve_recovery_generation(
        self,
        *,
        allocation_id: str,
        operator_id: str,
        archive_id: str,
        checksum: str,
        policy_version: str,
        lifetime_seconds: int,
        reservation_lease_seconds: int,
        now: datetime,
    ) -> ManagedSandboxAllocation:
        """원본 세대를 종결하고 generation + 1 을 **한 트랜잭션**에서 만든다.

        갈라질 수 없다. 045의 부분 유니크 인덱스
        (`idx_coding_managed_sandboxes_current_task`)가 태스크당 살아 있는
        할당을 하나로 강제하므로, 원본을 먼저 `FAILED`로 닫지 않으면 새 행
        INSERT 가 인덱스에 걸린다. 반대로 원본만 닫고 새 행을 못 만들면
        태스크는 샌드박스 없는 상태로 남는다.

        멱등하다. 새 admission 의 `idempotency_key`가
        `recovery:{allocation_id}:g{n}` 으로 **결정론적**이라, 같은 승인이 두 번
        오면 `UNIQUE (tenant_id, idempotency_key)`가 두 번째를 막는다 -- 운영자가
        버튼을 두 번 눌러 세대가 둘 생기는 일이 없다.

        쿼터는 원본의 예약액을 그대로 옮긴다. 살아 있는 할당 수가 순증하지
        않기 때문이다 -- 원본이 같은 트랜잭션에서 `FAILED`(=`_LIVE_QUOTA_STATES`
        밖)로 닫힌다. 새 `reservation_id`와 새 리스를 주므로 예약 자체는
        신선하다.

        감사 기록은 `coding_events`에 남긴다. seq 할당을 여기서 다시 만들지
        않고 `PostgresCodingService.append_in_session()`을 그대로 쓴다.
        본문은 절대 싣지 않는다 -- 식별자·체크섬·정책 버전·결과뿐이다.
        """
        _require_timezone_aware("approval time", now)
        if lifetime_seconds <= 0 or reservation_lease_seconds <= 0:
            raise ValueError("recovery lifetimes must be positive")
        async with await self._session_factory() as session:
            async with session.begin():
                source = (
                    await session.execute(
                        text(
                            """
                            SELECT sandbox.allocation_id, sandbox.tenant_id,
                                   sandbox.task_id, sandbox.run_id,
                                   sandbox.provider, sandbox.region,
                                   sandbox.state, sandbox.generation,
                                   sandbox.image_identity,
                                   sandbox.toolchain_identity,
                                   admission.reserved_active_seconds,
                                   admission.reserved_archive_bytes,
                                   admission.reserved_cost_micros
                              FROM coding_managed_sandboxes AS sandbox
                              JOIN coding_sandbox_admissions AS admission
                                ON admission.admission_id = sandbox.admission_id
                             WHERE sandbox.allocation_id = :allocation_id
                               FOR UPDATE OF sandbox, admission
                            """
                        ),
                        {"allocation_id": allocation_id},
                    )
                ).one_or_none()
                if source is None:
                    raise ManagedSandboxNotFound(allocation_id)
                if source.state != ManagedSandboxState.MANUAL_RECOVERY_REQUIRED.value:
                    raise PortableRecoveryConflict("recovery_not_required")

                # ⚠️ 이 검사는 **지금 도달 불가능한 심층 방어**다.
                # 045의 부분 유니크 인덱스
                # (`idx_coding_managed_sandboxes_current_task`)가
                # `manual_recovery_required` 를 '살아 있음'으로 세므로
                # (`state NOT IN ('cleaned','failed')`), "복구 대기 중인 원본 +
                # 같은 태스크의 살아 있는 다른 세대"는 DB 가 애초에 표현하지
                # 못한다 -- 통합 테스트가 그것을 확인했다
                # (`test_postgres_recovery.py::
                #   test_a_stuck_allocation_cannot_coexist_with_a_live_generation`).
                # 그 인덱스가 완화되면 이 검사가 유일한 방어선이 되므로
                # 남겨 두되, **이것이 지금 무언가를 막고 있다고 읽지 말 것.**
                live = (
                    await session.execute(
                        text(
                            """
                            SELECT 1
                              FROM coding_managed_sandboxes
                             WHERE task_id = :task_id
                               AND allocation_id <> :allocation_id
                               AND cleaned_at IS NULL
                               AND state NOT IN ('cleaned', 'failed')
                             LIMIT 1
                            """
                        ),
                        {
                            "task_id": source.task_id,
                            "allocation_id": allocation_id,
                        },
                    )
                ).one_or_none()
                if live is not None:
                    raise PortableRecoveryConflict("recovery_generation_exists")

                generation = int(source.generation) + 1
                new_allocation_id = f"msa_{uuid4().hex}"
                new_admission_id = f"adm_{uuid4().hex}"
                absolute_expires_at = now + timedelta(seconds=lifetime_seconds)
                await session.execute(
                    text(
                        """
                        UPDATE coding_managed_sandboxes
                           SET state = 'failed',
                               lease_expires_at = NULL,
                               version = version + 1,
                               updated_at = :now
                         WHERE allocation_id = :allocation_id
                        """
                    ),
                    {"allocation_id": allocation_id, "now": now},
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO coding_sandbox_admissions (
                            admission_id, idempotency_key, tenant_id, task_id,
                            provider, region, policy_version, decision, reason,
                            reservation_id, reservation_expires_at,
                            reserved_active_seconds, reserved_archive_bytes,
                            reserved_cost_micros, reservation_state, created_at
                        ) VALUES (
                            :admission_id, :idempotency_key, :tenant_id,
                            :task_id, :provider, :region, :policy_version,
                            'admitted', 'allowed', :reservation_id,
                            :reservation_expires_at, :reserved_active_seconds,
                            :reserved_archive_bytes, :reserved_cost_micros,
                            'reserved', :now
                        )
                        """
                    ),
                    {
                        "admission_id": new_admission_id,
                        "idempotency_key": (
                            f"recovery:{allocation_id}:g{generation}"
                        ),
                        "tenant_id": source.tenant_id,
                        "task_id": source.task_id,
                        "provider": source.provider,
                        "region": source.region,
                        "policy_version": policy_version,
                        "reservation_id": f"rsv_{uuid4().hex}",
                        "reservation_expires_at": (
                            now + timedelta(seconds=reservation_lease_seconds)
                        ),
                        "reserved_active_seconds": source.reserved_active_seconds,
                        "reserved_archive_bytes": source.reserved_archive_bytes,
                        "reserved_cost_micros": source.reserved_cost_micros,
                        "now": now,
                    },
                )
                created = (
                    await session.execute(
                        text(
                            """
                            INSERT INTO coding_managed_sandboxes (
                                allocation_id, admission_id, tenant_id, task_id,
                                run_id, provider, region, provider_ref,
                                ownership_digest, state, generation,
                                fencing_token, lease_expires_at,
                                absolute_expires_at, version, error_code,
                                snapshot_ref, archive_ref, image_identity,
                                toolchain_identity, created_at, updated_at
                            ) VALUES (
                                :allocation_id, :admission_id, :tenant_id,
                                :task_id, :run_id, :provider, :region, NULL,
                                NULL, 'admitted', :generation, 1, NULL,
                                :absolute_expires_at, 1, NULL, NULL,
                                :archive_ref, :image_identity,
                                :toolchain_identity, :now, :now
                            )
                         RETURNING allocation_id, tenant_id, task_id, run_id,
                                   provider, region, provider_ref,
                                   ownership_digest, state, generation,
                                   fencing_token, lease_expires_at,
                                   absolute_expires_at, version, error_code,
                                   snapshot_ref, archive_ref, image_identity
                            """
                        ),
                        {
                            "allocation_id": new_allocation_id,
                            "admission_id": new_admission_id,
                            "tenant_id": source.tenant_id,
                            "task_id": source.task_id,
                            "run_id": source.run_id,
                            "provider": source.provider,
                            "region": source.region,
                            "generation": generation,
                            "absolute_expires_at": absolute_expires_at,
                            "archive_ref": archive_id,
                            "image_identity": source.image_identity,
                            "toolchain_identity": source.toolchain_identity,
                            "now": now,
                        },
                    )
                ).one()
                await PostgresCodingService(
                    self._session_factory
                ).append_in_session(
                    session,
                    task_id=str(source.task_id),
                    event_type="managed_sandbox_recovery_approved",
                    payload={
                        "source_allocation_id": allocation_id,
                        "recovery_allocation_id": new_allocation_id,
                        "generation": generation,
                        "operator_id": operator_id,
                        "archive_id": archive_id,
                        "archive_checksum": checksum,
                        "policy_version": policy_version,
                        "outcome": "approved",
                    },
                    now=now,
                    run_id=str(source.run_id),
                )
        return _allocation_from_row(created)

    async def discover_lifecycle_candidates(
        self, *, now: datetime, limit: int
    ) -> LifecycleCandidates:
        """정리 후보와 전진 후보를 한 트랜잭션에서 고른다.

        provider 를 부르지 않는다 -- provider 가 죽어 있어도 **발견은 계속**
        돌아야 밀린 양이 보인다.

        정리 후보는 두 갈래를 합친 것이다.
        (a) 아직 살아 있는데 정리해야 하는 행 -- 태스크가 종료/삭제됐거나
            절대 만료가 지났다. 이쪽은 이 호출이 **원자적으로**
            `CLEANUP_PENDING` 으로 옮긴다.
        (b) 이미 정리 단계에 있는데 아무도 진행시키지 않는 행 -- 워커가 죽어
            리스가 만료됐거나, 재시도 시각이 됐다.

        전진 후보는 `advance()`가 받는 상태에서 리스가 죽어 있고 아직 절대
        만료 전인 행이다. ADMITTED 도 여기 들어온다 -- 아직 시작하지 않은
        할당과 좌초한 할당은 원장에서 구별되지 않고, 어차피 둘 다
        `advance()` 한 번이 정답이다.
        """
        _require_timezone_aware("discovery time", now)
        if not 1 <= limit <= 1000:
            raise ValueError("discovery limit must be between 1 and 1000")
        async with await self._session_factory() as session:
            async with session.begin():
                promoted = (
                    await session.execute(
                        text(
                            """
                            WITH candidates AS (
                                SELECT sandbox.allocation_id
                                  FROM coding_managed_sandboxes AS sandbox
                                  JOIN coding_tasks AS task
                                    ON task.task_id = sandbox.task_id
                                 WHERE sandbox.state = ANY(
                                           CAST(:source_states AS VARCHAR[])
                                       )
                                   AND (
                                       task.deleted_at IS NOT NULL
                                       OR task.status = ANY(
                                           CAST(:terminal_statuses AS VARCHAR[])
                                       )
                                       OR sandbox.absolute_expires_at <= :now
                                   )
                                 ORDER BY sandbox.absolute_expires_at,
                                          sandbox.allocation_id
                                 LIMIT :limit
                                   FOR UPDATE OF sandbox SKIP LOCKED
                            )
                            UPDATE coding_managed_sandboxes AS sandbox
                               SET state = :cleanup_pending,
                                   lease_expires_at = NULL,
                                   version = sandbox.version + 1,
                                   updated_at = :now
                              FROM candidates
                             WHERE sandbox.allocation_id =
                                   candidates.allocation_id
                         RETURNING sandbox.allocation_id, sandbox.provider,
                                   sandbox.region
                            """
                        ),
                        {
                            "now": now,
                            "limit": limit,
                            "source_states": list(_CLEANUP_SOURCE_STATE_VALUES),
                            "terminal_statuses": list(_TERMINAL_TASK_STATUS_VALUES),
                            "cleanup_pending": (
                                ManagedSandboxState.CLEANUP_PENDING.value
                            ),
                        },
                    )
                ).all()
                stalled = (
                    await session.execute(
                        text(
                            """
                            SELECT sandbox.allocation_id, sandbox.provider,
                                   sandbox.region, sandbox.updated_at
                              FROM coding_managed_sandboxes AS sandbox
                             WHERE sandbox.state = ANY(
                                       CAST(:cleanup_states AS VARCHAR[])
                                   )
                               AND (
                                   sandbox.lease_expires_at IS NULL
                                   OR sandbox.lease_expires_at <= :now
                               )
                               AND NOT EXISTS (
                                   SELECT 1
                                     FROM coding_sandbox_cleanup_attempts
                                          AS attempt
                                    WHERE attempt.allocation_id =
                                          sandbox.allocation_id
                                      AND attempt.next_retry_at > :now
                               )
                             ORDER BY sandbox.updated_at, sandbox.allocation_id
                             LIMIT :limit
                            """
                        ),
                        {
                            "now": now,
                            "limit": limit,
                            "cleanup_states": list(_CLEANABLE_STATE_VALUES),
                        },
                    )
                ).all()
                recovery = (
                    await session.execute(
                        text(
                            """
                            SELECT allocation_id
                              FROM coding_managed_sandboxes
                             WHERE state = ANY(
                                       CAST(:recovery_states AS VARCHAR[])
                                   )
                               AND (
                                   lease_expires_at IS NULL
                                   OR lease_expires_at <= :now
                               )
                               AND absolute_expires_at > :now
                             ORDER BY updated_at, allocation_id
                             LIMIT :limit
                            """
                        ),
                        {
                            "now": now,
                            "limit": limit,
                            "recovery_states": list(_RECOVERY_STATE_VALUES),
                        },
                    )
                ).all()
        # (a)가 방금 옮긴 행은 (b)의 SELECT 에도 잡힌다 -- 같은 트랜잭션이라
        # UPDATE 가 보인다. allocation_id 로 중복을 걷어내되 (b)가 들고 온
        # 실제 대기 시작 시각(updated_at)을 살린다: (a)의 `now`를 쓰면 방금
        # 승격한 것처럼 보여 적체 나이가 0으로 리셋된다.
        candidates: dict[str, CleanupCandidate] = {}
        for row in promoted:
            candidates[str(row.allocation_id)] = CleanupCandidate(
                allocation_id=str(row.allocation_id),
                provider=str(row.provider),
                region=str(row.region),
                pending_since=now,
            )
        for row in stalled:
            candidates[str(row.allocation_id)] = CleanupCandidate(
                allocation_id=str(row.allocation_id),
                provider=str(row.provider),
                region=str(row.region),
                pending_since=row.updated_at,
            )
        return LifecycleCandidates(
            cleanup=tuple(
                candidates[key] for key in sorted(candidates)
            ),
            recovery=tuple(str(row.allocation_id) for row in recovery),
        )

    @staticmethod
    async def _read_admission(
        session,
        *,
        tenant_id: str,
        idempotency_key: str,
    ):
        result = await session.execute(
            text(
                """
                SELECT admission.admission_id, allocation.allocation_id,
                       admission.decision, admission.reason,
                       admission.reevaluate_at
                FROM coding_sandbox_admissions AS admission
                LEFT JOIN coding_managed_sandboxes AS allocation
                  ON allocation.admission_id = admission.admission_id
                WHERE admission.tenant_id = :tenant_id
                  AND admission.idempotency_key = :idempotency_key
                """
            ),
            {
                "tenant_id": tenant_id,
                "idempotency_key": idempotency_key,
            },
        )
        return result.first()

    @staticmethod
    def _from_row(row, *, created: bool) -> AdmissionResult:
        return AdmissionResult(
            admission_id=str(row[0]),
            allocation_id=str(row[1]) if row[1] is not None else None,
            decision=AdmissionDecision(row[2]),
            reason=AdmissionReason(row[3]),
            reevaluate_after=row[4],
            created=created,
        )


async def _read_quota_usage(
    session,
    *,
    tenant_id: str,
    now: datetime,
) -> tuple[int, int, int, int, int]:
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    result = await session.execute(
        text(
            """
            SELECT
                count(*) FILTER (
                    WHERE (
                        (
                            admission.reservation_state = 'reserved'
                            AND admission.reservation_expires_at > :now
                        )
                        OR allocation.state =
                            ANY(CAST(:live_states AS VARCHAR[]))
                    )
                ),
                count(*) FILTER (
                    WHERE admission.decision = 'admitted'
                      AND admission.created_at >= :day_start
                      AND admission.created_at < :day_end
                ),
                COALESCE(sum(
                    CASE
                        WHEN admission.created_at >= :day_start
                         AND admission.created_at < :day_end
                         AND admission.reservation_state = 'settled'
                        THEN admission.actual_active_seconds
                        WHEN admission.created_at >= :day_start
                         AND admission.created_at < :day_end
                         AND (
                            (
                                admission.reservation_state = 'reserved'
                                AND admission.reservation_expires_at > :now
                            )
                            OR allocation.state =
                                ANY(CAST(:live_states AS VARCHAR[]))
                         )
                        THEN admission.reserved_active_seconds
                        ELSE 0
                    END
                ), 0),
                COALESCE(sum(
                    CASE
                        WHEN admission.reservation_state = 'settled'
                        THEN admission.actual_archive_bytes
                        WHEN (
                            (
                                admission.reservation_state = 'reserved'
                                AND admission.reservation_expires_at > :now
                            )
                            OR allocation.state =
                                ANY(CAST(:live_states AS VARCHAR[]))
                        )
                        THEN admission.reserved_archive_bytes
                        ELSE 0
                    END
                ), 0),
                COALESCE(sum(
                    CASE
                        WHEN admission.created_at >= :day_start
                         AND admission.created_at < :day_end
                         AND admission.reservation_state = 'settled'
                        THEN admission.actual_cost_micros
                        WHEN admission.created_at >= :day_start
                         AND admission.created_at < :day_end
                         AND (
                            (
                                admission.reservation_state = 'reserved'
                                AND admission.reservation_expires_at > :now
                            )
                            OR allocation.state =
                                ANY(CAST(:live_states AS VARCHAR[]))
                         )
                        THEN admission.reserved_cost_micros
                        ELSE 0
                    END
                ), 0)
            FROM coding_sandbox_admissions AS admission
            LEFT JOIN coding_managed_sandboxes AS allocation
              ON allocation.admission_id = admission.admission_id
            WHERE admission.tenant_id = :tenant_id
            """
        ),
        {
            "tenant_id": tenant_id,
            "now": now,
            "day_start": day_start,
            "day_end": day_start + timedelta(days=1),
            "live_states": list(_LIVE_QUOTA_STATES),
        },
    )
    row = result.first()
    if row is None:
        raise RuntimeError("quota usage query returned no aggregate row")
    return (
        int(row[0] or 0),
        int(row[1] or 0),
        int(row[2] or 0),
        int(row[3] or 0),
        int(row[4] or 0),
    )


def _quota_reason(
    request: AdmissionRequest,
    *,
    usage: tuple[int, int, int, int, int],
    concurrent_quota: int,
    daily_quota: int,
    daily_active_seconds_quota: int,
    archive_bytes_quota: int,
    daily_cost_micros_quota: int,
) -> AdmissionReason | None:
    concurrent, daily, active, archive, cost = usage
    if concurrent >= concurrent_quota:
        return AdmissionReason.QUOTA_EXCEEDED
    if daily >= daily_quota:
        return AdmissionReason.QUOTA_EXCEEDED
    if (
        active + request.estimated_active_seconds > daily_active_seconds_quota
        or archive + request.estimated_archive_bytes > archive_bytes_quota
        or cost + request.estimated_cost_micros > daily_cost_micros_quota
    ):
        return AdmissionReason.BUDGET_EXCEEDED
    return None


async def _raise_claim_failure(session, allocation_id: str) -> None:
    """`claim_allocation`의 원자적 UPDATE가 0행을 반환했을 때 원인을 구분해서
    알린다.

    이 조회는 UPDATE와 별개 문장이라 그 사이에 다른 트랜잭션이 행을 바꿀 수
    있다 -- 그래도 소유권 판정 자체(누가 이겼는지)는 이미 끝난 원자적 UPDATE가
    했으므로 안전하다. 이 함수는 그 실패를 사람이 구분할 수 있는 예외로
    번역할 뿐이다.
    """
    row = (
        await session.execute(
            text(
                """
                SELECT state
                  FROM coding_managed_sandboxes
                 WHERE allocation_id = :allocation_id
                """
            ),
            {"allocation_id": allocation_id},
        )
    ).one_or_none()
    if row is None:
        raise ManagedSandboxNotFound(allocation_id)
    if row.state not in _CLAIMABLE_STATES:
        raise ManagedSandboxNotClaimable(allocation_id)
    raise StaleManagedSandboxLease(allocation_id)


async def _execute_fenced_commit(
    session,
    lease: ManagedAllocationLease,
    *,
    now: datetime,
    assignments: str,
    params: dict[str, object],
):
    """펜싱 UPDATE 한 번. 호출자가 트랜잭션을 소유한다.

    `_commit()`은 이것만 하고 끝나지만 `commit_cleanup_outcome()`은 같은
    트랜잭션에서 시도 행도 함께 넣어야 해서 세션을 밖에서 연다. 갱신된 행이
    없으면(=낡은 펜스) `None`을 돌려주고, 그것을
    `StaleManagedSandboxLease`로 올릴지는 호출자가 정한다.

    `assignments`는 이 모듈 안에서 만든 리터럴 문자열만 들어간다
    (사용자 입력이 아니다). 값은 전부 바인드 파라미터다.
    """
    return (
        await session.execute(
            text(
                f"""
                UPDATE coding_managed_sandboxes
                   SET {assignments},
                       version = version + 1,
                       updated_at = :now
                 WHERE allocation_id = :allocation_id
                   AND fencing_token = :fencing_token
             RETURNING allocation_id, tenant_id, task_id, run_id,
                       provider, region, provider_ref,
                       ownership_digest, state, generation,
                       fencing_token, lease_expires_at,
                       absolute_expires_at, version, error_code,
                       snapshot_ref, archive_ref, image_identity
                """
            ),
            {
                **params,
                "allocation_id": lease.allocation_id,
                "fencing_token": lease.fencing_token,
                "now": now,
            },
        )
    ).one_or_none()


def _allocation_from_row(row) -> ManagedSandboxAllocation:
    return ManagedSandboxAllocation(
        allocation_id=str(row.allocation_id),
        tenant_id=str(row.tenant_id),
        task_id=str(row.task_id),
        run_id=str(row.run_id),
        provider=str(row.provider),
        region=str(row.region),
        provider_ref=row.provider_ref,
        ownership_digest=row.ownership_digest,
        state=ManagedSandboxState(row.state),
        generation=row.generation,
        fencing_token=row.fencing_token,
        lease_expires_at=row.lease_expires_at,
        absolute_expires_at=row.absolute_expires_at,
        version=row.version,
        error_code=(
            ProviderErrorCode(row.error_code) if row.error_code is not None else None
        ),
        snapshot_ref=row.snapshot_ref,
        archive_ref=row.archive_ref,
        image_identity=row.image_identity,
    )


def _require_timezone_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _require_positive_quotas(**quotas: int) -> None:
    for name, value in quotas.items():
        if value <= 0:
            raise ValueError(f"{name} must be positive")


def _require_nonnegative_usage(**usage: int) -> None:
    for name, value in usage.items():
        if value < 0:
            raise ValueError(f"{name} must not be negative")

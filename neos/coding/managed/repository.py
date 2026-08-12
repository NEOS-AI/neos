from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import text

from neos.coding.managed.adapters import AllocationResult
from neos.coding.managed.admission import AdmissionRequest, AdmissionResult
from neos.coding.managed.allocation import (
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
from neos.coding.persistence.postgres import SessionFactory


_POLICY_VERSION = "managed-v1"
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
        """
        _require_timezone_aware("claim time", now)
        if lease_seconds < 1:
            raise ValueError("lease_seconds_invalid")
        expires_at = now + timedelta(seconds=lease_seconds)
        async with await self._session_factory() as session:
            async with session.begin():
                row = (
                    await session.execute(
                        text(
                            """
                            UPDATE coding_managed_sandboxes
                               SET fencing_token = fencing_token + 1,
                                   lease_expires_at = :expires_at,
                                   version = version + 1,
                                   updated_at = :now
                             WHERE allocation_id = :allocation_id
                               AND state = ANY(CAST(:claimable_states AS VARCHAR[]))
                               AND (
                                   lease_expires_at IS NULL
                                   OR lease_expires_at <= :now
                               )
                         RETURNING fencing_token
                            """
                        ),
                        {
                            "allocation_id": allocation_id,
                            "expires_at": expires_at,
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
            expires_at=expires_at,
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
                row = (
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

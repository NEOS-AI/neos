from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import text

from neos.coding.managed.admission import AdmissionRequest, AdmissionResult
from neos.coding.managed.domain import (
    AdmissionDecision,
    AdmissionReason,
    ManagedSandboxState,
)
from neos.coding.persistence.postgres import SessionFactory


_POLICY_VERSION = "managed-v1"


class PostgresManagedSandboxRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

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
                    usage = await session.execute(
                        text(
                            """
                            SELECT
                                count(*) FILTER (
                                    WHERE reservation_state = 'reserved'
                                      AND reservation_expires_at > :now
                                ),
                                count(*) FILTER (
                                    WHERE decision = 'admitted'
                                      AND created_at >= :day_start
                                      AND created_at < :day_end
                                ),
                                COALESCE(sum(
                                    CASE
                                        WHEN created_at >= :day_start
                                         AND created_at < :day_end
                                         AND reservation_state = 'reserved'
                                         AND reservation_expires_at > :now
                                        THEN reserved_active_seconds
                                        WHEN created_at >= :day_start
                                         AND created_at < :day_end
                                         AND reservation_state = 'settled'
                                        THEN actual_active_seconds
                                        ELSE 0
                                    END
                                ), 0),
                                COALESCE(sum(
                                    CASE
                                        WHEN reservation_state = 'reserved'
                                         AND reservation_expires_at > :now
                                        THEN reserved_archive_bytes
                                        WHEN reservation_state = 'settled'
                                        THEN actual_archive_bytes
                                        ELSE 0
                                    END
                                ), 0),
                                COALESCE(sum(
                                    CASE
                                        WHEN created_at >= :day_start
                                         AND created_at < :day_end
                                         AND reservation_state = 'reserved'
                                         AND reservation_expires_at > :now
                                        THEN reserved_cost_micros
                                        WHEN created_at >= :day_start
                                         AND created_at < :day_end
                                         AND reservation_state = 'settled'
                                        THEN actual_cost_micros
                                        ELSE 0
                                    END
                                ), 0)
                            FROM coding_sandbox_admissions
                            WHERE tenant_id = :tenant_id
                            """
                        ),
                        {
                            "tenant_id": request.tenant_id,
                            "now": now,
                            "day_start": now.replace(
                                hour=0, minute=0, second=0, microsecond=0
                            ),
                            "day_end": now.replace(
                                hour=0, minute=0, second=0, microsecond=0
                            )
                            + timedelta(days=1),
                        },
                    )
                    row = usage.first()
                    assert row is not None
                    concurrent, daily, active, archive, cost = (
                        int(row[index] or 0) for index in range(5)
                    )
                    if concurrent >= concurrent_quota or daily >= daily_quota:
                        final_decision = AdmissionDecision.DENIED
                        final_reason = AdmissionReason.QUOTA_EXCEEDED
                    elif (
                        active + request.estimated_active_seconds
                        > daily_active_seconds_quota
                        or archive + request.estimated_archive_bytes
                        > archive_bytes_quota
                        or cost + request.estimated_cost_micros
                        > daily_cost_micros_quota
                    ):
                        final_decision = AdmissionDecision.DENIED
                        final_reason = AdmissionReason.BUDGET_EXCEEDED
                    if final_decision is AdmissionDecision.DENIED:
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
                result = await session.execute(
                    text(
                        """
                        WITH candidates AS (
                            SELECT admission_id
                            FROM coding_sandbox_admissions
                            WHERE reservation_state = 'reserved'
                              AND reservation_expires_at <= :now
                            ORDER BY reservation_expires_at, admission_id
                            LIMIT :limit
                            FOR UPDATE SKIP LOCKED
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
                    {"now": now, "limit": limit},
                )
                rows = result.all()
        return [str(row[0]) for row in rows]

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

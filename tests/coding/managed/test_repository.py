from collections import namedtuple
from datetime import UTC, datetime, timedelta

import pytest

from neos.coding.managed.admission import AdmissionRequest, AdmissionResult
from neos.coding.managed.adapters import AllocationResult
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
    ManagedSandboxState,
)
from neos.coding.managed.repository import PostgresManagedSandboxRepository


NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


class FakeResult:
    def __init__(self, *, row=None, rows=()) -> None:
        self._row = row
        self._rows = list(rows)

    def first(self):
        return self._row

    def one_or_none(self):
        return self._row

    def all(self):
        return self._rows


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


class FakeSession:
    def __init__(self, results: list[FakeResult]) -> None:
        self.results = results
        self.statements: list[tuple[str, dict[str, object]]] = []

    def begin(self):
        return FakeTransaction()

    async def execute(self, statement, params=None):
        self.statements.append((str(statement), params or {}))
        return self.results.pop(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


def request_fixture(**changes: object) -> AdmissionRequest:
    values: dict[str, object] = {
        "tenant_id": "tenant_1",
        "task_id": "ct_1",
        "run_id": "cr_1",
        "repository_organization": "acme",
        "provider": "fake",
        "region": "local",
        "required_capabilities": frozenset({"network_block_all"}),
        "idempotency_key": "idem_1",
        "estimated_active_seconds": 300,
        "estimated_archive_bytes": 1024,
        "estimated_cost_micros": 500,
    }
    values.update(changes)
    return AdmissionRequest(**values)  # type: ignore[arg-type]


def repository_for(session: FakeSession) -> PostgresManagedSandboxRepository:
    async def session_factory():
        return session

    return PostgresManagedSandboxRepository(session_factory)


# claim_allocation/commit_state/commit_active 테스트 전용 별칭 -- 모양은
# repository_for와 같다 (브리프가 지정한 헬퍼 이름).
repository_with = repository_for


_AllocationRow = namedtuple(
    "_AllocationRow",
    [
        "allocation_id",
        "tenant_id",
        "task_id",
        "run_id",
        "provider",
        "region",
        "provider_ref",
        "ownership_digest",
        "state",
        "generation",
        "fencing_token",
        "lease_expires_at",
        "absolute_expires_at",
        "version",
        "error_code",
        "snapshot_ref",
        "archive_ref",
        "image_identity",
        # read_allocation_plan의 조인 결과에만 있는 admission 소유 필드.
        # claim/commit 경로의 RETURNING 행에는 없지만, _allocation_from_row는
        # 이 속성을 읽지 않으므로 같은 fake 행 모양을 공유해도 무해하다.
        "idempotency_key",
    ],
)


def _row(**changes: object) -> _AllocationRow:
    """claim/commit/read_allocation_plan이 돌려받는 행을 흉내낸다.

    claim_allocation은 이 중 `fencing_token`만 읽고, `_commit`과
    `read_allocation_plan`은 `_allocation_from_row`로 나머지까지 전부 읽어
    `ManagedSandboxAllocation`을 만든다 -- 세 경로 모두 같은 fake 행으로
    통과하도록 전 필드에 기본값을 둔다.
    """
    values: dict[str, object] = {
        "allocation_id": "msa_1",
        "tenant_id": "tenant_1",
        "task_id": "ct_1",
        "run_id": "cr_1",
        "provider": "fake",
        "region": "local",
        "provider_ref": None,
        "ownership_digest": None,
        "state": "allocating",
        "generation": 1,
        "fencing_token": 1,
        "lease_expires_at": None,
        "absolute_expires_at": NOW + timedelta(hours=1),
        "version": 1,
        "error_code": None,
        "snapshot_ref": None,
        "archive_ref": None,
        "image_identity": None,
        "idempotency_key": "idem_1",
    }
    values.update(changes)
    return _AllocationRow(**values)


async def test_direct_repository_caller_with_brief_request_reaches_processing() -> None:
    denied = (
        "adm_direct",
        None,
        "denied",
        "provider_unavailable",
        NOW + timedelta(seconds=30),
    )
    session = FakeSession(
        [
            FakeResult(),
            FakeResult(row=None),
            FakeResult(row=("adm_direct",)),
            FakeResult(row=denied),
        ]
    )
    request = AdmissionRequest(
        tenant_id="tenant_1",
        task_id="ct_direct",
        run_id="cr_direct",
        repository_organization="acme",
        provider="fake",
        region="local",
        required_capabilities=frozenset({"network_block_all"}),
        idempotency_key="idem_direct",
        estimated_active_seconds=300,
        estimated_archive_bytes=1024,
        estimated_cost_micros=500,
    )

    result = await repository_for(session).admit(
        request,
        decision=AdmissionDecision.DENIED,
        reason=AdmissionReason.PROVIDER_UNAVAILABLE,
        now=NOW,
        reevaluate_after=NOW + timedelta(seconds=30),
        reservation_expires_at=None,
        concurrent_quota=3,
        daily_quota=50,
        daily_active_seconds_quota=43_200,
        archive_bytes_quota=5 * 1024**3,
        daily_cost_micros_quota=10_000_000,
    )

    assert result.admission_id == "adm_direct"
    assert result.created is True
    assert len(session.statements) == 4
    assert session.statements[2][1]["policy_version"] == "managed-v1"


async def test_preflight_prefers_concurrent_quota_before_daily_budget() -> None:
    session = FakeSession(
        [
            FakeResult(
                row=(3, 50, 43_200, 5 * 1024**3, 10_000_000),
            )
        ]
    )

    reason = await repository_for(session).preflight_quota(
        request_fixture(),
        now=NOW,
        concurrent_quota=3,
        daily_quota=50,
        daily_active_seconds_quota=43_200,
        archive_bytes_quota=5 * 1024**3,
        daily_cost_micros_quota=10_000_000,
    )

    assert reason is AdmissionReason.QUOTA_EXCEEDED
    assert len(session.statements) == 1
    assert "pg_advisory_xact_lock" not in session.statements[0][0]


async def test_admit_serializes_tenant_before_reading_quota_and_replays_exactly() -> (
    None
):
    original = (
        "adm_original",
        "alloc_original",
        "admitted",
        "allowed",
        None,
    )
    session = FakeSession([FakeResult(), FakeResult(row=original)])

    result = await repository_for(session).admit(
        request_fixture(),
        decision=AdmissionDecision.ADMITTED,
        reason=AdmissionReason.ALLOWED,
        now=NOW,
        reevaluate_after=None,
        reservation_expires_at=NOW + timedelta(seconds=60),
        concurrent_quota=3,
        daily_quota=50,
        daily_active_seconds_quota=43_200,
        archive_bytes_quota=5 * 1024**3,
        daily_cost_micros_quota=10_000_000,
    )

    sql = [statement for statement, _ in session.statements]
    assert "pg_advisory_xact_lock" in sql[0]
    assert "tenant_id = :tenant_id" in sql[1]
    assert "idempotency_key = :idempotency_key" in sql[1]
    assert session.statements[1][1] == {
        "tenant_id": "tenant_1",
        "idempotency_key": "idem_1",
    }
    assert len(sql) == 2
    assert result == AdmissionResult(
        admission_id="adm_original",
        allocation_id="alloc_original",
        decision=AdmissionDecision.ADMITTED,
        reason=AdmissionReason.ALLOWED,
        reevaluate_after=None,
        created=False,
    )


async def test_pre_admission_denial_is_persisted_without_reading_quota() -> None:
    denied = (
        "adm_1",
        None,
        "denied",
        "provider_unavailable",
        NOW + timedelta(seconds=30),
    )
    session = FakeSession(
        [
            FakeResult(),
            FakeResult(row=None),
            FakeResult(row=("adm_1",)),
            FakeResult(row=denied),
        ]
    )

    result = await repository_for(session).admit(
        request_fixture(),
        decision=AdmissionDecision.DENIED,
        reason=AdmissionReason.PROVIDER_UNAVAILABLE,
        now=NOW,
        reevaluate_after=NOW + timedelta(seconds=30),
        reservation_expires_at=None,
        concurrent_quota=3,
        daily_quota=50,
        daily_active_seconds_quota=43_200,
        archive_bytes_quota=5 * 1024**3,
        daily_cost_micros_quota=10_000_000,
    )

    sql = "\n".join(statement for statement, _ in session.statements)
    assert "FILTER (WHERE" not in sql
    _, insert_params = session.statements[2]
    assert insert_params["reservation_state"] == "unreserved"
    assert insert_params["reservation_expires_at"] is None
    assert insert_params["policy_version"] == "managed-v1"
    assert result.decision is AdmissionDecision.DENIED


async def test_admit_reserves_estimates_and_creates_admitted_allocation_atomically() -> (
    None
):
    quota_row = (2, 10, 1_000, 2_000, 3_000)
    created = ("adm_1", "alloc_1", "admitted", "allowed", None)
    session = FakeSession(
        [
            FakeResult(),
            FakeResult(row=None),
            FakeResult(row=quota_row),
            FakeResult(row=("adm_1",)),
            FakeResult(),
            FakeResult(row=created),
        ]
    )
    request = request_fixture(
        estimated_active_seconds=300,
        estimated_archive_bytes=1024,
        estimated_cost_micros=500,
    )

    result = await repository_for(session).admit(
        request,
        decision=AdmissionDecision.ADMITTED,
        reason=AdmissionReason.ALLOWED,
        now=NOW,
        reevaluate_after=None,
        reservation_expires_at=NOW + timedelta(seconds=60),
        concurrent_quota=3,
        daily_quota=50,
        daily_active_seconds_quota=43_200,
        archive_bytes_quota=5 * 1024**3,
        daily_cost_micros_quota=10_000_000,
    )

    sql = "\n".join(statement for statement, _ in session.statements)
    admission_sql, admission_params = session.statements[3]
    allocation_sql, allocation_params = session.statements[4]
    assert "ON CONFLICT (tenant_id, idempotency_key) DO NOTHING" in admission_sql
    assert admission_params["reservation_state"] == "reserved"
    assert admission_params["reserved_active_seconds"] == 300
    assert admission_params["reserved_archive_bytes"] == 1024
    assert admission_params["reserved_cost_micros"] == 500
    assert admission_params["policy_version"] == "managed-v1"
    assert "coding_managed_sandboxes" in allocation_sql
    assert allocation_params["admission_id"] == "adm_1"
    assert allocation_params["state"] == "admitted"
    assert "coding_sandbox_admissions" in sql
    assert result.created is True
    assert result.allocation_id == "alloc_1"


async def test_admit_counts_all_five_quota_dimensions_from_durable_usage() -> None:
    session = FakeSession(
        [
            FakeResult(),
            FakeResult(row=None),
            FakeResult(row=(0, 0, 0, 0, 0)),
            FakeResult(row=("adm_1",)),
            FakeResult(),
            FakeResult(row=("adm_1", "alloc_1", "admitted", "allowed", None)),
        ]
    )

    await repository_for(session).admit(
        request_fixture(),
        decision=AdmissionDecision.ADMITTED,
        reason=AdmissionReason.ALLOWED,
        now=NOW,
        reevaluate_after=None,
        reservation_expires_at=NOW + timedelta(seconds=60),
        concurrent_quota=3,
        daily_quota=50,
        daily_active_seconds_quota=43_200,
        archive_bytes_quota=5 * 1024**3,
        daily_cost_micros_quota=10_000_000,
    )

    quota_sql, quota_params = session.statements[2]
    assert "reservation_state = 'reserved'" in quota_sql
    assert "reservation_expires_at > :now" in quota_sql
    assert "decision = 'admitted'" in quota_sql
    assert "created_at >= :day_start" in quota_sql
    assert "reserved_active_seconds" in quota_sql
    assert "actual_active_seconds" in quota_sql
    assert "reserved_archive_bytes" in quota_sql
    assert "actual_archive_bytes" in quota_sql
    assert "reserved_cost_micros" in quota_sql
    assert "actual_cost_micros" in quota_sql
    assert "LEFT JOIN coding_managed_sandboxes AS allocation" in quota_sql
    assert "allocation.state" in quota_sql
    assert "ANY(CAST(:live_states AS VARCHAR[]))" in quota_sql
    assert quota_params["tenant_id"] == "tenant_1"
    assert quota_params["live_states"] == [
        "allocating",
        "active",
        "suspended",
        "recovery_pending",
    ]


async def test_admission_ledger_excludes_policy_inputs_and_sensitive_content() -> None:
    secret_organization = "credential-bearing-organization"
    secret_capability = "workspace-content-capability"
    session = FakeSession(
        [
            FakeResult(),
            FakeResult(row=None),
            FakeResult(row=(0, 0, 0, 0, 0)),
            FakeResult(row=("adm_1",)),
            FakeResult(),
            FakeResult(row=("adm_1", "alloc_1", "admitted", "allowed", None)),
        ]
    )

    await repository_for(session).admit(
        request_fixture(
            repository_organization=secret_organization,
            required_capabilities=frozenset({secret_capability}),
        ),
        decision=AdmissionDecision.ADMITTED,
        reason=AdmissionReason.ALLOWED,
        now=NOW,
        reevaluate_after=None,
        reservation_expires_at=NOW + timedelta(seconds=60),
        concurrent_quota=3,
        daily_quota=50,
        daily_active_seconds_quota=43_200,
        archive_bytes_quota=5 * 1024**3,
        daily_cost_micros_quota=10_000_000,
    )

    persisted_values = {
        value
        for _, params in session.statements
        for value in params.values()
        if isinstance(value, str)
    }
    persisted_sql = "\n".join(statement for statement, _ in session.statements)
    assert secret_organization not in persisted_values
    assert secret_capability not in persisted_values
    assert "repository_organization" not in persisted_sql
    assert "required_capabilities" not in persisted_sql


@pytest.mark.parametrize(
    ("quota_row", "expected_reason"),
    [
        ((3, 10, 1_000, 2_000, 3_000), AdmissionReason.QUOTA_EXCEEDED),
        ((2, 50, 1_000, 2_000, 3_000), AdmissionReason.QUOTA_EXCEEDED),
        ((2, 10, 43_000, 2_000, 3_000), AdmissionReason.BUDGET_EXCEEDED),
        ((2, 10, 1_000, 5 * 1024**3, 3_000), AdmissionReason.BUDGET_EXCEEDED),
        ((2, 10, 1_000, 2_000, 9_999_800), AdmissionReason.BUDGET_EXCEEDED),
    ],
)
async def test_admit_converts_quota_or_budget_overflow_to_durable_denial(
    quota_row: tuple[int, int, int, int, int],
    expected_reason: AdmissionReason,
) -> None:
    created = ("adm_1", None, "denied", expected_reason.value, NOW)
    session = FakeSession(
        [
            FakeResult(),
            FakeResult(row=None),
            FakeResult(row=quota_row),
            FakeResult(row=("adm_1",)),
            FakeResult(row=created),
        ]
    )

    result = await repository_for(session).admit(
        request_fixture(),
        decision=AdmissionDecision.ADMITTED,
        reason=AdmissionReason.ALLOWED,
        now=NOW,
        reevaluate_after=NOW + timedelta(seconds=30),
        reservation_expires_at=NOW + timedelta(seconds=60),
        concurrent_quota=3,
        daily_quota=50,
        daily_active_seconds_quota=43_200,
        archive_bytes_quota=5 * 1024**3,
        daily_cost_micros_quota=10_000_000,
    )

    _, params = session.statements[3]
    assert params["decision"] == "denied"
    assert params["reason"] == expected_reason.value
    assert params["reservation_state"] == "unreserved"
    assert params["reservation_expires_at"] is None
    assert result.reason is expected_reason
    assert result.allocation_id is None


async def test_settle_updates_state_usage_and_matching_timestamp_together() -> None:
    session = FakeSession(
        [
            FakeResult(row=(None,)),
            FakeResult(row=("alloc_1",)),
        ]
    )

    changed = await repository_for(session).settle_reservation(
        "alloc_1",
        active_seconds=123,
        archive_bytes=456,
        cost_micros=789,
        now=NOW,
    )

    lock_sql, lock_params = session.statements[0]
    update_sql, params = session.statements[1]
    assert "pg_advisory_xact_lock" in lock_sql
    assert "hashtextextended(allocation.tenant_id, 0)" in lock_sql
    assert "reservation_state = 'reserved'" in lock_sql
    assert lock_params == {"allocation_id": "alloc_1"}
    assert "reservation_state = 'settled'" in update_sql
    assert "reservation_settled_at = :now" in update_sql
    assert "reservation_released_at = NULL" in update_sql
    assert "reservation_state = 'reserved'" in update_sql
    assert params["active_seconds"] == 123
    assert params["archive_bytes"] == 456
    assert params["cost_micros"] == 789
    assert changed is True


async def test_release_expired_reservations_sets_state_and_timestamp_atomically() -> (
    None
):
    session = FakeSession(
        [
            FakeResult(rows=[("tenant_1",)]),
            FakeResult(rows=[("alloc_1",), ("alloc_2",)]),
        ]
    )

    released = await repository_for(session).release_expired_reservations(
        now=NOW, limit=2
    )

    assert len(session.statements) == 2
    lock_sql, lock_params = session.statements[0]
    update_sql, params = session.statements[1]
    assert "pg_advisory_xact_lock" in lock_sql
    assert "hashtextextended(candidate.tenant_id, 0)" in lock_sql
    assert "reservation_state = 'reserved'" in lock_sql
    assert "reservation_expires_at <= :now" in lock_sql
    assert "allocation.state <> ALL" in lock_sql
    assert lock_params == {
        "now": NOW,
        "limit": 2,
        "live_states": [
            "allocating",
            "active",
            "suspended",
            "recovery_pending",
        ],
    }
    assert "FOR UPDATE OF admission, allocation SKIP LOCKED" in update_sql
    assert "reservation_state = 'released'" in update_sql
    assert "reservation_released_at = :now" in update_sql
    assert "reservation_settled_at = NULL" in update_sql
    assert "reservation_state = 'reserved'" in update_sql
    assert "ANY(CAST(:tenant_ids AS VARCHAR[]))" in update_sql
    assert "reservation_expires_at <= :now" in update_sql
    assert "allocation.state <> ALL" in update_sql
    assert params["limit"] == 2
    assert params["tenant_ids"] == ["tenant_1"]
    assert params["live_states"] == [
        "allocating",
        "active",
        "suspended",
        "recovery_pending",
    ]
    assert released == ["alloc_1", "alloc_2"]


@pytest.mark.parametrize("limit", [0, 1001])
async def test_release_rejects_unbounded_batch(limit: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 1000"):
        await repository_for(FakeSession([])).release_expired_reservations(
            now=NOW, limit=limit
        )


async def test_claim_allocation_only_takes_a_free_or_expired_lease() -> None:
    session = FakeSession([FakeResult(row=_row(fencing_token=2))])
    repo = repository_with(session)

    lease = await repo.claim_allocation("msa_1", "worker_1", now=NOW, lease_seconds=300)

    statement, params = session.statements[-1]
    assert "fencing_token = fencing_token + 1" in statement
    assert "state = ANY(CAST(:claimable_states AS VARCHAR[]))" in statement
    assert "lease_expires_at IS NULL" in statement
    assert "lease_expires_at <= :now" in statement
    assert params["allocation_id"] == "msa_1"
    assert params["claimable_states"] == [
        "admitted",
        "recovery_pending",
        "cleanup_pending",
        "cleanup_retry",
    ]
    assert lease.fencing_token == 2
    assert lease.worker_id == "worker_1"


async def test_claim_allocation_raises_when_a_live_lease_holds() -> None:
    # 첫 결과 = 원자적 UPDATE가 0행(리스가 살아 있어 걸러짐), 두 번째 결과 =
    # 실패 원인을 구분하려고 같은 트랜잭션에서 한 번 더 읽는 진단 SELECT.
    session = FakeSession(
        [
            FakeResult(row=None),
            FakeResult(row=_row(state="admitted")),
        ]
    )
    repo = repository_with(session)

    with pytest.raises(StaleManagedSandboxLease):
        await repo.claim_allocation("msa_1", "worker_2", now=NOW, lease_seconds=300)


async def test_claim_allocation_raises_not_claimable_for_an_ineligible_state() -> None:
    """리스가 살아있어 지는 것과 상태 자체가 claim 대상이 아닌 것은 구별돼야
    한다 -- 호출자가 재시도할지 포기할지 다르게 판단해야 하기 때문이다.
    """
    session = FakeSession(
        [
            FakeResult(row=None),
            FakeResult(row=_row(state="active")),
        ]
    )
    repo = repository_with(session)

    with pytest.raises(ManagedSandboxNotClaimable):
        await repo.claim_allocation("msa_1", "worker_1", now=NOW, lease_seconds=300)


async def test_commit_filters_on_the_fencing_token() -> None:
    session = FakeSession([FakeResult(row=_row(fencing_token=2))])
    repo = repository_with(session)
    lease = ManagedAllocationLease(
        allocation_id="msa_1",
        worker_id="worker_1",
        fencing_token=2,
        expires_at=NOW + timedelta(seconds=300),
    )

    await repo.commit_state(lease, ManagedSandboxState.ALLOCATING, now=NOW)

    statement, params = session.statements[-1]
    assert "fencing_token = :fencing_token" in statement
    assert params["fencing_token"] == 2


async def test_commit_state_to_cleaned_clears_provider_and_lease_columns() -> None:
    """045의 CHECK 제약은 state='cleaned'인 행에 provider_ref/ownership_digest/
    lease_expires_at이 NULL이고 cleaned_at이 NOT NULL이길 요구한다 -- 이걸
    맞추지 않으면 UPDATE 자체가 DB에서 거부된다. domain.transition_allocation()이
    메모리에서 이미 하는 클리어링을 쓰기 경로도 그대로 반영해야 한다.
    """
    session = FakeSession([FakeResult(row=_row(fencing_token=2, state="cleaned"))])
    repo = repository_with(session)
    lease = ManagedAllocationLease(
        allocation_id="msa_1",
        worker_id="worker_1",
        fencing_token=2,
        expires_at=NOW + timedelta(seconds=300),
    )

    await repo.commit_state(lease, ManagedSandboxState.CLEANED, now=NOW)

    statement, params = session.statements[-1]
    assert "provider_ref = NULL" in statement
    assert "ownership_digest = NULL" in statement
    assert "lease_expires_at = NULL" in statement
    assert "cleaned_at = :now" in statement
    assert params["state"] == "cleaned"
    assert params["now"] == NOW


async def test_commit_state_writes_image_identity_when_given() -> None:
    """다음 태스크가 ALLOCATING 전이 시점에 이미지를 고정할 때 쓸 쓰기 경로.
    안 주면(기본 None) SET 절에 안 들어가야 한다 -- 이미 확정된 값을 실수로
    지우면 안 되기 때문이다.
    """
    session = FakeSession([FakeResult(row=_row(fencing_token=2))])
    repo = repository_with(session)
    lease = ManagedAllocationLease(
        allocation_id="msa_1",
        worker_id="worker_1",
        fencing_token=2,
        expires_at=NOW + timedelta(seconds=300),
    )

    await repo.commit_state(
        lease,
        ManagedSandboxState.ALLOCATING,
        now=NOW,
        image_identity="ghcr.io/acme/sandbox:sha-1",
    )

    statement, params = session.statements[-1]
    assert "image_identity = :image_identity" in statement
    assert params["image_identity"] == "ghcr.io/acme/sandbox:sha-1"


async def test_commit_state_omits_image_identity_when_not_given() -> None:
    session = FakeSession([FakeResult(row=_row(fencing_token=2))])
    repo = repository_with(session)
    lease = ManagedAllocationLease(
        allocation_id="msa_1",
        worker_id="worker_1",
        fencing_token=2,
        expires_at=NOW + timedelta(seconds=300),
    )

    await repo.commit_state(lease, ManagedSandboxState.ALLOCATING, now=NOW)

    # RETURNING 절에는 image_identity가 항상 있다(응답 왕복용) -- 여기서
    # 확인할 건 SET 절에 안 들어갔다는 것과 바인드하지 않았다는 것뿐이다.
    statement, params = session.statements[-1]
    assert "image_identity = :image_identity" not in statement
    assert "image_identity" not in params


async def test_commit_active_binds_only_the_encrypted_reference() -> None:
    session = FakeSession([FakeResult(row=_row(fencing_token=2))])
    repo = repository_with(session)
    lease = ManagedAllocationLease(
        allocation_id="msa_1",
        worker_id="worker_1",
        fencing_token=2,
        expires_at=NOW + timedelta(seconds=300),
    )

    await repo.commit_active(
        lease,
        AllocationResult(
            provider_ref="ref_secret",
            ownership_digest="digest_1",
            state=ManagedSandboxState.ACTIVE,
        ),
        encrypted_ref=b"cipher",
        now=NOW,
    )

    _statement, params = session.statements[-1]
    assert params["provider_ref"] == b"cipher"
    assert "ref_secret" not in str(params)


async def test_read_allocation_plan_joins_admission_for_the_idempotency_key() -> None:
    session = FakeSession(
        [FakeResult(row=_row(allocation_id="msa_1", idempotency_key="idem_9"))]
    )
    repo = repository_with(session)

    plan = await repo.read_allocation_plan("msa_1")

    statement, params = session.statements[-1]
    assert "JOIN coding_sandbox_admissions AS a" in statement
    assert "a.admission_id = s.admission_id" in statement
    assert "a.idempotency_key" in statement
    assert "s.allocation_id = :allocation_id" in statement
    assert params["allocation_id"] == "msa_1"
    assert isinstance(plan, AllocationPlan)
    assert plan.idempotency_key == "idem_9"
    assert plan.allocation.allocation_id == "msa_1"


async def test_read_allocation_plan_raises_when_the_allocation_is_missing() -> None:
    session = FakeSession([FakeResult(row=None)])
    repo = repository_with(session)

    with pytest.raises(ManagedSandboxNotFound):
        await repo.read_allocation_plan("msa_missing")

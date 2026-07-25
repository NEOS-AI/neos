from datetime import UTC, datetime, timedelta

import pytest

from neos.coding.managed.admission import AdmissionRequest, AdmissionResult
from neos.coding.managed.domain import AdmissionDecision, AdmissionReason
from neos.coding.managed.repository import PostgresManagedSandboxRepository


NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


class FakeResult:
    def __init__(self, *, row=None, rows=()) -> None:
        self._row = row
        self._rows = list(rows)

    def first(self):
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
    assert "coding_managed_sandboxes" in allocation_sql
    assert allocation_params["admission_id"] == "adm_1"
    assert allocation_params["state"] == "admitted"
    assert "coding_sandbox_admissions" in sql
    assert result.created is True
    assert result.allocation_id == "alloc_1"


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
    session = FakeSession([FakeResult(row=("alloc_1",))])

    changed = await repository_for(session).settle_reservation(
        "alloc_1",
        active_seconds=123,
        archive_bytes=456,
        cost_micros=789,
        now=NOW,
    )

    sql, params = session.statements[0]
    assert "reservation_state = 'settled'" in sql
    assert "reservation_settled_at = :now" in sql
    assert "reservation_released_at = NULL" in sql
    assert "reservation_state = 'reserved'" in sql
    assert params["active_seconds"] == 123
    assert params["archive_bytes"] == 456
    assert params["cost_micros"] == 789
    assert changed is True


async def test_release_expired_reservations_sets_state_and_timestamp_atomically() -> (
    None
):
    session = FakeSession([FakeResult(rows=[("alloc_1",), ("alloc_2",)])])

    released = await repository_for(session).release_expired_reservations(
        now=NOW, limit=2
    )

    sql, params = session.statements[0]
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "reservation_state = 'released'" in sql
    assert "reservation_released_at = :now" in sql
    assert "reservation_settled_at = NULL" in sql
    assert "reservation_state = 'reserved'" in sql
    assert "reservation_expires_at <= :now" in sql
    assert params["limit"] == 2
    assert released == ["alloc_1", "alloc_2"]


@pytest.mark.parametrize("limit", [0, 1001])
async def test_release_rejects_unbounded_batch(limit: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 1000"):
        await repository_for(FakeSession([])).release_expired_reservations(
            now=NOW, limit=limit
        )

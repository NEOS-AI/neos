from datetime import UTC, datetime, timedelta

import pytest

from neos.coding.domain.durability import ExecutionLease, StaleExecutionLease


NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


def test_execution_lease_requires_positive_fencing_token() -> None:
    with pytest.raises(ValueError, match="fencing token"):
        ExecutionLease(
            task_id="ct_1",
            run_id="cr_1",
            worker_id="worker-a",
            fencing_token=0,
            acquired_at=NOW,
            expires_at=NOW + timedelta(seconds=30),
        )


def test_execution_lease_rejects_non_future_expiry() -> None:
    with pytest.raises(ValueError, match="expires_at"):
        ExecutionLease(
            task_id="ct_1",
            run_id="cr_1",
            worker_id="worker-a",
            fencing_token=1,
            acquired_at=NOW,
            expires_at=NOW,
        )


def test_stale_execution_lease_is_a_distinct_runtime_error() -> None:
    assert issubclass(StaleExecutionLease, RuntimeError)

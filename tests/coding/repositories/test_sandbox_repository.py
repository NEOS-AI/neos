from dataclasses import replace
from datetime import UTC, datetime

import pytest

from neos.coding.domain.durability import ExecutionLease, StaleExecutionLease
from neos.coding.repositories.sandbox_repository import (
    PostgresSandboxBindingRepository,
)
from neos.coding.sandbox.bindings import SandboxBinding


NOW = datetime(2026, 7, 19, 10, tzinfo=UTC)
LEASE = ExecutionLease(
    "ct_1", "cr_1", "worker-1", 7, NOW, datetime(2026, 7, 19, 10, 1, tzinfo=UTC)
)
BINDING = SandboxBinding(
    task_id="ct_1",
    run_id="cr_1",
    sandbox_id="sb_1",
    provider="fake",
    image_digest="sha256:image",
    workspace_revision="3",
    latest_snapshot_id="ss_1",
    health_state="healthy",
    mutation_count=0,
    version=1,
)


class Result:
    def __init__(self, row=None) -> None:
        self._row = row

    def first(self):
        return self._row


class Session:
    def __init__(self, results) -> None:
        self.results = list(results)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def begin(self):
        return self

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return Result(self.results.pop(0) if self.results else None)


def row(value: SandboxBinding):
    return (
        value.task_id,
        value.run_id,
        value.sandbox_id,
        value.provider,
        value.image_digest,
        value.workspace_revision,
        value.latest_snapshot_id,
        value.health_state,
        value.mutation_count,
        value.version,
    )


def factory(session: Session):
    async def create_session():
        return session

    return create_session


async def test_get_maps_binding_row() -> None:
    session = Session([row(BINDING)])
    repository = PostgresSandboxBindingRepository(factory(session))

    found = await repository.get("ct_1")

    query, params = session.calls[0]
    assert "FROM coding_sandbox_bindings" in query
    assert params == {"task_id": "ct_1"}
    assert found == BINDING


async def test_replace_uses_version_compare_and_swap_and_maps_returned_row() -> None:
    replacement = replace(BINDING, sandbox_id="sb_2", workspace_revision="4")
    session = Session([row(replace(replacement, version=2))])
    repository = PostgresSandboxBindingRepository(factory(session))

    updated = await repository.replace_admin(
        replacement, expected_version=1, now=NOW
    )

    query, params = session.calls[0]
    assert "WHERE task_id = :task_id AND version = :expected_version" in query
    assert "version = version + 1" in query
    assert "RETURNING" in query
    assert params["expected_version"] == 1
    assert updated is not None and updated.version == 2


async def test_replace_returns_none_when_compare_and_swap_loses() -> None:
    session = Session([None])
    repository = PostgresSandboxBindingRepository(factory(session))

    updated = await repository.replace_admin(
        BINDING, expected_version=4, now=NOW
    )

    assert updated is None


async def test_delete_uses_version_cas_and_returns_result() -> None:
    session = Session([("ct_1",)])
    repository = PostgresSandboxBindingRepository(factory(session))

    deleted = await repository.delete_admin("ct_1", expected_version=3)

    query, params = session.calls[0]
    assert "DELETE FROM coding_sandbox_bindings" in query
    assert "WHERE task_id = :task_id AND version = :expected_version" in query
    assert "RETURNING task_id" in query
    assert params == {"task_id": "ct_1", "expected_version": 3}
    assert deleted is True


async def test_delete_returns_false_when_version_cas_loses() -> None:
    session = Session([None])
    repository = PostgresSandboxBindingRepository(factory(session))

    assert await repository.delete_admin("ct_1", expected_version=3) is False


async def test_worker_create_validates_execution_lease_in_insert_transaction() -> None:
    session = Session([("ct_1",)])
    repository = PostgresSandboxBindingRepository(factory(session))

    created = await repository.create_fenced(BINDING, lease=LEASE, now=NOW)

    query, params = session.calls[0]
    assert created is True
    assert "FROM coding_run_leases" in query
    assert "fencing_token = :fencing_token" in query
    assert "worker_id = :worker_id" in query
    assert "expires_at > :now" in query
    assert params["fencing_token"] == 7


async def test_worker_replace_validates_lease_in_same_update_as_binding_cas() -> None:
    replacement = replace(BINDING, workspace_revision="4")
    session = Session([row(replace(replacement, version=2))])
    repository = PostgresSandboxBindingRepository(factory(session))

    updated = await repository.replace_fenced(
        replacement, expected_version=1, lease=LEASE, now=NOW
    )

    query, params = session.calls[0]
    assert updated is not None
    assert "version = :expected_version" in query
    assert "EXISTS" in query
    assert "coding_run_leases" in query
    assert "fencing_token = :fencing_token" in query
    assert params["worker_id"] == "worker-1"


async def test_worker_can_validate_lease_transactionally_before_lifecycle_change() -> None:
    session = Session([(1,)])
    repository = PostgresSandboxBindingRepository(factory(session))

    await repository.validate_fenced(lease=LEASE, now=NOW)

    query, params = session.calls[0]
    assert "coding_run_leases" in query
    assert "FOR UPDATE" in query
    assert params["fencing_token"] == 7


async def test_worker_replace_rejects_stale_lease_after_atomic_cas_miss() -> None:
    session = Session([None, None])
    repository = PostgresSandboxBindingRepository(factory(session))

    with pytest.raises(StaleExecutionLease):
        await repository.replace_fenced(
            BINDING, expected_version=1, lease=LEASE, now=NOW
        )

    assert "FOR UPDATE" in session.calls[1][0]

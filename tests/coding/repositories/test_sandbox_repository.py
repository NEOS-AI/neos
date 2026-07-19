from dataclasses import replace
from datetime import UTC, datetime

from neos.coding.repositories.sandbox_repository import (
    PostgresSandboxBindingRepository,
)
from neos.coding.sandbox.bindings import SandboxBinding


NOW = datetime(2026, 7, 19, 10, tzinfo=UTC)
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


async def test_create_uses_conflict_safe_insert() -> None:
    session = Session([("ct_1",)])
    repository = PostgresSandboxBindingRepository(factory(session))

    created = await repository.create(BINDING, now=NOW)

    query, params = session.calls[0]
    assert created is True
    assert "ON CONFLICT (task_id) DO NOTHING" in query
    assert "RETURNING task_id" in query
    assert params["sandbox_id"] == "sb_1"


async def test_replace_uses_version_compare_and_swap_and_maps_returned_row() -> None:
    replacement = replace(BINDING, sandbox_id="sb_2", workspace_revision="4")
    session = Session([row(replace(replacement, version=2))])
    repository = PostgresSandboxBindingRepository(factory(session))

    updated = await repository.replace(replacement, expected_version=1, now=NOW)

    query, params = session.calls[0]
    assert "WHERE task_id = :task_id AND version = :expected_version" in query
    assert "version = version + 1" in query
    assert "RETURNING" in query
    assert params["expected_version"] == 1
    assert updated is not None and updated.version == 2


async def test_replace_returns_none_when_compare_and_swap_loses() -> None:
    session = Session([None])
    repository = PostgresSandboxBindingRepository(factory(session))

    updated = await repository.replace(BINDING, expected_version=4, now=NOW)

    assert updated is None

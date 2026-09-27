"""Store SQL shape. No live database and no CodingRunService."""

from __future__ import annotations

from pathlib import Path

import pytest

from neos.gepa_opt.evaluators import clear_evaluators, get_evaluator, register_evaluator
from neos.gepa_opt.store import GepaOptStore

pytestmark = pytest.mark.no_db

_MIGRATION = (
    Path(__file__).resolve().parents[2] / "db" / "migrations" / "066_add_gepa_opt.sql"
)


class _Result:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _Begin:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _Begin:
        self._session.begins += 1
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class FakeSession:
    def __init__(self, rowcount: int = 1) -> None:
        self.statements: list[tuple[str, dict | None]] = []
        self.begins = 0
        self._rowcount = rowcount

    def begin(self) -> _Begin:
        return _Begin(self)

    async def execute(self, stmt: object, params: dict | None = None) -> _Result:
        self.statements.append((str(stmt), params))
        return _Result(self._rowcount)


class _Conn:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> FakeSession:
        return self._session

    async def __aexit__(self, *_exc: object) -> None:
        return None


def _factory(session: FakeSession):
    async def open_session() -> _Conn:
        return _Conn(session)

    return open_session


def _sql(session: FakeSession) -> list[str]:
    return [statement.lower() for statement, _params in session.statements]


def test_migration_has_required_constraints() -> None:
    sql = _MIGRATION.read_text(encoding="utf-8").lower()
    assert "merge_enabled = false" in sql
    assert "component_cursor" in sql
    assert "approved_by varchar(255)" in sql
    assert "where status = 'approved'" in sql
    assert "pickle" not in sql
    assert sql.count("owner_namespace text not null") == 5


@pytest.mark.asyncio
async def test_insert_run_sets_seed_after_the_candidate_row() -> None:
    session = FakeSession()
    store = GepaOptStore(_factory(session))
    await store.insert_run_with_seed(
        run_id="11111111-1111-1111-1111-111111111111",
        owner_namespace="owner:1",
        surface="coding_overlay",
        engine_label="gepa",
        pareto_enabled=True,
        max_evals=10,
        max_token_cost=100,
        seed_components={"instr": "a"},
        examples=[{"split": "train", "payload": {"id": "t"}}],
    )
    sql = _sql(session)
    run_at = next(i for i, statement in enumerate(sql) if "insert into gepa_opt_runs" in statement)
    candidate_at = next(
        i for i, statement in enumerate(sql) if "insert into gepa_opt_candidates" in statement
    )
    seed_at = next(i for i, statement in enumerate(sql) if "seed_candidate_id" in statement)
    assert run_at < candidate_at < seed_at
    assert session.begins == 1
    assert all("owner_namespace" in statement for statement in sql)


@pytest.mark.asyncio
async def test_lost_claim_returns_false() -> None:
    session = FakeSession(rowcount=0)
    store = GepaOptStore(_factory(session))
    claimed = await store.claim("11111111-1111-1111-1111-111111111111", "owner:1", "task-1")
    assert claimed is False
    statement = _sql(session)[0]
    assert "status = 'queued'" in statement
    assert "celery_task_id is null" in statement
    assert "owner_namespace" in statement


@pytest.mark.asyncio
async def test_commit_iteration_is_one_transaction() -> None:
    session = FakeSession()
    store = GepaOptStore(_factory(session))
    await store.commit_iteration(
        run_id="11111111-1111-1111-1111-111111111111",
        owner_namespace="owner:1",
        candidate={
            "iteration": 1,
            "proposal_kind": "reflective",
            "components": {"instr": "b"},
            "accepted": True,
            "val_mean": 0.5,
        },
        scores=[
            {
                "example_id": "22222222-2222-2222-2222-222222222222",
                "split": "val",
                "phase": "full_val",
                "score": 0.5,
                "side_info": {},
            }
        ],
        advance_cursor=True,
        best_candidate_id=None,
    )
    assert session.begins == 1
    assert any("component_cursor" in statement for statement in _sql(session))


@pytest.mark.asyncio
async def test_fail_run_does_not_insert_an_overlay() -> None:
    session = FakeSession()
    store = GepaOptStore(_factory(session))
    await store.fail_run("11111111-1111-1111-1111-111111111111", "owner:1", "no_evaluator")
    joined = "\n".join(_sql(session))
    assert "gepa_opt_overlays" not in joined
    assert "error_code" in joined


@pytest.mark.asyncio
async def test_approve_locks_in_overlay_id_order_and_archives_first() -> None:
    session = FakeSession()
    store = GepaOptStore(_factory(session))
    await store.approve("33333333-3333-3333-3333-333333333333", "user-1", "owner:1")
    sql = _sql(session)
    lock_at = next(i for i, statement in enumerate(sql) if "for update" in statement)
    archive_at = next(i for i, statement in enumerate(sql) if "set status = 'archived'" in statement)
    approve_at = next(i for i, statement in enumerate(sql) if "set status = 'approved'" in statement)
    assert "order by overlay_id" in sql[lock_at]
    assert lock_at < archive_at < approve_at
    assert session.statements[approve_at][1]["actor"] == "user-1"


@pytest.mark.asyncio
async def test_approve_requires_an_actor() -> None:
    store = GepaOptStore(_factory(FakeSession()))
    with pytest.raises(ValueError):
        await store.approve("33333333-3333-3333-3333-333333333333", "", "owner:1")


def test_evaluator_registry_starts_empty() -> None:
    clear_evaluators()
    assert get_evaluator("coding_overlay") is None
    register_evaluator("coding_overlay", lambda _c, _e: (1.0, {}))
    assert get_evaluator("coding_overlay") is not None
    clear_evaluators()

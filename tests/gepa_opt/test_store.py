"""Store SQL shape. No live database and no CodingRunService."""

from __future__ import annotations

from pathlib import Path

import pytest

from neos.gepa_opt.evaluators import clear_evaluators, get_evaluator, register_evaluator
from neos.gepa_opt.store import GepaOptStore, _example_item

pytestmark = pytest.mark.no_db

_MIGRATION = (
    Path(__file__).resolve().parents[2] / "db" / "migrations" / "066_add_gepa_opt.sql"
)
_FKS = (
    Path(__file__).resolve().parents[2] / "db" / "migrations" / "067_add_gepa_opt_candidate_fks.sql"
)


class _Mappings:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def all(self) -> list[dict]:
        return list(self._rows)

    def first(self) -> dict | None:
        return self._rows[0] if self._rows else None


class _Result:
    def __init__(self, rowcount: int, rows: list[dict] | None = None) -> None:
        self.rowcount = rowcount
        self._rows = rows or []

    def mappings(self) -> _Mappings:
        return _Mappings(self._rows)


class _Begin:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _Begin:
        self._session.begins += 1
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class FakeSession:
    def __init__(self, rowcount: int = 1, rows: list[dict] | None = None) -> None:
        self.statements: list[tuple[str, dict | None]] = []
        self.begins = 0
        self._rowcount = rowcount
        self._rows = rows or []

    def begin(self) -> _Begin:
        return _Begin(self)

    async def execute(self, stmt: object, params: dict | None = None) -> _Result:
        self.statements.append((str(stmt), params))
        return _Result(self._rowcount, self._rows)


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
    fks = _FKS.read_text(encoding="utf-8").lower()
    assert "gepa_opt_runs_seed_candidate_fk" in fks
    assert "gepa_opt_runs_best_candidate_fk" in fks
    assert "gepa_opt_candidates_parent_fk" in fks


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
    assert claimed == "lost"
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


def test_example_item_attaches_the_id_column() -> None:
    item = _example_item({"example_id": "ex-1", "split": "val", "payload": {"id": "v"}})
    assert item["example_id"] == "ex-1"
    assert item["split"] == "val"
    assert item["id"] == "v"


@pytest.mark.asyncio
async def test_approve_locks_in_overlay_id_order_and_archives_first() -> None:
    session = FakeSession(
        rows=[
            {
                "overlay_id": "33333333-3333-3333-3333-333333333333",
                "status": "staged",
            }
        ]
    )
    store = GepaOptStore(_factory(session))
    await store.approve("33333333-3333-3333-3333-333333333333", "user-1", "owner:1")
    sql = _sql(session)
    lock_at = next(i for i, statement in enumerate(sql) if "for update" in statement)
    archive_at = next(i for i, statement in enumerate(sql) if "set status = 'archived'" in statement)
    approve_at = next(i for i, statement in enumerate(sql) if "set status = 'approved'" in statement)
    assert "order by overlay_id" in sql[lock_at]
    assert lock_at < archive_at < approve_at
    assert session.statements[approve_at][1]["actor"] == "user-1"
    assert "status = 'staged'" in sql[approve_at]


@pytest.mark.asyncio
async def test_approve_refuses_a_row_that_is_not_staged() -> None:
    session = FakeSession(rows=[{"overlay_id": "other", "status": "approved"}])
    store = GepaOptStore(_factory(session))
    with pytest.raises(ValueError, match="staged"):
        await store.approve("33333333-3333-3333-3333-333333333333", "user-1", "owner:1")
    assert not any("set status = 'archived'" in statement for statement in _sql(session))


@pytest.mark.asyncio
async def test_approve_requires_an_actor() -> None:
    store = GepaOptStore(_factory(FakeSession()))
    with pytest.raises(ValueError):
        await store.approve("33333333-3333-3333-3333-333333333333", "", "owner:1")


@pytest.mark.asyncio
async def test_approved_components_filters_owner_and_status() -> None:
    session = FakeSession()
    store = GepaOptStore(_factory(session))
    found = await store.approved_components("owner:1", "coding_overlay")
    statement, params = session.statements[0]
    assert "status = 'approved'" in statement.lower()
    assert params["owner_namespace"] == "owner:1"
    assert params["surface"] == "coding_overlay"
    assert found is None


def test_evaluator_registry_starts_empty() -> None:
    clear_evaluators()
    assert get_evaluator("coding_overlay") is None
    register_evaluator("coding_overlay", lambda _c, _e: (1.0, {}))
    assert get_evaluator("coding_overlay") is not None
    clear_evaluators()

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from neos.subagent.postgres import (
    PostgresSubagentStore,
    _INSERT_CHECKPOINT,
    _LATEST_CHECKPOINT,
    _RESTORE_CHECKPOINT,
    _SELECT_RUN,
    _SELECT_RUN_FOR_UPDATE,
    _UPDATE_CHECKPOINT,
    _UPDATE_RUN_IF_LIVE,
    _mapping,
)
from neos.subagent.store import PLACEHOLDER_STATE, CheckpointWrite, is_placeholder
from neos.subagent.types import SubagentStatus


pytestmark = pytest.mark.no_db

_NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
_MIGRATION = Path("db/migrations/055_add_subagent_tables.sql")
# 055 가 표를 만들고 091 이 `max_turns` 제약을 티켓 상한에 맞춘다(D114).
_MIGRATIONS = (_MIGRATION, _MIGRATION.with_name("091_widen_subagent_max_turns.sql"))


def _write(**overrides) -> CheckpointWrite:
    payload: dict[str, Any] = {
        "loop_state": {"messages": [{"role": "user", "content": "brief"}]},
        "status": SubagentStatus.RUNNING,
        "turn_count": 1,
        "tool_count": 0,
    }
    payload.update(overrides)
    return CheckpointWrite(**payload)


def _run_row(run_id: str, **overrides) -> SimpleNamespace:
    payload: dict[str, Any] = {
        "run_id": run_id,
        "parent_kind": "coding",
        "parent_id": "ct_cas",
        "parent_run_id": "cr_cas",
        "parent_tool_call_id": "toolu_cas",
        "lineage_kind": "delegate",
        "spec": "explore",
        "status": "pending",
        "provider": "anthropic",
        "model": "claude-test",
        "max_turns": 4,
        "turn_count": 0,
        "tool_count": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_micros": 0,
        "briefing_json": {"goal": "cas"},
        "error_code": "",
        "sandbox_mode": "none",
        "created_at": _NOW,
        "updated_at": _NOW,
        "completed_at": None,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _ckpt_row(
    checkpoint_id: str, run_id: str, seq: int, loop_state: Any
) -> SimpleNamespace:
    return SimpleNamespace(
        checkpoint_id=checkpoint_id,
        run_id=run_id,
        seq=seq,
        loop_state_json=loop_state,
        created_at=_NOW,
    )


class _FakeResult:
    def __init__(self, row: Any = None, rows: list[Any] | None = None) -> None:
        self._row = row
        self._rows = list(rows or ([] if row is None else [row]))

    def first(self):
        return self._row

    def all(self):
        return self._rows


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


class CasSession:
    """In-memory 055 contract: FOR UPDATE, latest/restore, UNIQUE (run_id, seq)."""

    def __init__(self) -> None:
        self.runs: dict[str, SimpleNamespace] = {}
        self.checkpoints: dict[str, list[SimpleNamespace]] = {}
        self._racing: dict[str, list[SimpleNamespace]] = {}
        self.statements: list[tuple[str, dict[str, Any]]] = []

    def seed_run(self, run_id: str, **overrides) -> SimpleNamespace:
        row = _run_row(run_id, **overrides)
        self.runs[run_id] = row
        self.checkpoints.setdefault(run_id, [])
        return row

    def seed_checkpoint(
        self, run_id: str, checkpoint_id: str, seq: int, loop_state: Any
    ) -> SimpleNamespace:
        row = _ckpt_row(checkpoint_id, run_id, seq, loop_state)
        self.checkpoints.setdefault(run_id, []).append(row)
        return row

    def stage_unique_collision(self, row: SimpleNamespace) -> None:
        # Visible to UNIQUE, hidden from SELECT latest until INSERT collides.
        self._racing.setdefault(row.run_id, []).append(row)

    def begin(self):
        return _FakeTransaction()

    def begin_nested(self):
        return _FakeTransaction()

    async def execute(self, statement, params=None):
        params = dict(params or {})
        sql = str(statement)
        self.statements.append((sql, params))
        if _matches(statement, _SELECT_RUN_FOR_UPDATE) or _matches(
            statement, _SELECT_RUN
        ):
            return _FakeResult(self.runs.get(params["run_id"]))
        if _matches(statement, _RESTORE_CHECKPOINT):
            return _FakeResult(self._restore(params["run_id"]))
        if _matches(statement, _LATEST_CHECKPOINT):
            return _FakeResult(self._latest(params["run_id"]))
        if _matches(statement, _INSERT_CHECKPOINT):
            return self._insert_checkpoint(sql, params)
        if _matches(statement, _UPDATE_CHECKPOINT):
            return self._update_checkpoint(params)
        if _matches(statement, _UPDATE_RUN_IF_LIVE):
            return self._update_run_if_live(params)
        raise AssertionError(f"unhandled SQL: {sql}")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    def _visible(self, run_id: str) -> list[SimpleNamespace]:
        return self.checkpoints.setdefault(run_id, [])

    def _latest(self, run_id: str) -> SimpleNamespace | None:
        rows = self._visible(run_id)
        if not rows:
            return None
        return max(rows, key=lambda item: int(item.seq))

    def _restore(self, run_id: str) -> SimpleNamespace | None:
        rows = [
            item
            for item in self._visible(run_id)
            if not is_placeholder(_mapping(item.loop_state_json))
        ]
        if not rows:
            return None
        return max(rows, key=lambda item: int(item.seq))

    def _insert_checkpoint(self, sql: str, params: dict[str, Any]) -> _FakeResult:
        run_id = params["run_id"]
        seq = int(params["seq"])
        checkpoint_id = params["checkpoint_id"]
        visible = self._visible(run_id)
        racing = self._racing.get(run_id, [])
        collided = [
            item
            for item in visible + racing
            if int(item.seq) == seq or item.checkpoint_id == checkpoint_id
        ]
        if collided:
            for item in racing:
                if item not in visible:
                    visible.append(item)
            self._racing[run_id] = []
            raise IntegrityError(sql, params, Exception("unique_violation"))
        visible.append(
            _ckpt_row(checkpoint_id, run_id, seq, params["loop_state_json"])
        )
        return _FakeResult()

    def _update_checkpoint(self, params: dict[str, Any]) -> _FakeResult:
        run_id = params["run_id"]
        seq = int(params["seq"])
        for item in self._visible(run_id):
            if int(item.seq) == seq:
                item.loop_state_json = params["loop_state_json"]
        return _FakeResult()

    def _update_run_if_live(self, params: dict[str, Any]) -> _FakeResult:
        run = self.runs.get(params["run_id"])
        if run is None or run.status in {"completed", "failed", "killed"}:
            return _FakeResult()
        run.status = params["status"]
        run.turn_count = params["turn_count"]
        run.tool_count = params["tool_count"]
        run.input_tokens = params["input_tokens"]
        run.output_tokens = params["output_tokens"]
        run.cost_micros = params["cost_micros"]
        run.error_code = params["error_code"]
        run.updated_at = params["updated_at"]
        run.completed_at = params["completed_at"]
        return _FakeResult()


def _matches(statement, target) -> bool:
    return statement is target or str(statement) == str(target)


def _store(session: CasSession) -> PostgresSubagentStore:
    async def session_factory():
        return session

    return PostgresSubagentStore(session_factory)


@pytest.mark.asyncio
async def test_reserve_placeholder_takeover_keeps_same_seq() -> None:
    session = CasSession()
    run_id = "sa_takeover"
    checkpoint_id = "sc_placeholder"
    session.seed_run(run_id)
    session.seed_checkpoint(run_id, checkpoint_id, 1, dict(PLACEHOLDER_STATE))
    store = _store(session)

    reserved = await store.reserve(run_id, None)
    assert reserved.matched is True
    assert reserved.takeover is True
    assert reserved.seq == 1
    assert reserved.checkpoint_id == checkpoint_id
    assert reserved.loop_state == PLACEHOLDER_STATE

    same = await store.reserve(run_id, checkpoint_id)
    assert same.matched is True
    assert same.takeover is True
    assert same.seq == 1
    assert same.checkpoint_id == checkpoint_id

    committed = await store.commit(same, _write())
    assert committed.latest_seq == 1
    assert committed.latest_checkpoint_id == checkpoint_id
    assert committed.status is SubagentStatus.RUNNING
    state = await store.get_loop_state(run_id)
    assert state.get("_placeholder") is not True
    assert state.get("messages") == [{"role": "user", "content": "brief"}]


@pytest.mark.asyncio
async def test_reserve_unique_seq_integrity_error_is_mismatch() -> None:
    session = CasSession()
    run_id = "sa_unique"
    expected = "sc_one"
    session.seed_run(run_id, status="running")
    session.seed_checkpoint(
        run_id, expected, 1, {"messages": [{"role": "user", "content": "brief"}]}
    )
    session.stage_unique_collision(
        _ckpt_row("sc_winner", run_id, 2, dict(PLACEHOLDER_STATE))
    )
    store = _store(session)

    reserved = await store.reserve(run_id, expected)
    assert reserved.matched is False
    assert reserved.takeover is False
    assert reserved.seq == 2
    assert reserved.checkpoint_id == "sc_winner"
    assert any("INSERT INTO subagent_checkpoints" in sql for sql, _ in session.statements)


@pytest.mark.asyncio
async def test_reserve_stale_expected_is_mismatch() -> None:
    session = CasSession()
    run_id = "sa_stale"
    session.seed_run(run_id, status="running")
    session.seed_checkpoint(
        run_id, "sc_one", 1, {"messages": [{"role": "user", "content": "brief"}]}
    )
    store = _store(session)

    reserved = await store.reserve(run_id, "sc_stale")
    assert reserved.matched is False
    assert reserved.takeover is False
    assert reserved.seq == 1
    assert reserved.checkpoint_id == "sc_one"
    loaded = await store.get(run_id)
    assert loaded.latest_seq == 1
    assert loaded.latest_checkpoint_id == "sc_one"


class _InjectUniqueCollision:
    """Same-session racing INSERT after latest is read, so UNIQUE fires on insert."""

    def __init__(self, inner, winner: dict[str, Any]) -> None:
        self._inner = inner
        self._winner = winner
        self._armed = True

    def begin(self):
        return self._inner.begin()

    def begin_nested(self):
        return self._inner.begin_nested()

    async def execute(self, statement, params=None):
        result = await self._inner.execute(statement, params)
        if self._armed and _matches(statement, _RESTORE_CHECKPOINT):
            self._armed = False
            await self._inner.execute(
                _INSERT_CHECKPOINT,
                {
                    "checkpoint_id": self._winner["checkpoint_id"],
                    "run_id": self._winner["run_id"],
                    "seq": self._winner["seq"],
                    "loop_state_json": json.dumps(self._winner["loop_state"]),
                    "created_at": self._winner["created_at"],
                },
            )
        return result


@pytest.fixture
async def live_postgres():
    url = os.getenv("CODING_TEST_DATABASE_URL")
    if not url:
        pytest.skip("CODING_TEST_DATABASE_URL is not configured")
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(url)
    async with engine.begin() as connection:
        for migration in _MIGRATIONS:
            for statement in migration.read_text().split(";"):
                if statement.strip():
                    await connection.exec_driver_sql(statement)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def session_factory():
        @asynccontextmanager
        async def context():
            async with maker() as session:
                yield session

        return context()

    try:
        yield session_factory
    finally:
        async with engine.begin() as connection:
            await connection.exec_driver_sql(
                "TRUNCATE subagent_checkpoints, subagent_runs CASCADE"
            )
        await engine.dispose()


async def _seed_live(
    session_factory,
    *,
    run_id: str,
    checkpoint_id: str,
    seq: int,
    loop_state: dict[str, Any],
    status: str = "pending",
) -> None:
    from sqlalchemy import text

    async with await session_factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    """
                    INSERT INTO subagent_runs (
                        run_id, parent_kind, parent_id, parent_run_id,
                        parent_tool_call_id, lineage_kind, spec, status,
                        provider, model, max_turns, turn_count, tool_count,
                        input_tokens, output_tokens, cost_micros, briefing_json,
                        error_code, sandbox_mode, created_at, updated_at,
                        completed_at
                    ) VALUES (
                        :run_id, 'coding', :parent_id, :parent_run_id,
                        :parent_tool_call_id, 'delegate', 'explore', :status,
                        'anthropic', 'claude-test', 4, 0, 0,
                        0, 0, 0, CAST(:briefing_json AS JSONB),
                        '', 'none', :now, :now, NULL
                    )
                    """
                ),
                {
                    "run_id": run_id,
                    "parent_id": f"ct_{uuid4().hex}",
                    "parent_run_id": f"cr_{uuid4().hex}",
                    "parent_tool_call_id": f"toolu_{uuid4().hex}",
                    "status": status,
                    "briefing_json": json.dumps({"goal": "cas"}),
                    "now": _NOW,
                },
            )
            await session.execute(
                text(
                    """
                    INSERT INTO subagent_checkpoints (
                        checkpoint_id, run_id, seq, loop_state_json, created_at
                    ) VALUES (
                        :checkpoint_id, :run_id, :seq,
                        CAST(:loop_state_json AS JSONB), :now
                    )
                    """
                ),
                {
                    "checkpoint_id": checkpoint_id,
                    "run_id": run_id,
                    "seq": seq,
                    "loop_state_json": json.dumps(loop_state),
                    "now": _NOW,
                },
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_reserve_placeholder_takeover_keeps_same_seq(
    live_postgres,
) -> None:
    run_id = f"sa_{uuid4().hex}"
    checkpoint_id = f"sc_{uuid4().hex}"
    await _seed_live(
        live_postgres,
        run_id=run_id,
        checkpoint_id=checkpoint_id,
        seq=1,
        loop_state=dict(PLACEHOLDER_STATE),
    )
    store = PostgresSubagentStore(live_postgres)

    reserved = await store.reserve(run_id, None)
    assert reserved.matched is True
    assert reserved.takeover is True
    assert reserved.seq == 1
    assert reserved.checkpoint_id == checkpoint_id

    committed = await store.commit(reserved, _write())
    assert committed.latest_seq == 1
    assert committed.latest_checkpoint_id == checkpoint_id
    state = await store.get_loop_state(run_id)
    assert state.get("_placeholder") is not True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_reserve_unique_seq_integrity_error_is_mismatch(
    live_postgres,
) -> None:
    run_id = f"sa_{uuid4().hex}"
    expected = f"sc_{uuid4().hex}"
    winner_id = f"sc_{uuid4().hex}"
    await _seed_live(
        live_postgres,
        run_id=run_id,
        checkpoint_id=expected,
        seq=1,
        loop_state={"messages": [{"role": "user", "content": "brief"}]},
        status="running",
    )

    async def colliding_factory():
        @asynccontextmanager
        async def context():
            async with await live_postgres() as session:
                yield _InjectUniqueCollision(
                    session,
                    {
                        "checkpoint_id": winner_id,
                        "run_id": run_id,
                        "seq": 2,
                        "loop_state": dict(PLACEHOLDER_STATE),
                        "created_at": _NOW,
                    },
                )

        return context()

    store = PostgresSubagentStore(colliding_factory)
    reserved = await store.reserve(run_id, expected)
    assert reserved.matched is False
    assert reserved.takeover is False
    assert reserved.seq == 2
    assert reserved.checkpoint_id == winner_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_reserve_stale_expected_is_mismatch(live_postgres) -> None:
    run_id = f"sa_{uuid4().hex}"
    checkpoint_id = f"sc_{uuid4().hex}"
    await _seed_live(
        live_postgres,
        run_id=run_id,
        checkpoint_id=checkpoint_id,
        seq=1,
        loop_state={"messages": [{"role": "user", "content": "brief"}]},
        status="running",
    )
    store = PostgresSubagentStore(live_postgres)

    reserved = await store.reserve(run_id, "sc_stale")
    assert reserved.matched is False
    assert reserved.takeover is False
    assert reserved.seq == 1
    assert reserved.checkpoint_id == checkpoint_id
    loaded = await store.get(run_id)
    assert loaded.latest_seq == 1
    assert loaded.latest_checkpoint_id == checkpoint_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_store_accepts_the_ticket_turn_ceiling(live_postgres) -> None:
    """DB 의 `max_turns` 제약이 코드의 티켓 상한과 같다(091, D114). 055 의 8 이 compose 의 12 턴 행을 거절했다."""
    from neos.subagent.types import (
        MAX_TICKET_TURNS,
        ModelPin,
        ParentBriefing,
        ParentKind,
        SubagentTicket,
    )

    store = PostgresSubagentStore(live_postgres)
    ticket = SubagentTicket(
        parent_kind=ParentKind.DEEP_ANALYSIS,
        parent_id=f"da_{uuid4().hex[:8]}",
        parent_run_id=f"da_{uuid4().hex[:8]}",
        parent_tool_call_id="compose:root:0",
        spec="explore",
        briefing=ParentBriefing(goal="ceiling"),
        model=ModelPin(provider="anthropic", model="claude-test"),
        max_turns=MAX_TICKET_TURNS,
    )
    record = await store.resolve_or_create(ticket)
    assert record.max_turns == MAX_TICKET_TURNS

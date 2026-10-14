"""작업 생명주기 (spec 2026-10-13 §4.4).

입구에서 실행 한 번이 작업 하나다. 같은 ID 체계 · 같은 승인 상태 · 같은 결과 저장 위치를 모든
입구(웹·채널·예약·트리거)가 쓴다. 전달(아웃박스)은 Plan 2b 가 붙인다.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import text

_CHANNEL_SOURCES = frozenset({"slack", "discord", "telegram"})
_TRANSITIONS: dict[str, frozenset[str]] = {
    "running": frozenset({"waiting_approval", "completed", "failed"}),
    "waiting_approval": frozenset({"running", "expired"}),
}


class _Keep:
    def __repr__(self) -> str:
        return "KEEP"


KEEP: Any = _Keep()


@dataclass(frozen=True)
class WorkRecord:
    work_id: str
    entry: str
    kind: str
    user_id: str
    session_id: str | None
    status: str
    pending: dict[str, Any] | None
    result: dict[str, Any] | None
    delivery: dict[str, Any]
    ref_id: str | None
    parent_work_id: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class WorkConflict(RuntimeError):
    pass


class WorkStore(Protocol):
    async def create(self, record: WorkRecord) -> None: ...

    async def get(self, work_id: str) -> WorkRecord | None: ...

    async def waiting_for_session(self, session_id: str) -> WorkRecord | None: ...

    async def waiting_rows_for_session(self, session_id: str) -> list[WorkRecord]: ...

    async def waiting_by_request(self, session_id: str, request_id: str) -> WorkRecord | None: ...

    async def by_ref(self, kind: str, ref_id: str) -> WorkRecord | None: ...

    async def transition(
        self, work_id: str, *, expected_version: int, status: str, pending: Any = KEEP, result: Any = KEEP
    ) -> WorkRecord: ...


def entry_and_delivery(user_input: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """호출자가 이미 넘기는 키에서 입구와 전달 대상을 정한다 -- 입력 모양을 바꾸지 않는다(spec §4.4)."""
    source = str(user_input.get("channel_source") or "")
    if source in _CHANNEL_SOURCES or user_input.get("channel_type") in _CHANNEL_SOURCES:
        channel_type = str(user_input.get("channel_type") or source)
        return "channel", {
            "kind": "channel",
            "channel_type": channel_type,
            "channel_id": user_input.get("channel_id"),
        }
    if source == "scheduler":
        return "schedule", {"kind": "none"}
    return "web", {"kind": "sse", "conversation_id": user_input.get("session_id")}


def _check(record: WorkRecord | None, work_id: str, expected_version: int, status: str) -> WorkRecord:
    if record is None:
        raise WorkConflict(f"{work_id}: 없음")
    if record.version != expected_version:
        raise WorkConflict(f"{work_id}: version {record.version} != expected {expected_version}")
    if status not in _TRANSITIONS.get(record.status, frozenset()):
        raise WorkConflict(f"{work_id}: {record.status} → {status} 는 허용되지 않는다")
    return record


class InMemoryWorkStore:
    def __init__(self) -> None:
        self._rows: dict[str, WorkRecord] = {}
        self._lock = asyncio.Lock()

    async def create(self, record: WorkRecord) -> None:
        async with self._lock:
            self._rows[record.work_id] = record

    async def get(self, work_id: str) -> WorkRecord | None:
        return self._rows.get(work_id)

    async def waiting_for_session(self, session_id: str) -> WorkRecord | None:
        waiting = [r for r in self._rows.values() if r.session_id == session_id and r.status == "waiting_approval"]
        return max(waiting, key=lambda r: r.updated_at, default=None)

    async def waiting_rows_for_session(self, session_id: str) -> list[WorkRecord]:
        waiting = [r for r in self._rows.values() if r.session_id == session_id and r.status == "waiting_approval"]
        return sorted(waiting, key=lambda r: r.updated_at, reverse=True)

    async def waiting_by_request(self, session_id: str, request_id: str) -> WorkRecord | None:
        matching = [
            r for r in await self.waiting_rows_for_session(session_id)
            if request_id in ((r.pending or {}).get("request_ids") or [])
        ]
        return matching[0] if matching else None

    async def by_ref(self, kind: str, ref_id: str) -> WorkRecord | None:
        return next((r for r in self._rows.values() if r.kind == kind and r.ref_id == ref_id), None)

    async def transition(
        self, work_id: str, *, expected_version: int, status: str, pending: Any = KEEP, result: Any = KEEP
    ) -> WorkRecord:
        async with self._lock:
            record = _check(self._rows.get(work_id), work_id, expected_version, status)
            updated = replace(
                record,
                status=status,
                pending=record.pending if pending is KEEP else pending,
                result=record.result if result is KEEP else result,
                version=record.version + 1,
                updated_at=datetime.now(UTC),
            )
            self._rows[work_id] = updated
            return updated


_COLUMNS = (
    "work_id, entry, kind, user_id, session_id, status, pending, result, delivery, "
    "ref_id, parent_work_id, version, created_at, updated_at"
)


def _json(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def _row(row: Any) -> WorkRecord:
    return WorkRecord(
        work_id=row[0], entry=row[1], kind=row[2], user_id=row[3], session_id=row[4], status=row[5],
        pending=_json(row[6]), result=_json(row[7]), delivery=_json(row[8]) or {},
        ref_id=row[9], parent_work_id=row[10], version=row[11], created_at=row[12], updated_at=row[13],
    )


class PostgresWorkStore:
    def __init__(self, session_factory: Callable[[], Awaitable[Any]]) -> None:
        self._session_factory = session_factory

    async def create(self, record: WorkRecord) -> None:
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        INSERT INTO workflow_runs
                            (work_id, entry, kind, user_id, session_id, status, pending, result,
                             delivery, ref_id, parent_work_id, version, created_at, updated_at)
                        VALUES
                            (:work_id, :entry, :kind, :user_id, :session_id, :status,
                             CAST(:pending AS JSONB), CAST(:result AS JSONB), CAST(:delivery AS JSONB),
                             :ref_id, :parent, :version, :created_at, :updated_at)
                        """
                    ),
                    {
                        "work_id": record.work_id, "entry": record.entry, "kind": record.kind,
                        "user_id": record.user_id, "session_id": record.session_id, "status": record.status,
                        "pending": json.dumps(record.pending) if record.pending is not None else None,
                        "result": json.dumps(record.result) if record.result is not None else None,
                        "delivery": json.dumps(record.delivery), "ref_id": record.ref_id,
                        "parent": record.parent_work_id, "version": record.version,
                        "created_at": record.created_at, "updated_at": record.updated_at,
                    },
                )

    async def _one(self, sql: str, params: Mapping[str, Any]) -> WorkRecord | None:
        async with await self._session_factory() as session:
            row = (await session.execute(text(sql), dict(params))).first()
        return _row(row) if row is not None else None

    async def get(self, work_id: str) -> WorkRecord | None:
        return await self._one(f"SELECT {_COLUMNS} FROM workflow_runs WHERE work_id = :w", {"w": work_id})

    async def waiting_for_session(self, session_id: str) -> WorkRecord | None:
        return await self._one(
            f"""SELECT {_COLUMNS} FROM workflow_runs
                WHERE session_id = :s AND status = 'waiting_approval'
                ORDER BY updated_at DESC LIMIT 1""",
            {"s": session_id},
        )

    async def waiting_rows_for_session(self, session_id: str) -> list[WorkRecord]:
        async with await self._session_factory() as session:
            rows = (
                await session.execute(
                    text(
                        f"""SELECT {_COLUMNS} FROM workflow_runs
                            WHERE session_id = :s AND status = 'waiting_approval'
                            ORDER BY updated_at DESC"""
                    ),
                    {"s": session_id},
                )
            ).all()
        return [_row(row) for row in rows]

    async def waiting_by_request(self, session_id: str, request_id: str) -> WorkRecord | None:
        return await self._one(
            f"""SELECT {_COLUMNS} FROM workflow_runs
                WHERE session_id = :s AND status = 'waiting_approval'
                  AND pending -> 'request_ids' @> CAST(:r AS JSONB)
                ORDER BY updated_at DESC LIMIT 1""",
            {"s": session_id, "r": json.dumps([request_id])},
        )

    async def by_ref(self, kind: str, ref_id: str) -> WorkRecord | None:
        return await self._one(
            f"SELECT {_COLUMNS} FROM workflow_runs WHERE kind = :k AND ref_id = :r ORDER BY created_at DESC LIMIT 1",
            {"k": kind, "r": ref_id},
        )

    async def transition(
        self, work_id: str, *, expected_version: int, status: str, pending: Any = KEEP, result: Any = KEEP
    ) -> WorkRecord:
        allowed_from = [src for src, targets in _TRANSITIONS.items() if status in targets]
        sets = ["status = :status", "version = version + 1", "updated_at = now()"]
        params: dict[str, Any] = {"w": work_id, "v": expected_version, "status": status, "from": allowed_from}
        if pending is not KEEP:
            sets.append("pending = CAST(:pending AS JSONB)")
            params["pending"] = json.dumps(pending) if pending is not None else None
        if result is not KEEP:
            sets.append("result = CAST(:result AS JSONB)")
            params["result"] = json.dumps(result) if result is not None else None
        async with await self._session_factory() as session:
            async with session.begin():
                row = (
                    await session.execute(
                        text(
                            f"""UPDATE workflow_runs SET {", ".join(sets)}
                                WHERE work_id = :w AND version = :v AND status = ANY(:from)
                                RETURNING {_COLUMNS}"""
                        ),
                        params,
                    )
                ).first()
        if row is None:
            raise WorkConflict(f"{work_id}: version {expected_version} 또는 {status} 로의 전이가 맞지 않는다")
        return _row(row)


class WorkLifecycle:
    def __init__(self, store: WorkStore, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.store = store
        self._clock = clock

    async def start(
        self,
        entry: str,
        kind: str,
        *,
        user_id: str,
        session_id: str | None,
        delivery: Mapping[str, Any],
        parent: str | None = None,
        ref_id: str | None = None,
    ) -> str:
        now = self._clock()
        record = WorkRecord(
            work_id=f"wk_{uuid4().hex}", entry=entry, kind=kind, user_id=user_id, session_id=session_id,
            status="running", pending=None, result=None, delivery=dict(delivery), ref_id=ref_id,
            parent_work_id=parent, version=1, created_at=now, updated_at=now,
        )
        await self.store.create(record)
        return record.work_id

    async def _move(self, work_id: str, status: str, **fields: Any) -> WorkRecord:
        record = await self.store.get(work_id)
        if record is None:
            raise WorkConflict(f"{work_id}: 없음")
        return await self.store.transition(work_id, expected_version=record.version, status=status, **fields)

    async def interrupt(self, work_id: str, pending: Mapping[str, Any]) -> None:
        await self._move(work_id, "waiting_approval", pending=dict(pending))

    async def complete(self, work_id: str, result: Mapping[str, Any]) -> None:
        await self._move(work_id, "completed", result=dict(result))

    async def fail(self, work_id: str, error: str) -> None:
        await self._move(work_id, "failed", result={"error": error})

    async def claim(self, work_id: str, *, expected_version: int) -> WorkRecord:
        return await self.store.transition(work_id, expected_version=expected_version, status="running", pending=None)

    async def expire(self, work_id: str, *, expected_version: int) -> WorkRecord:
        return await self.store.transition(work_id, expected_version=expected_version, status="expired", pending=None)

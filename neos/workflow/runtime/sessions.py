"""세션 저장소와 상태 이어받기 (spec 2026-10-13 §4.3).

**규칙: 이번 턴의 입력은 이어받은 상태 위의 갱신이다** -- `carry(saved, initial)` 이 리듀서
의미론(`node_updates.apply_update`)으로 병합한다. 이어받을 필드 목록을 따로 두지 않는다.

세션당 최신 스냅샷 한 행. 저장은 낙관적 잠금이다 -- 겹친 턴은 나중 저장이 `SessionConflict` 로
진다. 턴 내내 행 잠금을 잡지 않는다.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import text

from neos.workflow.runtime.node_updates import apply_update, reducer_kinds
from neos.workflow.runtime.state_codec import decode_state, encode_state


@dataclass(frozen=True)
class SessionSnapshot:
    session_id: str
    user_id: str
    state: dict[str, Any]
    version: int


class SessionConflict(RuntimeError):
    pass


class SessionStore(Protocol):
    async def load(self, session_id: str) -> SessionSnapshot | None: ...

    async def save(
        self, session_id: str, *, user_id: str, state: Mapping[str, Any], expected_version: int | None
    ) -> int: ...

    async def reset(self, session_id: str) -> bool: ...

    async def purge_older_than(self, cutoff: datetime) -> int: ...


def carry(saved: Mapping[str, Any] | None, initial: Mapping[str, Any]) -> dict[str, Any]:
    if not saved:
        return dict(initial)
    return apply_update(saved, initial)


def trim(state: Mapping[str, Any], max_items: int) -> tuple[dict[str, Any], dict[str, int]]:
    kinds = reducer_kinds()
    trimmed = dict(state)
    cut: dict[str, int] = {}
    for key, kind in kinds.items():
        value = trimmed.get(key)
        if kind == "append" and isinstance(value, list) and len(value) > max_items:
            cut[key] = len(value) - max_items
            trimmed[key] = value[-max_items:]
    return trimmed, cut


class InMemorySessionStore:
    def __init__(self) -> None:
        self._rows: dict[str, tuple[str, str, int, datetime]] = {}
        self._lock = asyncio.Lock()

    async def load(self, session_id: str) -> SessionSnapshot | None:
        row = self._rows.get(session_id)
        if row is None:
            return None
        user_id, payload, version, _ = row
        return SessionSnapshot(session_id, user_id, decode_state(json.loads(payload)), version)

    async def save(
        self, session_id: str, *, user_id: str, state: Mapping[str, Any], expected_version: int | None
    ) -> int:
        payload = json.dumps(encode_state(state))
        async with self._lock:
            row = self._rows.get(session_id)
            current = row[2] if row is not None else None
            if current != expected_version:
                raise SessionConflict(f"{session_id}: version {current} != expected {expected_version}")
            version = 1 if current is None else current + 1
            self._rows[session_id] = (user_id, payload, version, datetime.now(UTC))
            return version

    async def reset(self, session_id: str) -> bool:
        async with self._lock:
            return self._rows.pop(session_id, None) is not None

    async def purge_older_than(self, cutoff: datetime) -> int:
        async with self._lock:
            old = [key for key, row in self._rows.items() if row[3] < cutoff]
            for key in old:
                del self._rows[key]
            return len(old)


class PostgresSessionStore:
    def __init__(self, session_factory: Callable[[], Awaitable[Any]]) -> None:
        self._session_factory = session_factory

    async def load(self, session_id: str) -> SessionSnapshot | None:
        async with await self._session_factory() as session:
            row = (
                await session.execute(
                    text("SELECT user_id, state, version FROM workflow_sessions WHERE session_id = :sid"),
                    {"sid": session_id},
                )
            ).first()
        if row is None:
            return None
        payload = row[1] if isinstance(row[1], Mapping) else json.loads(row[1])
        return SessionSnapshot(session_id, row[0], decode_state(payload), row[2])

    async def save(
        self, session_id: str, *, user_id: str, state: Mapping[str, Any], expected_version: int | None
    ) -> int:
        payload = json.dumps(encode_state(state))
        async with await self._session_factory() as session:
            async with session.begin():
                if expected_version is None:
                    result = await session.execute(
                        text(
                            """
                            INSERT INTO workflow_sessions (session_id, user_id, state, version, updated_at)
                            VALUES (:sid, :uid, CAST(:state AS JSONB), 1, now())
                            ON CONFLICT (session_id) DO NOTHING
                            RETURNING version
                            """
                        ),
                        {"sid": session_id, "uid": user_id, "state": payload},
                    )
                else:
                    result = await session.execute(
                        text(
                            """
                            UPDATE workflow_sessions
                            SET state = CAST(:state AS JSONB), user_id = :uid,
                                version = version + 1, updated_at = now()
                            WHERE session_id = :sid AND version = :expected
                            RETURNING version
                            """
                        ),
                        {"sid": session_id, "uid": user_id, "state": payload, "expected": expected_version},
                    )
                version = result.scalar_one_or_none()
        if version is None:
            raise SessionConflict(f"{session_id}: expected version {expected_version} lost")
        return int(version)

    async def reset(self, session_id: str) -> bool:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text("DELETE FROM workflow_sessions WHERE session_id = :sid"), {"sid": session_id}
                )
        return bool(result.rowcount)

    async def purge_older_than(self, cutoff: datetime) -> int:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text("DELETE FROM workflow_sessions WHERE updated_at < :cutoff"), {"cutoff": cutoff}
                )
        return int(result.rowcount or 0)

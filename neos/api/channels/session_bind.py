"""Durable channel session_id → coding task_id bindings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Awaitable, Callable, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


SessionFactory = Callable[[], Awaitable[AsyncSession]]


@dataclass(frozen=True, slots=True)
class ChannelCodingBinding:
    session_id: str
    task_id: str
    owner_id: str
    created_at: datetime
    updated_at: datetime


async def session_is_bound(gateway: object, session_id: str) -> bool:
    """True when gateway exposes a bind store and this session is bound."""
    if not session_id:
        return False
    get_binding = getattr(gateway, "get_binding", None)
    if get_binding is None:
        return False
    try:
        return await get_binding(session_id) is not None
    except Exception:
        return False


class ChannelCodingBindStore(Protocol):
    async def bind(
        self, session_id: str, task_id: str, owner_id: str
    ) -> ChannelCodingBinding: ...

    async def get(self, session_id: str) -> ChannelCodingBinding | None: ...


class InMemoryChannelCodingBindStore:
    def __init__(
        self, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._items: dict[str, ChannelCodingBinding] = {}
        self._clock = clock

    async def bind(
        self, session_id: str, task_id: str, owner_id: str
    ) -> ChannelCodingBinding:
        now = self._clock()
        existing = self._items.get(session_id)
        binding = ChannelCodingBinding(
            session_id=session_id,
            task_id=task_id,
            owner_id=owner_id,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        self._items[session_id] = binding
        return binding

    async def get(self, session_id: str) -> ChannelCodingBinding | None:
        return self._items.get(session_id)


class PostgresChannelCodingBindStore:
    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def bind(
        self, session_id: str, task_id: str, owner_id: str
    ) -> ChannelCodingBinding:
        now = self._clock()
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        """
                        INSERT INTO channel_coding_bindings
                            (session_id, task_id, owner_id, created_at, updated_at)
                        VALUES
                            (:session_id, :task_id, :owner_id, :now, :now)
                        ON CONFLICT (session_id) DO UPDATE
                        SET task_id = EXCLUDED.task_id,
                            owner_id = EXCLUDED.owner_id,
                            updated_at = EXCLUDED.updated_at
                        RETURNING session_id, task_id, owner_id,
                                  created_at, updated_at
                        """
                    ),
                    {
                        "session_id": session_id,
                        "task_id": task_id,
                        "owner_id": owner_id,
                        "now": now,
                    },
                )
                row = result.first()
        if row is None:
            return ChannelCodingBinding(session_id, task_id, owner_id, now, now)
        return ChannelCodingBinding(
            session_id=row[0],
            task_id=row[1],
            owner_id=row[2],
            created_at=row[3],
            updated_at=row[4],
        )

    async def get(self, session_id: str) -> ChannelCodingBinding | None:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        """
                        SELECT session_id, task_id, owner_id, created_at, updated_at
                        FROM channel_coding_bindings
                        WHERE session_id = :session_id
                        """
                    ),
                    {"session_id": session_id},
                )
                row = result.first()
        if row is None:
            return None
        return ChannelCodingBinding(
            session_id=row[0],
            task_id=row[1],
            owner_id=row[2],
            created_at=row[3],
            updated_at=row[4],
        )

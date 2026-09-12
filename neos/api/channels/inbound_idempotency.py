"""Durable per-session inbound idempotency records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Awaitable, Callable, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

EMPTY_CLAIM_TTL = timedelta(minutes=5)


SessionFactory = Callable[[], Awaitable[AsyncSession]]


@dataclass(frozen=True, slots=True)
class ChannelInboundRecord:
    session_id: str
    idempotency_key: str
    outcome: str
    created_at: datetime


class ChannelInboundIdempotencyStore(Protocol):
    async def claim(
        self, session_id: str, idempotency_key: str
    ) -> tuple[bool, ChannelInboundRecord | None]: ...

    async def remember(
        self, session_id: str, idempotency_key: str, outcome: str
    ) -> ChannelInboundRecord: ...

    async def abandon(self, session_id: str, idempotency_key: str) -> None: ...

    async def get(
        self, session_id: str, idempotency_key: str
    ) -> ChannelInboundRecord | None: ...

    async def clear_session(self, session_id: str) -> None: ...


def _empty_claim_expired(record: ChannelInboundRecord, now: datetime) -> bool:
    return not record.outcome and now - record.created_at > EMPTY_CLAIM_TTL


class InMemoryChannelInboundIdempotencyStore:
    def __init__(
        self, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._items: dict[tuple[str, str], ChannelInboundRecord] = {}
        self._clock = clock

    def _drop_expired(self, key: tuple[str, str]) -> None:
        existing = self._items.get(key)
        if existing is not None and _empty_claim_expired(existing, self._clock()):
            self._items.pop(key, None)

    async def claim(
        self, session_id: str, idempotency_key: str
    ) -> tuple[bool, ChannelInboundRecord | None]:
        key = (session_id, idempotency_key)
        self._drop_expired(key)
        existing = self._items.get(key)
        if existing is not None:
            return False, existing
        record = ChannelInboundRecord(
            session_id=session_id,
            idempotency_key=idempotency_key,
            outcome="",
            created_at=self._clock(),
        )
        self._items[key] = record
        return True, record

    async def remember(
        self, session_id: str, idempotency_key: str, outcome: str
    ) -> ChannelInboundRecord:
        key = (session_id, idempotency_key)
        existing = self._items.get(key)
        if existing is not None and existing.outcome:
            return existing
        record = ChannelInboundRecord(
            session_id=session_id,
            idempotency_key=idempotency_key,
            outcome=outcome,
            created_at=existing.created_at if existing is not None else self._clock(),
        )
        self._items[key] = record
        return record

    async def abandon(self, session_id: str, idempotency_key: str) -> None:
        key = (session_id, idempotency_key)
        existing = self._items.get(key)
        if existing is not None and not existing.outcome:
            self._items.pop(key, None)

    async def get(
        self, session_id: str, idempotency_key: str
    ) -> ChannelInboundRecord | None:
        key = (session_id, idempotency_key)
        self._drop_expired(key)
        return self._items.get(key)

    async def clear_session(self, session_id: str) -> None:
        self._items = {
            key: value for key, value in self._items.items() if key[0] != session_id
        }


class PostgresChannelInboundIdempotencyStore:
    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def _expire_empty_claim(
        self, session: AsyncSession, session_id: str, idempotency_key: str
    ) -> None:
        await session.execute(
            text(
                """
                DELETE FROM channel_inbound_idempotency
                WHERE session_id = :session_id
                  AND idempotency_key = :idempotency_key
                  AND outcome = ''
                  AND created_at < :cutoff
                """
            ),
            {
                "session_id": session_id,
                "idempotency_key": idempotency_key,
                "cutoff": self._clock() - EMPTY_CLAIM_TTL,
            },
        )

    async def claim(
        self, session_id: str, idempotency_key: str
    ) -> tuple[bool, ChannelInboundRecord | None]:
        now = self._clock()
        async with await self._session_factory() as session:
            async with session.begin():
                await self._expire_empty_claim(session, session_id, idempotency_key)
                result = await session.execute(
                    text(
                        """
                        INSERT INTO channel_inbound_idempotency
                            (session_id, idempotency_key, outcome, created_at)
                        VALUES
                            (:session_id, :idempotency_key, '', :now)
                        ON CONFLICT (session_id, idempotency_key) DO NOTHING
                        RETURNING session_id, idempotency_key, outcome, created_at
                        """
                    ),
                    {
                        "session_id": session_id,
                        "idempotency_key": idempotency_key,
                        "now": now,
                    },
                )
                row = result.first()
                if row is not None:
                    return True, ChannelInboundRecord(
                        session_id=row[0],
                        idempotency_key=row[1],
                        outcome=row[2],
                        created_at=row[3],
                    )
                result = await session.execute(
                    text(
                        """
                        SELECT session_id, idempotency_key, outcome, created_at
                        FROM channel_inbound_idempotency
                        WHERE session_id = :session_id
                          AND idempotency_key = :idempotency_key
                        """
                    ),
                    {
                        "session_id": session_id,
                        "idempotency_key": idempotency_key,
                    },
                )
                row = result.first()
        if row is None:
            return False, None
        return False, ChannelInboundRecord(
            session_id=row[0],
            idempotency_key=row[1],
            outcome=row[2],
            created_at=row[3],
        )

    async def remember(
        self, session_id: str, idempotency_key: str, outcome: str
    ) -> ChannelInboundRecord:
        now = self._clock()
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        """
                        UPDATE channel_inbound_idempotency
                        SET outcome = :outcome
                        WHERE session_id = :session_id
                          AND idempotency_key = :idempotency_key
                          AND outcome = ''
                        RETURNING session_id, idempotency_key, outcome, created_at
                        """
                    ),
                    {
                        "session_id": session_id,
                        "idempotency_key": idempotency_key,
                        "outcome": outcome,
                    },
                )
                row = result.first()
                if row is None:
                    result = await session.execute(
                        text(
                            """
                            INSERT INTO channel_inbound_idempotency
                                (session_id, idempotency_key, outcome, created_at)
                            VALUES
                                (:session_id, :idempotency_key, :outcome, :now)
                            ON CONFLICT (session_id, idempotency_key) DO NOTHING
                            RETURNING session_id, idempotency_key, outcome, created_at
                            """
                        ),
                        {
                            "session_id": session_id,
                            "idempotency_key": idempotency_key,
                            "outcome": outcome,
                            "now": now,
                        },
                    )
                    row = result.first()
                if row is None:
                    result = await session.execute(
                        text(
                            """
                            SELECT session_id, idempotency_key, outcome, created_at
                            FROM channel_inbound_idempotency
                            WHERE session_id = :session_id
                              AND idempotency_key = :idempotency_key
                            """
                        ),
                        {
                            "session_id": session_id,
                            "idempotency_key": idempotency_key,
                        },
                    )
                    row = result.first()
        if row is None:
            return ChannelInboundRecord(session_id, idempotency_key, outcome, now)
        return ChannelInboundRecord(
            session_id=row[0],
            idempotency_key=row[1],
            outcome=row[2],
            created_at=row[3],
        )

    async def abandon(self, session_id: str, idempotency_key: str) -> None:
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        DELETE FROM channel_inbound_idempotency
                        WHERE session_id = :session_id
                          AND idempotency_key = :idempotency_key
                          AND outcome = ''
                        """
                    ),
                    {
                        "session_id": session_id,
                        "idempotency_key": idempotency_key,
                    },
                )

    async def get(
        self, session_id: str, idempotency_key: str
    ) -> ChannelInboundRecord | None:
        async with await self._session_factory() as session:
            async with session.begin():
                await self._expire_empty_claim(session, session_id, idempotency_key)
                result = await session.execute(
                    text(
                        """
                        SELECT session_id, idempotency_key, outcome, created_at
                        FROM channel_inbound_idempotency
                        WHERE session_id = :session_id
                          AND idempotency_key = :idempotency_key
                        """
                    ),
                    {
                        "session_id": session_id,
                        "idempotency_key": idempotency_key,
                    },
                )
                row = result.first()
        if row is None:
            return None
        return ChannelInboundRecord(
            session_id=row[0],
            idempotency_key=row[1],
            outcome=row[2],
            created_at=row[3],
        )

    async def clear_session(self, session_id: str) -> None:
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        DELETE FROM channel_inbound_idempotency
                        WHERE session_id = :session_id
                        """
                    ),
                    {"session_id": session_id},
                )

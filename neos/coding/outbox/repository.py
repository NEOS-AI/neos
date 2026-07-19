from datetime import datetime
from typing import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from neos.coding.domain.events import CodingEvent
from neos.coding.outbox.models import ClaimedOutboxEvent


SessionFactory = Callable[[], Awaitable[AsyncSession]]


class PostgresCodingOutboxRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def claim_batch(
        self,
        *,
        limit: int,
        now: datetime,
        stale_before: datetime,
    ) -> list[ClaimedOutboxEvent]:
        if not 1 <= limit <= 500:
            raise ValueError("outbox claim limit must be between 1 and 500")
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        """
                        WITH candidates AS (
                            SELECT candidate.outbox_id
                            FROM coding_event_outbox candidate
                            WHERE candidate.published_at IS NULL
                              AND candidate.next_attempt_at <= :now
                              AND (
                                  candidate.claimed_at IS NULL
                                  OR candidate.claimed_at < :stale_before
                              )
                              AND NOT EXISTS (
                                  SELECT 1
                                  FROM coding_event_outbox earlier
                                  WHERE earlier.task_id = candidate.task_id
                                    AND earlier.seq < candidate.seq
                                    AND earlier.published_at IS NULL
                              )
                            ORDER BY candidate.created_at, candidate.outbox_id
                            LIMIT :limit
                            FOR UPDATE SKIP LOCKED
                        ), claimed AS (
                            UPDATE coding_event_outbox target
                            SET claimed_at = :now
                            FROM candidates
                            WHERE target.outbox_id = candidates.outbox_id
                            RETURNING target.outbox_id, target.event_id,
                                      target.attempt_count
                        )
                        SELECT claimed.outbox_id, claimed.attempt_count,
                               event.version, event.task_id, event.seq,
                               event.event_id, event.event_type, event.payload,
                               event.created_at, event.run_id, event.turn_id,
                               event.tool_call_id
                        FROM claimed
                        JOIN coding_events event
                          ON event.event_id = claimed.event_id
                        ORDER BY event.task_id, event.seq
                        """
                    ),
                    {"limit": limit, "now": now, "stale_before": stale_before},
                )
                rows = result.all()
        return [self._map_claimed(row) for row in rows]

    async def mark_published(
        self, outbox_id: str, *, published_at: datetime
    ) -> None:
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        UPDATE coding_event_outbox
                        SET published_at = :published_at,
                            claimed_at = NULL,
                            last_error = NULL
                        WHERE outbox_id = :outbox_id
                        """
                    ),
                    {"outbox_id": outbox_id, "published_at": published_at},
                )

    async def mark_failed(
        self, outbox_id: str, *, error: str, next_attempt_at: datetime
    ) -> None:
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        UPDATE coding_event_outbox
                        SET attempt_count = attempt_count + 1,
                            next_attempt_at = :next_attempt_at,
                            claimed_at = NULL,
                            last_error = :error
                        WHERE outbox_id = :outbox_id
                        """
                    ),
                    {
                        "outbox_id": outbox_id,
                        "error": error[:2000],
                        "next_attempt_at": next_attempt_at,
                    },
                )

    @staticmethod
    def _map_claimed(row) -> ClaimedOutboxEvent:
        return ClaimedOutboxEvent(
            outbox_id=row[0],
            attempt_count=int(row[1]),
            event=CodingEvent(
                version=row[2],
                task_id=row[3],
                seq=row[4],
                event_id=row[5],
                type=row[6],
                payload=row[7],
                created_at=row[8],
                run_id=row[9],
                turn_id=row[10],
                tool_call_id=row[11],
            ),
        )

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable, Mapping, Protocol
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from neos.coding.application.task_service import CodingTaskSnapshot
from neos.coding.domain.events import CodingEvent
from neos.coding.domain.models import CodingTask, CodingTaskStatus


SessionFactory = Callable[[], Awaitable[AsyncSession]]


class EventPublisher(Protocol):
    async def publish(self, event: CodingEvent) -> None: ...


class PostgresCodingService:
    """Durable coding service with transactionally ordered task events."""

    def __init__(
        self, session_factory: SessionFactory, broker: EventPublisher | None = None
    ) -> None:
        self._session_factory = session_factory
        self._broker = broker
        self.events = self

    async def create_task(
        self, *, owner_id: str, prompt: str, task_id: str | None = None
    ) -> CodingTask:
        now = datetime.now(UTC)
        task = CodingTask(
            task_id=task_id or f"ct_{uuid4().hex}",
            owner_id=owner_id,
            prompt=prompt,
            status=CodingTaskStatus.QUEUED,
            version=1,
            last_seq=0,
            created_at=now,
            updated_at=now,
        )
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        INSERT INTO coding_tasks
                            (task_id, owner_id, prompt, status, version, last_seq,
                             created_at, updated_at, last_activity_at)
                        VALUES
                            (:task_id, :owner_id, :prompt, :status, 1, 0,
                             :now, :now, :now)
                        """
                    ),
                    {
                        "task_id": task.task_id,
                        "owner_id": owner_id,
                        "prompt": prompt,
                        "status": task.status.value,
                        "now": now,
                    },
                )
                event = await self._append_in_session(
                    session,
                    task_id=task.task_id,
                    event_type="task.created",
                    payload={"status": task.status.value, "prompt": prompt},
                    now=now,
                )
        return replace(task, last_seq=event.seq)

    async def append(
        self,
        *,
        task_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        now: datetime | None = None,
    ) -> CodingEvent:
        async with await self._session_factory() as session:
            async with session.begin():
                event = await self._append_in_session(
                    session,
                    task_id=task_id,
                    event_type=event_type,
                    payload=payload,
                    now=now or datetime.now(UTC),
                )
        if self._broker is not None:
            await self._broker.publish(event)
        return event

    async def _append_in_session(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        now: datetime,
    ) -> CodingEvent:
        await session.execute(
            text("SELECT task_id FROM coding_tasks WHERE task_id = :task_id FOR UPDATE"),
            {"task_id": task_id},
        )
        result = await session.execute(
            text(
                """
                UPDATE coding_tasks
                SET last_seq = last_seq + 1,
                    updated_at = :now,
                    last_activity_at = :now
                WHERE task_id = :task_id
                RETURNING last_seq
                """
            ),
            {"task_id": task_id, "now": now},
        )
        seq = int(result.scalar_one())
        event = CodingEvent(
            version=1,
            task_id=task_id,
            seq=seq,
            event_id=f"ce_{uuid4().hex}",
            type=event_type,
            payload=dict(payload),
            created_at=now,
        )
        await session.execute(
            text(
                """
                INSERT INTO coding_events
                    (event_id, task_id, seq, version, event_type, payload, created_at)
                VALUES
                    (:event_id, :task_id, :seq, 1, :event_type,
                     CAST(:payload AS JSONB), :created_at)
                """
            ),
            {
                "event_id": event.event_id,
                "task_id": task_id,
                "seq": seq,
                "event_type": event_type,
                "payload": __import__("json").dumps(dict(payload)),
                "created_at": now,
            },
        )
        await session.execute(
            text(
                """
                INSERT INTO coding_event_outbox
                    (outbox_id, event_id, task_id, seq,
                     next_attempt_at, created_at)
                VALUES
                    (:outbox_id, :event_id, :task_id, :seq, :now, :now)
                ON CONFLICT (event_id) DO NOTHING
                """
            ),
            {
                "outbox_id": f"co_{uuid4().hex}",
                "event_id": event.event_id,
                "task_id": task_id,
                "seq": seq,
                "now": now,
            },
        )
        return event

    async def snapshot(
        self, task_id: str, owner_id: str
    ) -> CodingTaskSnapshot | None:
        async with await self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT task_id, owner_id, prompt, status, version, last_seq,
                           created_at, updated_at
                    FROM coding_tasks
                    WHERE task_id = :task_id AND owner_id = :owner_id
                      AND deleted_at IS NULL
                    """
                ),
                {"task_id": task_id, "owner_id": owner_id},
            )
            row = result.first()
        if row is None:
            return None
        task = CodingTask(
            task_id=row[0], owner_id=row[1], prompt=row[2],
            status=CodingTaskStatus(row[3]), version=row[4], last_seq=row[5],
            created_at=row[6], updated_at=row[7],
        )
        return CodingTaskSnapshot(task=task, head_seq=task.last_seq)

    async def list_after(
        self, task_id: str, *, after_seq: int = 0, limit: int = 500
    ) -> list[CodingEvent]:
        async with await self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT version, task_id, seq, event_id, event_type, payload,
                           created_at, run_id, turn_id, tool_call_id
                    FROM coding_events
                    WHERE task_id = :task_id AND seq > :after_seq
                    ORDER BY seq ASC LIMIT :limit
                    """
                ),
                {"task_id": task_id, "after_seq": after_seq, "limit": limit},
            )
            rows = result.all()
        return [
            CodingEvent(
                version=row[0], task_id=row[1], seq=row[2], event_id=row[3],
                type=row[4], payload=row[5], created_at=row[6], run_id=row[7],
                turn_id=row[8], tool_call_id=row[9],
            )
            for row in rows
        ]

    async def head_seq(self, task_id: str) -> int:
        async with await self._session_factory() as session:
            result = await session.execute(
                text("SELECT last_seq FROM coding_tasks WHERE task_id = :task_id"),
                {"task_id": task_id},
            )
            row = result.first()
        return int(row[0]) if row else 0

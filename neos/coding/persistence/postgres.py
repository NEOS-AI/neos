import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable, Mapping
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from neos.coding.application.task_service import CodingTaskSnapshot
from neos.coding.domain.events import CodingEvent
from neos.coding.domain.models import CodingTask, CodingTaskStatus


logger = logging.getLogger(__name__)


SessionFactory = Callable[[], Awaitable[AsyncSession]]


class PostgresCodingService:
    """Durable coding service with transactionally ordered task events."""

    def __init__(
        self,
        session_factory: SessionFactory,
        wake_outbox: Callable[[], None] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._wake_outbox = wake_outbox
        self._task_created_notifier: Callable[[str], bool | None] | None = None
        self.events = self

    def set_task_created_notifier(
        self, notifier: Callable[[str], bool | None] | None
    ) -> None:
        self._task_created_notifier = notifier

    def _notify_task_created(self, task_id: str) -> None:
        if self._task_created_notifier is None:
            return
        try:
            self._task_created_notifier(task_id)
        except Exception:
            logger.exception(
                "Coding task wake notification failed",
                extra={"task_id": task_id},
            )

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
        if self._wake_outbox is not None:
            self._wake_outbox()
        task = replace(task, last_seq=event.seq)
        self._notify_task_created(task.task_id)
        return task

    async def append(
        self,
        *,
        task_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        now: datetime | None = None,
        run_id: str | None = None,
        turn_id: str | None = None,
        tool_call_id: str | None = None,
        checkpoint_id: str | None = None,
    ) -> CodingEvent:
        if checkpoint_id is not None:
            raise ValueError(
                "checkpoint-linked events require an atomic checkpoint command"
            )
        async with await self._session_factory() as session:
            async with session.begin():
                event = await self._append_in_session(
                    session,
                    task_id=task_id,
                    event_type=event_type,
                    payload=payload,
                    now=now or datetime.now(UTC),
                    run_id=run_id,
                    turn_id=turn_id,
                    tool_call_id=tool_call_id,
                    checkpoint_id=checkpoint_id,
                )
        if self._wake_outbox is not None:
            self._wake_outbox()
        return event

    async def append_in_session(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        now: datetime,
        run_id: str | None = None,
    ) -> CodingEvent:
        """호출자가 소유한 트랜잭션 안에서 이벤트 하나를 덧붙인다.

        `append()`와 달리 세션을 열지 않는다 -- 다른 테이블 쓰기와 **원자적**
        이어야 하는 호출자를 위한 것이다(관리형 복구 승인이 새 세대 생성과
        감사 기록을 함께 커밋한다).

        seq 할당을 스스로 하지 말 것. `coding_tasks`를 `FOR UPDATE`로 잠그고
        `last_seq + 1`을 `RETURNING` 하는 이 경로를 우회하면
        `coding_checkpoints_task_id_seq_key` 위반과 같은 계열의 사고가 난다.
        outbox 발행도 여기서 함께 일어난다.
        """
        return await self._append_in_session(
            session,
            task_id=task_id,
            event_type=event_type,
            payload=payload,
            now=now,
            run_id=run_id,
        )

    async def _append_in_session(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        now: datetime,
        run_id: str | None = None,
        turn_id: str | None = None,
        tool_call_id: str | None = None,
        checkpoint_id: str | None = None,
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
            run_id=run_id,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            checkpoint_id=checkpoint_id,
        )
        await session.execute(
            text(
                """
                INSERT INTO coding_events
                    (event_id, task_id, seq, version, event_type, payload, created_at,
                     run_id, turn_id, tool_call_id, checkpoint_id)
                VALUES
                    (:event_id, :task_id, :seq, 1, :event_type,
                     CAST(:payload AS JSONB), :created_at,
                     :run_id, :turn_id, :tool_call_id, :checkpoint_id)
                """
            ),
            {
                "event_id": event.event_id,
                "task_id": task_id,
                "seq": seq,
                "event_type": event_type,
                "payload": __import__("json").dumps(dict(payload)),
                "created_at": now,
                "run_id": run_id,
                "turn_id": turn_id,
                "tool_call_id": tool_call_id,
                "checkpoint_id": checkpoint_id,
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
                           created_at, run_id, turn_id, tool_call_id, checkpoint_id
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
                checkpoint_id=row[10],
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

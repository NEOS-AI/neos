"""상시 에이전트 활동 피드 -- 트랙 Q13d (설계 §7.1, F17).

새 테이블이 아니라 **조회**다: 에이전트가 연 태스크(`coding_tasks.agent_id`)를 고르고
그 원장 이벤트를 하나의 스트림으로 합친다. Q5 의 `monitor.judged` 도 여기서 보인다.

커서는 `(position, task_id, seq)` 다. Postgres 의 position 은 이벤트를 쓴 트랜잭션
id(`xact_id`, 마이그레이션 072)이고, 독자는 `pg_snapshot_xmin` 미만만 읽는다 --
늦게 커밋되는 이벤트가 이미 지나간 커서 뒤로 떨어지지 않게(자세한 이유는 072).
`created_at` 은 호출자의 시계라 커서가 못 된다. 메모리 구현의 position 은 추가 순서다.

소유 검사는 새로 만들지 않는다: 에이전트는 `resolve_agent`(소유자의 것만)로 찾고,
태스크는 지금처럼 `owner_id` 로 거른다.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from neos.coding.application.task_service import InMemoryCodingTaskRepository
from neos.coding.domain.events import CodingEvent
from neos.coding.events.store import InMemoryCodingEventStore
from neos.standing.resolve import resolve_agent
from neos.standing.store import StandingAgentStore

MAX_LIMIT = 500


@dataclass(frozen=True, order=True, slots=True)
class FeedCursor:
    position: int
    task_id: str
    seq: int

    def encode(self) -> str:
        raw = json.dumps([self.position, self.task_id, self.seq], separators=(",", ":"))
        return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")

    @classmethod
    def decode(cls, value: str) -> "FeedCursor":
        """불투명 문자열. 읽을 수 없으면 ValueError (API 는 422)."""
        try:
            padded = value + "=" * (-len(value) % 4)
            position, task_id, seq = json.loads(base64.urlsafe_b64decode(padded))
        except Exception as error:
            raise ValueError("unreadable activity cursor") from error
        if not (
            isinstance(position, int)
            and isinstance(task_id, str)
            and isinstance(seq, int)
            and position >= 0
            and seq >= 0
        ):
            raise ValueError("unreadable activity cursor")
        return cls(position, task_id, seq)


START = FeedCursor(0, "", 0)


class ActivitySource(Protocol):
    async def read(
        self, owner_id: str, agent_id: str, *, after: FeedCursor, limit: int
    ) -> list[tuple[FeedCursor, CodingEvent]]: ...


@dataclass(frozen=True, slots=True)
class ActivityPage:
    events: list[CodingEvent]
    #: 다음 요청의 `after`. 빈 쪽이면 받은 커서 그대로 -- 계속 물어볼 수 있게.
    next: str


async def agent_activity(
    agents: StandingAgentStore,
    source: ActivitySource,
    *,
    owner_id: str,
    agent_id: str | None,
    after: str | None = None,
    limit: int = 100,
) -> ActivityPage | None:
    """None 이면 그런 에이전트가 없다(남의 것 포함 -- 존재를 확인해 주지 않는다)."""
    cursor = FeedCursor.decode(after) if after else START
    agent = await resolve_agent(agents, owner_id, agent_id)
    if agent is None:
        return None
    rows = await source.read(
        agent.owner_id,
        agent.agent_id,
        after=cursor,
        limit=max(1, min(int(limit), MAX_LIMIT)),
    )
    last = rows[-1][0] if rows else cursor
    return ActivityPage(events=[event for _, event in rows], next=last.encode())


class InMemoryActivitySource:
    def __init__(
        self, tasks: InMemoryCodingTaskRepository, events: InMemoryCodingEventStore
    ) -> None:
        self._tasks = tasks
        self._events = events

    async def read(
        self, owner_id: str, agent_id: str, *, after: FeedCursor, limit: int
    ) -> list[tuple[FeedCursor, CodingEvent]]:
        mine = self._tasks.agent_task_ids(owner_id, agent_id)
        rows = [
            (FeedCursor(position, event.task_id, event.seq), event)
            for position, event in enumerate(self._events.in_append_order(), start=1)
            if event.task_id in mine
        ]
        return [row for row in rows if row[0] > after][:limit]


SessionFactory = Callable[[], Awaitable[AsyncSession]]


class PostgresActivitySource:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read(
        self, owner_id: str, agent_id: str, *, after: FeedCursor, limit: int
    ) -> list[tuple[FeedCursor, CodingEvent]]:
        async with await self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT e.xact_id::text, e.version, e.task_id, e.seq, e.event_id,
                           e.event_type, e.payload, e.created_at, e.run_id,
                           e.turn_id, e.tool_call_id, e.checkpoint_id
                      FROM coding_events e
                      JOIN coding_tasks t ON t.task_id = e.task_id
                     WHERE t.agent_id = :agent_id
                       AND t.owner_id = :owner_id
                       AND t.deleted_at IS NULL
                       AND e.xact_id < pg_snapshot_xmin(pg_current_snapshot())
                       AND (e.xact_id, e.task_id, e.seq)
                           > (CAST(:position AS xid8), :task_id, :seq)
                     ORDER BY e.xact_id, e.task_id, e.seq
                     LIMIT :limit
                    """
                ),
                {
                    "agent_id": agent_id,
                    "owner_id": owner_id,
                    "position": after.position,
                    "task_id": after.task_id,
                    "seq": after.seq,
                    "limit": limit,
                },
            )
            rows = result.all()
        return [
            (
                FeedCursor(int(row[0]), row[2], row[3]),
                CodingEvent(
                    version=row[1], task_id=row[2], seq=row[3], event_id=row[4],
                    type=row[5], payload=row[6], created_at=row[7], run_id=row[8],
                    turn_id=row[9], tool_call_id=row[10], checkpoint_id=row[11],
                ),
            )
            for row in rows
        ]

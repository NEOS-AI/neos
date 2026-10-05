"""소유자 알림 -- 트랙 Q10b · Q3 (docs/Q10B_Q3_PAUSE_STANDING_QUESTIONS_DESIGN_261002.md §4).

**워커는 보내지 않고 적는다.** 채널 어댑터(`ChannelGateway`)는 API 프로세스의
lifespan 에서만 만들어진다(`main.py`). Celery 워커에서 `ChannelGateway.get_instance()`
는 `RuntimeError` 를 내고, 기존 스케줄 태스크의 채널 전송(`scheduled_task_runner.
_send_to_channel`)은 그 예외를 경고 한 줄로 삼킨다 -- 워커에서 보낸 결과는 어디에도
가지 않았다. 그래서 알림은 durable 큐(`standing_notifications`, 마이그레이션 085)에
적고, 게이트웨이를 가진 API 프로세스가 꺼내 보낸다.

- **목적지는 적을 때 정한다.** 에이전트의 알림 대상(`standing_agent_notify_targets`)이
  없으면 적지 않는다(`False`). 대상을 나중에 붙이면 다음 판정에서 적힌다 -- 중복 키가
  아직 쓰이지 않았으므로.
- **중복 키가 한 번을 보장한다.** `(agent_id, dedupe_key)` 유일. 봉투 경고는 달마다
  하나(`budget_warning:2026-10`), 멈춤은 멈춤 이벤트마다 하나, 상시 질문은 DA 런마다 하나.
- **본문은 사람에게 가는 평문이다.** 상한을 넘으면 자르고 끝을 표시한다.
- 메모리 구현과 Postgres 구현이 같은 계약을 지킨다(`tests/standing/test_notifications.py`).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import text

logger = logging.getLogger(__name__)

#: 마이그레이션 085 의 CHECK 와 같아야 한다(kind 는 095 가 넓혔다).
NOTIFY_CHANNEL_TYPES = frozenset({"slack", "discord", "telegram"})
KIND_BUDGET_WARNING = "budget_warning"
KIND_TASK_PAUSED = "task_paused"
KIND_QUESTION_CHANGED = "question_changed"
#: 트랙 Q9 -- 에이전트가 소유자에게 묻는다(Q9b) · 답 없이 질문이 만료됐다(Q9d). 095 가 CHECK 를 넓혔다.
KIND_QUESTION_ASKED = "question_asked"
KIND_ASK_EXPIRED = "ask_expired"
NOTICE_KINDS = frozenset(
    {
        KIND_BUDGET_WARNING,
        KIND_TASK_PAUSED,
        KIND_QUESTION_CHANGED,
        KIND_QUESTION_ASKED,
        KIND_ASK_EXPIRED,
    }
)

_TRUNCATED = "\n…(잘림)"


@dataclass(frozen=True, slots=True)
class NotifyTarget:
    channel_type: str
    channel_id: str

    def __post_init__(self) -> None:
        if self.channel_type not in NOTIFY_CHANNEL_TYPES:
            raise ValueError(f"unsupported channel_type: {self.channel_type!r}")
        if not self.channel_id or not self.channel_id.strip():
            raise ValueError("channel_id must not be empty")


@dataclass(frozen=True, slots=True)
class StandingNotice:
    agent_id: str
    kind: str
    dedupe_key: str
    body: str

    def __post_init__(self) -> None:
        if self.kind not in NOTICE_KINDS:
            raise ValueError(f"unknown notice kind: {self.kind!r}")
        if not self.dedupe_key:
            raise ValueError("dedupe_key must not be empty")


@dataclass(frozen=True, slots=True)
class QueuedNotice:
    notification_id: str
    agent_id: str
    kind: str
    channel_type: str
    channel_id: str
    body: str
    attempts: int


def bounded_body(body: str, max_chars: int) -> str:
    """상한 안의 본문. 자르면 끝에 표시를 단다 -- 잘린 줄 모르게 하지 않는다."""
    if len(body) <= max_chars:
        return body
    return body[: max(0, max_chars - len(_TRUNCATED))] + _TRUNCATED


def retry_delay(attempts: int) -> timedelta:
    """보내기 실패 뒤 다음 시도까지. 30초에서 두 배씩, 한 시간이 상한."""
    return timedelta(seconds=min(3600, 30 * 2 ** max(0, attempts - 1)))


class NotificationStore(Protocol):
    async def set_target(self, owner_id: str, agent_id: str, target: NotifyTarget) -> bool: ...

    async def get_target(self, owner_id: str, agent_id: str) -> NotifyTarget | None: ...

    async def clear_target(self, owner_id: str, agent_id: str) -> bool: ...

    async def enqueue(self, notice: StandingNotice, *, now: datetime) -> bool: ...

    async def claim_due(self, *, limit: int, now: datetime) -> list[QueuedNotice]: ...

    async def mark_sent(self, notification_id: str, *, now: datetime) -> None: ...

    async def mark_failed(
        self, notification_id: str, *, error: str, now: datetime, give_up: bool
    ) -> None: ...


class InMemoryNotificationStore:
    """테스트용. 소유 관계는 `agents` 로 직접 적는다(agent_id -> owner_id)."""

    def __init__(self, agents: dict[str, str] | None = None) -> None:
        self.agents = dict(agents or {})
        self.targets: dict[str, NotifyTarget] = {}
        self.rows: dict[str, dict[str, Any]] = {}

    async def set_target(self, owner_id: str, agent_id: str, target: NotifyTarget) -> bool:
        if self.agents.get(agent_id) != owner_id:
            return False
        self.targets[agent_id] = target
        return True

    async def get_target(self, owner_id: str, agent_id: str) -> NotifyTarget | None:
        if self.agents.get(agent_id) != owner_id:
            return None
        return self.targets.get(agent_id)

    async def clear_target(self, owner_id: str, agent_id: str) -> bool:
        if self.agents.get(agent_id) != owner_id:
            return False
        return self.targets.pop(agent_id, None) is not None

    async def enqueue(self, notice: StandingNotice, *, now: datetime) -> bool:
        target = self.targets.get(notice.agent_id)
        if target is None or notice.agent_id not in self.agents:
            return False
        if any(
            row["agent_id"] == notice.agent_id and row["dedupe_key"] == notice.dedupe_key
            for row in self.rows.values()
        ):
            return False
        notification_id = f"sn_{uuid4().hex}"
        self.rows[notification_id] = {
            "agent_id": notice.agent_id,
            "kind": notice.kind,
            "dedupe_key": notice.dedupe_key,
            "channel_type": target.channel_type,
            "channel_id": target.channel_id,
            "body": notice.body,
            "status": "pending",
            "attempts": 0,
            "next_attempt_at": now,
            "last_error": None,
            "sent_at": None,
        }
        return True

    async def claim_due(self, *, limit: int, now: datetime) -> list[QueuedNotice]:
        due = [
            (notification_id, row)
            for notification_id, row in self.rows.items()
            if row["status"] == "pending" and row["next_attempt_at"] <= now
        ][:limit]
        return [
            QueuedNotice(
                notification_id=notification_id,
                agent_id=row["agent_id"],
                kind=row["kind"],
                channel_type=row["channel_type"],
                channel_id=row["channel_id"],
                body=row["body"],
                attempts=row["attempts"],
            )
            for notification_id, row in due
        ]

    async def mark_sent(self, notification_id: str, *, now: datetime) -> None:
        row = self.rows[notification_id]
        row.update(status="sent", sent_at=now, attempts=row["attempts"] + 1)

    async def mark_failed(
        self, notification_id: str, *, error: str, now: datetime, give_up: bool
    ) -> None:
        row = self.rows[notification_id]
        attempts = row["attempts"] + 1
        row.update(
            attempts=attempts,
            last_error=error[:500],
            status="failed" if give_up else "pending",
            next_attempt_at=now + retry_delay(attempts),
        )


class PostgresNotificationStore:
    def __init__(self, session_factory: Callable[[], Awaitable[Any]]) -> None:
        self._session_factory = session_factory

    async def set_target(self, owner_id: str, agent_id: str, target: NotifyTarget) -> bool:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        """
                        INSERT INTO standing_agent_notify_targets
                            (agent_id, channel_type, channel_id, updated_at)
                        SELECT agent_id, :channel_type, :channel_id, NOW()
                        FROM standing_agents
                        WHERE agent_id = :agent_id AND owner_id = :owner_id
                          AND deleted_at IS NULL
                        ON CONFLICT (agent_id) DO UPDATE
                        SET channel_type = EXCLUDED.channel_type,
                            channel_id = EXCLUDED.channel_id,
                            updated_at = EXCLUDED.updated_at
                        RETURNING agent_id
                        """
                    ),
                    {
                        "agent_id": agent_id,
                        "owner_id": owner_id,
                        "channel_type": target.channel_type,
                        "channel_id": target.channel_id,
                    },
                )
                return result.first() is not None

    async def get_target(self, owner_id: str, agent_id: str) -> NotifyTarget | None:
        async with await self._session_factory() as session:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT target.channel_type, target.channel_id
                        FROM standing_agent_notify_targets target
                        JOIN standing_agents agent ON agent.agent_id = target.agent_id
                        WHERE target.agent_id = :agent_id AND agent.owner_id = :owner_id
                          AND agent.deleted_at IS NULL
                        """
                    ),
                    {"agent_id": agent_id, "owner_id": owner_id},
                )
            ).first()
        return NotifyTarget(row[0], row[1]) if row is not None else None

    async def clear_target(self, owner_id: str, agent_id: str) -> bool:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        """
                        DELETE FROM standing_agent_notify_targets target
                        USING standing_agents agent
                        WHERE target.agent_id = :agent_id
                          AND agent.agent_id = target.agent_id
                          AND agent.owner_id = :owner_id
                        RETURNING target.agent_id
                        """
                    ),
                    {"agent_id": agent_id, "owner_id": owner_id},
                )
                return result.first() is not None

    async def enqueue(self, notice: StandingNotice, *, now: datetime) -> bool:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        """
                        INSERT INTO standing_notifications
                            (notification_id, agent_id, kind, dedupe_key,
                             channel_type, channel_id, body, status, attempts,
                             next_attempt_at, created_at)
                        SELECT :notification_id, target.agent_id, :kind, :dedupe_key,
                               target.channel_type, target.channel_id, :body,
                               'pending', 0, :now, :now
                        FROM standing_agent_notify_targets target
                        JOIN standing_agents agent ON agent.agent_id = target.agent_id
                        WHERE target.agent_id = :agent_id AND agent.deleted_at IS NULL
                        ON CONFLICT (agent_id, dedupe_key) DO NOTHING
                        RETURNING notification_id
                        """
                    ),
                    {
                        "notification_id": f"sn_{uuid4().hex}",
                        "agent_id": notice.agent_id,
                        "kind": notice.kind,
                        "dedupe_key": notice.dedupe_key,
                        "body": notice.body,
                        "now": now,
                    },
                )
                return result.first() is not None

    async def claim_due(self, *, limit: int, now: datetime) -> list[QueuedNotice]:
        """`SKIP LOCKED` 로 꺼내고 다음 시도 시각을 미뤄 둔다 -- API 워커가 여럿이어도
        같은 알림을 둘이 동시에 보내지 않는다. 보낸 뒤 `mark_sent` 가 확정한다."""
        async with await self._session_factory() as session:
            async with session.begin():
                rows = (
                    await session.execute(
                        text(
                            """
                            WITH due AS (
                                SELECT notification_id
                                FROM standing_notifications
                                WHERE status = 'pending' AND next_attempt_at <= :now
                                ORDER BY next_attempt_at, notification_id
                                FOR UPDATE SKIP LOCKED
                                LIMIT :limit
                            )
                            UPDATE standing_notifications notice
                            SET next_attempt_at = :lease_until
                            FROM due
                            WHERE notice.notification_id = due.notification_id
                            RETURNING notice.notification_id, notice.agent_id, notice.kind,
                                      notice.channel_type, notice.channel_id, notice.body,
                                      notice.attempts
                            """
                        ),
                        {
                            "now": now,
                            "limit": limit,
                            "lease_until": now + timedelta(minutes=5),
                        },
                    )
                ).all()
        return [QueuedNotice(*row) for row in rows]

    async def mark_sent(self, notification_id: str, *, now: datetime) -> None:
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        UPDATE standing_notifications
                        SET status = 'sent', sent_at = :now, attempts = attempts + 1
                        WHERE notification_id = :notification_id
                        """
                    ),
                    {"notification_id": notification_id, "now": now},
                )

    async def mark_failed(
        self, notification_id: str, *, error: str, now: datetime, give_up: bool
    ) -> None:
        async with await self._session_factory() as session:
            async with session.begin():
                row = (
                    await session.execute(
                        text(
                            """
                            UPDATE standing_notifications
                            SET attempts = attempts + 1, last_error = :error,
                                status = CASE WHEN :give_up THEN 'failed' ELSE 'pending' END
                            WHERE notification_id = :notification_id
                            RETURNING attempts
                            """
                        ),
                        {
                            "notification_id": notification_id,
                            "error": error[:500],
                            "give_up": give_up,
                        },
                    )
                ).first()
                if row is not None and not give_up:
                    await session.execute(
                        text(
                            """
                            UPDATE standing_notifications
                            SET next_attempt_at = :next_attempt_at
                            WHERE notification_id = :notification_id
                            """
                        ),
                        {
                            "notification_id": notification_id,
                            "next_attempt_at": now + retry_delay(int(row[0])),
                        },
                    )


class StandingNotifier:
    """적는 쪽(워커·루프)이 쓰는 입구. 본문 상한을 여기서 건다.

    적기 실패는 **삼키고 로그만** 남긴다 -- 알림은 판정의 부산물이다. 알림을 적지
    못했다고 멈춤·판정이 바뀌면 안 된다.
    """

    def __init__(
        self,
        store: NotificationStore,
        *,
        max_body_chars: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._max_body_chars = max_body_chars
        self._clock = clock

    async def notify(self, notice: StandingNotice) -> bool:
        try:
            return await self._store.enqueue(
                replace(notice, body=bounded_body(notice.body, self._max_body_chars)),
                now=self._clock(),
            )
        except Exception:  # noqa: BLE001 -- 알림은 판정을 바꾸지 않는다
            logger.warning("standing notice enqueue failed kind=%s", notice.kind, exc_info=True)
            return False


SendFn = Callable[[str, str, str], Awaitable[None]]


async def drain_once(
    store: NotificationStore,
    send: SendFn,
    *,
    batch_size: int,
    max_attempts: int,
    now: datetime,
) -> int:
    """꺼낸 것을 보낸다. 보낸 수를 돌려준다. 한 알림의 실패가 나머지를 막지 않는다."""
    sent = 0
    for notice in await store.claim_due(limit=batch_size, now=now):
        try:
            await send(notice.channel_type, notice.channel_id, notice.body)
        except Exception as error:  # noqa: BLE001 -- 어댑터마다 예외가 다르다
            await store.mark_failed(
                notice.notification_id,
                error=f"{type(error).__name__}: {error}",
                now=now,
                give_up=notice.attempts + 1 >= max_attempts,
            )
            continue
        await store.mark_sent(notice.notification_id, now=now)
        sent += 1
    return sent


async def gateway_send(channel_type: str, channel_id: str, body: str) -> None:
    """API 프로세스의 게이트웨이로 보낸다. 어댑터가 없으면 **실패**다 -- 게이트웨이의
    `send_to_channel` 은 경고만 남기고 돌아오므로, 그것을 성공으로 세지 않게 먼저 본다."""
    from neos.api.channels.gateway import ChannelGateway

    gateway = ChannelGateway.get_instance()
    if not gateway.has_adapter(channel_type):
        raise RuntimeError(f"no channel adapter for {channel_type}")
    await gateway.send_to_channel(channel_type, channel_id, body)


async def run_notification_drain(
    store: NotificationStore,
    *,
    poll_interval_seconds: float,
    batch_size: int,
    max_attempts: int,
    send: SendFn = gateway_send,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> None:
    """API 프로세스의 lifespan 이 띄우는 루프. 취소되면 끝난다."""
    while True:
        try:
            await drain_once(
                store,
                send,
                batch_size=batch_size,
                max_attempts=max_attempts,
                now=clock(),
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 -- 다음 주기에 다시 본다
            logger.warning("standing notification drain failed", exc_info=True)
        await asyncio.sleep(poll_interval_seconds)


def build_standing_notifier(
    standing: Any, session_factory: Callable[[], Awaitable[Any]]
) -> StandingNotifier | None:
    """`None` 이 off 다. 켜졌는지 판단하는 자리는 이 팩토리 하나다."""
    notifications = getattr(standing, "notifications", None)
    if not getattr(standing, "enabled", False) or notifications is None:
        return None
    if not notifications.enabled:
        return None
    return StandingNotifier(
        PostgresNotificationStore(session_factory),
        max_body_chars=notifications.max_body_chars,
    )

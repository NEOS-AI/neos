"""상시 에이전트의 대기 질문 -- 트랙 Q9a (docs/Q9_ASK_AND_WAIT_DESIGN_261005.md §4).

에이전트의 `autonomous` 태스크가 `ask_user.v1` 을 부르면 질문 행 하나가 생기고 태스크는
`waiting_user` 로 선다. 이 모듈은 그 행의 **SQL 이 사는 유일한 곳**이다.

- **"에이전트당 대기 하나"는 부분 unique 인덱스 하나에만 산다**(마이그레이션 095). 둘째
  `open` 은 None 이다 -- 루프는 그것을 `ask_pending` 거절로 바꾸고 계속 돈다.
- **원장에 닿는 트랜잭션은 코딩 저장소가 갖는다**(설계 §9.2). 원장 이벤트 어휘는
  `tests/coding/test_event_kinds.py` 가 `neos/coding/` 만 훑어 고정하므로, 이벤트를 여기서
  쓰면 그 검사가 못 본다. 그래서 쓰기는 `*_in_session(session, ...)` 함수로 두고,
  `PostgresCodingRunRepository` 가 자기 트랜잭션 안에서 그것을 부른다.
- **답은 한 번이다.** `answer` 는 `waiting` 일 때만 통과한다.
- **이 모듈은 소유 검사를 하지 않는다.** 행에 `owner_id` 가 없다 -- 부르는 쪽(코딩 저장소의
  트랜잭션, 게이트웨이의 `resolve_agent`)이 한다.
- 메모리 구현과 Postgres 구현이 같은 계약을 지킨다(`tests/standing/test_pending_asks_contract.py`).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Protocol
from uuid import uuid4

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

#: 마이그레이션 095 의 CHECK 와 같아야 한다.
ASK_WAITING = "waiting"
ASK_ANSWERED = "answered"
ASK_EXPIRED = "expired"
ASK_CANCELLED = "cancelled"
ASK_STATUSES = frozenset({ASK_WAITING, ASK_ANSWERED, ASK_EXPIRED, ASK_CANCELLED})


#: `standing_ask_total{outcome}` 의 값(설계 §9.1). Q9d 가 `expired` 를 더한다.
ASK_OUTCOMES = frozenset(
    {
        "asked",
        "refused_pending",
        "refused_no_channel",
        "lookup_failed",
        "answered",
        # Q9c 고침 1 -- 질문을 찾은 뒤 재개가 실패했다(소유자에게 다시 보내 달라고 했다).
        "answer_failed",
    }
)


def count_ask(outcome: str) -> None:
    """질문 결과 하나를 센다. 계측 실패는 판정을 바꾸지 않는다."""
    if outcome not in ASK_OUTCOMES:
        raise ValueError(f"unknown ask outcome: {outcome!r}")
    try:
        from neos.observability.metrics import metrics

        metrics.standing_ask_total.labels(outcome=outcome).inc()
    except Exception:  # noqa: BLE001
        logger.debug("standing ask counter unavailable", exc_info=True)


def new_ask_id() -> str:
    return f"spa_{uuid4().hex}"


@dataclass(frozen=True, slots=True)
class PendingAsk:
    ask_id: str
    agent_id: str
    task_id: str
    run_id: str
    tool_call_id: str
    questions: tuple[Any, ...]
    reply_session_id: str | None
    asked_at: datetime
    expires_at: datetime
    answered_at: datetime | None = None
    answers: tuple[str, ...] | None = None
    status: str = ASK_WAITING

    def __post_init__(self) -> None:
        if self.status not in ASK_STATUSES:
            raise ValueError(f"unknown ask status: {self.status!r}")
        if self.expires_at <= self.asked_at:
            raise ValueError("ask expiry must follow the ask")


@dataclass(frozen=True, slots=True)
class ReplyDestination:
    """질문을 보낼 곳(설계 §6.1). 답할 세션이 없어 알림 대상으로 보내면 `session_id` 는 None."""

    channel_type: str
    channel_id: str
    session_id: str | None = None


class PendingAskStore(Protocol):
    async def open(
        self,
        *,
        agent_id: str,
        task_id: str,
        run_id: str,
        tool_call_id: str,
        questions: Sequence[Any],
        reply_session_id: str | None,
        asked_at: datetime,
        expires_at: datetime,
        ask_id: str | None = None,
    ) -> PendingAsk | None:
        """대기 질문을 연다. `ask_id` 를 주면 그 id 로 연다(알림의 중복 키가 먼저 필요할 때, Q9b). 그 에이전트에 이미 대기 중인 질문이 있으면 None."""
        ...

    async def waiting_for_agent(self, agent_id: str) -> PendingAsk | None: ...

    async def answer(
        self, ask_id: str, answers: Sequence[str], *, now: datetime
    ) -> PendingAsk | None:
        """`waiting` 이면 답을 적는다. 아니면 None -- 답은 한 번이다."""
        ...

    async def expire_due(self, now: datetime) -> list[PendingAsk]: ...

    async def for_call(
        self, task_id: str, run_id: str, tool_call_id: str
    ) -> PendingAsk | None:
        """그 도구 호출의 질문. 재개한 루프가 자기 질문을 찾는 열쇠다."""
        ...

    async def cancel_for_task(self, task_id: str) -> int:
        """태스크의 대기 질문을 닫는다(취소, 설계 §8.1). 닫은 수."""
        ...


def _questions(questions: Sequence[Any]) -> tuple[Any, ...]:
    return tuple(dict(item) if isinstance(item, Mapping) else str(item) for item in questions)


class InMemoryPendingAskStore:
    """테스트용. Postgres 와 같은 계약 -- 인덱스 둘을 흉내 낸다."""

    def __init__(self) -> None:
        self.rows: dict[str, PendingAsk] = {}
        self._lock = asyncio.Lock()

    async def open(
        self,
        *,
        agent_id,
        task_id,
        run_id,
        tool_call_id,
        questions,
        reply_session_id,
        asked_at,
        expires_at,
        ask_id=None,
    ):
        async with self._lock:
            if any(
                row.agent_id == agent_id and row.status == ASK_WAITING
                for row in self.rows.values()
            ):
                return None
            if any(
                (row.task_id, row.run_id, row.tool_call_id) == (task_id, run_id, tool_call_id)
                for row in self.rows.values()
            ):
                return None
            ask = PendingAsk(
                ask_id=ask_id or new_ask_id(),
                agent_id=agent_id,
                task_id=task_id,
                run_id=run_id,
                tool_call_id=tool_call_id,
                questions=_questions(questions),
                reply_session_id=reply_session_id,
                asked_at=asked_at,
                expires_at=expires_at,
            )
            self.rows[ask.ask_id] = ask
            return ask

    async def waiting_for_agent(self, agent_id):
        return next(
            (
                row
                for row in self.rows.values()
                if row.agent_id == agent_id and row.status == ASK_WAITING
            ),
            None,
        )

    async def answer(self, ask_id, answers, *, now):
        async with self._lock:
            row = self.rows.get(ask_id)
            if row is None or row.status != ASK_WAITING:
                return None
            answered = replace(
                row,
                status=ASK_ANSWERED,
                answered_at=now,
                answers=tuple(str(item) for item in answers),
            )
            self.rows[ask_id] = answered
            return answered

    async def expire_due(self, now):
        async with self._lock:
            due = [
                row
                for row in self.rows.values()
                if row.status == ASK_WAITING and row.expires_at <= now
            ]
            expired = []
            for row in sorted(due, key=lambda item: (item.expires_at, item.ask_id)):
                updated = replace(row, status=ASK_EXPIRED)
                self.rows[row.ask_id] = updated
                expired.append(updated)
            return expired

    async def for_call(self, task_id, run_id, tool_call_id):
        return next(
            (
                row
                for row in self.rows.values()
                if (row.task_id, row.run_id, row.tool_call_id) == (task_id, run_id, tool_call_id)
            ),
            None,
        )

    async def cancel_for_task(self, task_id):
        async with self._lock:
            closed = 0
            for ask_id, row in list(self.rows.items()):
                if row.task_id == task_id and row.status == ASK_WAITING:
                    self.rows[ask_id] = replace(row, status=ASK_CANCELLED)
                    closed += 1
            return closed


# ---- Postgres -------------------------------------------------------------------

_COLUMNS = """ask_id, agent_id, task_id, run_id, tool_call_id, questions,
              reply_session_id, asked_at, expires_at, answered_at, answers, status"""


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _row(row) -> PendingAsk:
    answers = _json(row[10])
    return PendingAsk(
        ask_id=row[0],
        agent_id=row[1],
        task_id=row[2],
        run_id=row[3],
        tool_call_id=row[4],
        questions=_questions(_json(row[5]) or ()),
        reply_session_id=row[6],
        asked_at=row[7],
        expires_at=row[8],
        answered_at=row[9],
        answers=tuple(str(item) for item in answers) if answers is not None else None,
        status=row[11],
    )


async def open_in_session(
    session,
    *,
    agent_id: str,
    task_id: str,
    run_id: str,
    tool_call_id: str,
    questions: Sequence[Any],
    reply_session_id: str | None,
    asked_at: datetime,
    expires_at: datetime,
    ask_id: str | None = None,
) -> PendingAsk | None:
    """한 행 INSERT. 대기 중인 질문이 이미 있거나 같은 도구 호출이면 None.

    `ON CONFLICT DO NOTHING` 은 대상 없이 쓴다 -- 부분 unique 인덱스와 호출 인덱스 **둘 다**
    에 걸려야 하기 때문이다. 동시에 둘이 들어오면 둘째는 첫째의 커밋을 기다렸다가 진다.
    """
    if expires_at <= asked_at:
        raise ValueError("ask expiry must follow the ask")
    result = await session.execute(
        text(
            f"""
            INSERT INTO standing_pending_asks
                (ask_id, agent_id, task_id, run_id, tool_call_id, questions,
                 reply_session_id, status, asked_at, expires_at)
            VALUES
                (:ask_id, :agent_id, :task_id, :run_id, :tool_call_id,
                 CAST(:questions AS JSONB), :reply_session_id, 'waiting',
                 :asked_at, :expires_at)
            ON CONFLICT DO NOTHING
            RETURNING {_COLUMNS}
            """
        ),
        {
            "ask_id": ask_id or new_ask_id(),
            "agent_id": agent_id,
            "task_id": task_id,
            "run_id": run_id,
            "tool_call_id": tool_call_id,
            "questions": json.dumps(list(_questions(questions))),
            "reply_session_id": reply_session_id,
            "asked_at": asked_at,
            "expires_at": expires_at,
        },
    )
    row = result.first()
    return _row(row) if row is not None else None


async def answer_in_session(
    session, ask_id: str, answers: Sequence[str], *, now: datetime
) -> PendingAsk | None:
    result = await session.execute(
        text(
            f"""
            UPDATE standing_pending_asks
            SET status = 'answered', answered_at = :now, answers = CAST(:answers AS JSONB)
            WHERE ask_id = :ask_id AND status = 'waiting'
            RETURNING {_COLUMNS}
            """
        ),
        {
            "ask_id": ask_id,
            "now": now,
            "answers": json.dumps([str(item) for item in answers]),
        },
    )
    row = result.first()
    return _row(row) if row is not None else None


async def expire_due_in_session(session, now: datetime, *, limit: int = 100) -> list[PendingAsk]:
    """기한이 지난 대기 질문을 `expired` 로. 폴러가 여럿이어도 한 번(SKIP LOCKED)."""
    result = await session.execute(
        text(
            f"""
            WITH due AS (
                SELECT ask_id FROM standing_pending_asks
                WHERE status = 'waiting' AND expires_at <= :now
                ORDER BY expires_at, ask_id
                FOR UPDATE SKIP LOCKED
                LIMIT :limit
            )
            UPDATE standing_pending_asks ask
            SET status = 'expired'
            FROM due
            WHERE ask.ask_id = due.ask_id
            RETURNING {", ".join("ask." + c.strip() for c in _COLUMNS.split(","))}
            """
        ),
        {"now": now, "limit": limit},
    )
    return sorted((_row(row) for row in result.all()), key=lambda a: (a.expires_at, a.ask_id))


async def cancel_for_task_in_session(session, task_id: str) -> int:
    result = await session.execute(
        text(
            """
            UPDATE standing_pending_asks SET status = 'cancelled'
            WHERE task_id = :task_id AND status = 'waiting'
            RETURNING ask_id
            """
        ),
        {"task_id": task_id},
    )
    return len(result.all())


class PostgresPendingAskStore:
    def __init__(self, session_factory: Callable[[], Awaitable[Any]]) -> None:
        self._session_factory = session_factory

    async def open(self, **kwargs):
        async with await self._session_factory() as session:
            async with session.begin():
                return await open_in_session(session, **kwargs)

    async def waiting_for_agent(self, agent_id):
        async with await self._session_factory() as session:
            row = (
                await session.execute(
                    text(
                        f"""
                        SELECT {_COLUMNS} FROM standing_pending_asks
                        WHERE agent_id = :agent_id AND status = 'waiting'
                        """
                    ),
                    {"agent_id": agent_id},
                )
            ).first()
        return _row(row) if row is not None else None

    async def answer(self, ask_id, answers, *, now):
        async with await self._session_factory() as session:
            async with session.begin():
                return await answer_in_session(session, ask_id, answers, now=now)

    async def expire_due(self, now):
        async with await self._session_factory() as session:
            async with session.begin():
                return await expire_due_in_session(session, now)

    async def for_call(self, task_id, run_id, tool_call_id):
        async with await self._session_factory() as session:
            row = (
                await session.execute(
                    text(
                        f"""
                        SELECT {_COLUMNS} FROM standing_pending_asks
                        WHERE task_id = :task_id AND run_id = :run_id
                          AND tool_call_id = :tool_call_id
                        """
                    ),
                    {"task_id": task_id, "run_id": run_id, "tool_call_id": tool_call_id},
                )
            ).first()
        return _row(row) if row is not None else None

    async def cancel_for_task(self, task_id):
        async with await self._session_factory() as session:
            async with session.begin():
                return await cancel_for_task_in_session(session, task_id)


# ---- the loop's port ------------------------------------------------------------

DestinationFn = Callable[[str, "str | None"], Awaitable["ReplyDestination | None"]]


@dataclass(frozen=True, slots=True)
class AgentAsks:
    """루프가 쥐는 창구(설계 §5). `_prepare_real_coding_loop` 가 늘 배선하고, 켜졌는지는
    `enabled()` 가 호출 때마다 말한다(`ask_effective`).

    루프는 설정을 읽지 않는다. 질문을 커밋하는 트랜잭션은 루프의 저장소
    (`request_user_answer`)가 갖고, 여기는 읽기 둘 · 기한 · 알림 본문을 준다.
    """

    store: PendingAskStore
    destination: DestinationFn
    expire_hours: int = 24
    #: 질문 알림 본문의 상한(`standing_agents.notifications.max_body_chars`).
    max_body_chars: int = 3_500
    #: 질문 경로가 켜졌는가 -- 루프가 호출 때마다 읽는다. 포트는 늘 배선되고(Q9b), 꺼져
    #: 있으면 에이전트 태스크도 지금처럼 무인 DENY 다.
    enabled: Callable[[], bool] = lambda: True

    def notice_for(
        self, ask_id: str, agent_id: str, questions: Sequence[Any], destination: "ReplyDestination"
    ):
        """질문 알림과 목적지. 루프가 질문 커밋에 함께 실어 같은 트랜잭션에서 적는다."""
        return question_notice(
            ask_id, agent_id, questions, destination, max_body_chars=self.max_body_chars
        )

    async def for_call(self, task_id: str, run_id: str, tool_call_id: str) -> PendingAsk | None:
        return await self.store.for_call(task_id, run_id, tool_call_id)

    async def reply_destination(
        self, agent_id: str, owner_id: str | None
    ) -> ReplyDestination | None:
        """질문을 보낼 곳. None 이면 묻지 않는다(`no_reply_channel`)."""
        return await self.destination(agent_id, owner_id)


def ask_effective(config: Any) -> bool:
    """질문 경로가 켜졌는가 -- 판단하는 자리는 이 함수 하나다(설계 §9.1).

    알림이 꺼져 있으면 질문이 나가지 않고(드레인이 없다), 스레드가 꺼져 있으면 답을
    알아볼 수 없다. 넷 중 하나라도 꺼져 있으면 지금처럼 무인 DENY 다.
    """
    standing = getattr(config, "standing_agents", None)
    if standing is None:
        return False
    return bool(
        standing.enabled
        and standing.ask.enabled
        and standing.notifications.enabled
        and standing.threads.enabled
    )


# ---- delivery (track Q9b, design §6) ---------------------------------------------

_REPLY_LINE = "Reply in this chat to answer."
_ONE_LINE_EACH = "Answer one line per question, in order."


def _question_lines(questions: Sequence[Any]) -> list[str]:
    lines: list[str] = []
    numbered = len(questions) > 1
    for index, item in enumerate(questions, start=1):
        if isinstance(item, Mapping):
            prompt = str(item.get("prompt") or "")
            labels = []
            for option in item.get("options") or ():
                label = option.get("label") if isinstance(option, Mapping) else option
                if label:
                    labels.append(str(label))
        else:
            prompt, labels = str(item), []
        lines.append(f"{index}. {prompt}" if numbered else prompt)
        lines.extend(f"   {chr(ord('a') + n)}) {label}" for n, label in enumerate(labels))
    return lines


def question_notice(
    ask_id: str,
    agent_id: str,
    questions: Sequence[Any],
    destination: ReplyDestination,
    *,
    max_body_chars: int,
):
    """질문 알림(설계 §6.2)과 그 목적지. 중복 키는 `question:{ask_id}` 다.

    본문은 질문 목록(선택지 포함) 다음에, 질문이 여럿이면 "한 줄에 한 질문씩"(결정 Q-B),
    맨 끝에 "Reply in this chat to answer." 를 둔다. 상한을 넘으면 질문 쪽을 자르고 안내 줄은 남긴다.
    """
    from neos.standing.notifications import (
        KIND_QUESTION_ASKED,
        NotifyTarget,
        StandingNotice,
        bounded_body,
    )

    footer = [_ONE_LINE_EACH] if len(questions) > 1 else []
    footer.append(_REPLY_LINE)
    tail = "\n\n" + "\n".join(footer)
    head = bounded_body("\n".join(_question_lines(questions)), max(0, max_body_chars - len(tail)))
    notice = StandingNotice(
        agent_id=agent_id,
        kind=KIND_QUESTION_ASKED,
        dedupe_key=f"question:{ask_id}",
        body=head + tail,
    )
    return notice, NotifyTarget(destination.channel_type, destination.channel_id)


def owner_mapped_on(channels: Any, platform: str, owner_id: str | None) -> bool:
    """`channels.principals` 가 그 플랫폼에서 소유자를 매핑하는가. 매핑이 없는 곳에서 온 답은
    알아볼 수 없으므로(`mapped_owner`) 그곳에는 묻지 않는다(설계 §6.1)."""
    if not owner_id:
        return False
    return any(
        item.platform == platform and item.user_id == owner_id
        for item in getattr(channels, "principals", None) or ()
    )


async def resolve_reply_destination(
    agent_id: str,
    owner_id: str | None,
    *,
    threads: Any,
    notices: Any,
    channels: Any,
) -> ReplyDestination | None:
    """질문을 보낼 곳(설계 §6.1): 최근 말한 붙은 채널 세션 → 알림 대상 → None.

    읽기가 실패하면 None 이다 -- 묻지 않는다(`no_reply_channel`). 답이 올 수 없는 곳에
    묻고 만료까지 매달리는 것보다 낫다.
    """
    from neos.api.channels.session_key import session_key_destination
    from neos.standing.threads import reply_session_for

    try:
        session = await reply_session_for(threads, agent_id)
        if session is not None:
            address = session_key_destination(session.session_id)
            if address is not None and owner_mapped_on(channels, address[0], owner_id):
                return ReplyDestination(address[0], address[1], session.session_id)
        if not owner_id:
            return None
        target = await notices.get_target(owner_id, agent_id)
    except Exception:  # noqa: BLE001 -- 위 독스트링
        logger.warning("agent ask destination lookup failed agent_id=%s", agent_id, exc_info=True)
        count_ask("lookup_failed")
        return None
    if target is None or not owner_mapped_on(channels, target.channel_type, owner_id):
        return None
    return ReplyDestination(target.channel_type, target.channel_id, None)


async def enqueue_question(
    notice_store: Any,
    ask: PendingAsk,
    *,
    owner_id: str | None,
    now: datetime,
    max_body_chars: int,
) -> bool:
    """질문 알림을 **따로** 적는다 -- 루프는 질문 커밋과 같은 트랜잭션에서 적으므로 이것을 부르지
    않는다. 다시 적어도 중복 키(`question:{ask_id}`)가 한 줄로 막는다. 목적지는 질문의
    `reply_session_id`(v2 키)에서, 없으면 알림 대상에서 읽는다."""
    from neos.api.channels.session_key import session_key_destination

    destination = None
    if ask.reply_session_id:
        address = session_key_destination(ask.reply_session_id)
        if address is not None:
            destination = ReplyDestination(address[0], address[1], ask.reply_session_id)
    if destination is None and owner_id:
        target = await notice_store.get_target(owner_id, ask.agent_id)
        if target is not None:
            destination = ReplyDestination(target.channel_type, target.channel_id, None)
    if destination is None:
        return False
    notice, target = question_notice(
        ask.ask_id, ask.agent_id, ask.questions, destination, max_body_chars=max_body_chars
    )
    return await notice_store.enqueue_to(notice, target, now=now)


def build_agent_asks(config: Any, session_factory: Callable[[], Awaitable[Any]]) -> AgentAsks:
    """루프의 포트. 늘 만든다 -- 켜졌는지는 `enabled()` 가 호출 때마다 `ask_effective` 로 본다."""
    from neos.standing.notifications import PostgresNotificationStore
    from neos.standing.threads import PostgresAgentThreadStore

    threads = PostgresAgentThreadStore(session_factory)
    notices = PostgresNotificationStore(session_factory)
    standing = config.standing_agents

    async def destination(agent_id: str, owner_id: str | None) -> ReplyDestination | None:
        return await resolve_reply_destination(
            agent_id, owner_id, threads=threads, notices=notices, channels=config.channels
        )

    return AgentAsks(
        store=PostgresPendingAskStore(session_factory),
        destination=destination,
        expire_hours=standing.ask.expire_hours,
        max_body_chars=standing.notifications.max_body_chars,
        enabled=lambda: ask_effective(config),
    )

"""상시 에이전트의 채널 횡단 스레드 -- 트랙 Q8a (docs/Q8_CROSS_CHANNEL_THREAD_DESIGN_261005.md).

에이전트마다 **활성 스레드 하나**. 소유자의 DM 채널 세션과 웹 에이전트 대화가 그 스레드에
붙고, 붙은 세션의 턴이 쌓인다. 다음 턴의 맥락은 채널이 아니라 스레드에서 읽는다.

- **"하나"는 부분 unique 인덱스 하나에만 산다**(마이그레이션 092). 둘째로 만들려는 쪽은
  지고, 이긴 쪽을 다시 읽는다 -- 잠금을 따로 두지 않는다.
- **"새로 시작"은 보관하고 새로 연다**(결정 Q8-2). 회전은 한 트랜잭션에서 활성 스레드를
  보관하고, 새 스레드를 열고, 붙은 세션을 **옮긴다**(떼지 않는다).
- **에이전트를 지우면 스레드·세션·턴을 지운다**(결정 Q8-4). Postgres 는 에이전트 저장소의
  `delete` 가 같은 트랜잭션에서, 메모리 구현은 삭제 통지로 흉내 낸다.
- 저장소 메서드는 `agent_id` 를 받는다. **소유 검사는 호출자가 `resolve_agent` 로 이미
  했다**는 전제다 -- 그래서 모듈 함수(`resolve_agent_thread` · `rotate_agent_thread`)는
  `StandingAgent` 를 받는다. 스레드를 찾는 길은 이 함수들 하나다(Q13 §6 과 같은 규칙).
- 메모리 구현과 Postgres 구현이 같은 계약을 지킨다(`tests/standing/test_agent_threads_contract.py`).
"""

from __future__ import annotations

import base64
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from neos.standing.models import StandingAgent

#: 마이그레이션 092 의 CHECK 와 같아야 한다.
THREAD_CHANNEL_TYPES = frozenset({"slack", "discord", "telegram", "web"})
TURN_ROLES = frozenset({"user", "assistant"})


@dataclass(frozen=True, slots=True)
class AgentThread:
    agent_thread_id: str
    agent_id: str
    created_at: datetime
    archived_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ThreadSession:
    session_id: str
    agent_thread_id: str
    channel_type: str
    attached_at: datetime


@dataclass(frozen=True, slots=True)
class ThreadTurn:
    turn_id: int
    agent_thread_id: str
    session_id: str
    channel_type: str
    role: str
    content: str
    created_at: datetime


@dataclass(frozen=True, order=True, slots=True)
class TurnCursor:
    """피드 커서 `(position, turn_id)` (Q8c). Postgres 의 position 은 턴을 쓴 트랜잭션 id
    (`xact_id`)이고 독자는 `pg_snapshot_xmin` 미만만 읽는다 -- 늦게 커밋된 턴이 지나간 커서
    뒤로 떨어지지 않게(마이그레이션 093 · Q13d 와 같은 이유). 메모리 구현의 position 은
    추가 순서(`turn_id`)다."""

    position: int
    turn_id: int

    def encode(self) -> str:
        raw = json.dumps([self.position, self.turn_id], separators=(",", ":"))
        return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")

    @classmethod
    def decode(cls, value: str) -> "TurnCursor":
        """불투명 문자열. 읽을 수 없으면 ValueError (API 는 422)."""
        try:
            padded = value + "=" * (-len(value) % 4)
            position, turn_id = json.loads(base64.urlsafe_b64decode(padded))
        except Exception as error:
            raise ValueError("unreadable turn cursor") from error
        if not (
            type(position) is int and type(turn_id) is int and position >= 0 and turn_id >= 0
        ):
            raise ValueError("unreadable turn cursor")
        return cls(position, turn_id)


TURN_FEED_START = TurnCursor(0, 0)


def new_agent_thread_id() -> str:
    return f"sat_{uuid4().hex}"


def _check_channel_type(channel_type: str) -> None:
    if channel_type not in THREAD_CHANNEL_TYPES:
        raise ValueError(f"unsupported channel_type: {channel_type!r}")


def _check_turn(channel_type: str, role: str, content: str) -> None:
    _check_channel_type(channel_type)
    if role not in TURN_ROLES:
        raise ValueError(f"unsupported role: {role!r}")
    if not content or not content.strip():
        raise ValueError("turn content must not be empty")


class AgentThreadStore(Protocol):
    async def get_or_create_active(self, agent_id: str) -> AgentThread | None:
        """활성 스레드. 없으면 연다. 살아 있는 에이전트가 아니면 None."""
        ...

    async def rotate(self, agent_id: str) -> AgentThread | None:
        """보관 + 새로 열기 + 세션 옮기기, 한 트랜잭션. 동시 회전은 하나만 일어난다."""
        ...

    async def attach_session(
        self, agent_id: str, session_id: str, channel_type: str
    ) -> AgentThread | None:
        """세션을 활성 스레드에 붙인다. 다른 에이전트에 붙은 세션이면 None -- 빼앗지 않는다.

        웹 세션은 스레드당 하나다(094). 이미 다른 웹 세션이 붙어 있으면 None.
        """
        ...

    async def thread_for_session(self, session_id: str) -> AgentThread | None: ...

    async def list_threads(self, agent_id: str) -> list[AgentThread]:
        """보관 포함, 연 순서대로."""
        ...

    async def list_sessions(self, agent_thread_id: str) -> list[ThreadSession]: ...

    async def append_turn(
        self,
        agent_thread_id: str,
        session_id: str,
        channel_type: str,
        role: str,
        content: str,
        *,
        idem_key: str | None = None,
    ) -> bool:
        """썼으면 True, 같은 `idem_key` 가 이미 있으면 False."""
        ...

    async def recent_turns(self, agent_thread_id: str, *, limit: int) -> list[ThreadTurn]:
        """최근 `limit` 개, 오래된 것부터."""
        ...

    # ---- 읽기 API (Q8c). 전부 부작용이 없다 -- 활성 스레드를 열지 않는다.

    async def active(self, agent_id: str) -> AgentThread | None: ...

    async def get_thread(self, agent_id: str, agent_thread_id: str) -> AgentThread | None:
        """그 에이전트의 스레드(보관 포함). 다른 에이전트의 스레드 id 는 None."""
        ...

    async def detach_session(self, agent_id: str, session_id: str) -> bool:
        """그 에이전트의 스레드에 붙은 세션이면 떼고 True. 남의 세션·없는 세션은 False."""
        ...

    async def turns_after(
        self, agent_thread_id: str, *, after: TurnCursor, limit: int
    ) -> list[tuple[TurnCursor, ThreadTurn]]:
        """피드. 커서 뒤의 턴을 커밋 순서에 가깝게, `limit` 개까지."""
        ...


async def resolve_agent_thread(
    store: AgentThreadStore, agent: StandingAgent
) -> AgentThread | None:
    """에이전트의 활성 스레드(없으면 연다). `agent` 는 `resolve_agent` 가 돌려준 것이어야 한다."""
    return await store.get_or_create_active(agent.agent_id)


async def rotate_agent_thread(store: AgentThreadStore, agent: StandingAgent) -> AgentThread | None:
    """"새로 시작" -- 에이전트 단위다. 붙은 모든 세션의 맥락이 새 스레드에서 시작한다."""
    return await store.rotate(agent.agent_id)


async def thread_window(
    store: AgentThreadStore, agent_thread_id: str, *, limit: int
) -> list[ThreadTurn]:
    """다음 턴이 보는 맥락. `limit` 은 `chat.max_history_messages` 를 쓴다(설계 §6)."""
    if limit <= 0:
        return []
    return await store.recent_turns(agent_thread_id, limit=limit)


class InMemoryAgentThreadStore:
    """테스트와 로컬용. 부분 unique 인덱스와 CASCADE 를 코드로 흉내 낸다.

    에이전트의 생사는 메모리 에이전트 저장소에 묻고, 에이전트 삭제 통지를 받아 그
    에이전트의 스레드·세션·턴을 지운다 -- Postgres 저장소가 같은 트랜잭션에서 하는 일이다.
    """

    def __init__(
        self,
        agents: Any,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._agents = agents
        self._clock = clock
        self._threads: dict[str, AgentThread] = {}
        self._sessions: dict[str, ThreadSession] = {}
        self._turns: list[ThreadTurn] = []
        self._idem: set[tuple[str, str, str, str]] = set()
        self._next_turn_id = 1
        agents.add_delete_listener(self._purge_agent)

    def _purge_agent(self, agent_id: str) -> None:
        gone = {t.agent_thread_id for t in self._threads.values() if t.agent_id == agent_id}
        self._threads = {k: v for k, v in self._threads.items() if k not in gone}
        self._sessions = {
            k: v for k, v in self._sessions.items() if v.agent_thread_id not in gone
        }
        self._turns = [t for t in self._turns if t.agent_thread_id not in gone]
        self._idem = {key for key in self._idem if key[0] not in gone}

    def _active(self, agent_id: str) -> AgentThread | None:
        for thread in self._threads.values():
            if thread.agent_id == agent_id and thread.archived_at is None:
                return thread
        return None

    def _open(self, agent_id: str) -> AgentThread:
        thread = AgentThread(new_agent_thread_id(), agent_id, self._clock())
        self._threads[thread.agent_thread_id] = thread
        return thread

    async def get_or_create_active(self, agent_id: str) -> AgentThread | None:
        if not self._agents.is_live(agent_id):
            return None
        return self._active(agent_id) or self._open(agent_id)

    async def rotate(self, agent_id: str) -> AgentThread | None:
        if not self._agents.is_live(agent_id):
            return None
        old = self._active(agent_id)
        if old is not None:
            self._threads[old.agent_thread_id] = replace(old, archived_at=self._clock())
        new = self._open(agent_id)
        if old is not None:
            for key, session in self._sessions.items():
                if session.agent_thread_id == old.agent_thread_id:
                    self._sessions[key] = replace(session, agent_thread_id=new.agent_thread_id)
        return new

    async def attach_session(
        self, agent_id: str, session_id: str, channel_type: str
    ) -> AgentThread | None:
        _check_channel_type(channel_type)
        thread = await self.get_or_create_active(agent_id)
        if thread is None:
            return None
        existing = self._sessions.get(session_id)
        if existing is None and channel_type == "web" and any(
            s.channel_type == "web" and s.agent_thread_id == thread.agent_thread_id
            for s in self._sessions.values()
        ):
            return None  # uq_standing_agent_thread_sessions_one_web
        if existing is None:
            self._sessions[session_id] = ThreadSession(
                session_id, thread.agent_thread_id, channel_type, self._clock()
            )
            return thread
        bound = self._threads[existing.agent_thread_id]
        if bound.agent_id != agent_id:
            return None
        if bound.archived_at is not None:
            # 회전과 경합해 보관된 스레드에 남은 행 -- 활성 스레드로 옮긴다(Postgres 와 같다).
            self._sessions[session_id] = replace(existing, agent_thread_id=thread.agent_thread_id)
            return thread
        return bound

    async def thread_for_session(self, session_id: str) -> AgentThread | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        thread = self._threads.get(session.agent_thread_id)
        return thread if thread is not None and thread.archived_at is None else None

    async def list_threads(self, agent_id: str) -> list[AgentThread]:
        return sorted(
            (t for t in self._threads.values() if t.agent_id == agent_id),
            key=lambda t: t.created_at,
        )

    async def list_sessions(self, agent_thread_id: str) -> list[ThreadSession]:
        return sorted(
            (s for s in self._sessions.values() if s.agent_thread_id == agent_thread_id),
            key=lambda s: (s.attached_at, s.session_id),
        )

    async def append_turn(
        self,
        agent_thread_id: str,
        session_id: str,
        channel_type: str,
        role: str,
        content: str,
        *,
        idem_key: str | None = None,
    ) -> bool:
        _check_turn(channel_type, role, content)
        if agent_thread_id not in self._threads:
            raise LookupError(f"unknown agent thread: {agent_thread_id}")
        if idem_key is not None:
            key = (agent_thread_id, session_id, role, idem_key)
            if key in self._idem:
                return False
            self._idem.add(key)
        self._turns.append(
            ThreadTurn(
                turn_id=self._next_turn_id,
                agent_thread_id=agent_thread_id,
                session_id=session_id,
                channel_type=channel_type,
                role=role,
                content=content,
                created_at=self._clock(),
            )
        )
        self._next_turn_id += 1
        return True

    async def recent_turns(self, agent_thread_id: str, *, limit: int) -> list[ThreadTurn]:
        mine = [t for t in self._turns if t.agent_thread_id == agent_thread_id]
        return mine[-limit:] if limit > 0 else []

    async def active(self, agent_id: str) -> AgentThread | None:
        return self._active(agent_id)

    async def get_thread(self, agent_id: str, agent_thread_id: str) -> AgentThread | None:
        thread = self._threads.get(agent_thread_id)
        return thread if thread is not None and thread.agent_id == agent_id else None

    async def detach_session(self, agent_id: str, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if session is None or self._threads[session.agent_thread_id].agent_id != agent_id:
            return False
        del self._sessions[session_id]
        return True

    async def turns_after(
        self, agent_thread_id: str, *, after: TurnCursor, limit: int
    ) -> list[tuple[TurnCursor, ThreadTurn]]:
        rows = [
            (TurnCursor(turn.turn_id, turn.turn_id), turn)
            for turn in self._turns
            if turn.agent_thread_id == agent_thread_id
        ]
        return [row for row in rows if row[0] > after][: max(0, limit)]


_THREAD_COLUMNS = "agent_thread_id, agent_id, created_at, archived_at"


def _thread(row: Any) -> AgentThread:
    return AgentThread(row.agent_thread_id, row.agent_id, row.created_at, row.archived_at)


class PostgresAgentThreadStore:
    def __init__(
        self,
        session_factory: Callable[[], Awaitable[Any]],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    # 살아 있는 에이전트에만 연다. 부분 unique 인덱스에 지면 아무것도 쓰지 않는다.
    _OPEN = f"""
        INSERT INTO standing_agent_threads (agent_thread_id, agent_id, created_at)
        SELECT :agent_thread_id, agent_id, :now
        FROM standing_agents
        WHERE agent_id = :agent_id AND deleted_at IS NULL
        ON CONFLICT (agent_id) WHERE archived_at IS NULL DO NOTHING
        RETURNING {_THREAD_COLUMNS}
    """
    _ACTIVE = f"""
        SELECT {_THREAD_COLUMNS} FROM standing_agent_threads
        WHERE agent_id = :agent_id AND archived_at IS NULL
    """

    async def get_or_create_active(self, agent_id: str) -> AgentThread | None:
        async with await self._session_factory() as session:
            async with session.begin():
                row = (await session.execute(text(self._ACTIVE), {"agent_id": agent_id})).first()
                if row is not None:
                    return _thread(row)
                row = (
                    await session.execute(
                        text(self._OPEN),
                        {
                            "agent_thread_id": new_agent_thread_id(),
                            "agent_id": agent_id,
                            "now": self._clock(),
                        },
                    )
                ).first()
            if row is not None:
                return _thread(row)
        # 졌다(동시에 연 쪽이 이겼다) 또는 에이전트가 없다. 새 문장이 이긴 쪽을 본다.
        return await self._read_active(agent_id)

    async def rotate(self, agent_id: str) -> AgentThread | None:
        now = self._clock()
        async with await self._session_factory() as session:
            async with session.begin():
                # 살아 있는 에이전트인지 먼저 -- 죽은 에이전트의 스레드를 보관하지 않는다.
                live = (
                    await session.execute(
                        text(
                            "SELECT 1 FROM standing_agents"
                            " WHERE agent_id = :agent_id AND deleted_at IS NULL"
                        ),
                        {"agent_id": agent_id},
                    )
                ).first()
                if live is None:
                    return None
                old = (
                    await session.execute(
                        text(
                            """
                            UPDATE standing_agent_threads SET archived_at = :now
                            WHERE agent_id = :agent_id AND archived_at IS NULL
                            RETURNING agent_thread_id
                            """
                        ),
                        {"agent_id": agent_id, "now": now},
                    )
                ).first()
                new = (
                    await session.execute(
                        text(self._OPEN),
                        {
                            "agent_thread_id": new_agent_thread_id(),
                            "agent_id": agent_id,
                            "now": now,
                        },
                    )
                ).first()
                if new is None:
                    # 동시에 회전한 쪽이 이미 새 스레드를 열고 커밋했다. 우리 UPDATE 는
                    # 그 커밋을 기다린 뒤 0행이 됐으므로 바꾼 것이 없다 -- 회전은 한 번이다.
                    new_thread = None
                else:
                    new_thread = _thread(new)
                    if old is not None:
                        await session.execute(
                            text(
                                """
                                UPDATE standing_agent_thread_sessions
                                SET agent_thread_id = :new_id
                                WHERE agent_thread_id = :old_id
                                """
                            ),
                            {"new_id": new_thread.agent_thread_id, "old_id": old.agent_thread_id},
                        )
        return new_thread if new_thread is not None else await self._read_active(agent_id)

    async def attach_session(
        self, agent_id: str, session_id: str, channel_type: str
    ) -> AgentThread | None:
        _check_channel_type(channel_type)
        thread = await self.get_or_create_active(agent_id)
        if thread is None:
            return None
        try:
            return await self._attach(agent_id, thread, session_id, channel_type)
        except IntegrityError as error:
            if "uq_standing_agent_thread_sessions_one_web" in str(error):
                return None
            raise

    async def _attach(
        self, agent_id: str, thread: AgentThread, session_id: str, channel_type: str
    ) -> AgentThread | None:
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        INSERT INTO standing_agent_thread_sessions
                            (session_id, agent_thread_id, channel_type, attached_at)
                        VALUES (:session_id, :agent_thread_id, :channel_type, :now)
                        ON CONFLICT (session_id) DO NOTHING
                        """
                    ),
                    {
                        "session_id": session_id,
                        "agent_thread_id": thread.agent_thread_id,
                        "channel_type": channel_type,
                        "now": self._clock(),
                    },
                )
                # 회전이 커밋되기 직전에 옛 활성 스레드를 읽고 붙은 행은 보관된 스레드에 남는다.
                # 같은 에이전트의 보관 스레드에 붙은 세션이면 활성 스레드로 옮긴다. 다른
                # 에이전트의 행은 건드리지 않는다(아래에서 None).
                await session.execute(
                    text(
                        """
                        UPDATE standing_agent_thread_sessions s
                        SET agent_thread_id = :agent_thread_id
                        FROM standing_agent_threads t
                        WHERE s.session_id = :session_id
                          AND t.agent_thread_id = s.agent_thread_id
                          AND t.agent_id = :agent_id
                          AND t.archived_at IS NOT NULL
                        """
                    ),
                    {
                        "session_id": session_id,
                        "agent_thread_id": thread.agent_thread_id,
                        "agent_id": agent_id,
                    },
                )
                row = (
                    await session.execute(
                        text(
                            f"""
                            SELECT {", ".join("t." + c for c in _THREAD_COLUMNS.split(", "))}
                            FROM standing_agent_thread_sessions s
                            JOIN standing_agent_threads t USING (agent_thread_id)
                            WHERE s.session_id = :session_id
                            """
                        ),
                        {"session_id": session_id},
                    )
                ).first()
        if row is None or row.agent_id != agent_id:
            return None
        return _thread(row)

    async def thread_for_session(self, session_id: str) -> AgentThread | None:
        async with await self._session_factory() as session:
            row = (
                await session.execute(
                    text(
                        f"""
                        SELECT {", ".join("t." + c for c in _THREAD_COLUMNS.split(", "))}
                        FROM standing_agent_thread_sessions s
                        JOIN standing_agent_threads t USING (agent_thread_id)
                        WHERE s.session_id = :session_id AND t.archived_at IS NULL
                        """
                    ),
                    {"session_id": session_id},
                )
            ).first()
        return _thread(row) if row is not None else None

    async def list_threads(self, agent_id: str) -> list[AgentThread]:
        async with await self._session_factory() as session:
            result = await session.execute(
                text(
                    f"SELECT {_THREAD_COLUMNS} FROM standing_agent_threads"
                    " WHERE agent_id = :agent_id ORDER BY created_at, agent_thread_id"
                ),
                {"agent_id": agent_id},
            )
            return [_thread(row) for row in result]

    async def list_sessions(self, agent_thread_id: str) -> list[ThreadSession]:
        async with await self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT session_id, agent_thread_id, channel_type, attached_at
                    FROM standing_agent_thread_sessions
                    WHERE agent_thread_id = :agent_thread_id
                    ORDER BY attached_at, session_id
                    """
                ),
                {"agent_thread_id": agent_thread_id},
            )
            return [
                ThreadSession(r.session_id, r.agent_thread_id, r.channel_type, r.attached_at)
                for r in result
            ]

    async def append_turn(
        self,
        agent_thread_id: str,
        session_id: str,
        channel_type: str,
        role: str,
        content: str,
        *,
        idem_key: str | None = None,
    ) -> bool:
        _check_turn(channel_type, role, content)
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        """
                        INSERT INTO standing_agent_thread_turns
                            (agent_thread_id, session_id, channel_type, role, content,
                             idem_key, created_at)
                        VALUES (:agent_thread_id, :session_id, :channel_type, :role, :content,
                                :idem_key, :now)
                        ON CONFLICT (agent_thread_id, session_id, role, idem_key)
                            WHERE idem_key IS NOT NULL DO NOTHING
                        RETURNING turn_id
                        """
                    ),
                    {
                        "agent_thread_id": agent_thread_id,
                        "session_id": session_id,
                        "channel_type": channel_type,
                        "role": role,
                        "content": content,
                        "idem_key": idem_key,
                        "now": self._clock(),
                    },
                )
                return result.first() is not None

    async def recent_turns(self, agent_thread_id: str, *, limit: int) -> list[ThreadTurn]:
        if limit <= 0:
            return []
        async with await self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT turn_id, agent_thread_id, session_id, channel_type, role,
                           content, created_at
                    FROM standing_agent_thread_turns
                    WHERE agent_thread_id = :agent_thread_id
                    ORDER BY turn_id DESC
                    LIMIT :limit
                    """
                ),
                {"agent_thread_id": agent_thread_id, "limit": limit},
            )
            rows = list(result)
        return [
            ThreadTurn(
                turn_id=r.turn_id,
                agent_thread_id=r.agent_thread_id,
                session_id=r.session_id,
                channel_type=r.channel_type,
                role=r.role,
                content=r.content,
                created_at=r.created_at,
            )
            for r in reversed(rows)
        ]

    async def active(self, agent_id: str) -> AgentThread | None:
        return await self._read_active(agent_id)

    async def get_thread(self, agent_id: str, agent_thread_id: str) -> AgentThread | None:
        async with await self._session_factory() as session:
            row = (
                await session.execute(
                    text(
                        f"SELECT {_THREAD_COLUMNS} FROM standing_agent_threads"
                        " WHERE agent_id = :agent_id AND agent_thread_id = :agent_thread_id"
                    ),
                    {"agent_id": agent_id, "agent_thread_id": agent_thread_id},
                )
            ).first()
        return _thread(row) if row is not None else None

    async def detach_session(self, agent_id: str, session_id: str) -> bool:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        """
                        DELETE FROM standing_agent_thread_sessions s
                        USING standing_agent_threads t
                        WHERE s.session_id = :session_id
                          AND t.agent_thread_id = s.agent_thread_id
                          AND t.agent_id = :agent_id
                        """
                    ),
                    {"session_id": session_id, "agent_id": agent_id},
                )
        return bool(result.rowcount)

    async def turns_after(
        self, agent_thread_id: str, *, after: TurnCursor, limit: int
    ) -> list[tuple[TurnCursor, ThreadTurn]]:
        if limit <= 0:
            return []
        async with await self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT xact_id::text AS position, turn_id, agent_thread_id, session_id,
                           channel_type, role, content, created_at
                    FROM standing_agent_thread_turns
                    WHERE agent_thread_id = :agent_thread_id
                      AND xact_id < pg_snapshot_xmin(pg_current_snapshot())
                      AND (xact_id, turn_id) > (CAST(:position AS xid8), :turn_id)
                    ORDER BY xact_id, turn_id
                    LIMIT :limit
                    """
                ),
                {
                    "agent_thread_id": agent_thread_id,
                    "position": after.position,
                    "turn_id": after.turn_id,
                    "limit": limit,
                },
            )
            rows = result.all()
        return [
            (
                TurnCursor(int(r.position), r.turn_id),
                ThreadTurn(
                    turn_id=r.turn_id,
                    agent_thread_id=r.agent_thread_id,
                    session_id=r.session_id,
                    channel_type=r.channel_type,
                    role=r.role,
                    content=r.content,
                    created_at=r.created_at,
                ),
            )
            for r in rows
        ]

    async def _read_active(self, agent_id: str) -> AgentThread | None:
        async with await self._session_factory() as session:
            row = (await session.execute(text(self._ACTIVE), {"agent_id": agent_id})).first()
        return _thread(row) if row is not None else None

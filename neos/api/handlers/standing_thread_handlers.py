"""상시 에이전트 스레드 API -- 트랙 Q8c (docs/Q8_CROSS_CHANNEL_THREAD_DESIGN_261005.md §9).

소유자가 에이전트의 스레드를 보고(활성 · 보관 · 턴 피드), 새로 시작하고(회전), 붙은 세션을 뗀다.

- 전부 `resolve_agent` 를 거친다. 남의 에이전트도, 남의 스레드 id 도 404 다(존재를 확인해
  주지 않는다). 남의 세션을 떼려 해도 404 다
- 읽기는 부작용이 없다 -- `GET .../thread` 는 활성 스레드가 없으면 열지 않고 `thread: null` 이다
- 피드 커서는 `(xact_id, turn_id)` 를 감싼 불투명 문자열이다. 읽을 수 없으면 422

`standing_agents.enabled` 와 `standing_agents.threads.enabled` 가 둘 다 켜져야 `main.py` 가
마운트한다. 꺼져 있으면 라우트가 **없다**.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel

from neos.api.dependencies.auth import get_current_user
from neos.api.handlers.standing_agent_handlers import get_standing_agent_store
from neos.database.connection import db_manager
from neos.database.models import User
from neos.standing.channel_threads import WEB, conversation_id_of, web_session_id
from neos.standing.models import StandingAgent
from neos.standing.resolve import resolve_agent
from neos.standing.store import StandingAgentStore
from neos.standing.threads import (
    TURN_FEED_START,
    AgentThread,
    AgentThreadStore,
    PostgresAgentThreadStore,
    ThreadSession,
    TurnCursor,
    resolve_agent_thread,
    rotate_agent_thread,
)

router = APIRouter(prefix="/standing-agents", tags=["Standing Agent Threads"])

#: 피드 한 쪽의 상한. 활동 피드(Q13d)와 같다.
MAX_TURN_LIMIT = 500


def get_thread_store() -> AgentThreadStore:
    return PostgresAgentThreadStore(db_manager.get_session)


class ConversationPort(Protocol):
    """웹 에이전트 대화가 쓰는 채팅 대화 연산 셋(Q8d)."""

    async def owned(self, user_id: str, conversation_id: str) -> bool:
        """살아 있는(지워지지 않은) 이 사용자의 대화인가."""
        ...

    async def create(self, user_id: str, title: str) -> str: ...

    async def delete(self, conversation_id: str) -> None: ...


class ChatServiceConversations:
    async def owned(self, user_id: str, conversation_id: str) -> bool:
        from neos.api.services.chat_service import ChatService

        conversation = await ChatService.get_conversation(conversation_id)
        return bool(
            conversation
            and conversation.get("user_id") == user_id
            and conversation.get("status") != "deleted"
        )

    async def create(self, user_id: str, title: str) -> str:
        from neos.api.services.chat_service import ChatService

        created = await ChatService.create_conversation(
            user_id=user_id, title=title, metadata={"standing_agent_conversation": True}
        )
        return str(created["conversation_id"])

    async def delete(self, conversation_id: str) -> None:
        from neos.api.services.chat_service import ChatService

        await ChatService.delete_conversation(conversation_id)


def get_conversation_port() -> ConversationPort:
    return ChatServiceConversations()


class ThreadOut(BaseModel):
    agent_thread_id: str
    agent_id: str
    created_at: datetime
    archived_at: datetime | None = None


class SessionOut(BaseModel):
    session_id: str
    channel_type: str
    attached_at: datetime


class ActiveThreadOut(BaseModel):
    #: 활성 스레드. 아직 연 적이 없으면 null -- 읽기는 열지 않는다.
    thread: ThreadOut | None
    sessions: list[SessionOut]


class WebConversationOut(BaseModel):
    conversation_id: str
    agent_thread_id: str
    #: 이번 요청이 새로 만들었는가. 아니면 이미 있던 에이전트 대화다.
    created: bool


class TurnOut(BaseModel):
    turn_id: int
    session_id: str
    channel_type: str
    role: str
    content: str
    created_at: datetime


class TurnPageOut(BaseModel):
    turns: list[TurnOut]
    #: 다음 요청의 `after`. 빈 쪽이면 받은 커서 그대로다.
    next: str


def _thread_out(thread: AgentThread) -> ThreadOut:
    return ThreadOut(
        agent_thread_id=thread.agent_thread_id,
        agent_id=thread.agent_id,
        created_at=thread.created_at,
        archived_at=thread.archived_at,
    )


def _session_out(session: ThreadSession) -> SessionOut:
    return SessionOut(
        session_id=session.session_id,
        channel_type=session.channel_type,
        attached_at=session.attached_at,
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")


async def _agent(agents: StandingAgentStore, owner_id: str, agent_id: str) -> StandingAgent:
    agent = await resolve_agent(agents, owner_id, agent_id)
    if agent is None:
        raise _not_found()
    return agent


@router.get("/{agent_id}/thread", response_model=ActiveThreadOut)
async def get_active_thread(
    agent_id: str,
    current_user: User = Depends(get_current_user),
    agents: StandingAgentStore = Depends(get_standing_agent_store),
    threads: AgentThreadStore = Depends(get_thread_store),
) -> ActiveThreadOut:
    agent = await _agent(agents, current_user.user_id, agent_id)
    thread = await threads.active(agent.agent_id)
    if thread is None:
        return ActiveThreadOut(thread=None, sessions=[])
    sessions = await threads.list_sessions(thread.agent_thread_id)
    return ActiveThreadOut(
        thread=_thread_out(thread), sessions=[_session_out(s) for s in sessions]
    )


@router.get("/{agent_id}/threads", response_model=list[ThreadOut])
async def list_agent_threads(
    agent_id: str,
    current_user: User = Depends(get_current_user),
    agents: StandingAgentStore = Depends(get_standing_agent_store),
    threads: AgentThreadStore = Depends(get_thread_store),
) -> list[ThreadOut]:
    """보관 포함, 연 순서대로. 처음부터 배열이다(여러 프로젝트로 늘릴 때 깨지지 않게)."""
    agent = await _agent(agents, current_user.user_id, agent_id)
    return [_thread_out(thread) for thread in await threads.list_threads(agent.agent_id)]


@router.get("/{agent_id}/threads/{agent_thread_id}/turns", response_model=TurnPageOut)
async def get_thread_turns(
    agent_id: str,
    agent_thread_id: str,
    after: str | None = Query(None, description="직전 응답의 `next`"),
    limit: int = Query(100, ge=1, le=MAX_TURN_LIMIT),
    current_user: User = Depends(get_current_user),
    agents: StandingAgentStore = Depends(get_standing_agent_store),
    threads: AgentThreadStore = Depends(get_thread_store),
) -> TurnPageOut:
    try:
        cursor = TurnCursor.decode(after) if after else TURN_FEED_START
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    agent = await _agent(agents, current_user.user_id, agent_id)
    if await threads.get_thread(agent.agent_id, agent_thread_id) is None:
        raise _not_found()
    rows = await threads.turns_after(agent_thread_id, after=cursor, limit=limit)
    last = rows[-1][0] if rows else cursor
    return TurnPageOut(
        turns=[
            TurnOut(
                turn_id=turn.turn_id,
                session_id=turn.session_id,
                channel_type=turn.channel_type,
                role=turn.role,
                content=turn.content,
                created_at=turn.created_at,
            )
            for _, turn in rows
        ],
        next=last.encode(),
    )


@router.post("/{agent_id}/thread/rotate", response_model=ThreadOut)
async def rotate_thread(
    agent_id: str,
    current_user: User = Depends(get_current_user),
    agents: StandingAgentStore = Depends(get_standing_agent_store),
    threads: AgentThreadStore = Depends(get_thread_store),
) -> ThreadOut:
    """새로 시작 -- 채널의 `/new` 와 같다. 에이전트 상태는 보지 않는다(새로 시작은 일을 만들지 않는다)."""
    agent = await _agent(agents, current_user.user_id, agent_id)
    thread = await rotate_agent_thread(threads, agent)
    if thread is None:  # 방금 지워졌다
        raise _not_found()
    return _thread_out(thread)


@router.delete(
    "/{agent_id}/thread/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def detach_thread_session(
    agent_id: str,
    session_id: str,
    current_user: User = Depends(get_current_user),
    agents: StandingAgentStore = Depends(get_standing_agent_store),
    threads: AgentThreadStore = Depends(get_thread_store),
) -> Response:
    """세션 떼기. 그 채널의 다음 DM 은 붙이기 규칙(§5)을 다시 거쳐 **다시 붙는다** -- 떼기는
    잘못 붙은 세션을 정리하는 것이지 채널을 끄는 스위치가 아니다."""
    agent = await _agent(agents, current_user.user_id, agent_id)
    if not await threads.detach_session(agent.agent_id, session_id):
        raise _not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{agent_id}/thread/web-conversation", response_model=WebConversationOut)
async def open_web_conversation(
    agent_id: str,
    response: Response,
    current_user: User = Depends(get_current_user),
    agents: StandingAgentStore = Depends(get_standing_agent_store),
    threads: AgentThreadStore = Depends(get_thread_store),
    conversations: ConversationPort = Depends(get_conversation_port),
) -> WebConversationOut:
    """웹 "에이전트 대화"를 돌려준다 -- 에이전트당 하나(결정 Q8-3, 094). 없으면 만든다(201).

    메시지 전송은 기존 `/chat/conversations/{id}/messages/stream` 을 그대로 쓴다. 이 대화가
    스레드에 붙어 있으면 파이프라인이 이력을 스레드 창으로 바꾼다. 소유자가 웹에서 그 대화를
    지웠으면 세션을 떼고 새로 만든다.
    """
    agent = await _agent(agents, current_user.user_id, agent_id)
    thread = await resolve_agent_thread(threads, agent)
    if thread is None:  # 방금 지워졌다
        raise _not_found()

    existing = await _live_web_conversation(threads, conversations, agent, thread, current_user)
    if existing is not None:
        return WebConversationOut(
            conversation_id=existing, agent_thread_id=thread.agent_thread_id, created=False
        )

    conversation_id = await conversations.create(current_user.user_id, agent.name)
    attached = await threads.attach_session(
        agent.agent_id, web_session_id(conversation_id), WEB
    )
    if attached is None:
        # 동시에 만든 쪽이 이겼다(094). 우리가 만든 대화를 지우고 이긴 쪽을 돌려준다.
        await conversations.delete(conversation_id)
        winner = await _live_web_conversation(
            threads, conversations, agent, thread, current_user
        )
        if winner is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="web_conversation_race")
        return WebConversationOut(
            conversation_id=winner, agent_thread_id=thread.agent_thread_id, created=False
        )
    response.status_code = status.HTTP_201_CREATED
    return WebConversationOut(
        conversation_id=conversation_id,
        agent_thread_id=attached.agent_thread_id,
        created=True,
    )


async def _live_web_conversation(
    threads: AgentThreadStore,
    conversations: ConversationPort,
    agent: StandingAgent,
    thread: AgentThread,
    current_user: User,
) -> str | None:
    """활성 스레드에 붙은 웹 대화 중 살아 있는 것. 지워진 대화의 세션은 떼어 낸다."""
    for session in await threads.list_sessions(thread.agent_thread_id):
        conversation_id = conversation_id_of(session.session_id)
        if session.channel_type != WEB or conversation_id is None:
            continue
        if await conversations.owned(current_user.user_id, conversation_id):
            return conversation_id
        await threads.detach_session(agent.agent_id, session.session_id)
    return None

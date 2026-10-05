"""채널 대화를 에이전트 스레드에 잇는다 -- 트랙 Q8b (docs/Q8_CROSS_CHANNEL_THREAD_DESIGN_261005.md §5·§6·§8).

게이트웨이는 이 모듈을 부르기만 한다. 붙이는 규칙 · 창 조립 · 턴 기록 · 회전이 전부 여기 있다.

- **붙는 세션(§5):** 플래그 둘(`standing_agents.enabled` · `threads.enabled`) · 어댑터가 판정한
  `metadata["is_dm"] is True`(없으면 DM 이 아니다) · `channels.principals` 로 소유자에 매핑된
  발신자 · 그 소유자의 `active` 에이전트. 코딩 바인딩 세션은 게이트웨이가 이 경로로 보내지 않는다
- **창(§6):** 이번 턴을 쓰기 **전에** 읽는다 -- 이번 턴은 `query` 가 나른다(웹 파이프라인과 같다).
  크기는 `chat.max_history_messages`. 다른 채널에서 온 턴에는 `[slack]` 같은 표지를 붙인다
- **스레드는 대화를 막지 못한다(§8).** 무엇이 실패해도 던지지 않고, 경고 한 줄과
  `standing_thread_failures_total{op}` 하나를 남긴 채 스레드 없이 대화한다
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from neos.standing.models import StandingAgentStatus
from neos.standing.resolve import resolve_agent
from neos.standing.store import StandingAgentStore
from neos.standing.threads import AgentThreadStore, rotate_agent_thread, thread_window

logger = logging.getLogger(__name__)

#: 자동으로 붙을 수 있는 채널. 웹은 소유자가 지정한 대화 하나만 붙는다(Q8d, `web_session_id`).
CHANNEL_TYPES = frozenset({"slack", "discord", "telegram"})
WEB = "web"


def web_session_id(conversation_id: str) -> str:
    """웹 에이전트 대화의 세션 id. 채널 키(`v2:`)와 이름 공간이 겹치지 않는다."""
    return f"{WEB}:{conversation_id}"


def conversation_id_of(session_id: str) -> str | None:
    prefix = f"{WEB}:"
    return session_id[len(prefix):] if session_id.startswith(prefix) else None


def _history(window: list[Any], channel_type: str) -> list[dict[str, Any]]:
    """웹 채팅과 같은 모양. 다른 채널에서 온 턴에는 `[slack]` 같은 표지를 붙인다(§6)."""
    return [
        {
            "role": turn.role,
            "content": (
                turn.content
                if turn.channel_type == channel_type
                else f"[{turn.channel_type}] {turn.content}"
            ),
            "timestamp": turn.created_at.isoformat(),
        }
        for turn in window
    ]


@dataclass(frozen=True, slots=True)
class ChannelThreadTurn:
    """열린 턴. 게이트웨이가 워크플로우 뒤에 `close_turn` 으로 닫는다."""

    agent_thread_id: str
    session_id: str
    channel_type: str
    idem_key: str | None
    #: 웹 채팅과 같은 모양의 `chat_history` -- 이번 턴은 들어 있지 않다.
    history: list[dict[str, Any]] = field(default_factory=list)


def _enabled() -> bool:
    from neos.config.settings import settings

    standing = settings.config.standing_agents
    return bool(standing.enabled and standing.threads.enabled)


def _window_limit() -> int:
    from neos.config.settings import settings

    return int(settings.MAX_HISTORY_MESSAGES)


def mapped_owner(message: Any) -> str | None:
    """principals 로 매핑된 NEOS 사용자. 매핑이 없거나 principals 가 비어 있으면 None.

    게이트웨이의 `user_id` 를 쓰지 않는다 -- principals 가 비면 그것은 매핑되지 않은 값이다.
    """
    from neos.api.channels.principals import (
        platform_user_id_from_message,
        resolve_channel_principal,
    )
    from neos.config.settings import settings

    channels = settings.config.channels
    if not channels.principals:
        return None
    return resolve_channel_principal(
        platform=message.channel_type,
        platform_user_id=platform_user_id_from_message(message),
        channels=channels,
    )


def _is_dm(message: Any) -> bool:
    return (message.metadata or {}).get("is_dm") is True


def _idem_key(message: Any) -> str | None:
    value = (message.metadata or {}).get("idempotency_key")
    return str(value) if value else None


def _count_failure(op: str) -> None:
    try:
        from neos.observability.metrics import metrics

        metrics.standing_thread_failures_total.labels(op=op).inc()
    except Exception:  # noqa: BLE001 -- 계측 실패가 대화를 막지 않는다
        logger.debug("standing thread failure counter unavailable", exc_info=True)


class ChannelAgentThreads:
    """게이트웨이가 쥐는 창구. 저장소 둘(에이전트 · 스레드)을 받는다."""

    def __init__(self, agents: StandingAgentStore, threads: AgentThreadStore) -> None:
        self._agents = agents
        self._threads = threads

    async def open_turn(self, message: Any, user_text: str) -> ChannelThreadTurn | None:
        """붙는 세션이면 창을 읽고 사용자 턴을 쓴다. 아니면(또는 실패하면) None."""
        if not _enabled():
            return None
        if message.channel_type not in CHANNEL_TYPES or not _is_dm(message):
            return None
        owner = mapped_owner(message)
        if not owner:
            return None
        try:
            agent = await resolve_agent(self._agents, owner)
            if agent is None or agent.status is not StandingAgentStatus.ACTIVE:
                return None
            thread = await self._threads.attach_session(
                agent.agent_id, message.session_id, message.channel_type
            )
            if thread is None:
                return None
            window = await thread_window(
                self._threads, thread.agent_thread_id, limit=_window_limit()
            )
            idem = _idem_key(message)
            await self._threads.append_turn(
                thread.agent_thread_id,
                message.session_id,
                message.channel_type,
                "user",
                user_text,
                idem_key=idem,
            )
        except Exception:  # noqa: BLE001 -- 스레드는 대화를 막지 못한다
            logger.warning("standing thread open failed session=%s", message.session_id, exc_info=True)
            _count_failure("open")
            return None
        return ChannelThreadTurn(
            agent_thread_id=thread.agent_thread_id,
            session_id=message.session_id,
            channel_type=message.channel_type,
            idem_key=idem,
            history=_history(window, message.channel_type),
        )

    async def open_web_turn(
        self,
        *,
        conversation_id: str,
        user_id: str,
        user_text: str,
        idem_key: str | None,
    ) -> ChannelThreadTurn | None:
        """웹 에이전트 대화의 턴(Q8d). 그 대화가 이 사용자의 `active` 에이전트 스레드에 붙어
        있을 때만 연다. 대화 소유 검사는 파이프라인이 이미 했다(`get_owned_conversation`)."""
        if not _enabled():
            return None
        session_id = web_session_id(conversation_id)
        try:
            thread = await self._threads.thread_for_session(session_id)
            if thread is None:
                return None
            agent = await resolve_agent(self._agents, user_id, thread.agent_id)
            if agent is None or agent.status is not StandingAgentStatus.ACTIVE:
                return None
            window = await thread_window(
                self._threads, thread.agent_thread_id, limit=_window_limit()
            )
            await self._threads.append_turn(
                thread.agent_thread_id, session_id, WEB, "user", user_text, idem_key=idem_key
            )
        except Exception:  # noqa: BLE001 -- 스레드는 대화를 막지 못한다
            logger.warning("standing thread open failed session=%s", session_id, exc_info=True)
            _count_failure("open")
            return None
        return ChannelThreadTurn(
            agent_thread_id=thread.agent_thread_id,
            session_id=session_id,
            channel_type=WEB,
            idem_key=idem_key,
            history=_history(window, WEB),
        )

    async def close_turn(self, turn: ChannelThreadTurn, reply: str) -> None:
        """사용자가 실제로 받은 답을 assistant 턴으로. 빈 답은 쓰지 않는다."""
        if not reply or not reply.strip():
            return
        try:
            await self._threads.append_turn(
                turn.agent_thread_id,
                turn.session_id,
                turn.channel_type,
                "assistant",
                reply,
                idem_key=turn.idem_key,
            )
        except Exception:  # noqa: BLE001
            logger.warning("standing thread close failed session=%s", turn.session_id, exc_info=True)
            _count_failure("close")

    async def rotate_for_session(self, message: Any) -> bool:
        """`/new` -- 이 세션이 소유자 에이전트의 스레드에 붙어 있으면 회전하고 True.

        회전은 에이전트 단위다: 붙은 모든 세션의 맥락이 새로 시작한다(설계 §7). 에이전트
        상태는 보지 않는다 -- 새로 시작하는 것은 대화를 만드는 일이 아니다.
        """
        if not _enabled() or not _is_dm(message):
            return False
        owner = mapped_owner(message)
        if not owner:
            return False
        try:
            thread = await self._threads.thread_for_session(message.session_id)
            if thread is None:
                return False
            agent = await resolve_agent(self._agents, owner)
            if agent is None or agent.agent_id != thread.agent_id:
                return False
            return await rotate_agent_thread(self._threads, agent) is not None
        except Exception:  # noqa: BLE001
            logger.warning("standing thread rotate failed session=%s", message.session_id, exc_info=True)
            _count_failure("rotate")
            return False


def build_channel_agent_threads(session_factory: Any) -> ChannelAgentThreads:
    """API 프로세스의 배선(`main.py`). 플래그는 호출 때마다 읽으므로 늘 만든다."""
    from neos.standing.store import PostgresStandingAgentStore
    from neos.standing.threads import PostgresAgentThreadStore

    return ChannelAgentThreads(
        PostgresStandingAgentStore(session_factory),
        PostgresAgentThreadStore(session_factory),
    )

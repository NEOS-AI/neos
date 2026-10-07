"""채널의 답이 기다리는 에이전트 태스크를 깨운다 -- 트랙 Q9c
(docs/Q9_ASK_AND_WAIT_DESIGN_261005.md §7).

게이트웨이는 `try_answer` 를 부르기만 한다. 무엇이 답인지 · 답을 어떻게 나누는지 ·
재개 · 스레드 기록이 전부 여기 있다.

- **답이 되는 메시지(§7.1):** 플래그(`ask_effective`) · 채널 DM(`metadata["is_dm"] is True`) ·
  principals 로 매핑된 소유자 · 그 소유자의 `active` 에이전트 · 그 에이전트의 대기 질문 ·
  이 세션이 그 에이전트 스레드에 붙어 있거나 **이번에 붙는다**(설계 이탈 1). 명령(`/…`)과
  코딩에 바인딩된 세션은 게이트웨이가 여기로 보내지 않는다.
- **나누기(결정 Q-B):** 질문 알림은 "Answer one line per question, in order." 라고 말하고
  질문에 `1.` `2.` 번호를 단다. 줄 수가 질문 수와 같으면 줄마다(앞 번호는 뗀다), 아니면
  메시지 전체가 모든 질문의 답이다.
- **재개:** Q10b 재개 경로(`CodingRunService.resume_answered`)다. 런은 닫힌 적이 없고, 깨어난
  워커는 같은 런의 최신 체크포인트에서 자기 `ask_user.v1` 을 다시 만난다 -- 이번에는 답이 있다.
- **스레드(설계 이탈 10):** 답이 오면 질문(assistant)과 답(user) 턴을 이 프로세스가 적는다.
  스레드는 대화를 막지 못한다 -- 실패는 경고와 `standing_thread_failures_total{op}` 하나.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from neos.api.channels.base import VOICE_PREFIX, RetryableReply
from neos.standing.asks import PendingAsk, PendingAskStore, ask_effective, count_ask
from neos.standing.models import StandingAgentStatus
from neos.standing.resolve import resolve_agent

logger = logging.getLogger(__name__)

CONFIRMATION = "Answer recorded — resuming."
#: 질문을 찾은 뒤 기록·재개가 실패했다(일시적 DB 오류 등). 대화로 흘리지 않고 다시 보내 달라고 한다.
RESEND = "Could not record your answer — please send it again."
#: 다른 채널에서 같은 질문의 답이 먼저 닿았다. 이 메시지는 대화가 되지 않는다.
ALREADY_ANSWERED = "That question was already answered — the agent is resuming."
_SUMMARY_CHARS = 120
_NUMBERED = re.compile(r"^\s*\d+\s*[.)]\s*")

#: (ask, owner_id, answers, channel_type) -> commit, 또는 답이 되지 못했으면 None.
ResumeFn = Callable[[PendingAsk, str, list[str], str], Awaitable[Any]]


def split_answers(text: str, question_count: int) -> list[str]:
    """결정 Q-B. 줄 수가 질문 수와 같으면 줄마다, 아니면 메시지 전체가 모든 질문의 답."""
    whole = (text or "").strip()
    if question_count <= 1:
        return [whole]
    lines = [line.strip() for line in whole.splitlines() if line.strip()]
    if len(lines) == question_count:
        return [_NUMBERED.sub("", line, count=1).strip() or line for line in lines]
    return [whole] * question_count


def answer_text(message: Any, text: str) -> str:
    """답 값. 전사된 음성(Q15)이면 `"[voice] "` 표지를 뗀다 -- 재개된 도구 호출은 말한 내용만 받는다.

    스레드의 사용자 턴은 이 값이 아니라 전사된 본문 그대로다(Q9 × Q15 통합 결정). 표지는 게이트웨이가
    실제로 전사한 메시지(`metadata["voice"]` 가 있다)에서만 뗀다 -- 타이핑한 "[voice] ..." 는 그대로 답이다.
    """
    if isinstance((message.metadata or {}).get("voice"), dict) and text.startswith(VOICE_PREFIX):
        return text[len(VOICE_PREFIX) :].strip() or text
    return text


def _prompts(questions: Sequence[Any]) -> list[str]:
    return [
        str(item.get("prompt") or "") if isinstance(item, Mapping) else str(item)
        for item in questions
    ]


def confirmation(ask: PendingAsk) -> str:
    """Review Focus 2: 무엇에 대한 답으로 적혔는지 말한다 -- 엉뚱한 말이 답이 됐으면 알아챈다."""
    prompts = _prompts(ask.questions)
    first = prompts[0] if prompts else ""
    if len(first) > _SUMMARY_CHARS:
        first = first[: _SUMMARY_CHARS - 1] + "…"
    more = f" (+{len(prompts) - 1} more)" if len(prompts) > 1 else ""
    return f"{CONFIRMATION}\nQ: {first}{more}"


def question_turn(ask: PendingAsk) -> str:
    """스레드에 남기는 질문 -- 알림과 같은 번호를 단다."""
    prompts = _prompts(ask.questions)
    if len(prompts) == 1:
        return prompts[0]
    return "\n".join(f"{index}. {prompt}" for index, prompt in enumerate(prompts, start=1))


def _enabled() -> bool:
    from neos.config.settings import settings

    return ask_effective(settings.config)


def _count_thread_failure(op: str) -> None:
    try:
        from neos.observability.metrics import metrics

        metrics.standing_thread_failures_total.labels(op=op).inc()
    except Exception:  # noqa: BLE001
        logger.debug("standing thread failure counter unavailable", exc_info=True)


async def _resume_through_run_service(ask, owner_id, answers, channel_type):
    """API 프로세스의 배선 -- Q10b 와 같은 `CodingRunService` 의 wake 를 쓴다."""
    from neos.coding.runtime import coding_run_service

    return await coding_run_service.resume_answered(
        ask_id=ask.ask_id, owner_id=owner_id, answers=answers, channel_type=channel_type
    )


class ChannelAskAnswers:
    """게이트웨이가 쥐는 창구. 저장소 셋(에이전트 · 스레드 · 질문)과 재개 함수를 받는다."""

    def __init__(
        self,
        agents: Any,
        threads: Any,
        asks: PendingAskStore,
        *,
        resume: ResumeFn = _resume_through_run_service,
        enabled: Callable[[], bool] = _enabled,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._agents = agents
        self._threads = threads
        self._asks = asks
        self._resume = resume
        self._enabled = enabled
        self._clock = clock

    async def try_answer(self, message: Any) -> str | None:
        """답이면 확인 문구, 아니면 None(→ 게이트웨이는 지금처럼 대화로 보낸다)."""
        from neos.standing.channel_threads import CHANNEL_TYPES, mapped_owner

        if not self._enabled():
            return None
        if message.channel_type not in CHANNEL_TYPES:
            return None
        if (message.metadata or {}).get("is_dm") is not True:
            return None
        owner = mapped_owner(message)
        if not owner:
            return None
        agent = await resolve_agent(self._agents, owner)
        if agent is None or agent.status is not StandingAgentStatus.ACTIVE:
            return None
        ask = await self._asks.waiting_for_agent(agent.agent_id)
        if ask is None:
            return None
        text = (message.text or "").strip()
        if not text:
            return None
        # 여기부터 질문을 찾았다. 실패는 대화로 흘리지 않는다 -- 흘리면 진짜 답이 채팅이 되고,
        # 질문은 기다리는 채로 남아 소유자의 다음 엉뚱한 DM 이 답이 된다(Q9c 고침 1).
        try:
            thread = await self._threads.attach_session(
                agent.agent_id, message.session_id, message.channel_type
            )
            if thread is None:
                return None
            answers = split_answers(answer_text(message, text), len(ask.questions))
            commit = await self._resume(ask, owner, answers, message.channel_type)
            if commit is None:
                return await self._not_resumed(ask)
        except Exception:  # noqa: BLE001 -- 원인과 상관없이 다시 보내 달라고 한다
            logger.warning("standing ask answer failed ask_id=%s", ask.ask_id, exc_info=True)
            count_ask("answer_failed")
            return RetryableReply(RESEND)
        count_ask("answered")
        await self._record_turns(thread.agent_thread_id, ask, message, text)
        return confirmation(ask)

    async def _not_resumed(self, ask: PendingAsk) -> str | None:
        """재개되지 않았다. 다른 채널의 답이 먼저 닿았으면 그렇게 말한다(대화로 보내지 않는다).
        태스크가 움직였으면(취소 등) None -- 지금처럼 대화로 간다."""
        current = await self._asks.for_call(ask.task_id, ask.run_id, ask.tool_call_id)
        if current is not None and current.status == "answered":
            return ALREADY_ANSWERED
        return None

    async def _record_turns(self, agent_thread_id: str, ask: PendingAsk, message: Any, text: str) -> None:
        from neos.api.channels.session_key import session_key_destination

        asked_in = ask.reply_session_id or message.session_id
        address = session_key_destination(asked_in)
        asked_channel = address[0] if address is not None else message.channel_type
        idem = (message.metadata or {}).get("idempotency_key")
        try:
            await self._threads.append_turn(
                agent_thread_id,
                asked_in,
                asked_channel,
                "assistant",
                question_turn(ask),
                idem_key=f"ask:{ask.ask_id}",
            )
            await self._threads.append_turn(
                agent_thread_id,
                message.session_id,
                message.channel_type,
                "user",
                text,
                idem_key=str(idem) if idem else None,
            )
        except Exception:  # noqa: BLE001 -- 스레드는 대화를 막지 못한다
            logger.warning("standing ask thread turns failed ask_id=%s", ask.ask_id, exc_info=True)
            _count_thread_failure("close")


def build_channel_ask_answers(session_factory: Callable[[], Awaitable[Any]]) -> ChannelAskAnswers:
    """API 프로세스의 배선(`main.py`). 플래그는 호출 때마다 읽으므로 늘 만든다."""
    from neos.standing.asks import PostgresPendingAskStore
    from neos.standing.store import PostgresStandingAgentStore
    from neos.standing.threads import PostgresAgentThreadStore

    return ChannelAskAnswers(
        PostgresStandingAgentStore(session_factory),
        PostgresAgentThreadStore(session_factory),
        PostgresPendingAskStore(session_factory),
    )

"""채널 게이트웨이 (Phase 1 — OpenClaw Channel Gateway)

외부 채널 어댑터로부터 ChannelMessage를 받아 NEOS 워크플로우를 직접 실행하고
최종 응답을 반환한다. HTTP 호출 없이 같은 프로세스 내에서 함수를 직접 호출한다.

채널별 circuit_breaker를 독립적으로 유지하여 특정 채널 장애가 다른 채널에
전파되지 않도록 격리한다.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from neos.workflow.graph import MultiAgentWorkflow

from .base import ChannelMessage, RetryableReply
from .commands import (
    ChannelCommandKind,
    display_name_from_metadata,
    neutralize_untrusted_inline,
    parse_channel_command,
    sender_prefix,
)
from .inflight import SessionInboundPark, SessionInflightLock
from .replies import ChannelOutcome, annotate_status_reply, channel_reply

logger = logging.getLogger(__name__)

_BUSY = channel_reply(ChannelOutcome.DROP, "Already working on this thread.")
_PARKED = channel_reply(ChannelOutcome.PARK, "Parked for next turn.")
_CODE_USAGE = "Usage: /code <task>"
_CODE_DISABLED = "Coding invoke is disabled."
_CODE_NO_OWNER = "Coding owner is not configured."
_NO_OWNER = "Owner is not configured."
_NO_TASK = "No coding task in this thread."
_APPROVAL_NOT_CONFIGURED = "Workflow approval is not configured."
_LEARN_DISABLED = "Learning is disabled."
_LEARN_STAGED = "Lesson staged."
_LEARN_USAGE = "Usage: /learn <text>"
_SESSION_RESET = "Session reset."
_AGENT_THREAD_ROTATED = (
    "Session reset. Your agent's conversation starts fresh on every channel it is attached to."
)
_DRAFT_WORKFLOW = "Working..."
_DRAFT_CODING = "Starting coding task..."
_COMPACT_UNAVAILABLE = "Compact is not available."
_CONTEXT_CLEAR_REQUESTED = "Conversation context clear is requested."
_COST_TRACKED = "Cost is tracked on the task."
_EXPORT_UI = "Transcript export is available in the Code UI."
_UNKNOWN_COMMAND = "Unknown command. Try /help."
# Q15c 음성 거절 문구(설계 §9). 거절이면 워크플로우도 스레드도 돌지 않는다.
_VOICE_TRANSCRIBE_FAILED = "Could not transcribe the voice message."
_VOICE_REPLIES = {
    "too_large": "The voice message is too large to transcribe.",
    "too_long": "The voice message is too long to transcribe (limit: {max_seconds}s).",
    "unsupported_format": "This audio format can't be transcribed.",
    "download_failed": "Could not read the voice message.",
    "empty": "No speech was found in the voice message.",
    "provider_error": _VOICE_TRANSCRIBE_FAILED,
    "timeout": _VOICE_TRANSCRIBE_FAILED,
}
_VOICE_PREFIX = "[voice] "
_CONTROL_LOCK_BYPASS = frozenset(
    {
        ChannelCommandKind.STOP,
        ChannelCommandKind.NEW,
        ChannelCommandKind.APPROVE,
        ChannelCommandKind.DENY,
        ChannelCommandKind.STATUS,
        ChannelCommandKind.COMPACT,
        ChannelCommandKind.CLEAR,
        ChannelCommandKind.COST,
        ChannelCommandKind.EXPORT,
        ChannelCommandKind.DIFF,
        ChannelCommandKind.HELP,
        ChannelCommandKind.LOOP,
        ChannelCommandKind.UNKNOWN,
    }
)


def _loop_state_from_snapshot(snapshot: Any) -> dict[str, Any]:
    if snapshot is None:
        return {}
    checkpoint = getattr(snapshot, "latest_checkpoint", None)
    if checkpoint is None and isinstance(snapshot, dict):
        checkpoint = snapshot.get("latest_checkpoint")
    if checkpoint is None:
        return {}
    loop_state = getattr(checkpoint, "loop_state", None)
    if loop_state is None and isinstance(checkpoint, dict):
        loop_state = checkpoint.get("loop_state")
    return loop_state if isinstance(loop_state, dict) else {}


def _cost_line_from_snapshot(snapshot: Any, task_id: str) -> str:
    loop_state = _loop_state_from_snapshot(snapshot)
    if not loop_state:
        return ""
    cost = loop_state.get("cost_micros")
    inbound = loop_state.get("input_tokens")
    outbound = loop_state.get("output_tokens")
    parts: list[str] = []
    if isinstance(cost, int):
        parts.append(f"cost_micros={cost}")
    if isinstance(inbound, int) or isinstance(outbound, int):
        parts.append(f"tokens={int(inbound or 0)}+{int(outbound or 0)}")
    if not parts:
        return ""
    return f"{task_id} " + " ".join(parts)


async def _read_coding_snapshot(coding: Any, *, task_id: str, owner_id: str) -> Any:
    snapshot_fn = getattr(coding, "snapshot", None)
    if not callable(snapshot_fn):
        return None
    try:
        return await snapshot_fn(task_id=task_id, owner_id=owner_id)
    except TypeError:
        try:
            return await snapshot_fn(task_id, owner_id)
        except Exception:
            return None
    except Exception:
        return None


def _generation_token(message: ChannelMessage, command: Any | None = None) -> str:
    meta = message.metadata or {}
    for key in ("generation_id", "generation"):
        value = str(meta.get(key) or "").strip()
        if value:
            return neutralize_untrusted_inline(value, max_len=80)
    rest = str(getattr(command, "rest", "") or "").strip()
    if rest:
        return neutralize_untrusted_inline(rest, max_len=80)
    return ""


def _sender_label(message: ChannelMessage) -> str:
    from .principals import platform_user_id_from_message

    return sender_prefix(
        platform_user_id_from_message(message),
        display_name_from_metadata(message.metadata, message.channel_type),
    )


def _with_sender_prefix(message: ChannelMessage, text: str) -> str:
    label = _sender_label(message)
    body = text or ""
    if not label:
        return body
    if not body:
        return label
    return f"{label} {body}"


def _mapped_user_id(message: ChannelMessage) -> str | None:
    """대화할 NEOS 사용자. principals 가 있는데 발신자가 매핑되지 않으면 None(`_NO_OWNER`).

    `_run_workflow`·`_run_learn` 과 음성 전사 앞단(Q15c)이 이 함수 하나를 쓴다 — 미매핑 발신자의
    음성은 공급자에 가기 전에 여기서 멈춘다.
    """
    from neos.config.settings import settings

    from .principals import platform_user_id_from_message, resolve_channel_principal

    channels = settings.config.channels
    if not channels.principals:
        return message.user_id
    mapped = resolve_channel_principal(
        platform=message.channel_type,
        platform_user_id=platform_user_id_from_message(message),
        channels=channels,
    )
    return mapped or None


def _count_voice(outcome: str) -> None:
    try:
        from neos.observability.metrics import metrics

        metrics.channel_voice_transcriptions_total.labels(outcome=outcome).inc()
    except Exception:  # noqa: BLE001 -- 계측 실패가 대화를 막지 않는다
        logger.debug("voice transcription counter unavailable", exc_info=True)


def _attachment_bytes(item: dict[str, Any]) -> bytes:
    raw = item.get("bytes")
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw)
    raw = item.get("data")
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw)
    return b""


def _attachment_prompt(message: ChannelMessage) -> str:
    attachments = list((message.metadata or {}).get("attachments") or [])
    if not attachments:
        return ""
    lines = []
    for item in attachments:
        if not isinstance(item, dict):
            continue
        name = neutralize_untrusted_inline(str(item.get("name") or "file")) or "file"
        content_type = str(item.get("content_type") or "application/octet-stream")
        size = len(_attachment_bytes(item))
        lines.append(f"- {name} ({content_type}, {size} bytes)")
    if not lines:
        return ""
    return "\n\nUser attached files:\n" + "\n".join(lines)


def _channel_attachment_blocks(message: ChannelMessage) -> list[dict[str, Any]]:
    from neos.config.settings import settings

    if not settings.config.channels.inbound_media:
        return []
    attachments = list((message.metadata or {}).get("attachments") or [])
    blocks: list[dict[str, Any]] = []
    for item in attachments:
        if not isinstance(item, dict):
            continue
        data = _attachment_bytes(item)
        if not data:
            continue
        mime = str(item.get("content_type") or "application/octet-stream")
        try:
            from neos.services.attachment_blocks import classify

            kind = classify(mime)
        except Exception:
            kind = None
        block: dict[str, Any] = {
            "name": neutralize_untrusted_inline(str(item.get("name") or "file"))
            or "file",
            "content_type": mime,
            "kind": getattr(kind, "value", None),
            "size": len(data),
        }
        kind_name = getattr(kind, "value", None)
        if kind_name == "IMAGE":
            import base64

            block["data_b64"] = base64.b64encode(data).decode("ascii")
        elif kind_name in {"FILE_TEXT", "EXTRACT"}:
            block["text"] = data.decode("utf-8", errors="replace")[:8000]
        blocks.append(block)
    return blocks


class ChannelGateway:
    """
    채널 어댑터 → NEOS 워크플로우 라우팅 게이트웨이

    - 채널별 독립 circuit_breaker 유지
    - multi_agent_workflow.execute_workflow() 직접 호출 (HTTP 우회)
    - channel_source를 초기 state에 포함하여 워크플로우 시작 시점에 올바르게 기록
    """

    _INSTANCE: "ChannelGateway | None" = None

    @classmethod
    def get_instance(cls) -> "ChannelGateway":
        if cls._INSTANCE is None:
            raise RuntimeError("ChannelGateway is not initialized")
        return cls._INSTANCE

    @classmethod
    def set_instance(cls, gateway: "ChannelGateway | None") -> None:
        cls._INSTANCE = gateway

    def register_adapter(self, adapter: Any) -> None:
        channel_type = str(getattr(adapter, "channel_type", "") or "")
        if channel_type:
            self._adapters[channel_type] = adapter

    def has_adapter(self, channel_type: str) -> bool:
        """`send_to_channel` 은 어댑터가 없으면 경고만 남기고 돌아온다. 보낸 것으로
        세려는 쪽(상시 에이전트 알림, 트랙 Q10b)은 이것을 먼저 본다."""
        return channel_type in self._adapters

    async def send_to_channel(
        self,
        channel_type: str,
        channel_id: str,
        content: str,
        *,
        thread_id: str | None = None,
    ) -> None:
        adapter = self._adapters.get(channel_type)
        if adapter is None:
            logger.warning(
                "[ChannelGateway] no adapter registered for channel_type=%s",
                channel_type,
            )
            return
        await adapter.send_response(
            channel_id, content, thread_id=thread_id
        )

    async def _send_start_draft(self, message: ChannelMessage, content: str) -> None:
        from neos.config.settings import settings

        if not settings.config.channels.draft_streaming:
            return
        adapter = self._adapters.get(message.channel_type)
        if adapter is None:
            return
        send_draft = getattr(adapter, "send_draft", None)
        if not callable(send_draft):
            return
        thread_id = (message.metadata or {}).get("thread_id")
        try:
            await send_draft(
                message.channel_id,
                content,
                thread_id=str(thread_id) if thread_id is not None else None,
            )
        except Exception as e:
            logger.warning(
                "[ChannelGateway] send_draft failed channel=%s: %s",
                message.channel_id,
                e,
            )

    def __init__(
        self,
        workflow: "MultiAgentWorkflow",
        *,
        coding: Any | None = None,
        inflight: SessionInflightLock | None = None,
        park: SessionInboundPark | None = None,
        binds: Any | None = None,
        inbound: Any | None = None,
        generations: Any | None = None,
        workflow_approvals: Any | None = None,
        agent_threads: Any | None = None,
        ask_answers: Any | None = None,
    ) -> None:
        self._workflow = workflow
        # Q9c 묻고 기다리기(`neos.standing.ask_answers.ChannelAskAnswers`). 없으면 답을 받지
        # 않는다 -- 플래그는 그쪽이 호출 때마다 읽는다.
        self._ask_answers = ask_answers
        # Q8b 채널 횡단 스레드(`neos.standing.channel_threads.ChannelAgentThreads`). 없으면
        # 스레드가 없다 -- 플래그는 그쪽이 호출 때마다 읽는다.
        self._agent_threads = agent_threads
        self._coding = coding
        self._workflow_approvals = workflow_approvals
        self._workflow_pending: Dict[str, Dict[str, str]] = {}
        self._workflow_reset: set[str] = set()
        self._inflight = inflight or SessionInflightLock()
        self._park = park or SessionInboundPark()
        if binds is None:
            from .session_bind import InMemoryChannelCodingBindStore

            binds = InMemoryChannelCodingBindStore()
        self._binds = binds
        if inbound is None:
            from .inbound_idempotency import InMemoryChannelInboundIdempotencyStore

            inbound = InMemoryChannelInboundIdempotencyStore()
        self._inbound = inbound
        if generations is None:
            from .generation_fence import InMemoryChannelGenerationFenceStore

            generations = InMemoryChannelGenerationFenceStore()
        self._generations = generations
        self._adapters: Dict[str, Any] = {}
        # 채널별 async circuit_breaker (lazy init)
        self._breakers: Dict[str, Any] = {}
        # Process-local /code start dedupe: (session_id, idempotency_key) → task_id.
        # Not durable across processes or restarts. Durable store is source of truth.
        self._code_starts: Dict[tuple[str, str], str] = {}
        ChannelGateway._INSTANCE = self

    def _get_breaker(self, channel_type: str):
        """채널 유형별 async circuit_breaker를 lazy-init하여 반환한다."""
        if channel_type not in self._breakers:
            try:
                from neos.workflow.utils.circuit_breaker import (
                    CircuitBreaker,
                    CircuitBreakerConfig,
                )
                self._breakers[channel_type] = CircuitBreaker(
                    name=f"channel_{channel_type}",
                    config=CircuitBreakerConfig(
                        failure_threshold=3,
                        timeout_seconds=60.0,
                        half_open_max_calls=1,
                    ),
                )
            except Exception as e:
                logger.warning(
                    f"[ChannelGateway] circuit_breaker init failed for {channel_type}: {e} — skipping"
                )
                self._breakers[channel_type] = None
        return self._breakers[channel_type]

    async def dispatch(self, message: ChannelMessage) -> str:
        """
        ChannelMessage를 받아 NEOS 워크플로우를 실행하고 최종 응답 텍스트를 반환한다.

        Args:
            message: 정규화된 채널 메시지

        Returns:
            LLM이 생성한 최종 응답 텍스트. 실패 시 에러 메시지 반환.
        """
        logger.info(
            f"[ChannelGateway] dispatch: channel={message.channel_type}, "
            f"user={message.user_id}, session={message.session_id}"
        )

        idem = str((message.metadata or {}).get("idempotency_key") or "")
        if idem:
            prior = await self._inbound.get(message.session_id, idem)
            if prior is not None and prior.outcome:
                return prior.outcome

        command = parse_channel_command(message.text)
        skip_lock = command.kind in _CONTROL_LOCK_BYPASS
        held_lock = False
        if not skip_lock:
            held_lock = self._inflight.acquire(message.session_id)
            if not held_lock:
                if command.kind in {
                    ChannelCommandKind.CHAT,
                    ChannelCommandKind.PROMPT,
                }:
                    self._park.put(message.session_id, message)
                    return _PARKED
                return _BUSY
        breaker = self._get_breaker(message.channel_type)
        try:
            if idem:
                won, prior = await self._inbound.claim(message.session_id, idem)
                if not won:
                    if prior is not None and prior.outcome:
                        return prior.outcome
                    return _BUSY
            if breaker is not None:
                response = await breaker.call(self._route, message)
            else:
                response = await self._route(message)
            if idem:
                if isinstance(response, RetryableReply):
                    # Q9c -- "다시 보내 주세요"를 기억하면 같은 이벤트의 재전송이 그 문구만 돌려받는다.
                    await self._inbound.abandon(message.session_id, idem)
                else:
                    await self._inbound.remember(message.session_id, idem, response)
        except Exception as e:
            logger.error(
                f"[ChannelGateway] dispatch failed for channel={message.channel_type}: {e}"
            )
            if idem:
                await self._inbound.abandon(message.session_id, idem)
            response = "죄송합니다. 요청을 처리하는 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
        finally:
            if held_lock:
                self._inflight.release(message.session_id)
                self._schedule_fold(message.session_id)

        return response

    async def _route(self, message: ChannelMessage) -> str:
        # Q15c: 음성은 무엇보다 먼저 텍스트가 된다(통합 순서: 전사 → Q9 답 판정 → 갈래).
        voice_refusal = await self._transcribe_voice(message)
        if voice_refusal is not None:
            return voice_refusal
        command = parse_channel_command(message.text)
        if command.kind is ChannelCommandKind.CHAT:
            # Q9c -- 기다리는 에이전트 질문의 답이면 여기서 끝난다(워크플로우는 돌지 않는다).
            answered = await self._answer_waiting_question(message)
            if answered is not None:
                return answered
            binding = await self._binds.get(message.session_id)
            if binding is not None:
                return await self._steer_bound_chat(message, binding)
            return await self._run_workflow(message)
        if command.kind is ChannelCommandKind.LEARN:
            return await self._run_learn(message, command)
        if command.kind is ChannelCommandKind.NEW:
            return await self._run_new(message, command)
        if command.kind is ChannelCommandKind.CLEAR:
            return await self._run_clear(message)
        if command.kind is ChannelCommandKind.COMPACT:
            return await self._run_compact(message, command)
        if command.kind is ChannelCommandKind.COST:
            return await self._run_cost(message)
        if command.kind is ChannelCommandKind.EXPORT:
            return await self._run_export(message)
        if command.kind is ChannelCommandKind.DIFF:
            return await self._run_diff(message)
        if command.kind is ChannelCommandKind.HELP:
            return await self._run_help(message, command)
        if command.kind is ChannelCommandKind.LOOP:
            return await self._run_disabled_command(message, command)
        if command.kind is ChannelCommandKind.UNKNOWN:
            return _UNKNOWN_COMMAND
        if command.kind is ChannelCommandKind.PROMPT:
            return await self._run_prompt_command(message, command)
        return await self._run_coding_command(message, command)

    async def _answer_waiting_question(self, message: ChannelMessage) -> str | None:
        """Q9c 답 확인 -- `CHAT` 메시지만 온다(명령은 답이 아니다). 확인 문구 또는 None.

        코딩에 바인딩된 세션의 말은 그 태스크의 조향이므로 답이 아니다(설계 §7.1 의 3).
        **질문을 찾기 전의** 실패만 여기서 삼킨다: 경고 한 줄을 남기고 None -- 메시지는 지금처럼
        대화로 간다. 질문을 찾은 **뒤의** 실패는 `ChannelAskAnswers` 가 `RetryableReply` 로 바꾼다
        -- 다시 보내 달라는 응답이고, `dispatch` 는 그것을 멱등 기록에 남기지 않는다(Q9c 고침 1).
        트랙 Q15 의 전사 단계가 이 앞에 선다(전사 → 답 확인).
        """
        if self._ask_answers is None:
            return None
        try:
            if await self._binds.get(message.session_id) is not None:
                return None
            return await self._ask_answers.try_answer(message)
        except Exception:
            logger.warning(
                "[ChannelGateway] ask answer check failed session=%s",
                message.session_id,
                exc_info=True,
            )
            return None

    async def _transcribe_voice(self, message: ChannelMessage) -> str | None:
        """`metadata["voice"]` 를 `"[voice] <전사>"` 본문으로 바꾼다(설계 §8). 거절이면 그 문구.

        음성이 없거나, 플래그가 꺼져 있거나, 캡션이 명령이면 아무것도 하지 않는다(None).
        미매핑 발신자는 공급자에 보내지 않고 `_NO_OWNER`. 어느 경우에도 오디오 바이트는 이 함수가
        끝날 때 메시지에서 지운다 — 공급자 말고는 어디에도 가지 않는다.
        """
        voice = (message.metadata or {}).get("voice")
        if not isinstance(voice, dict):
            return None
        try:
            from neos.config.settings import settings

            config = settings.config.channels.voice
            if not config.enabled:
                return None
            # dispatch 가 이미 캡션으로 잠금·주차를 정했다 — 전사가 갈래를 바꾸면 안 된다.
            if parse_channel_command(message.text).kind is not ChannelCommandKind.CHAT:
                return None
            if _mapped_user_id(message) is None:
                return _NO_OWNER
            outcome, transcript = await self._voice_transcript(voice, config)
            _count_voice(outcome)
            if transcript is None:
                reply = _VOICE_REPLIES.get(outcome, _VOICE_TRANSCRIBE_FAILED)
                return reply.format(max_seconds=config.max_seconds)
            caption = (message.text or "").strip()
            # 접두 `[voice]` 덕에 말한 "/new" 는 명령이 되지 않는다.
            message.text = _VOICE_PREFIX + transcript + (f"\n\n{caption}" if caption else "")
            return None
        finally:
            voice["bytes"] = None

    @staticmethod
    async def _voice_transcript(voice: dict[str, Any], config: Any) -> tuple[str, str | None]:
        """(outcome, 전사 텍스트 | None). 수집 단계의 거절은 공급자를 부르지 않고 그대로 넘긴다."""
        from neos.services import speech_to_text

        refused = voice.get("refused")
        if refused:
            return (refused if refused in _VOICE_REPLIES else "download_failed"), None
        audio = voice.get("bytes")
        if not isinstance(audio, (bytes, bytearray)) or not audio:
            return "download_failed", None
        try:
            result = await speech_to_text.transcribe(
                bytes(audio),
                filename=str(voice.get("filename") or ""),
                content_type=str(voice.get("content_type") or ""),
                duration_seconds=voice.get("duration_seconds"),
                config=config,
            )
        except speech_to_text.TranscriptionRefused as refusal:
            return refusal.reason, None
        return "ok", result.text

    async def _run_workflow(self, message: ChannelMessage) -> str:
        """
        multi_agent_workflow.execute_workflow()를 직접 호출한다.

        channel_type / channel_id를 초기 상태에 포함시켜 워크플로우 전체에서
        채널 정보를 활용할 수 있게 한다 (Phase 3 ContextAssemblyEngine 연동).
        """
        user_id = _mapped_user_id(message)
        if user_id is None:
            return _NO_OWNER

        query = (message.text or "").strip() + _attachment_prompt(message)
        if not query.strip():
            query = "The user sent a message with no text."
        # 스레드에는 발신자 표지 없이 적는다 -- 붙는 세션은 소유자의 DM 뿐이다(Q8 §5).
        agent_turn = (
            await self._agent_threads.open_turn(message, query)
            if self._agent_threads is not None
            else None
        )
        query = _with_sender_prefix(message, query)
        channel_attachments = _channel_attachment_blocks(message)
        await self._send_start_draft(message, _DRAFT_WORKFLOW)

        workflow_input: Dict[str, Any] = {
            "user_id": user_id,
            "session_id": message.session_id,
            "query": query,
            "original_query": query,
            # Phase 3 state 필드: 채널 정보 전달
            "channel_type": message.channel_type,
            "channel_id": message.channel_id,
            # channel_source를 초기 state에 직접 포함하여 INSERT 시점에 올바르게 기록
            "channel_source": message.channel_type,
            # 채널 요청은 히스토리 컨텍스트 활성화 (세션 기반 대화 지원)
            "enable_history_context": True,
            "execution_start": datetime.utcnow(),
            "execution_steps": [],
            "errors": [],
            "structured_errors": [],
            "required_agents": [],
            "search_results": [],
            "analysis_results": [],
            "generation_results": [],
            "retry_count": 0,
            "channel_attachments": channel_attachments,
        }
        if agent_turn is not None:
            # 웹 채팅과 같은 모양 -- 워크플로우는 고치지 않는다(Q8 §6).
            workflow_input["chat_history"] = agent_turn.history

        # 워크플로우 실행 (checkpointer 사용 — 세션 지속성 보장)
        result = await self._workflow.execute_workflow(
            workflow_input,
            use_checkpointer=True,
        )

        if result.get("interrupted"):
            pending = result.get("pending_approvals") or []
            first = pending[0] if pending else {}
            request_id = str(first.get("request_id") or "")
            self._workflow_reset.discard(message.session_id)
            self._workflow_pending[message.session_id] = {
                "request_id": request_id,
                "owner_id": user_id,
            }
            if request_id:
                return f"{message.session_id} waiting_approval {request_id} workflow"
            return f"{message.session_id} waiting_approval"

        final_response = result.get("final_response") or result.get("response") or ""
        if agent_turn is not None and final_response:
            await self._agent_threads.close_turn(agent_turn, final_response)
        if not final_response:
            final_response = "응답을 생성하지 못했습니다. 다시 시도해주세요."

        return final_response

    async def _run_coding_command(self, message: ChannelMessage, command) -> str:
        from neos.config.settings import settings

        if command.kind is ChannelCommandKind.CODE:
            if not command.rest:
                return _CODE_USAGE
            if not settings.config.channels.coding_invoke:
                return _CODE_DISABLED
            from .principals import resolve_coding_owner

            owner = resolve_coding_owner(
                message=message, channels=settings.config.channels
            )
            if not owner:
                return _CODE_NO_OWNER
            existing = await self._binds.get(message.session_id)
            if existing is not None:
                return f"Started coding task {existing.task_id}"
            idem = str((message.metadata or {}).get("idempotency_key") or "")
            start_key = (message.session_id, idem)
            if idem:
                prior = self._code_starts.get(start_key)
                if prior:
                    return f"Started coding task {prior}"
                if prior is not None:
                    return _BUSY
                self._code_starts[start_key] = ""
            prompt = _with_sender_prefix(
                message, command.rest + _attachment_prompt(message)
            )
            await self._send_start_draft(message, _DRAFT_CODING)
            coding = self._coding_port()
            try:
                task_id = await coding.start_task(owner_id=owner, prompt=prompt)
            except Exception:
                if idem:
                    self._code_starts.pop(start_key, None)
                raise
            binding = await self._binds.bind(message.session_id, task_id, owner)
            if idem:
                self._code_starts[start_key] = binding.task_id
            return f"Started coding task {binding.task_id}"

        binding = await self._binds.get(message.session_id)
        if binding is None:
            if command.kind in {
                ChannelCommandKind.APPROVE,
                ChannelCommandKind.DENY,
            }:
                return await self._resume_workflow_approval(message, command)
            return _NO_TASK
        task_id = binding.task_id
        owner = binding.owner_id or settings.config.channels.coding_owner_user_id
        coding = self._coding_port()
        if command.kind is ChannelCommandKind.STOP:
            await coding.stop_task(task_id=task_id, owner_id=owner)
            return channel_reply(ChannelOutcome.CANCEL, f"Stopped {task_id}")
        if command.kind is ChannelCommandKind.STATUS:
            return annotate_status_reply(
                await coding.status(task_id=task_id, owner_id=owner)
            )
        if command.kind in {
            ChannelCommandKind.APPROVE,
            ChannelCommandKind.DENY,
        }:
            return await coding.decide(
                task_id=task_id,
                owner_id=owner,
                approve=command.kind is ChannelCommandKind.APPROVE,
                approval_id=command.rest,
            )
        return _NO_TASK

    async def _run_learn(self, message: ChannelMessage, command) -> str:
        from dataclasses import replace

        from neos.coding.learn_lessons import _persist_lesson
        from neos.config.settings import settings
        from neos.learn.lessons import LessonStatus, new_lesson
        from neos.learn.policy import clip_knowledge, namespace, write_approval_required

        learn = settings.config.learn
        if not (learn.channel_learn or learn.coding_lessons):
            return _LEARN_DISABLED
        rest = neutralize_untrusted_inline(command.rest, max_len=400)
        if not rest:
            return _LEARN_USAGE

        user_id = _mapped_user_id(message)
        if user_id is None:
            return _NO_OWNER

        body = clip_knowledge(rest)
        lesson = new_lesson(
            namespace=namespace(user_id),
            title=body.split("\n", 1)[0][:60] or "channel-learn",
            body=body,
            kind="fact",
        )
        if not write_approval_required():
            lesson = replace(lesson, status=LessonStatus.APPROVED)
        await _persist_lesson(lesson)
        return _LEARN_STAGED

    async def _run_new(self, message: ChannelMessage, command) -> str:
        generation = _generation_token(message, command)
        if generation:
            won, _prior = await self._generations.claim(
                message.session_id, generation
            )
            if not won:
                return _SESSION_RESET
        binding = await self._binds.get(message.session_id)
        if binding is not None:
            coding = self._coding_port()
            await coding.stop_task(
                task_id=binding.task_id, owner_id=binding.owner_id
            )
        await self._binds.unbind(message.session_id)
        self._park.clear(message.session_id)
        self._workflow_pending.pop(message.session_id, None)
        self._workflow_reset.add(message.session_id)
        self._code_starts = {
            key: value
            for key, value in self._code_starts.items()
            if key[0] != message.session_id
        }
        await self._inbound.clear_session(message.session_id)
        if self._agent_threads is not None and await self._agent_threads.rotate_for_session(
            message
        ):
            return _AGENT_THREAD_ROTATED
        return _SESSION_RESET

    def _schedule_fold(self, session_id: str) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(
            self._fold_parked(session_id),
            name=f"channel-fold-{session_id}",
        )

    async def _fold_parked(self, session_id: str) -> None:
        parked = self._park.take(session_id)
        if parked is None:
            return
        if not self._inflight.acquire(session_id):
            if self._park.peek(session_id) is None:
                self._park.put(session_id, parked)
            return
        try:
            reply = await self._route(parked)
            raw_thread = (parked.metadata or {}).get("thread_id")
            thread_id = raw_thread if isinstance(raw_thread, str) else None
            await self.send_to_channel(
                parked.channel_type,
                parked.channel_id,
                reply,
                thread_id=thread_id,
            )
        except Exception as e:
            logger.error(
                f"[ChannelGateway] fold failed for session={session_id}: {e}"
            )
        finally:
            self._inflight.release(session_id)
            if self._park.peek(session_id) is not None:
                await self._fold_parked(session_id)

    async def _steer_bound_chat(self, message: ChannelMessage, binding: Any) -> str:
        from neos.coding.commands import interpret_coding_command
        from neos.coding.commands.types import CommandDisposition

        coding = self._coding_port()
        decision = interpret_coding_command(message.text)
        if decision.disposition is CommandDisposition.INJECT:
            body = decision.inject_text
        elif decision.disposition is CommandDisposition.APPLY_IN_LOOP:
            body = decision.canonical_text
        else:
            body = message.text
        instruction = _with_sender_prefix(message, body)
        return await coding.steer(
            task_id=binding.task_id,
            owner_id=binding.owner_id,
            instruction=instruction,
        )

    async def _run_clear(self, message: ChannelMessage) -> str:
        self._workflow_pending.pop(message.session_id, None)
        invoked = await self._invoke_bound_command(
            message, "/clear", require_task=False
        )
        if invoked is not None:
            return invoked
        return _CONTEXT_CLEAR_REQUESTED

    async def _run_compact(self, message: ChannelMessage, command) -> str:
        invoked = await self._invoke_bound_command(
            message, f"/compact {command.rest}".strip()
        )
        if invoked is not None:
            return invoked
        binding = await self._binds.get(message.session_id)
        if binding is None:
            return _NO_TASK
        coding = self._coding_port()
        compact_fn = getattr(coding, "compact", None)
        if not callable(compact_fn):
            return _COMPACT_UNAVAILABLE
        try:
            result = await compact_fn(
                task_id=binding.task_id,
                owner_id=binding.owner_id,
                instruction=command.rest,
            )
        except Exception:
            return _COMPACT_UNAVAILABLE
        if isinstance(result, str) and result.strip():
            return result
        return _COMPACT_UNAVAILABLE

    async def _run_cost(self, message: ChannelMessage) -> str:
        invoked = await self._invoke_bound_command(message, "/cost")
        if invoked is not None:
            return invoked
        binding = await self._binds.get(message.session_id)
        if binding is None:
            return _NO_TASK
        coding = self._coding_port()
        cost_fn = getattr(coding, "cost", None)
        if callable(cost_fn):
            try:
                text = await cost_fn(
                    task_id=binding.task_id, owner_id=binding.owner_id
                )
            except Exception:
                text = None
            if isinstance(text, str) and text.strip():
                return text
        snapshot = await _read_coding_snapshot(
            coding, task_id=binding.task_id, owner_id=binding.owner_id
        )
        line = _cost_line_from_snapshot(snapshot, binding.task_id)
        return line or _COST_TRACKED

    async def _run_export(self, message: ChannelMessage) -> str:
        invoked = await self._invoke_bound_command(message, "/export")
        if invoked is not None:
            return invoked
        binding = await self._binds.get(message.session_id)
        if binding is None:
            return _NO_TASK
        return _EXPORT_UI

    async def _run_diff(self, message: ChannelMessage) -> str:
        invoked = await self._invoke_bound_command(message, "/diff")
        if invoked is not None:
            return invoked
        binding = await self._binds.get(message.session_id)
        if binding is None:
            return _NO_TASK
        coding = self._coding_port()
        diff_fn = getattr(coding, "turn_diff", None)
        if callable(diff_fn):
            try:
                text = await diff_fn(
                    task_id=binding.task_id, owner_id=binding.owner_id
                )
            except Exception:
                text = None
            if isinstance(text, str) and text.strip():
                return text
        return f"{binding.task_id} no file changes in the last turn."

    async def _run_help(self, message: ChannelMessage, command) -> str:
        invoked = await self._invoke_bound_command(
            message, f"/help {command.rest}".strip(), require_task=False
        )
        if invoked is not None:
            return invoked
        from neos.coding.commands import format_help

        return format_help(command.rest)

    async def _run_disabled_command(
        self, message: ChannelMessage, command
    ) -> str:
        from neos.coding.commands import interpret_coding_command

        token = (message.text or "").strip() or f"/loop {command.rest}".strip()
        return interpret_coding_command(token).message

    async def _run_prompt_command(self, message: ChannelMessage, command) -> str:
        binding = await self._binds.get(message.session_id)
        if binding is None:
            return _NO_TASK
        return await self._steer_bound_chat(message, binding)

    async def _invoke_bound_command(
        self,
        message: ChannelMessage,
        text: str,
        *,
        require_task: bool = True,
    ) -> str | None:
        binding = await self._binds.get(message.session_id)
        if binding is None:
            return _NO_TASK if require_task else None
        coding = self._coding_port()
        invoke = getattr(coding, "invoke_command", None)
        if not callable(invoke):
            return None
        try:
            result = await invoke(
                task_id=binding.task_id,
                owner_id=binding.owner_id,
                text=text,
            )
        except Exception:
            return None
        if isinstance(result, str) and result.strip():
            return result
        return None

    async def _resume_workflow_approval(
        self, message: ChannelMessage, command, pending: Dict[str, str] | None = None
    ) -> str:
        from neos.config.settings import settings

        from .principals import platform_user_id_from_message, resolve_channel_principal

        if pending is None:
            if message.session_id in self._workflow_reset:
                return _NO_TASK
            pending = self._workflow_pending.get(message.session_id)
        port = self._workflow_approvals
        if port is None:
            return _APPROVAL_NOT_CONFIGURED
        owner_id = ""
        request_id = command.rest or ""
        if pending:
            owner_id = pending.get("owner_id") or ""
            request_id = request_id or pending.get("request_id") or ""
        else:
            peek = getattr(port, "interrupt_owner", None)
            if peek is not None:
                owner_id = str(await peek(message.session_id) or "")

        channels = settings.config.channels
        if channels.principals:
            actor = resolve_channel_principal(
                platform=message.channel_type,
                platform_user_id=platform_user_id_from_message(message),
                channels=channels,
            )
            if not owner_id or actor != owner_id:
                return _NO_OWNER

        approve = command.kind is ChannelCommandKind.APPROVE
        result = await port.decide(
            session_id=message.session_id,
            request_id=request_id,
            owner_id=owner_id,
            approve=approve,
        )
        applied = str(result)
        if (approve or command.kind is ChannelCommandKind.DENY) and (
            applied.endswith(" approved") or applied.endswith(" denied")
        ):
            self._workflow_pending.pop(message.session_id, None)
        return applied

    async def bind_session(
        self, session_id: str, task_id: str, owner_id: str
    ) -> None:
        await self._binds.bind(session_id, task_id, owner_id)

    async def get_binding(self, session_id: str) -> Any:
        return await self._binds.get(session_id)

    async def workflow_pending_owner(self, session_id: str) -> str | None:
        if session_id in self._workflow_reset:
            return None
        pending = self._workflow_pending.get(session_id)
        if pending:
            return pending.get("owner_id") or None
        peek = getattr(self._workflow_approvals, "interrupt_owner", None)
        if peek is None:
            return None
        owner = await peek(session_id)
        return str(owner) if owner else None

    async def unbind_session(self, session_id: str) -> None:
        await self._binds.unbind(session_id)

    def _coding_port(self):
        if self._coding is None:
            from .coding_bridge import RuntimeChannelCoding

            self._coding = RuntimeChannelCoding()
        return self._coding

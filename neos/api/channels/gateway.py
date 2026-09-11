"""채널 게이트웨이 (Phase 1 — OpenClaw Channel Gateway)

외부 채널 어댑터로부터 ChannelMessage를 받아 NEOS 워크플로우를 직접 실행하고
최종 응답을 반환한다. HTTP 호출 없이 같은 프로세스 내에서 함수를 직접 호출한다.

채널별 circuit_breaker를 독립적으로 유지하여 특정 채널 장애가 다른 채널에
전파되지 않도록 격리한다.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from neos.workflow.graph import MultiAgentWorkflow

from .base import ChannelMessage
from .commands import (
    ChannelCommandKind,
    display_name_from_metadata,
    neutralize_untrusted_inline,
    parse_channel_command,
    sender_prefix,
)
from .inflight import SessionInflightLock

logger = logging.getLogger(__name__)

_BUSY = "Already working on this thread."
_CODE_USAGE = "Usage: /code <task>"
_CODE_DISABLED = "Coding invoke is disabled."
_CODE_NO_OWNER = "Coding owner is not configured."
_NO_OWNER = "Owner is not configured."
_NO_TASK = "No coding task in this thread."
_LEARN_DISABLED = "Learning is disabled."
_LEARN_STAGED = "Lesson staged."
_LEARN_USAGE = "Usage: /learn <text>"
_SESSION_RESET = "Session reset."


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
        data = item.get("data") or b""
        size = len(data) if isinstance(data, (bytes, bytearray)) else 0
        lines.append(f"- {name} ({content_type}, {size} bytes)")
    if not lines:
        return ""
    return "\n\nUser attached files:\n" + "\n".join(lines)


class ChannelGateway:
    """
    채널 어댑터 → NEOS 워크플로우 라우팅 게이트웨이

    - 채널별 독립 circuit_breaker 유지
    - multi_agent_workflow.execute_workflow() 직접 호출 (HTTP 우회)
    - channel_source를 초기 state에 포함하여 워크플로우 시작 시점에 올바르게 기록
    """

    def __init__(
        self,
        workflow: "MultiAgentWorkflow",
        *,
        coding: Any | None = None,
        inflight: SessionInflightLock | None = None,
        binds: Any | None = None,
    ) -> None:
        self._workflow = workflow
        self._coding = coding
        self._inflight = inflight or SessionInflightLock()
        if binds is None:
            from .session_bind import InMemoryChannelCodingBindStore

            binds = InMemoryChannelCodingBindStore()
        self._binds = binds
        # 채널별 async circuit_breaker (lazy init)
        self._breakers: Dict[str, Any] = {}
        # Process-local /code start dedupe: (session_id, idempotency_key) → task_id.
        # Not durable across processes or restarts.
        self._code_starts: Dict[tuple[str, str], str] = {}

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

        if not self._inflight.acquire(message.session_id):
            return _BUSY
        breaker = self._get_breaker(message.channel_type)
        try:
            if breaker is not None:
                response = await breaker.call(self._route, message)
            else:
                response = await self._route(message)
        except Exception as e:
            logger.error(
                f"[ChannelGateway] dispatch failed for channel={message.channel_type}: {e}"
            )
            response = "죄송합니다. 요청을 처리하는 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
        finally:
            self._inflight.release(message.session_id)

        return response

    async def _route(self, message: ChannelMessage) -> str:
        command = parse_channel_command(message.text)
        if command.kind is ChannelCommandKind.CHAT:
            return await self._run_workflow(message)
        if command.kind is ChannelCommandKind.LEARN:
            return await self._run_learn(message, command)
        if command.kind is ChannelCommandKind.NEW:
            return await self._run_new(message)
        return await self._run_coding_command(message, command)

    async def _run_workflow(self, message: ChannelMessage) -> str:
        """
        multi_agent_workflow.execute_workflow()를 직접 호출한다.

        channel_type / channel_id를 초기 상태에 포함시켜 워크플로우 전체에서
        채널 정보를 활용할 수 있게 한다 (Phase 3 ContextAssemblyEngine 연동).
        """
        from neos.config.settings import settings

        from .principals import platform_user_id_from_message, resolve_channel_principal

        channels = settings.config.channels
        user_id = message.user_id
        if channels.principals:
            mapped = resolve_channel_principal(
                platform=message.channel_type,
                platform_user_id=platform_user_id_from_message(message),
                channels=channels,
            )
            if not mapped:
                return _NO_OWNER
            user_id = mapped

        query = (message.text or "").strip() + _attachment_prompt(message)
        if not query.strip():
            query = "The user sent a message with no text."
        query = _with_sender_prefix(message, query)

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
        }

        # 워크플로우 실행 (checkpointer 사용 — 세션 지속성 보장)
        result = await self._workflow.execute_workflow(
            workflow_input,
            use_checkpointer=True,
        )

        final_response = result.get("final_response") or ""
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
            coding = self._coding_port()
            try:
                task_id = await coding.start_task(owner_id=owner, prompt=prompt)
            except Exception:
                if idem:
                    self._code_starts.pop(start_key, None)
                raise
            await self._binds.bind(message.session_id, task_id, owner)
            if idem:
                self._code_starts[start_key] = task_id
            return f"Started coding task {task_id}"

        binding = await self._binds.get(message.session_id)
        if binding is None:
            return _NO_TASK
        task_id = binding.task_id
        owner = binding.owner_id or settings.config.channels.coding_owner_user_id
        coding = self._coding_port()
        if command.kind is ChannelCommandKind.STOP:
            await coding.stop_task(task_id=task_id, owner_id=owner)
            return f"Stopped {task_id}"
        if command.kind is ChannelCommandKind.STATUS:
            return await coding.status(task_id=task_id, owner_id=owner)
        return await coding.decide(
            task_id=task_id,
            owner_id=owner,
            approve=command.kind is ChannelCommandKind.APPROVE,
            approval_id=command.rest,
        )

    async def _run_learn(self, message: ChannelMessage, command) -> str:
        from dataclasses import replace

        from neos.config.settings import settings
        from neos.learn.lessons import LessonStatus, get_lesson_store, new_lesson
        from neos.learn.policy import clip_knowledge, namespace, write_approval_required

        from .principals import platform_user_id_from_message, resolve_channel_principal

        learn = settings.config.learn
        if not (learn.channel_learn or learn.coding_lessons):
            return _LEARN_DISABLED
        rest = neutralize_untrusted_inline(command.rest, max_len=400)
        if not rest:
            return _LEARN_USAGE

        channels = settings.config.channels
        user_id = message.user_id
        if channels.principals:
            mapped = resolve_channel_principal(
                platform=message.channel_type,
                platform_user_id=platform_user_id_from_message(message),
                channels=channels,
            )
            if not mapped:
                return _NO_OWNER
            user_id = mapped

        body = clip_knowledge(rest)
        lesson = new_lesson(
            namespace=namespace(user_id),
            title=body.split("\n", 1)[0][:60] or "channel-learn",
            body=body,
            kind="fact",
        )
        if not write_approval_required():
            lesson = replace(lesson, status=LessonStatus.APPROVED)
        get_lesson_store().add(lesson)
        return _LEARN_STAGED

    async def _run_new(self, message: ChannelMessage) -> str:
        await self._binds.unbind(message.session_id)
        self._code_starts = {
            key: value
            for key, value in self._code_starts.items()
            if key[0] != message.session_id
        }
        return _SESSION_RESET

    async def bind_session(
        self, session_id: str, task_id: str, owner_id: str
    ) -> None:
        await self._binds.bind(session_id, task_id, owner_id)

    async def get_binding(self, session_id: str) -> Any:
        return await self._binds.get(session_id)

    async def unbind_session(self, session_id: str) -> None:
        await self._binds.unbind(session_id)

    def _coding_port(self):
        if self._coding is None:
            from .coding_bridge import RuntimeChannelCoding

            self._coding = RuntimeChannelCoding()
        return self._coding

"""One model turn, from request to the checkpoint that ends it.

A turn has three stages:

1. `_prepare_turn` -- load instructions, apply pre-generate notes, build the
   system prompt and tool array, and guard replayed thinking.
2. `_stream_turn` -- persist text deltas as they arrive, emit status events,
   and start read-only tools speculatively (`_maybe_prefetch_readonly`).
3. `_settle_turn` -- decide what the finished turn means and commit it once.
   A turn with tool calls hands off to the tool path in the same step.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from uuid import uuid4

from neos.coding.domain.text_parts import TextPartConflict
from neos.coding.harness import fold_model_event, iter_model_turn
from neos.coding.instructions import (
    INSTRUCTION_CANDIDATES,
    load_workspace_instruction_tree,
    load_workspace_instructions,
)
from neos.coding.learn_lessons import coding_turn_system
from neos.gepa_opt.inject import coding_turn_overlay
from neos.coding.loop.hooks import invoke_post_generate, invoke_pre_generate
from neos.coding.model.base import (
    CanonicalMessage,
    ModelCompleted,
    ModelLimits,
    ModelRequest,
    SystemNoteContent,
    TextDelta,
    ThinkingCompleted,
    ToolCallCompleted,
    ToolDefinition,
    ToolInputDelta,
    strip_thinking,
)
from neos.coding.model.errors import CodingModelError
from neos.coding.monitor.monitor import pause_reason_code
from neos.coding.phases import (
    CodingAgentPhase,
    parse_phase,
    parse_plan_critical_files,
    parse_verify_verdict,
    persist_plan_critical_files,
    persist_verify_verdict,
    plan_text_has_body,
)
from neos.coding.prompts import inject_previous_summary
from neos.coding.loop._durable.hook_decisions import parse_stop_decision
from neos.coding.loop._durable.state import (
    EMPTY_RETRY_LIMIT,
    STOP_RETRY_LIMIT,
    AgentLoopState,
    CodingLoopFailure,
)
from neos.coding.loop._durable.transcript import (
    _is_empty_or_think_only,
    _scrub_think_blocks,
)
from neos.coding.loop._durable.usage import check_usage_budgets, with_turn_usage

# One status line's worth. `max_text_delta_bytes` governs durable model text
# and is three orders of magnitude too large for this.
THINKING_PREVIEW_CHARS = 200
_METRIC_STOP_REASONS = frozenset({"tool_use", "end_turn", "max_tokens", "refusal"})
#: Past this many prompt-too-long retries the turn fails. The first retry
#: compacts (with one LLM summary), the rest drop the oldest turn each.
_PROMPT_TOO_LONG_RETRIES = 4
#: 봉투 섀도가 "이 런에 이미 판정이 있나"를 볼 때 읽는 최근 원장 수. 판정 기준이
#: 아니라 중복 방지 창이라 설정이 아니다 -- 창 밖으로 밀려나면 한 번 더 남을 뿐이다.
_ENVELOPE_LEDGER_WINDOW = 2000


def _request_fingerprint(system: str, tools: Sequence[ToolDefinition]) -> str:
    """Digest of the two request fields a thinking block is bound to besides messages."""
    payload = json.dumps(
        {
            "system": system,
            "tools": [
                [tool.name, tool.description, dict(tool.input_schema)]
                for tool in tools
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _incomplete() -> CodingLoopFailure:
    return CodingLoopFailure("model_output_incomplete", retryable=False)


@dataclass
class _TurnStream:
    """What one streamed turn accumulated. Mutated only by `_stream_turn`."""

    part_id: str
    text_parts: list[str] = field(default_factory=list)
    calls: list[ToolCallCompleted] = field(default_factory=list)
    thinking: list[ThinkingCompleted] = field(default_factory=list)
    completion: ModelCompleted | None = None
    prefetch_tasks: dict[str, asyncio.Task] = field(default_factory=dict)
    #: Once text or tool input is durable, a retry would repeat it.
    persisted_stream: bool = False

    def cancel_prefetch(self) -> None:
        for task in self.prefetch_tasks.values():
            task.cancel()


logger = logging.getLogger("neos.coding.loop.durable")


async def _warn_if_due(envelope, agent_id, verdict) -> None:
    """봉투 경고(결정 D7). 알림기가 없으면 아무것도 하지 않는다 -- off 면 바이트가 같다."""
    warn = getattr(envelope, "warn_if_due", None)
    if not callable(warn):
        return
    try:
        await warn(agent_id, verdict)
    except Exception:  # noqa: BLE001 -- 알림은 판정을 바꾸지 않는다
        logger.warning("agent budget warning failed", exc_info=True)


class ModelTurnMixin:
    async def _monitor_safe_point(self, input, deps) -> None:
        """궤적 감시자(트랙 Q5)의 자리. **섀도** -- 무엇이 일어나도 런은 그대로다.

        감시자는 원장만 읽는다(`list_after`). 읽을 수 없는 싱크면 판정하지
        않는다. 감시자의 고장이 태스크를 멈추게 하면 섀도가 아니다. 멈추게 하는
        길(`PAUSED`)은 `enforce` 일 때의 `_monitor_pause_point` 다(Q5b).
        """
        monitor = getattr(self, "_monitor", None)
        reader = getattr(deps.events, "list_after", None)
        if monitor is None or not callable(reader):
            return
        if getattr(monitor, "enforce", False):
            return  # Q5b -- `_monitor_pause_point` 가 이미 이 턴을 판정했다
        try:
            events = await monitor.read_ledger(reader, input.task_id)
            if not monitor.due(events):
                return
            payload = await monitor.judge(events, mode=getattr(input, "mode", "interactive"))
            await deps.events.append(
                task_id=input.task_id,
                event_type="monitor.judged",
                payload=payload,
                run_id=input.run_id,
            )
        except Exception:  # noqa: BLE001 -- 섀도는 런을 바꾸지 않는다
            logger.warning("trajectory monitor failed", exc_info=True)

    async def _envelope_safe_point(self, input, deps) -> None:
        """상시 에이전트 예산 봉투(트랙 Q10a)의 자리. **섀도** -- 넘어도 런은 그대로다.

        에이전트가 연 태스크만 본다. 넘었을 때만 원장을 읽고, 이 런에 아직 판정이
        없으면 `budget.judged` 하나를 남긴다 -- 넘은 동안 매 턴 쌓이지 않게. 멈추게
        하는 길(`PAUSED`)은 `enforce` 일 때의 `_envelope_pause_point` 다(Q10b).
        """
        envelope = getattr(self, "_envelope", None)
        agent_id = getattr(input, "agent_id", None)
        reader = getattr(deps.events, "list_after", None)
        if envelope is None or agent_id is None or not callable(reader):
            return
        if getattr(envelope, "enforce", False):
            return  # Q10b -- `_envelope_pause_point` 가 이미 이 턴을 판정했다
        mode = getattr(input, "mode", "background")
        try:
            verdict = await envelope.judge(agent_id, mode)
            await _warn_if_due(envelope, agent_id, verdict)
            if not verdict.over:
                return
            events = await _read_ledger(reader, input.task_id, limit=_ENVELOPE_LEDGER_WINDOW)
            if any(
                event.type == "budget.judged" and event.run_id == input.run_id
                for event in events
            ):
                return
            await deps.events.append(
                task_id=input.task_id,
                event_type="budget.judged",
                payload=verdict.payload(mode=mode),
                run_id=input.run_id,
            )
        except Exception:  # noqa: BLE001 -- 섀도는 런을 바꾸지 않는다
            logger.warning("agent budget envelope failed", exc_info=True)

    async def _envelope_pause_point(self, input, deps):
        """봉투 집행(트랙 Q10b). 넘은 에이전트 태스크를 **이 자리에서** `PAUSED` 로 보낸다.

        턴의 맨 앞 -- 자식에게 한 걸음을 주기 **전**이다. 멈출 태스크의 자식이 한 번
        더 쓰지 않게, 그리고 이 자리의 상태가 최신 체크포인트와 같아 멈춤이 새
        체크포인트를 쓸 필요가 없게. 재개하면 같은 런이 그 체크포인트에서 이어 간다.

        판정을 읽지 못하면 멈추지 않는다: 다음 턴이 다시 판정하므로 일시적 고장의
        값은 많아야 한 턴이고, 계속되는 DB 고장이면 루프 자신의 커밋이 먼저 실패한다.
        멈춤 커밋의 실패(`StaleExecutionLease`)는 그대로 올라간다 -- 리스를 잃은 쪽은
        멈춰야 한다. 반환값은 멈춤의 `task.status.changed` 이벤트, 아니면 `None`.
        """
        envelope = getattr(self, "_envelope", None)
        agent_id = getattr(input, "agent_id", None)
        if envelope is None or agent_id is None or not getattr(envelope, "enforce", False):
            return None
        mode = getattr(input, "mode", "background")
        try:
            verdict = await envelope.judge(agent_id, mode)
        except Exception:  # noqa: BLE001 -- 위 독스트링: 다음 턴이 다시 판정한다
            logger.warning("agent budget envelope failed", exc_info=True)
            return None
        await _warn_if_due(envelope, agent_id, verdict)
        if not verdict.over:
            return None
        commit = await deps.repository.pause_task(
            lease=deps.lease,
            judgement_type="budget.judged",
            judgement=verdict.payload(mode=mode, enforced=True),
            reason_code=str(verdict.reason),
            now=self._clock(),
        )
        try:
            await envelope.notify_paused(
                agent_id, verdict, task_id=input.task_id, seq=commit.status_event.seq
            )
        except Exception:  # noqa: BLE001 -- 알림은 멈춤을 바꾸지 않는다
            logger.warning("agent budget pause notice failed", exc_info=True)
        return commit.status_event

    async def _monitor_pause_point(self, input, deps):
        """감시자 집행(트랙 Q5b). `would_pause` 인 태스크를 **이 자리에서** `PAUSED` 로 보낸다.

        봉투 집행(Q10b)과 같은 자리·같은 길이다: 턴의 맨 앞, 자식의 한 걸음 전이고,
        멈춤은 `pause_task` 한 트랜잭션(판정 `monitor.judged` + `task.status.changed`)이다.
        에이전트 태스크만이 아니라 **모든** 태스크를 본다.

        판정이 멈춤이 아니면 섀도와 같이 `monitor.judged` 하나만 남긴다(`enforced: true`).
        원장을 읽지 못하거나 감시자가 고장 나면 멈추지 않는다(MP5) -- Jev 의 실패는
        고장이 아니라 폴백 판정이다(`judge`). 멈춤 커밋의 실패(`StaleExecutionLease`)는
        그대로 올라간다. 반환값은 멈춤의 `task.status.changed` 이벤트, 아니면 `None`.
        """
        monitor = getattr(self, "_monitor", None)
        reader = getattr(deps.events, "list_after", None)
        if monitor is None or not getattr(monitor, "enforce", False) or not callable(reader):
            return None
        try:
            events = await monitor.read_ledger(reader, input.task_id)
            if not monitor.due(events):
                return None
            payload = await monitor.judge(events, mode=getattr(input, "mode", "interactive"))
            if not payload.get("would_pause"):
                await deps.events.append(
                    task_id=input.task_id,
                    event_type="monitor.judged",
                    payload=payload,
                    run_id=input.run_id,
                )
                return None
        except Exception:  # noqa: BLE001 -- 위 독스트링: 고장은 멈춤이 아니다
            logger.warning("trajectory monitor failed", exc_info=True)
            return None
        commit = await deps.repository.pause_task(
            lease=deps.lease,
            judgement_type="monitor.judged",
            judgement=payload,
            reason_code=pause_reason_code(payload),
            now=self._clock(),
        )
        return commit.status_event

    async def _advance_one_model_turn(self, input, state, bound, deps):
        check_usage_budgets(self._config, state)
        if state.turn_count >= self._config.max_turns:
            raise CodingLoopFailure("turn_budget_exceeded", retryable=False)
        # 멈춤 자리(Q10b·Q5b). 봉투가 먼저다(MP4): 둘이 같은 턴에 멈추려 해도 멈춤
        # 트랜잭션은 하나다 -- 봉투가 멈추면 감시자는 이 턴을 판정하지 않는다.
        paused = await self._envelope_pause_point(input, deps)
        if paused is None:
            paused = await self._monitor_pause_point(input, deps)
        if paused is not None:
            yield paused
            return
        # The safe point (K3). Before anything is built for this turn, every
        # detached child gets one step and every finished one hands its report
        # to the transcript -- so the report is in the request this turn sends,
        # and it lands as an append, ahead of the thinking guard below.
        state = await self._advance_detached_children(state, bound, deps)
        await self._monitor_safe_point(input, deps)
        await self._envelope_safe_point(input, deps)
        state, system, tools = await self._prepare_turn(input, state, bound)
        request = ModelRequest(
            system=system,
            messages=state.transcript,
            tools=tools,
            model=self._config.model,
            limits=self._model_limits(state),
            task_id=input.task_id,
            run_id=input.run_id,
            turn_id=f"turn_{uuid4().hex}",
        )
        turn = _TurnStream(part_id=f"ctp_{uuid4().hex}")
        started = await self._text_part_call(
            deps.repository.start_model_text_part,
            lease=deps.lease,
            part_id=turn.part_id,
            turn_id=request.turn_id,
            now=self._clock(),
        )
        yield started.event
        try:
            async for event in self._stream_turn(input, state, bound, deps, request, turn):
                yield event
        except CodingModelError as error:
            if error.code != "prompt_too_long":
                raise CodingLoopFailure(
                    error.code, retryable=error.retryable and not turn.persisted_stream
                ) from error
            recovered = await self._recover_prompt_too_long(state, error)
            committed = await self._commit_model(
                input, bound, deps, recovered, {"reason_code": "prompt_too_long"}
            )
            yield committed.event
            return
        if turn.completion is None:
            raise CodingLoopFailure(
                "model_stream_incomplete", retryable=not turn.persisted_stream
            )
        completed_part = await self._text_part_call(
            deps.repository.complete_model_text_part,
            lease=deps.lease,
            part_id=turn.part_id,
            turn_id=request.turn_id,
            now=self._clock(),
        )
        yield completed_part.event
        self._record_turn_metric(turn.completion)
        await invoke_post_generate(
            self._hooks, "".join(turn.text_parts), state.transcript
        )
        async for event in self._settle_turn(input, state, bound, deps, request, turn):
            yield event

    # -- stage 1: prepare ----------------------------------------------------

    async def _prepare_turn(self, input, state, bound):
        if not state.instructions_loaded:
            state = await self._load_workspace_instructions(state, bound)
        note = await invoke_pre_generate(self._hooks, state.transcript)
        append = str(note.get("append") or "")
        if append:
            state = self._with_note(state, append)
        system = await coding_turn_system(
            with_mode_overlay(self._config.system, getattr(input, "mode", "")),
            input.owner_id,
        )
        system = inject_previous_summary(system, state.summary)
        system = await coding_turn_overlay(system, input.owner_id)
        system_note = str(note.get("system") or "")
        if system_note:
            # Appended, never folded into `system`: rebuilding the system
            # prompt per turn invalidates every later thinking block.
            state = self._with_transcript(
                state,
                state.transcript
                + (CanonicalMessage("system", (SystemNoteContent(system_note),)),),
            )
        tools = self._catalog.definitions(state)
        state = self._guard_thinking_prefix(state, system, tools)
        return state, system, tools

    async def _load_workspace_instructions(self, state, bound) -> AgentLoopState:
        text = self._instruction_tree_text(bound.session)
        if text is None:
            files: dict[str, bytes] = {}
            for name in INSTRUCTION_CANDIDATES:
                try:
                    files[name] = await bound.session.read_file(name)
                except Exception:
                    continue
            text = load_workspace_instructions(files)
        if not text:
            return replace(state, instructions_loaded=True)
        return self._with_note(state, text, instructions_loaded=True)

    @staticmethod
    def _instruction_tree_text(session) -> str | None:
        """Instructions from the host workspace tree, if the session has one."""
        workspace = getattr(getattr(session, "_record", None), "workspace", None)
        if workspace is None:
            return None
        try:
            root = Path(workspace)
            raw_start = getattr(session, "cwd", None)
            if raw_start in {None, ""}:
                start = root
            else:
                start = Path(raw_start)
                if not start.is_absolute():
                    start = root / start
            return load_workspace_instruction_tree(root, start=start)
        except Exception:
            return None

    def _guard_thinking_prefix(
        self,
        state: AgentLoopState,
        system: str,
        tools: Sequence[ToolDefinition],
    ) -> AgentLoopState:
        """Keep replayed thinking valid across every non-append edit.

        Claude Fable 5.1 binds a thinking block to the system prompt, the
        tool set, and every earlier message. Compaction, head drops, result
        shrinking, a rebuilt system prompt, and a revealed tool all change
        that prefix. Rather than teach each of those paths, this one check
        compares what the last request carried with what this one would,
        and strips all thinking once where they differ.
        """
        transcript = state.transcript
        fingerprint = _request_fingerprint(system, tools)
        count = state.sent_prefix_count
        if count and (
            count > len(transcript)
            or self._prefix_digest(fingerprint, transcript[:count])
            != state.sent_prefix_digest
        ):
            transcript = strip_thinking(transcript)
        return self._with_transcript(
            state,
            transcript,
            sent_prefix_count=len(transcript),
            sent_prefix_digest=self._prefix_digest(fingerprint, transcript),
        )

    def _prefix_digest(
        self, fingerprint: str, messages: tuple[CanonicalMessage, ...]
    ) -> str:
        return hashlib.sha256(
            f"{fingerprint}:{self._digest(messages)}".encode()
        ).hexdigest()

    def _model_limits(self, state: AgentLoopState) -> ModelLimits:
        max_output_tokens = self._config.max_output_tokens
        if state.output_token_escalations:
            max_output_tokens = min(max_output_tokens * 4, 64_000)
        return ModelLimits(
            max_output_tokens,
            self._config.timeout_sec,
            context_window=self._config.context_window,
            input_limit=self._config.input_limit,
            thinking_budget=self._config.thinking_budget,
            effort=self._config.effort,
        )

    # -- stage 2: stream -----------------------------------------------------

    @staticmethod
    async def _text_part_call(method, **kwargs):
        try:
            return await method(**kwargs)
        except TextPartConflict as error:
            raise CodingLoopFailure(str(error), retryable=False) from error

    async def _abort_turn(self, input, state, bound, deps, turn: _TurnStream):
        turn.cancel_prefetch()
        await self._persist_abort_after_cancel(input, state, bound, deps)

    async def _stream_turn(self, input, state, bound, deps, request, turn: _TurnStream):
        try:
            if await self._has_pending_interrupt(deps, input.task_id):
                await self._persist_abort_after_cancel(input, state, bound, deps)
                raise asyncio.CancelledError
            async for model_event in iter_model_turn(self._model, request):
                if await self._has_pending_interrupt(deps, input.task_id):
                    await self._abort_turn(input, state, bound, deps, turn)
                    raise asyncio.CancelledError
                folded = fold_model_event(
                    model_event,
                    text_parts=turn.text_parts,
                    tool_calls=turn.calls,
                    thinking=turn.thinking,
                )
                if folded is not None:
                    turn.completion = folded
                event = await self._on_model_event(
                    input, state, bound, deps, request, turn, model_event
                )
                if event is not None:
                    yield event
        except asyncio.CancelledError:
            await self._abort_turn(input, state, bound, deps, turn)
            raise
        except CodingModelError:
            turn.cancel_prefetch()
            raise

    async def _on_model_event(
        self, input, state, bound, deps, request, turn: _TurnStream, model_event
    ):
        """Side effects of one stream event; the ledger event to yield, if any."""
        if isinstance(model_event, TextDelta):
            delta_bytes = len(model_event.text.encode("utf-8"))
            if delta_bytes > self._config.max_text_delta_bytes:
                raise CodingLoopFailure("model_text_delta_too_large", retryable=False)
            committed = await self._text_part_call(
                deps.repository.append_model_text_delta,
                lease=deps.lease,
                part_id=turn.part_id,
                turn_id=request.turn_id,
                delta=model_event.text,
                delta_bytes=delta_bytes,
                max_part_bytes=self._config.max_public_text_bytes,
                now=self._clock(),
            )
            turn.persisted_stream = True
            return committed.event
        if isinstance(model_event, ThinkingCompleted):
            # A status line, not the block. The signature is opaque
            # provenance and never belongs in a display event.
            #
            # This deliberately does not set `persisted_stream`: thinking
            # arrives at the head of a turn, so treating it as durable output
            # would make almost every turn unretryable after a transient
            # error. A retry repeats a status line, which the next turn
            # overwrites anyway.
            preview = model_event.thinking[:THINKING_PREVIEW_CHARS]
            return await deps.events.append(
                task_id=input.task_id,
                event_type="model.thinking",
                payload={
                    "preview": preview,
                    "chars": len(model_event.thinking),
                    "truncated": len(model_event.thinking) > len(preview),
                },
                run_id=input.run_id,
                turn_id=request.turn_id,
            )
        if isinstance(model_event, ToolInputDelta):
            turn.persisted_stream = True
            return await deps.events.append(
                task_id=input.task_id,
                event_type="model.tool_input_delta",
                payload={
                    "tool_call_id": model_event.tool_call_id,
                    "bytes": len(model_event.partial_json.encode("utf-8")),
                },
                run_id=input.run_id,
                turn_id=request.turn_id,
                tool_call_id=model_event.tool_call_id,
            )
        if isinstance(model_event, ToolCallCompleted):
            task = self._maybe_prefetch_readonly(model_event, bound, state)
            if task is not None:
                turn.prefetch_tasks[model_event.tool_call_id] = task
        return None

    async def _recover_prompt_too_long(self, state, error) -> AgentLoopState:
        if state.prompt_compact_retries < 1:
            return await self._compact_after_prompt_too_long(state)
        if state.prompt_compact_retries < _PROMPT_TOO_LONG_RETRIES:
            return self._head_drop_after_prompt_too_long(state)
        raise CodingLoopFailure("prompt_too_long", retryable=False) from error

    def _record_turn_metric(self, completion: ModelCompleted) -> None:
        if self._metrics is None:
            return
        outcome = (
            completion.stop_reason
            if completion.stop_reason in _METRIC_STOP_REASONS
            else "other"
        )
        self._metrics.coding_model_turn_total.labels(
            provider=self._config.provider, outcome=outcome
        ).inc()

    # -- stage 3: settle -----------------------------------------------------

    async def _settle_turn(self, input, state, bound, deps, request, turn: _TurnStream):
        completion = turn.completion
        if (
            not turn.calls
            and completion.stop_reason == "max_tokens"
            and state.output_token_escalations < 1
        ):
            # Cut at the output ceiling with nothing to act on: retry once
            # with a larger ceiling (`_model_limits`) instead of failing.
            retry_state = replace(
                with_turn_usage(self._config, state, completion),
                instructions_loaded=True,
                output_token_escalations=state.output_token_escalations + 1,
            )
            check_usage_budgets(self._config, retry_state)
            committed = await self._commit_model(
                input, bound, deps, retry_state, _completion_payload(completion)
            )
            yield committed.event
            return
        next_state = await self._completed_turn(
            state, turn.text_parts, turn.calls, completion, turn.thinking
        )
        check_usage_budgets(self._config, next_state)
        prefetch = await self._await_prefetch(turn.prefetch_tasks)
        if completion.stop_reason == "refusal":
            # A refusal is an answer, not a truncated turn. It gets its own
            # code and its own event so it never reads as a transport fault,
            # and it is never retried: the same request refuses again.
            await deps.events.append(
                task_id=input.task_id,
                event_type="model.refused",
                payload={
                    "stop_reason": "refusal",
                    "stop_category": completion.stop_category,
                },
                run_id=input.run_id,
                turn_id=request.turn_id,
            )
            raise CodingLoopFailure("model_refused", retryable=False)
        if turn.calls:
            committed = await self._commit_model(
                input, bound, deps, next_state, _completion_payload(completion)
            )
            yield committed.event
            async for event in self._advance_one_tool(
                input, next_state, bound, deps, prefetch=prefetch
            ):
                yield event
            return
        settled, payload = await self._settle_text_only_turn(
            next_state,
            _scrub_think_blocks("".join(turn.text_parts)),
            completion.stop_reason,
        )
        committed = await self._commit_model(input, bound, deps, settled, payload)
        yield committed.event

    async def _settle_text_only_turn(
        self, state: AgentLoopState, public_text: str, stop_reason: str
    ) -> tuple[AgentLoopState, dict[str, str]]:
        """What a turn without tool calls commits as, first match wins.

        hold (phase incomplete, or children still running) -> empty retry ->
        stop-hook retry -> terminal. Anything that fits none of them raises.
        """
        if stop_reason not in {"end_turn", "unknown"}:
            raise _incomplete()
        held = self._hold_incomplete_phase(state, public_text)
        if held is None:
            held = self._hold_for_detached_children(state)
        if held is not None:
            return held, {"stop_reason": stop_reason}
        if _is_empty_or_think_only(public_text):
            retry = self._maybe_empty_retry(state)
            if retry is None:
                raise _incomplete()
            return retry, {"reason_code": "empty_retry"}
        if stop_reason != "end_turn":
            raise _incomplete()
        retry = await self._maybe_stop_retry(state, stop_reason)
        if retry is not None:
            return retry, {"reason_code": "stop_retry"}
        final = replace(self._with_phase_artifacts(state, public_text), terminal_pending=True)
        return final, {"stop_reason": stop_reason}

    def _hold_incomplete_phase(
        self, state: AgentLoopState, text: str
    ) -> AgentLoopState | None:
        phase = parse_phase(state.phase)
        if phase is CodingAgentPhase.VERIFY and parse_verify_verdict(text) is None:
            note = (
                "Verify is incomplete. End with `VERDICT: PASS`, "
                "`VERDICT: FAIL`, or `VERDICT: PARTIAL`. Stay in verify."
            )
        elif phase is CodingAgentPhase.PLAN and (
            parse_plan_critical_files(text) is None or not plan_text_has_body(text)
        ):
            note = (
                "Plan is incomplete. Include a plan body and a `Critical Files:` "
                "heading. Stay in plan."
            )
        else:
            return None
        return self._with_note(state, note, terminal_pending=False)

    def _with_phase_artifacts(
        self, state: AgentLoopState, text: str
    ) -> AgentLoopState:
        phase = parse_phase(state.phase)
        if phase is CodingAgentPhase.VERIFY:
            return replace(state, verdict=persist_verify_verdict(text))
        if phase is CodingAgentPhase.PLAN:
            return replace(state, critical_files=persist_plan_critical_files(text))
        return state

    async def _stop_decision(self, reason: str) -> tuple[str, str]:
        try:
            raw = await self._hooks.stop(reason)
        except Exception:
            return "allow", ""
        return parse_stop_decision(raw)

    async def _maybe_stop_retry(
        self, state: AgentLoopState, reason: str
    ) -> AgentLoopState | None:
        decision, meta = await self._stop_decision(reason)
        if decision != "retry" or state.stop_retry_count >= STOP_RETRY_LIMIT:
            return None
        return self._with_note(
            state,
            meta or "Stop hook requested another turn.",
            terminal_pending=False,
            stop_retry_count=state.stop_retry_count + 1,
        )

    def _maybe_empty_retry(self, state: AgentLoopState) -> AgentLoopState | None:
        if state.empty_retry_count >= EMPTY_RETRY_LIMIT:
            return None
        return self._with_note(
            state,
            "Model produced no public text. Continue or use a tool.",
            terminal_pending=False,
            empty_retry_count=state.empty_retry_count + 1,
        )


def with_mode_overlay(system: str, mode: str) -> str:
    """K9: an autonomous task's system prompt opens with the official P-01 blocks
    and P-02 (autonomous only for now -- in interactive it would be a boundary).

    **In front**, not appended: the roadmap's principle 2 is that the first
    sentence declares the mode, and P-01's own first sentence ("The user is
    not watching in real time") is what carries the effect. An interactive
    task gets `system` back unchanged -- byte for byte, so nothing that runs
    today moves. The mode is fixed per task, so the prefix is stable across
    its turns (thinking guard, prompt cache).
    """
    if mode != "autonomous":
        return system
    from neos.coding.prompts.official import (
        AUTONOMOUS_EXECUTION,
        DELIVERING_WORK,
        SCOPE_OF_CHANGES,
    )

    return (
        f"{AUTONOMOUS_EXECUTION}\n\n{DELIVERING_WORK}\n\n{SCOPE_OF_CHANGES}"
        f"\n\n{system}"
    )


def _completion_payload(completion) -> dict[str, object]:
    """`model.completed` 의 payload. 이 턴의 토큰을 싣는다(트랙 Q5 FB6).

    체크포인트의 누적값으로는 원장이 "어느 턴이 얼마를 썼나"를 말하지 못한다.
    usage 를 모르는 턴은 토큰 키를 **싣지 않는다** -- 0 을 적으면 없는 값이
    측정값처럼 읽힌다.
    """
    payload: dict[str, object] = {"stop_reason": completion.stop_reason}
    usage = getattr(completion, "usage", None)
    if usage is not None:
        payload["input_tokens"] = int(usage.input_tokens)
        payload["output_tokens"] = int(usage.output_tokens)
    return payload


async def _read_ledger(reader, task_id: str, *, limit: int) -> list:
    """태스크의 원장을 앞에서부터 읽고 최근 `limit` 개를 돌려준다."""
    events: list = []
    after = 0
    while True:
        page = await reader(task_id, after_seq=after, limit=500)
        if not page:
            break
        events.extend(page)
        after = page[-1].seq
        if len(page) < 500:
            break
    return events[-limit:]

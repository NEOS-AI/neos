from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4
from pathlib import Path

from neos.coding.domain.events import CodingEvent
from neos.coding.domain.text_parts import TextPartConflict
from neos.coding.domain.approvals import (
    ApprovalGate,
    ApprovalMode,
    ApprovalPolicyOutcome,
    evaluate_approval,
)
from neos.coding.domain.phases import CodingCheckpoint
from neos.coding.harness import fold_model_event, iter_model_turn
from neos.coding.instructions import (
    INSTRUCTION_CANDIDATES,
    load_workspace_instruction_tree,
    load_workspace_instructions,
)
from neos.coding.learn_lessons import coding_turn_system
from neos.coding.loop.base import LoopDependencies, LoopInput
from neos.coding.prompts import inject_previous_summary
from neos.coding.model.errors import CodingModelError
from neos.coding.model.base import (
    CanonicalMessage,
    CodingModel,
    ModelCompleted,
    ModelLimits,
    ModelRequest,
    SystemNoteContent,
    TextContent,
    TextDelta,
    ThinkingCompleted,
    ThinkingContent,
    ToolCallCompleted,
    ToolDefinition,
    ToolInputDelta,
    ToolResultContent,
    ToolUseContent,
    strip_thinking,
)
from neos.config.model_identity import usable_window_tokens
from neos.coding.phases import (
    CodingAgentPhase,
    hidden_tools_for_phase,
    parse_phase,
    parse_plan_critical_files,
    parse_verify_verdict,
    plan_text_has_body,
    persist_plan_critical_files,
    persist_verify_verdict,
)
from neos.coding.hooks import CodingHookPort, NullCodingHooks, post_tool_prevented
from neos.coding.loop.hooks import (
    invoke_post_generate,
    invoke_pre_generate,
)
from neos.coding.redact import redact_sensitive, strip_binary_payloads
from neos.coding.sandbox.bindings import SandboxBindingService
from neos.coding.sandbox.observability import (
    CodingToolAuditEvent,
    NullCodingAuditSink,
)
from neos.coding.sandbox.paths import normalize_workspace_path
from neos.coding.tools.executor import SandboxToolExecutor
from neos.coding.tools.registry import (
    CodingToolRegistry,
    ToolRisk,
)
from neos.coding.loop._durable.state import (
    ActiveChildRef as ActiveChildRef,
    AgentLoopState as AgentLoopState,
    COMPACT_REF_THRESHOLD_BYTES as COMPACT_REF_THRESHOLD_BYTES,
    CodingLoopConfig as CodingLoopConfig,
    CodingLoopFailure as CodingLoopFailure,
    CodingLoopWaitingApproval as CodingLoopWaitingApproval,
    DEFAULT_MAX_TRANSCRIPT_TOKENS as DEFAULT_MAX_TRANSCRIPT_TOKENS,
    DelegatedSpawn as DelegatedSpawn,
    EMPTY_RETRY_LIMIT as EMPTY_RETRY_LIMIT,
    STALL_DENY_AFTER as STALL_DENY_AFTER,
    STOP_RETRY_LIMIT as STOP_RETRY_LIMIT,
    SpawnWork as SpawnWork,
    _AppliedPendingCommand as _AppliedPendingCommand,
    _BRIEF_PLACEHOLDER_RE as _BRIEF_PLACEHOLDER_RE,
    _CONTROL_PLANE_TOOLS as _CONTROL_PLANE_TOOLS,
    _EPOCH_STAMP as _EPOCH_STAMP,
    _STALE_SLACK_SEC as _STALE_SLACK_SEC,
    _STUB_GOALS as _STUB_GOALS,
    _THINK_CLOSED_RE as _THINK_CLOSED_RE,
    _THINK_UNCLOSED_RE as _THINK_UNCLOSED_RE,
    _UNCHANGED_PREVIEW as _UNCHANGED_PREVIEW,
)
from neos.coding.loop._durable.support import (
    _LINE_NUMBERED_RE as _LINE_NUMBERED_RE,
    _discard_lease as _discard_lease,
    _dump_read_stamp as _dump_read_stamp,
    _error_signature as _error_signature,
    _executor_read_stamps as _executor_read_stamps,
    _has_open_tool_pair as _has_open_tool_pair,
    _is_empty_or_think_only as _is_empty_or_think_only,
    _is_stall_denied as _is_stall_denied,
    _is_unchanged_stub as _is_unchanged_stub,
    _lease_from_ref as _lease_from_ref,
    _legacy_single as _legacy_single,
    _looks_like_file_read as _looks_like_file_read,
    _message_from_mapping as _message_from_mapping,
    _message_to_mapping as _message_to_mapping,
    _next_error_signature as _next_error_signature,
    _next_success_signature as _next_success_signature,
    _nonneg_int as _nonneg_int,
    _open_implement_worktree as _open_implement_worktree,
    _optional_str as _optional_str,
    _parse_utc_stamp as _parse_utc_stamp,
    _pending_by_id as _pending_by_id,
    _read_paths_from_transcript as _read_paths_from_transcript,
    _read_stamps_mapping as _read_stamps_mapping,
    _restore_active_children as _restore_active_children,
    _result_preview_hash as _result_preview_hash,
    _scrub_think_blocks as _scrub_think_blocks,
    _select_spawn_work as _select_spawn_work,
    _session_on_workspace as _session_on_workspace,
    _session_workspace as _session_workspace,
    _spawn_window as _spawn_window,
    _stamp_is_stale as _stamp_is_stale,
    _string_mapping as _string_mapping,
    _subagent_max_active as _subagent_max_active,
    _tool_event_payload as _tool_event_payload,
    _tool_event_preview as _tool_event_preview,
    _tool_result_bytes as _tool_result_bytes,
    _tool_result_ids as _tool_result_ids,
    _tool_use_names as _tool_use_names,
    _unchanged_stub_content as _unchanged_stub_content,
    _uniquify_tool_calls as _uniquify_tool_calls,
    _usage_tokens as _usage_tokens,
    _usage_window as _usage_window,
    _warn_stale_active_child_scalars as _warn_stale_active_child_scalars,
)
from neos.coding.loop._durable.tools import (
    ToolExecutionMixin as ToolExecutionMixin,
)
from neos.coding.loop._durable.spawn import (
    SubagentSpawnMixin as SubagentSpawnMixin,
)
from neos.coding.loop._durable.compaction import (
    CompactionMixin as CompactionMixin,
    _ref_tool_result as _ref_tool_result,
)
from neos.coding.loop._durable.checkpoint import (
    CheckpointMixin as CheckpointMixin,
)

logger = logging.getLogger(__name__)

# Read by `_pre_tool_decision` and `_execute_validated` on the core class.
# Keep both readers in this module: tests monkeypatch it on this module object.
PRE_TOOL_HOOK_TIMEOUT_SEC = 5.0
# One status line's worth. `max_text_delta_bytes` governs durable model text
# and is three orders of magnitude too large for this.
THINKING_PREVIEW_CHARS = 200


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


class DurableCodingLoop(ToolExecutionMixin, SubagentSpawnMixin, CompactionMixin, CheckpointMixin):
    def __init__(
        self,
        *,
        model: CodingModel,
        tools: CodingToolRegistry,
        executor: SandboxToolExecutor,
        bindings: SandboxBindingService,
        config: CodingLoopConfig,
        metrics=None,
        audit=None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        approval_evaluator: Callable[..., ApprovalPolicyOutcome] = evaluate_approval,
        hooks: CodingHookPort | None = None,
        subagents=None,
    ) -> None:
        self._model = model
        self._tools = tools
        self._executor = executor
        self._bindings = bindings
        self._config = config
        self._metrics = metrics
        self._audit = audit or NullCodingAuditSink()
        self._clock = clock
        self._approval_evaluator = approval_evaluator
        self._hooks = hooks or NullCodingHooks()
        self._subagents = subagents

    def _approval_gate(self, state: AgentLoopState) -> ApprovalGate:
        try:
            mode = ApprovalMode(self._config.approval_mode)
        except ValueError:
            mode = ApprovalMode.MANUAL
        return ApprovalGate(
            mode=mode,
            deny_tools=frozenset(self._config.approval_deny_tools),
            allow_tools=frozenset(self._config.approval_allow_tools),
            always_allow=frozenset(self._config.approval_always_allow),
            approved_always=state.approved_always,
            current_phase=state.phase,
            unattended=self._config.approval_unattended,
        )

    def _evaluate_call(self, validated, state: AgentLoopState) -> ApprovalPolicyOutcome:
        gate = self._approval_gate(state)
        try:
            return self._approval_evaluator(validated, gate)
        except TypeError:
            return self._approval_evaluator(validated)

    @staticmethod
    def _with_approval_answers(validated, approval) -> Any:
        if validated.name != "ask_user.v1":
            return validated
        answers = approval.display_summary.get("answers")
        if not isinstance(answers, list):
            return validated
        merged = dict(validated.input)
        merged["answers"] = [str(item) for item in answers]
        return replace(validated, input=merged)

    async def run(
        self,
        input: LoopInput,
        checkpoint: CodingCheckpoint | None,
        deps: LoopDependencies,
    ) -> AsyncIterator[CodingEvent]:
        lease = deps.lease
        if lease is None:
            raise RuntimeError("real coding loop requires an execution lease")
        state = self._restore(input, checkpoint)
        if state.terminal_pending:
            return
        if state.consecutive_tool_errors >= self._config.max_consecutive_tool_errors:
            raise CodingLoopFailure("tool_error_budget_exceeded", retryable=False)
        bound = await self._bindings.resolve(lease)
        if state.has_pending_tool:
            async for event in self._advance_one_tool(input, state, bound, deps):
                yield event
            return
        async for event in self._advance_one_model_turn(input, state, bound, deps):
            yield event

    async def _advance_one_model_turn(self, input, state, bound, deps):
        self._check_usage_budgets(state)
        if state.turn_count >= self._config.max_turns:
            raise CodingLoopFailure("turn_budget_exceeded", retryable=False)
        if not state.instructions_loaded:
            state = await self._load_workspace_instructions(state, bound)
        note = await invoke_pre_generate(self._hooks, state.transcript)
        append = str(note.get("append") or "")
        if append:
            transcript = self._append_user_meta(state.transcript, append)
            state = replace(
                state,
                transcript=transcript,
                transcript_digest=self._digest(transcript),
            )
        system = await coding_turn_system(self._config.system, input.owner_id)
        system = inject_previous_summary(system, state.summary)
        system_note = str(note.get("system") or "")
        if system_note:
            # Appended, never folded into `system`: rebuilding the system
            # prompt per turn invalidates every later thinking block.
            transcript = state.transcript + (
                CanonicalMessage("system", (SystemNoteContent(system_note),)),
            )
            state = replace(
                state,
                transcript=transcript,
                transcript_digest=self._digest(transcript),
            )
        tools = self._tool_definitions(state)
        state = self._guard_thinking_prefix(state, system, tools)
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
        part_id = f"ctp_{uuid4().hex}"
        persisted_stream = False
        try:
            started = await deps.repository.start_model_text_part(
                lease=deps.lease,
                part_id=part_id,
                turn_id=request.turn_id,
                now=self._clock(),
            )
        except TextPartConflict as error:
            raise CodingLoopFailure(str(error), retryable=False) from error
        yield started.event
        text_parts: list[str] = []
        calls: list[ToolCallCompleted] = []
        thinking: list[ThinkingCompleted] = []
        completion: ModelCompleted | None = None
        prefetch_tasks: dict[str, asyncio.Task] = {}
        try:
            if await self._has_pending_interrupt(deps, input.task_id):
                await self._persist_abort_after_cancel(input, state, bound, deps)
                raise asyncio.CancelledError
            async for model_event in iter_model_turn(self._model, request):
                if await self._has_pending_interrupt(deps, input.task_id):
                    for task in prefetch_tasks.values():
                        task.cancel()
                    await self._persist_abort_after_cancel(input, state, bound, deps)
                    raise asyncio.CancelledError
                folded = fold_model_event(
                    model_event,
                    text_parts=text_parts,
                    tool_calls=calls,
                    thinking=thinking,
                )
                if folded is not None:
                    completion = folded
                if isinstance(model_event, TextDelta):
                    delta_bytes = len(model_event.text.encode("utf-8"))
                    if delta_bytes > self._config.max_text_delta_bytes:
                        raise CodingLoopFailure(
                            "model_text_delta_too_large", retryable=False
                        )
                    try:
                        committed = await deps.repository.append_model_text_delta(
                            lease=deps.lease,
                            part_id=part_id,
                            turn_id=request.turn_id,
                            delta=model_event.text,
                            delta_bytes=delta_bytes,
                            max_part_bytes=self._config.max_public_text_bytes,
                            now=self._clock(),
                        )
                    except TextPartConflict as error:
                        raise CodingLoopFailure(str(error), retryable=False) from error
                    persisted_stream = True
                    yield committed.event
                elif isinstance(model_event, ThinkingCompleted):
                    # A status line, not the block. The signature is opaque
                    # provenance and never belongs in a display event.
                    #
                    # This deliberately does not set `persisted_stream`:
                    # thinking arrives at the head of a turn, so treating it as
                    # durable output would make almost every turn unretryable
                    # after a transient error. A retry repeats a status line,
                    # which the next turn overwrites anyway.
                    preview = model_event.thinking[:THINKING_PREVIEW_CHARS]
                    yield await deps.events.append(
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
                elif isinstance(model_event, ToolInputDelta):
                    persisted_stream = True
                    yield await deps.events.append(
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
                elif isinstance(model_event, ToolCallCompleted):
                    task = self._maybe_prefetch_readonly(
                        model_event, bound, state
                    )
                    if task is not None:
                        prefetch_tasks[model_event.tool_call_id] = task
        except asyncio.CancelledError:
            for task in prefetch_tasks.values():
                task.cancel()
            await self._persist_abort_after_cancel(input, state, bound, deps)
            raise
        except CodingModelError as error:
            for task in prefetch_tasks.values():
                task.cancel()
            if error.code == "prompt_too_long":
                if state.prompt_compact_retries < 1:
                    compacted = await self._compact_after_prompt_too_long(state)
                elif state.prompt_compact_retries < 4:
                    compacted = self._head_drop_after_prompt_too_long(state)
                else:
                    raise CodingLoopFailure("prompt_too_long", retryable=False) from error
                committed = await deps.repository.commit_model_checkpoint(
                    lease=deps.lease,
                    event_type="model.completed",
                    event_payload={"reason_code": "prompt_too_long"},
                    loop_state=self._dump_state(input, compacted),
                    workspace_revision=str(bound.binding.workspace_revision),
                    now=self._clock(),
                )
                yield committed.event
                return
            raise CodingLoopFailure(
                error.code, retryable=error.retryable and not persisted_stream
            ) from error
        if completion is None:
            raise CodingLoopFailure(
                "model_stream_incomplete", retryable=not persisted_stream
            )
        try:
            completed_part = await deps.repository.complete_model_text_part(
                lease=deps.lease,
                part_id=part_id,
                turn_id=request.turn_id,
                now=self._clock(),
            )
        except TextPartConflict as error:
            raise CodingLoopFailure(str(error), retryable=False) from error
        yield completed_part.event
        if self._metrics is not None:
            outcome = (
                completion.stop_reason
                if completion.stop_reason
                in {"tool_use", "end_turn", "max_tokens", "refusal"}
                else "other"
            )
            self._metrics.coding_model_turn_total.labels(
                provider=self._config.provider, outcome=outcome
            ).inc()
        await invoke_post_generate(
            self._hooks, "".join(text_parts), state.transcript
        )
        if (
            not calls
            and completion.stop_reason == "max_tokens"
            and state.output_token_escalations < 1
        ):
            in_tokens, out_tokens = _usage_tokens(completion)
            cache_read, cache_write, reasoning = _usage_window(completion)
            retry_state = replace(
                state,
                instructions_loaded=True,
                output_token_escalations=state.output_token_escalations + 1,
                input_tokens=state.input_tokens + in_tokens,
                output_tokens=state.output_tokens + out_tokens,
                cache_read_tokens=state.cache_read_tokens + cache_read,
                cache_write_tokens=state.cache_write_tokens + cache_write,
                reasoning_tokens=state.reasoning_tokens + reasoning,
                cost_micros=state.cost_micros
                + self._price_tokens(
                    in_tokens,
                    out_tokens,
                    cache_read_tokens=cache_read,
                    cache_write_tokens=cache_write,
                ),
                last_prompt_tokens=in_tokens,
            )
            self._check_usage_budgets(retry_state)
            committed = await deps.repository.commit_model_checkpoint(
                lease=deps.lease,
                event_type="model.completed",
                event_payload={"stop_reason": completion.stop_reason},
                loop_state=self._dump_state(input, retry_state),
                workspace_revision=str(bound.binding.workspace_revision),
                now=self._clock(),
            )
            yield committed.event
            return
        next_state = await self._completed_turn(
            state, text_parts, calls, completion, thinking
        )
        self._check_usage_budgets(next_state)
        prefetch = await self._await_prefetch(prefetch_tasks)
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
        if not calls:
            public_text = _scrub_think_blocks("".join(text_parts))
            if completion.stop_reason not in {"end_turn", "unknown"}:
                raise CodingLoopFailure("model_output_incomplete", retryable=False)
            held = self._hold_incomplete_phase(next_state, public_text)
            if held is not None:
                committed = await deps.repository.commit_model_checkpoint(
                    lease=deps.lease,
                    event_type="model.completed",
                    event_payload={"stop_reason": completion.stop_reason},
                    loop_state=self._dump_state(input, held),
                    workspace_revision=str(bound.binding.workspace_revision),
                    now=self._clock(),
                )
                yield committed.event
                return
            if _is_empty_or_think_only(public_text):
                retry_state = self._maybe_empty_retry(next_state)
                if retry_state is not None:
                    committed = await deps.repository.commit_model_checkpoint(
                        lease=deps.lease,
                        event_type="model.completed",
                        event_payload={"reason_code": "empty_retry"},
                        loop_state=self._dump_state(input, retry_state),
                        workspace_revision=str(bound.binding.workspace_revision),
                        now=self._clock(),
                    )
                    yield committed.event
                    return
                raise CodingLoopFailure("model_output_incomplete", retryable=False)
            if completion.stop_reason != "end_turn":
                raise CodingLoopFailure("model_output_incomplete", retryable=False)
            retry_state = await self._maybe_stop_retry(
                next_state, completion.stop_reason
            )
            if retry_state is not None:
                committed = await deps.repository.commit_model_checkpoint(
                    lease=deps.lease,
                    event_type="model.completed",
                    event_payload={"reason_code": "stop_retry"},
                    loop_state=self._dump_state(input, retry_state),
                    workspace_revision=str(bound.binding.workspace_revision),
                    now=self._clock(),
                )
                yield committed.event
                return
            next_state = self._with_phase_artifacts(next_state, public_text)
            next_state = self._with_terminal_pending(next_state)
            committed = await deps.repository.commit_model_checkpoint(
                lease=deps.lease,
                event_type="model.completed",
                event_payload={"stop_reason": completion.stop_reason},
                loop_state=self._dump_state(input, next_state),
                workspace_revision=str(bound.binding.workspace_revision),
                now=self._clock(),
            )
            yield committed.event
            return
        committed = await deps.repository.commit_model_checkpoint(
            lease=deps.lease,
            event_type="model.completed",
            event_payload={"stop_reason": completion.stop_reason},
            loop_state=self._dump_state(input, next_state),
            workspace_revision=str(bound.binding.workspace_revision),
            now=self._clock(),
        )
        yield committed.event
        async for event in self._advance_one_tool(
            input, next_state, bound, deps, prefetch=prefetch
        ):
            yield event

    async def _pre_tool_decision(
        self, validated
    ) -> tuple[str, str, Mapping[str, Any] | None]:
        try:
            raw = await asyncio.wait_for(
                self._hooks.pre_tool(validated),
                timeout=PRE_TOOL_HOOK_TIMEOUT_SEC,
            )
        except TimeoutError:
            return "deny", "hook_timeout", None
        except Exception:
            return "deny", "hook_error", None
        if raw is None:
            return "allow", "", None
        if not isinstance(raw, Mapping):
            return "deny", "hook_error", None
        decision = raw.get("decision")
        if decision not in {"allow", "deny", "retry", "prevent"}:
            return "deny", "hook_error", None
        reason = raw.get("reason")
        updated = raw.get("updatedInput")
        if updated is not None and not isinstance(updated, Mapping):
            return "deny", "hook_error", None
        return (
            str(decision),
            str(reason) if reason is not None else "",
            updated if decision == "allow" else None,
        )

    def _with_hook_retry(self, state: AgentLoopState, validated, reason: str):
        del validated, reason
        return replace(
            state,
            hook_retry_count=state.hook_retry_count + 1,
            terminal_pending=False,
        )

    def _append_user_meta(
        self, transcript: tuple[CanonicalMessage, ...], text: str
    ) -> tuple[CanonicalMessage, ...]:
        return tuple(transcript) + (CanonicalMessage("user", (TextContent(text),)),)

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
        return replace(
            state,
            transcript=transcript,
            transcript_digest=self._digest(transcript),
            sent_prefix_count=len(transcript),
            sent_prefix_digest=self._prefix_digest(fingerprint, transcript),
        )

    def _prefix_digest(
        self, fingerprint: str, messages: tuple[CanonicalMessage, ...]
    ) -> str:
        return hashlib.sha256(
            f"{fingerprint}:{self._digest(messages)}".encode()
        ).hexdigest()

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
        transcript = self._append_user_meta(state.transcript, note)
        return replace(
            state,
            transcript=transcript,
            transcript_digest=self._digest(transcript),
            terminal_pending=False,
        )

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
        if raw is None:
            return "allow", ""
        if not isinstance(raw, Mapping):
            return "allow", ""
        decision = raw.get("decision")
        if decision not in {"allow", "prevent", "retry"}:
            return "allow", ""
        detail = raw.get("reason")
        return str(decision), str(detail) if detail is not None else ""

    async def _maybe_stop_retry(
        self, state: AgentLoopState, reason: str
    ) -> AgentLoopState | None:
        decision, meta = await self._stop_decision(reason)
        if decision != "retry" or state.stop_retry_count >= STOP_RETRY_LIMIT:
            return None
        note = meta or "Stop hook requested another turn."
        transcript = self._append_user_meta(state.transcript, note)
        return replace(
            state,
            transcript=transcript,
            transcript_digest=self._digest(transcript),
            terminal_pending=False,
            stop_retry_count=state.stop_retry_count + 1,
        )

    def _maybe_empty_retry(self, state: AgentLoopState) -> AgentLoopState | None:
        if state.empty_retry_count >= EMPTY_RETRY_LIMIT:
            return None
        note = "Model produced no public text. Continue or use a tool."
        transcript = self._append_user_meta(state.transcript, note)
        return replace(
            state,
            transcript=transcript,
            transcript_digest=self._digest(transcript),
            terminal_pending=False,
            empty_retry_count=state.empty_retry_count + 1,
        )

    async def _execute_validated(
        self, bound, deps, validated, *, known_reads, known_stamps, prefetched=None
    ):
        try:
            if prefetched is not None:
                executed = prefetched
            else:
                executed = await self._executor.execute(
                    bound.session,
                    validated,
                    known_reads=known_reads,
                    known_stamps=known_stamps,
                )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            code = (
                "tool_outcome_unknown"
                if validated.risk is not ToolRisk.READ_ONLY
                else "tool_execution_failed"
            )
            await self._audit.emit(
                CodingToolAuditEvent.from_result(
                    provider=bound.binding.provider,
                    tool=validated.name,
                    operation="execute",
                    outcome="error",
                    error_code=code,
                )
            )
            raise CodingLoopFailure(
                code, retryable=validated.risk is ToolRisk.READ_ONLY
            ) from error
        result = strip_binary_payloads(dict(executed.to_mapping()))
        rewritten = None
        try:
            rewritten = await asyncio.wait_for(
                self._hooks.post_tool(validated, result),
                timeout=PRE_TOOL_HOOK_TIMEOUT_SEC,
            )
        except Exception:
            pass
        if post_tool_prevented(rewritten):
            redacted = dict(redact_sensitive(result))
            redacted["_post_tool_prevent"] = True
            return redacted
        if isinstance(rewritten, Mapping):
            result = dict(rewritten)
        return redact_sensitive(result)

    async def _completed_turn(self, state, text_parts, calls, completion, thinking=()):
        content = []
        raw_text = "".join(text_parts)
        text = _scrub_think_blocks(raw_text)
        if text:
            content.append(TextContent(text))
        calls = _uniquify_tool_calls(calls)
        content.extend(
            ToolUseContent(c.tool_call_id, c.name, dict(c.input)) for c in calls
        )
        if content:
            # Thinking leads the turn, in stream order. A thinking-only turn
            # is not appended: it is the empty turn the retry path handles.
            content = [
                ThinkingContent(block.thinking, block.signature) for block in thinking
            ] + content
        transcript = state.transcript
        if content:
            transcript += (CanonicalMessage("assistant", tuple(content)),)
        bodies = dict(state.compacted_bodies)
        before_compact = transcript
        transcript = await self._compact_with_hook(
            transcript, preserve_tools=bool(calls), bodies=bodies
        )
        revealed = state.revealed_tools | self._revealed_from_transcript(
            before_compact
        )
        in_tokens, out_tokens = _usage_tokens(completion)
        cache_read, cache_write, reasoning = _usage_window(completion)
        cost = state.cost_micros + self._price_tokens(
            in_tokens,
            out_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
        )
        reset_empty = bool(calls) or not _is_empty_or_think_only(text)
        return replace(
            state,
            transcript=transcript,
            turn_count=state.turn_count + 1,
            pending_tool_calls=tuple(calls),
            pending_tool_index=0,
            transcript_digest=self._digest(transcript),
            input_tokens=state.input_tokens + in_tokens,
            output_tokens=state.output_tokens + out_tokens,
            cache_read_tokens=state.cache_read_tokens + cache_read,
            cache_write_tokens=state.cache_write_tokens + cache_write,
            reasoning_tokens=state.reasoning_tokens + reasoning,
            cost_micros=cost,
            terminal_pending=False,
            compacted_bodies=bodies,
            revealed_tools=revealed,
            last_prompt_tokens=in_tokens,
            empty_retry_count=0 if reset_empty else state.empty_retry_count,
        )

    async def _after_result(
        self,
        state,
        result,
        *,
        tool_name: str,
        tool_input: Mapping[str, object],
        advance_index: bool = True,
    ):
        has_more_tools = state.pending_tool_index + 1 < len(state.pending_tool_calls)
        bodies = dict(state.compacted_bodies)
        transcript = self._maybe_ref_latest_tool_result(
            state.transcript + (CanonicalMessage("tool", (result,)),),
            tool_name=tool_name,
            bodies=bodies,
        )
        transcript = await self._compact_with_hook(
            transcript,
            preserve_tools=has_more_tools,
            bodies=bodies,
        )
        reason = ""
        if isinstance(result.content, Mapping):
            reason = str(result.content.get("reason_code") or "")
        if result.status == "ok":
            errors = 0
            last_error_signature = ""
            last_error_count = 0
            (
                last_success_signature,
                last_success_result_hash,
                last_success_count,
            ) = _next_success_signature(state, tool_name, tool_input, result)
        else:
            last_error_signature, last_error_count = _next_error_signature(
                state, tool_name, tool_input
            )
            if reason == "tool_outcome_unknown":
                errors = state.consecutive_tool_errors
            else:
                errors = state.consecutive_tool_errors + 1
            if reason == "policy_stall_denied":
                last_success_signature = state.last_success_signature
                last_success_result_hash = state.last_success_result_hash
                last_success_count = state.last_success_count
            else:
                last_success_signature = ""
                last_success_result_hash = ""
                last_success_count = 0
        read_paths = state.read_paths
        read_stamps = dict(state.read_stamps)
        if tool_name == "read_file.v1" and result.status == "ok":
            raw_path = tool_input.get("path")
            if raw_path:
                read_paths = read_paths | {
                    str(normalize_workspace_path(str(raw_path)))
                }
        if (
            result.status == "ok"
            and tool_name in {"read_file.v1", "write_file.v1", "edit_file.v1"}
        ):
            read_stamps.update(_executor_read_stamps(self._executor))
        todos = state.todos
        if tool_name == "todo_write.v1" and result.status == "ok":
            raw_todos = tool_input.get("todos")
            if isinstance(raw_todos, (list, tuple)):
                todos = tuple(
                    dict(item)
                    for item in raw_todos
                    if isinstance(item, Mapping)
                )
        phase = state.phase
        if tool_name == "set_phase.v1" and result.status == "ok":
            phase = parse_phase(tool_input.get("phase")).value
        revealed = state.revealed_tools
        if tool_name == "search_tools.v1" and result.status == "ok":
            names = {
                str(item.get("name"))
                for item in result.content.get("entries", ())
                if isinstance(item, Mapping) and item.get("name")
            }
            revealed = revealed | names
        allowed = state.allowed_tools
        if tool_name == "load_skill.v1" and result.status == "ok":
            allowed = self._union_skill_allowed_tools(allowed, result.content)
        return replace(
            state,
            transcript=transcript,
            tool_count=state.tool_count + 1,
            consecutive_tool_errors=errors,
            pending_tool_index=state.pending_tool_index + (1 if advance_index else 0),
            transcript_digest=self._digest(transcript),
            terminal_pending=False,
            read_paths=read_paths,
            read_stamps=read_stamps,
            todos=todos,
            phase=phase,
            revealed_tools=revealed,
            allowed_tools=allowed,
            hook_retry_count=0,
            compacted_bodies=bodies,
            last_error_signature=last_error_signature,
            last_error_count=last_error_count,
            last_success_signature=last_success_signature,
            last_success_result_hash=last_success_result_hash,
            last_success_count=last_success_count,
        )

    def _check_usage_budgets(self, state):
        spent = (
            state.input_tokens
            + state.output_tokens
            + state.cache_read_tokens
            + state.cache_write_tokens
            + state.reasoning_tokens
        )
        if spent > self._config.max_total_tokens:
            raise CodingLoopFailure("token_budget_exceeded", retryable=False)
        if state.cost_micros > self._config.max_cost_micros:
            raise CodingLoopFailure("cost_budget_exceeded", retryable=False)

    async def _enforce_usage_budgets_after_child_spend(
        self, state, deps, bound, input, *, except_tool_call_id: str | None = None
    ) -> None:
        # Production returns on first phase.completed; a post-yield check never runs.
        try:
            self._check_usage_budgets(state)
        except CodingLoopFailure as error:
            await self.fail_all_live_spawn_claims(
                state,
                deps,
                bound,
                reason=error.code,
                task_id=input.task_id,
                except_tool_call_id=except_tool_call_id,
            )
            raise

    async def _load_workspace_instructions(self, state, bound) -> AgentLoopState:
        text = None
        session = bound.session
        workspace = getattr(getattr(session, "_record", None), "workspace", None)
        if workspace is not None:
            try:
                root = Path(workspace)
                raw_start = getattr(session, "cwd", None)
                if raw_start in {None, ""}:
                    start = root
                else:
                    start = Path(raw_start)
                    if not start.is_absolute():
                        start = root / start
                text = load_workspace_instruction_tree(root, start=start)
            except Exception:
                text = None
        if text is None:
            files: dict[str, bytes] = {}
            for name in INSTRUCTION_CANDIDATES:
                try:
                    files[name] = await bound.session.read_file(name)
                except Exception:
                    continue
            text = load_workspace_instructions(files)
        transcript = state.transcript
        digest = state.transcript_digest
        if text:
            transcript = transcript + (
                CanonicalMessage("user", (TextContent(text),)),
            )
            digest = self._digest(transcript)
        return replace(
            state,
            transcript=transcript,
            transcript_digest=digest,
            instructions_loaded=True,
        )

    def _revealed_from_transcript(
        self, transcript: Sequence[CanonicalMessage]
    ) -> frozenset[str]:
        deferred = frozenset(self._tools.deferred_tool_names())
        search_ids: set[str] = set()
        names: set[str] = set()
        for message in transcript:
            for item in message.content:
                if isinstance(item, ToolUseContent):
                    if item.name == "search_tools.v1":
                        search_ids.add(item.tool_call_id)
                    elif item.name in deferred:
                        names.add(item.name)
                elif (
                    isinstance(item, ToolResultContent)
                    and item.tool_call_id in search_ids
                ):
                    entries = item.content.get("entries")
                    if not isinstance(entries, (list, tuple)):
                        continue
                    for entry in entries:
                        if isinstance(entry, Mapping) and entry.get("name"):
                            names.add(str(entry["name"]))
        return frozenset(names)

    def _tool_definitions(self, state: AgentLoopState):
        method = self._tools.definitions
        try:
            parameters = inspect.signature(method).parameters
        except (TypeError, ValueError):
            parameters = {}
        kwargs: dict[str, object] = {}
        if "phase" in parameters:
            kwargs["phase"] = state.phase
        if "revealed" in parameters:
            kwargs["revealed"] = state.revealed_tools
        if kwargs:
            definitions = method(**kwargs)
        else:
            hidden = hidden_tools_for_phase(state.phase)
            definitions = tuple(item for item in method() if item.name not in hidden)
        if not self._config.subagent_enabled:
            definitions = tuple(
                item
                for item in definitions
                if getattr(item, "name", item) not in _CONTROL_PLANE_TOOLS
            )
        if state.allowed_tools:
            definitions = tuple(
                item
                for item in definitions
                if self._tool_allowed_by_skills(getattr(item, "name", item), state)
            )
        return definitions

    def _registry_tool_names(self) -> frozenset[str]:
        specs = getattr(self._tools, "_tools", None)
        if isinstance(specs, Mapping):
            return frozenset(str(name) for name in specs)
        method = getattr(self._tools, "definitions", None)
        if not callable(method):
            return frozenset()
        try:
            return frozenset(str(item.name) for item in method())
        except TypeError:
            return frozenset()

    def _union_skill_allowed_tools(
        self, current: frozenset[str], content: Mapping[str, object]
    ) -> frozenset[str]:
        incoming: set[str] = set()
        entries = content.get("entries") if isinstance(content, Mapping) else None
        if isinstance(entries, (list, tuple)):
            for entry in entries:
                if not isinstance(entry, Mapping):
                    continue
                raw = entry.get("allowed_tools")
                if isinstance(raw, str) and raw.strip():
                    incoming.add(raw.strip())
                elif isinstance(raw, (list, tuple)):
                    incoming.update(
                        str(item).strip() for item in raw if str(item).strip()
                    )
        if not incoming:
            return current
        registry = self._registry_tool_names()
        merged = incoming if not current else set(current) | incoming
        if registry:
            merged &= set(registry)
        return frozenset(merged)

    @staticmethod
    def _tool_allowed_by_skills(name: str, state: AgentLoopState) -> bool:
        if not state.allowed_tools:
            return True
        if name == "load_skill.v1":
            return True
        return name in state.allowed_tools

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
        )

    def _transcript_token_limit(self) -> int:
        usable = usable_window_tokens(
            context_window=self._config.context_window,
            max_output_tokens=self._config.max_output_tokens,
            input_limit=self._config.input_limit,
            thinking_budget=self._config.thinking_budget,
        )
        if usable is None:
            return self._config.max_transcript_tokens
        return usable

    def _parent_headroom_chars(self, state: AgentLoopState) -> int:
        remaining = max(
            0, self._transcript_token_limit() - max(0, state.last_prompt_tokens)
        )
        return remaining * 4

    def _price_tokens(
        self,
        input_tokens: int,
        output_tokens: int,
        *,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> int:
        return (
            input_tokens * self._config.input_cost_micros_per_million
            + output_tokens * self._config.output_cost_micros_per_million
            + cache_write_tokens * self._config.cache_write_cost_micros_per_million
            + cache_read_tokens * self._config.cache_read_cost_micros_per_million
        ) // 1_000_000

    def _utc_stamp(self) -> str:
        return self._clock().astimezone(UTC).isoformat()

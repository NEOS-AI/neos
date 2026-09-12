from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import re
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from neos.coding.domain.events import CodingEvent
from neos.coding.domain.text_parts import TextPartConflict
from neos.coding.domain.approvals import (
    ApprovalGate,
    ApprovalMode,
    ApprovalPolicyOutcome,
    ApprovalStatus,
    denial_envelope,
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
from neos.coding.model.errors import CodingModelError
from neos.coding.model.base import (
    CanonicalMessage,
    CodingModel,
    ModelCompleted,
    ModelLimits,
    ModelRequest,
    TextContent,
    TextDelta,
    ToolCallCompleted,
    ToolInputDelta,
    ToolResultContent,
    ToolUseContent,
)
from neos.coding.phases import (
    CodingAgentPhase,
    durable_phase_kind,
    hidden_tools_for_phase,
    parse_phase,
    parse_plan_critical_files,
    parse_verify_verdict,
    persist_plan_critical_files,
    persist_verify_verdict,
    restore_plan_critical_files,
    restore_verify_verdict,
    tool_allowed_in_phase,
    write_risk_blocked,
)
from neos.coding.hooks import CodingHookPort, NullCodingHooks, post_tool_prevented
from neos.coding.redact import redact_sensitive
from neos.coding.sandbox.bindings import SandboxBindingService
from neos.coding.sandbox.observability import (
    CodingToolAuditEvent,
    NullCodingAuditSink,
)
from neos.coding.sandbox.paths import normalize_workspace_path
from neos.coding.tools.executor import SandboxToolExecutor, ToolResult
from neos.coding.tools.orchestrator import partition_leading_readonly
from neos.coding.tools.registry import (
    CodingToolRegistry,
    ToolRisk,
    ToolValidationError,
    ValidatedToolCall,
)
from neos.coding.domain.durability import ToolExecutionDisposition

logger = logging.getLogger(__name__)

PRE_TOOL_HOOK_TIMEOUT_SEC = 5.0
STOP_RETRY_LIMIT = 2
EMPTY_RETRY_LIMIT = 1
STALL_DENY_AFTER = 3
COMPACT_REF_THRESHOLD_BYTES = 4096
DEFAULT_MAX_TRANSCRIPT_TOKENS = 80_000
_THINK_CLOSED_RE = re.compile(
    r"<(think|thinking|reasoning)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_THINK_UNCLOSED_RE = re.compile(
    r"<(think|thinking|reasoning)\b[^>]*>.*\Z",
    re.IGNORECASE | re.DOTALL,
)


class CodingLoopFailure(RuntimeError):
    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class CodingLoopWaitingApproval(RuntimeError):
    pass


def _usage_tokens(completion: ModelCompleted) -> tuple[int, int]:
    usage = completion.usage
    if usage is None:
        return 0, 0
    return usage.input_tokens, usage.output_tokens


@dataclass(frozen=True, slots=True)
class CodingLoopConfig:
    model: str
    system: str
    provider: str = "anthropic"
    max_output_tokens: int = 4096
    timeout_sec: float = 120
    tool_claim_ttl_sec: float = 30
    max_turns: int = 40
    max_tools: int = 100
    max_consecutive_tool_errors: int = 5
    max_total_tokens: int = 1_000_000
    max_cost_micros: int = 100_000_000
    input_cost_micros_per_million: int = 0
    output_cost_micros_per_million: int = 0
    max_transcript_messages: int = 100
    max_transcript_bytes: int = 1_048_576
    max_transcript_tokens: int = DEFAULT_MAX_TRANSCRIPT_TOKENS
    max_text_delta_bytes: int = 16_384
    max_public_text_bytes: int = 1_048_576
    approval_ttl_sec: float = 900
    approval_mode: str = "manual"
    approval_deny_tools: frozenset[str] = frozenset()
    approval_allow_tools: frozenset[str] = frozenset()
    approval_always_allow: frozenset[str] = frozenset()
    subagent_enabled: bool = False
    subagent_max_active: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "subagent_max_active",
            min(4, max(1, self.subagent_max_active)),
        )
        numeric = (
            self.max_output_tokens,
            self.timeout_sec,
            self.tool_claim_ttl_sec,
            self.max_turns,
            self.max_tools,
            self.max_consecutive_tool_errors,
            self.max_total_tokens,
            self.max_cost_micros,
            self.max_transcript_messages,
            self.max_transcript_bytes,
            self.max_transcript_tokens,
            self.max_text_delta_bytes,
            self.max_public_text_bytes,
            self.approval_ttl_sec,
        )
        if not self.model or not self.system or any(value <= 0 for value in numeric):
            raise ValueError("coding loop configuration limits must be positive")
        if not self.provider:
            raise ValueError("coding loop provider is required")
        if not (
            self.max_text_delta_bytes
            <= self.max_public_text_bytes
            <= self.max_transcript_bytes
        ):
            raise ValueError("coding public text byte limits are invalid")
        if (
            self.input_cost_micros_per_million < 0
            or self.output_cost_micros_per_million < 0
        ):
            raise ValueError("coding model prices cannot be negative")


_EPOCH_STAMP = "1970-01-01T00:00:00+00:00"


@dataclass(frozen=True, slots=True)
class _AppliedPendingCommand:
    transcript: tuple[CanonicalMessage, ...]
    bodies: dict[str, str]
    todos: tuple
    instructions_loaded: bool


@dataclass(frozen=True, slots=True)
class ActiveChildRef:
    run_id: str
    checkpoint_id: str | None
    tool_call_id: str
    last_advanced_at: str  # UTC datetime.isoformat() from self._clock()


@dataclass(frozen=True, slots=True)
class AgentLoopState:
    transcript: tuple[CanonicalMessage, ...]
    turn_count: int
    tool_count: int
    consecutive_tool_errors: int
    pending_tool_calls: tuple[ToolCallCompleted, ...]
    pending_tool_index: int
    transcript_digest: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_micros: int = 0
    terminal_pending: bool = False
    read_paths: frozenset[str] = frozenset()
    pending_instruction: str | None = None
    todos: tuple[Mapping[str, object], ...] = ()
    phase: str = "implement"
    instructions_loaded: bool = False
    prompt_compact_retries: int = 0
    output_token_escalations: int = 0
    llm_compact_attempts: int = 0
    revealed_tools: frozenset[str] = frozenset()
    approved_always: frozenset[str] = frozenset()
    hook_retry_count: int = 0
    compacted_bodies: Mapping[str, str] = field(default_factory=dict)
    stop_retry_count: int = 0
    read_stamps: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    empty_retry_count: int = 0
    last_error_signature: str = ""
    last_error_count: int = 0
    last_success_signature: str = ""
    last_success_result_hash: str = ""
    last_success_count: int = 0
    verdict: str | None = None
    critical_files: tuple[str, ...] = ()
    active_child_run_id: str | None = None
    active_child_checkpoint_id: str | None = None
    active_child_tool_call_id: str | None = None
    active_children: tuple[ActiveChildRef, ...] = ()

    @property
    def has_pending_tool(self) -> bool:
        return self.pending_tool_index < len(self.pending_tool_calls)


@dataclass(frozen=True, slots=True)
class DelegatedSpawn:
    run_id: str
    checkpoint_id: str | None
    step_kind: str


@dataclass(frozen=True, slots=True)
class SpawnWork:
    kind: str
    call: ToolCallCompleted | None
    child: ActiveChildRef | None


class DurableCodingLoop:
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
        request = ModelRequest(
            system=await coding_turn_system(self._config.system, input.owner_id),
            messages=state.transcript,
            tools=self._tool_definitions(state),
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
                    model_event, text_parts=text_parts, tool_calls=calls
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
            if (
                error.code == "prompt_too_long"
                and state.prompt_compact_retries < 1
            ):
                compacted = await self._compact_after_prompt_too_long(state)
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
                if completion.stop_reason in {"tool_use", "end_turn", "max_tokens"}
                else "other"
            )
            self._metrics.coding_model_turn_total.labels(
                provider=self._config.provider, outcome=outcome
            ).inc()
        if (
            not calls
            and completion.stop_reason == "max_tokens"
            and state.output_token_escalations < 1
        ):
            in_tokens, out_tokens = _usage_tokens(completion)
            retry_state = replace(
                state,
                instructions_loaded=True,
                output_token_escalations=state.output_token_escalations + 1,
                input_tokens=state.input_tokens + in_tokens,
                output_tokens=state.output_tokens + out_tokens,
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
        next_state = await self._completed_turn(state, text_parts, calls, completion)
        self._check_usage_budgets(next_state)
        prefetch = await self._await_prefetch(prefetch_tasks)
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

    async def _advance_one_tool(self, input, state, bound, deps, prefetch=None):
        current = state
        try:
            async for event, current in self._advance_one_tool_body(
                input, state, bound, deps, prefetch=prefetch or {}
            ):
                yield event
        except asyncio.CancelledError:
            current = await self.fail_all_live_spawn_claims(
                current, deps, bound, reason="aborted", task_id=input.task_id
            )
            await self._persist_abort_after_cancel(input, current, bound, deps)
            raise

    async def _advance_one_tool_body(self, input, state, bound, deps, prefetch=None):
        prefetch = prefetch or {}
        if state.tool_count >= self._config.max_tools:
            raise CodingLoopFailure("tool_budget_exceeded", retryable=False)
        max_active = _subagent_max_active(self._config)
        work = _select_spawn_work(state, max_active=max_active)
        if work is not None and work.call is not None:
            call = work.call
        else:
            # resume with a missing pending id (mutation / corruption) uses
            # pending[index] so the existing cap guard still fails closed
            call = state.pending_tool_calls[state.pending_tool_index]
        if _is_stall_denied(state, call.name, call.input):
            event, denied_state = await self._commit_denied_tool(
                input, state, bound, deps, call, "policy_stall_denied"
            )
            yield event, denied_state
            return
        if work is not None and work.call is not None:
            batch = None
        else:
            batch = self._leading_readonly_batch(state)
        if batch is not None:
            hook_blocked = False
            for _call, validated in batch:
                decision, _reason, updated = await self._pre_tool_decision(validated)
                if decision in {"deny", "retry", "prevent"} or updated:
                    hook_blocked = True
                    break
                if self._evaluate_call(validated, state) is not ApprovalPolicyOutcome.ALLOW:
                    hook_blocked = True
                    break
            if not hook_blocked:
                async for event, current in self._advance_readonly_batch(
                    input, state, bound, deps, batch, prefetch=prefetch
                ):
                    yield event, current
                return
        if not tool_allowed_in_phase(call.name, state.phase):
            event, denied_state = await self._commit_denied_tool(
                input, state, bound, deps, call, "policy_phase_denied"
            )
            yield event, denied_state
            return
        try:
            validated = self._tools.validate(call.name, call.input)
        except ToolValidationError as error:
            event, denied_state = await self._commit_denied_tool(
                input, state, bound, deps, call, error.reason_code
            )
            yield event, denied_state
            return
        if write_risk_blocked(validated.risk, state.phase):
            event, denied_state = await self._commit_denied_tool(
                input, state, bound, deps, call, "policy_phase_denied"
            )
            yield event, denied_state
            return
        await self._audit.emit(
            CodingToolAuditEvent.from_result(
                provider=bound.binding.provider,
                tool=call.name,
                operation="validate",
                outcome="allowed",
            )
        )
        hook_decision, hook_reason, updated_input = await self._pre_tool_decision(
            validated
        )
        if hook_decision == "allow" and updated_input is not None:
            try:
                validated = self._tools.validate(validated.name, dict(updated_input))
            except ToolValidationError:
                hook_decision = "deny"
                hook_reason = "hook_updated_input_invalid"
        if hook_decision == "deny":
            event, denied_state = await self._commit_denied_tool(
                input, state, bound, deps, call, "policy_hook_denied"
            )
            yield event, denied_state
            return
        if hook_decision == "prevent":
            event, denied_state = await self._commit_denied_tool(
                input,
                state,
                bound,
                deps,
                call,
                "hook_prevented",
                terminal=True,
            )
            yield event, denied_state
            return
        if hook_decision == "retry":
            if state.hook_retry_count >= 2:
                event, denied_state = await self._commit_denied_tool(
                    input, state, bound, deps, call, "policy_hook_denied"
                )
                yield event, denied_state
                return
            retry_state = self._with_hook_retry(state, validated, hook_reason)
            committed = await deps.repository.commit_model_checkpoint(
                lease=deps.lease,
                event_type="model.completed",
                event_payload={"reason_code": "hook_retry"},
                loop_state=self._dump_state(input, retry_state),
                workspace_revision=str(bound.binding.workspace_revision),
                now=self._clock(),
            )
            yield committed.event, retry_state
            return
        approval_outcome = self._evaluate_call(validated, state)
        if approval_outcome is ApprovalPolicyOutcome.DENY:
            event, denied_state = await self._commit_denied_tool(
                input, state, bound, deps, call, "policy_approval_denied"
            )
            yield event, denied_state
            return
        if approval_outcome is ApprovalPolicyOutcome.REQUIRE_APPROVAL:
            approval = await deps.repository.get_tool_approval(
                task_id=input.task_id,
                run_id=input.run_id,
                tool_call_id=call.tool_call_id,
            )
            if approval is None:
                now = self._clock()
                committed = await deps.repository.request_tool_approval(
                    lease=deps.lease,
                    tool_call=call,
                    validated=validated,
                    loop_state=self._dump_state(input, state),
                    workspace_revision=str(bound.binding.workspace_revision),
                    requested_at=now,
                    expires_at=now + timedelta(seconds=self._config.approval_ttl_sec),
                )
                for event in committed.events:
                    yield event, state
                return
            if approval.status is ApprovalStatus.PENDING:
                raise CodingLoopWaitingApproval(approval.approval_id)
            if approval.status is not ApprovalStatus.APPROVED:
                reason_code = {
                    ApprovalStatus.DENIED: "approval_denied",
                    ApprovalStatus.EXPIRED: "approval_expired",
                    ApprovalStatus.INVALIDATED: "approval_invalidated",
                }[approval.status]
                denied = ToolResultContent(
                    call.tool_call_id,
                    "denied",
                    denial_envelope(call, reason_code),
                )
                advance_index = (
                    state.has_pending_tool
                    and state.pending_tool_calls[state.pending_tool_index].tool_call_id
                    == call.tool_call_id
                )
                denied_state = await self._after_result(
                    state,
                    denied,
                    tool_name=call.name,
                    tool_input=call.input,
                    advance_index=advance_index,
                )
                denied_state = self._drain_completed_prefix(denied_state)
                committed = await deps.repository.commit_model_checkpoint(
                    lease=deps.lease,
                    event_type="tool.denied",
                    event_payload=_tool_event_payload(
                        call, reason_code=reason_code
                    ),
                    loop_state=self._dump_state(input, denied_state),
                    workspace_revision=str(bound.binding.workspace_revision),
                    now=self._clock(),
                )
                yield committed.event, denied_state
                return
            validated = self._with_approval_answers(validated, approval)
            if (
                bool(approval.display_summary.get("remember"))
                and validated.risk is ToolRisk.WORKSPACE_WRITE
            ):
                state = replace(
                    state,
                    approved_always=state.approved_always | {validated.name},
                )
        claim_ttl = self._config.tool_claim_ttl_sec
        if call.name == "spawn_agent.v1" and self._config.subagent_enabled:
            claim_ttl = self._config.timeout_sec + 30
        claim = await deps.repository.claim_tool_execution(
            lease=deps.lease,
            tool_call_id=call.tool_call_id,
            now=self._clock(),
            claim_expires_at=self._clock() + timedelta(seconds=claim_ttl),
        )
        if claim.disposition is ToolExecutionDisposition.BUSY:
            raise CodingLoopFailure("tool_execution_busy", retryable=True)
        if (
            claim.disposition is ToolExecutionDisposition.RECLAIMED
            and validated.risk is not ToolRisk.READ_ONLY
        ):
            async for item in self._emit_unknown_tool_result(
                input, state, bound, deps, call, claim=claim
            ):
                yield item
            return
        started = await deps.repository.begin_phase(
            lease=deps.lease,
            kind=durable_phase_kind(state.phase),
            now=self._clock(),
        )
        if started.event is not None:
            yield started.event, state
        ran_spawn = False
        spawn_enabled = (
            call.name == "spawn_agent.v1" and self._config.subagent_enabled
        )
        if claim.disposition is ToolExecutionDisposition.COMPLETED:
            result = dict(claim.result or {})
            await self._audit.emit(
                CodingToolAuditEvent.from_result(
                    provider=bound.binding.provider,
                    tool=call.name,
                    operation="execute",
                    outcome="reused",
                )
            )
            tool_event = await deps.events.append(
                task_id=input.task_id,
                event_type="tool.completed",
                payload=_tool_event_payload(call, result=result, reused=True),
                run_id=input.run_id,
                tool_call_id=call.tool_call_id,
            )
        else:
            resume_spawn = spawn_enabled and claim.disposition in {
                ToolExecutionDisposition.DELEGATED,
                ToolExecutionDisposition.RECLAIMED,
            }
            if not resume_spawn:
                yield await self._emit_tool_started(input, deps, call), state
            try:
                if call.name == "spawn_agent.v1":
                    await self._adopt_all_live_claims(
                        state, deps, selected_tool_call_id=call.tool_call_id
                    )
                    result = await self._run_spawn_agent(
                        call, bound, state, input=input, deps=deps
                    )
                    ran_spawn = True
                    if isinstance(result, dict):
                        updated = result.pop("_loop_state", None)
                        if updated is not None:
                            state = updated
                else:
                    result = await self._execute_validated(
                        bound,
                        deps,
                        validated,
                        known_reads=state.read_paths,
                        known_stamps=state.read_stamps,
                        prefetched=prefetch.get(call.tool_call_id),
                    )
            except asyncio.CancelledError:
                await self._cancel_active_child(
                    state, reason="aborted", task_id=input.task_id
                )
                await self._fail_delegated_claim(deps, claim, bound)
                raise
            except CodingLoopFailure as error:
                if error.code != "tool_outcome_unknown":
                    raise
                async for item in self._emit_unknown_tool_result(
                    input, state, bound, deps, call, claim=claim, started=started
                ):
                    yield item
                return
            if isinstance(result, DelegatedSpawn):
                if claim.disposition in {
                    ToolExecutionDisposition.CLAIMED,
                    ToolExecutionDisposition.RECLAIMED,
                }:
                    await self._mark_spawn_delegated(deps, claim, result)
                parked = self._upsert_active_child(
                    state,
                    ActiveChildRef(
                        run_id=result.run_id,
                        checkpoint_id=result.checkpoint_id,
                        tool_call_id=call.tool_call_id,
                        last_advanced_at=self._utc_stamp(),
                    ),
                )
                payload = {
                    "child_run_id": result.run_id,
                    "child_checkpoint_id": result.checkpoint_id,
                    "step_kind": result.step_kind,
                    "live_count": len(parked.active_children),
                }
                self._record_spawn_live_children(parked, call)
                committed = await deps.repository.commit_phase_checkpoint(
                    lease=deps.lease,
                    phase=started.phase,
                    tool_call_id=call.tool_call_id,
                    result=payload,
                    loop_state=self._dump_state(input, parked),
                    workspace_revision=str(bound.binding.workspace_revision),
                    now=self._clock(),
                )
                yield committed.event, parked
                return
            if validated.risk is not ToolRisk.READ_ONLY:
                try:
                    await self._bindings.record_mutation(
                        deps.lease,
                        workspace_revision=(
                            await bound.session.workspace_revision()
                        ),
                    )
                except Exception:
                    await self._audit.emit(
                        CodingToolAuditEvent.from_result(
                            provider=bound.binding.provider,
                            tool=validated.name,
                            operation="execute",
                            outcome="error",
                            error_code="tool_outcome_unknown",
                        )
                    )
                    async for item in self._emit_unknown_tool_result(
                        input, state, bound, deps, call, claim=claim, started=started
                    ):
                        yield item
                    return
            if isinstance(result, dict) and result.pop("_post_tool_prevent", False):
                envelope = dict(denial_envelope(call, "hook_prevented"))
                envelope["denied_by"] = "hook"
                try:
                    await deps.repository.complete_tool_execution(
                        claim, result=envelope, now=self._clock()
                    )
                except Exception:
                    pass
                event, denied_state = await self._commit_denied_tool(
                    input,
                    state,
                    bound,
                    deps,
                    call,
                    "hook_prevented",
                    terminal=True,
                )
                yield event, denied_state
                return
            try:
                tool_event = await deps.repository.complete_tool_execution(
                    claim, result=result, now=self._clock()
                )
            except Exception:
                await self._audit.emit(
                    CodingToolAuditEvent.from_result(
                        provider=bound.binding.provider,
                        tool=call.name,
                        operation="execute",
                        outcome="error",
                        error_code="tool_outcome_unknown",
                    )
                )
                async for item in self._emit_unknown_tool_result(
                    input, state, bound, deps, call, claim=claim, started=started
                ):
                    yield item
                return
            await self._audit_execute_result(bound, call.name, result)
            tool_event = replace(
                tool_event,
                payload=_tool_event_payload(
                    call, **dict(tool_event.payload)
                ),
            )
        self._record_tool_metric(call.name, result)
        yield tool_event, state
        status = str(result.get("status", "ok"))
        canonical_status = status if status in {"ok", "error", "denied"} else "ok"
        reused = claim.disposition is ToolExecutionDisposition.COMPLETED
        child_fold = call.name == "spawn_agent.v1" and "child_status" in result
        if child_fold and (
            not reused or self._child_ref(state, call.tool_call_id) is not None
        ):
            state = self._apply_child_fold_usage(state, result)
        advance_index = (
            state.has_pending_tool
            and state.pending_tool_calls[state.pending_tool_index].tool_call_id
            == call.tool_call_id
        )
        if call.tool_call_id in _tool_result_ids(state.transcript):
            after = self._drain_completed_prefix(state)
        else:
            after = await self._after_result(
                state,
                ToolResultContent(call.tool_call_id, canonical_status, result),
                tool_name=call.name,
                tool_input=call.input,
                advance_index=advance_index,
            )
        if ran_spawn and not self._config.subagent_enabled:
            after = self._with_spawn_handoff(after, call, result)
        still_live = self._child_ref(after, call.tool_call_id) is not None
        if ran_spawn or child_fold or still_live:
            after = self._sync_active_children(
                after,
                tuple(
                    child
                    for child in after.active_children
                    if child.tool_call_id != call.tool_call_id
                ),
            )
            after = self._drain_completed_prefix(after)
            self._record_spawn_live_children(after, call)
        revision = str(result.get("workspace_revision") or "")
        if revision in {"", "unknown"}:
            revision = str(bound.binding.workspace_revision)
        committed = await deps.repository.commit_phase_checkpoint(
            lease=deps.lease,
            phase=started.phase,
            tool_call_id=call.tool_call_id,
            result=result,
            loop_state=self._dump_state(input, after),
            workspace_revision=revision,
            now=self._clock(),
        )
        if child_fold:
            # Production returns on first phase.completed; a post-yield check never runs.
            try:
                self._check_usage_budgets(after)
            except CodingLoopFailure as error:
                await self.fail_all_live_spawn_claims(
                    after,
                    deps,
                    bound,
                    reason=error.code,
                    task_id=input.task_id,
                )
                raise
        yield committed.event, after
        if after.consecutive_tool_errors >= self._config.max_consecutive_tool_errors:
            raise CodingLoopFailure("tool_error_budget_exceeded", retryable=False)

    def _leading_readonly_batch(self, state):
        remaining = state.pending_tool_calls[state.pending_tool_index :]
        remaining_budget = self._config.max_tools - state.tool_count
        if len(remaining) < 2 or remaining_budget < 2:
            return None
        pairs: list[tuple[ToolCallCompleted, ValidatedToolCall]] = []
        for call in remaining:
            if call.name in {"spawn_agent.v1", "set_phase.v1"}:
                break
            if not tool_allowed_in_phase(call.name, state.phase):
                break
            try:
                validated = self._tools.validate(call.name, call.input)
            except ToolValidationError:
                break
            pairs.append((call, validated))
        if len(pairs) < 2:
            return None
        batch, _rest = partition_leading_readonly(
            tuple(validated for _call, validated in pairs),
            max_batch=min(10, remaining_budget),
        )
        if len(batch) < 2:
            return None
        return tuple(pairs[: len(batch)])

    async def _advance_readonly_batch(
        self, input, state, bound, deps, pairs, prefetch=None
    ):
        prefetch = prefetch or {}
        current = state
        claims = []
        for call, validated in pairs:
            await self._audit.emit(
                CodingToolAuditEvent.from_result(
                    provider=bound.binding.provider,
                    tool=call.name,
                    operation="validate",
                    outcome="allowed",
                )
            )
            claim = await deps.repository.claim_tool_execution(
                lease=deps.lease,
                tool_call_id=call.tool_call_id,
                now=self._clock(),
                claim_expires_at=self._clock()
                + timedelta(seconds=self._config.tool_claim_ttl_sec),
            )
            if claim.disposition is ToolExecutionDisposition.BUSY:
                raise CodingLoopFailure("tool_execution_busy", retryable=True)
            claims.append((call, validated, claim))
        started = await deps.repository.begin_phase(
            lease=deps.lease,
            kind=durable_phase_kind(state.phase),
            now=self._clock(),
        )
        if started.event is not None:
            yield started.event, current
        for call, _validated, claim in claims:
            if claim.disposition is not ToolExecutionDisposition.COMPLETED:
                yield await self._emit_tool_started(input, deps, call), current

        async def run_one(call, validated, claim):
            if claim.disposition is ToolExecutionDisposition.COMPLETED:
                result = dict(claim.result or {})
                await self._audit.emit(
                    CodingToolAuditEvent.from_result(
                        provider=bound.binding.provider,
                        tool=call.name,
                        operation="execute",
                        outcome="reused",
                    )
                )
                return result, True
            result = await self._execute_validated(
                bound,
                deps,
                validated,
                known_reads=state.read_paths,
                known_stamps=state.read_stamps,
                prefetched=prefetch.get(call.tool_call_id),
            )
            await self._audit_execute_result(bound, call.name, result)
            return result, False

        gathered = await asyncio.gather(
            *(
                run_one(call, validated, claim)
                for call, validated, claim in claims
            )
        )
        last_call = claims[-1][0]
        last_result: dict[str, Any] = {}
        for (call, _validated, claim), (result, reused) in zip(
            claims, gathered, strict=True
        ):
            if reused:
                tool_event = await deps.events.append(
                    task_id=input.task_id,
                    event_type="tool.completed",
                    payload=_tool_event_payload(call, result=result, reused=True),
                    run_id=input.run_id,
                    tool_call_id=call.tool_call_id,
                )
            else:
                try:
                    tool_event = await deps.repository.complete_tool_execution(
                        claim, result=result, now=self._clock()
                    )
                except Exception as error:
                    await self._audit.emit(
                        CodingToolAuditEvent.from_result(
                            provider=bound.binding.provider,
                            tool=call.name,
                            operation="execute",
                            outcome="error",
                            error_code="tool_outcome_unknown",
                        )
                    )
                    raise CodingLoopFailure(
                        "tool_outcome_unknown", retryable=False
                    ) from error
                tool_event = replace(
                    tool_event,
                    payload=_tool_event_payload(call, **dict(tool_event.payload)),
                )
            self._record_tool_metric(call.name, result)
            yield tool_event, current
            if isinstance(result, dict) and result.pop("_post_tool_prevent", False):
                envelope = dict(denial_envelope(call, "hook_prevented"))
                envelope["denied_by"] = "hook"
                current = await self._after_result(
                    current,
                    ToolResultContent(call.tool_call_id, "denied", envelope),
                    tool_name=call.name,
                    tool_input=call.input,
                )
                current = replace(current, terminal_pending=True)
                last_call = call
                last_result = envelope
                break
            status = str(result.get("status", "ok"))
            canonical_status = status if status in {"ok", "error", "denied"} else "ok"
            current = await self._after_result(
                current,
                ToolResultContent(call.tool_call_id, canonical_status, result),
                tool_name=call.name,
                tool_input=call.input,
            )
            last_call = call
            last_result = result
        revision = str(
            last_result.get("workspace_revision", bound.binding.workspace_revision)
        )
        committed = await deps.repository.commit_phase_checkpoint(
            lease=deps.lease,
            phase=started.phase,
            tool_call_id=last_call.tool_call_id,
            result=last_result,
            loop_state=self._dump_state(input, current),
            workspace_revision=revision,
            now=self._clock(),
        )
        yield committed.event, current
        if current.consecutive_tool_errors >= self._config.max_consecutive_tool_errors:
            raise CodingLoopFailure("tool_error_budget_exceeded", retryable=False)

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

    def _hold_incomplete_phase(
        self, state: AgentLoopState, text: str
    ) -> AgentLoopState | None:
        phase = parse_phase(state.phase)
        if phase is CodingAgentPhase.VERIFY and parse_verify_verdict(text) is None:
            note = (
                "Verify is incomplete. End with `VERDICT: PASS`, "
                "`VERDICT: FAIL`, or `VERDICT: PARTIAL`. Stay in verify."
            )
        elif (
            phase is CodingAgentPhase.PLAN
            and parse_plan_critical_files(text) is None
        ):
            note = (
                "Plan is incomplete. Include a `Critical Files:` heading. "
                "Stay in plan."
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

    async def _emit_tool_started(self, input, deps, call):
        return await deps.events.append(
            task_id=input.task_id,
            event_type="tool.started",
            payload=_tool_event_payload(call),
            run_id=input.run_id,
            tool_call_id=call.tool_call_id,
        )

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

    async def _emit_unknown_tool_result(
        self, input, state, bound, deps, call, *, claim=None, started=None
    ):
        result = self._spawn_tool_error(bound, "tool_outcome_unknown")
        tool_event = None
        if claim is not None and claim.disposition is not ToolExecutionDisposition.COMPLETED:
            try:
                tool_event = await deps.repository.complete_tool_execution(
                    claim, result=result, now=self._clock()
                )
            except Exception:
                tool_event = None
        if tool_event is None:
            tool_event = await deps.events.append(
                task_id=input.task_id,
                event_type="tool.completed",
                payload=_tool_event_payload(
                    call, result=result, reason_code="tool_outcome_unknown"
                ),
                run_id=input.run_id,
                tool_call_id=call.tool_call_id,
            )
        else:
            tool_event = replace(
                tool_event,
                payload=_tool_event_payload(call, **dict(tool_event.payload)),
            )
        after = await self._after_result(
            state,
            ToolResultContent(call.tool_call_id, "error", result),
            tool_name=call.name,
            tool_input=call.input,
        )
        if started is not None:
            committed = await deps.repository.commit_phase_checkpoint(
                lease=deps.lease,
                phase=started.phase,
                tool_call_id=call.tool_call_id,
                result=result,
                loop_state=self._dump_state(input, after),
                workspace_revision=str(bound.binding.workspace_revision),
                now=self._clock(),
            )
        else:
            committed = await deps.repository.commit_model_checkpoint(
                lease=deps.lease,
                event_type="tool.completed",
                event_payload={"reason_code": "tool_outcome_unknown"},
                loop_state=self._dump_state(input, after),
                workspace_revision=str(bound.binding.workspace_revision),
                now=self._clock(),
            )
        yield tool_event, state
        yield committed.event, after

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
        result = dict(executed.to_mapping())
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

    async def _audit_execute_result(self, bound, tool_name, result) -> None:
        result_status = str(result.get("status", "ok"))
        await self._audit.emit(
            CodingToolAuditEvent.from_result(
                provider=bound.binding.provider,
                tool=tool_name,
                operation="execute",
                outcome=(
                    result_status
                    if result_status in {"ok", "error", "denied"}
                    else "error"
                ),
                error_code=(
                    str(result.get("reason_code"))
                    if result_status != "ok"
                    else None
                ),
            )
        )

    async def _commit_denied_tool(
        self, input, state, bound, deps, call, reason_code, *, terminal: bool = False
    ):
        await self._audit.emit(
            CodingToolAuditEvent.from_result(
                provider=bound.binding.provider,
                tool=call.name,
                operation="validate",
                outcome="denied",
                error_code=reason_code,
            )
        )
        envelope = dict(denial_envelope(call, reason_code))
        if reason_code == "hook_prevented":
            envelope["denied_by"] = "hook"
        denied = ToolResultContent(call.tool_call_id, "denied", envelope)
        advance_index = (
            state.has_pending_tool
            and state.pending_tool_calls[state.pending_tool_index].tool_call_id
            == call.tool_call_id
        )
        denied_state = await self._after_result(
            state,
            denied,
            tool_name=call.name,
            tool_input=call.input,
            advance_index=advance_index,
        )
        denied_state = self._drain_completed_prefix(denied_state)
        if terminal:
            denied_state = replace(denied_state, terminal_pending=True)
        committed = await deps.repository.commit_model_checkpoint(
            lease=deps.lease,
            event_type="tool.denied",
            event_payload=_tool_event_payload(call, reason_code=reason_code),
            loop_state=self._dump_state(input, denied_state),
            workspace_revision=str(bound.binding.workspace_revision),
            now=self._clock(),
        )
        return committed.event, denied_state

    def _record_tool_metric(self, tool_name, result) -> None:
        if self._metrics is None:
            return
        metric_outcome = str(result.get("status", "ok"))
        if metric_outcome not in {"ok", "error", "denied"}:
            metric_outcome = "error"
        self._metrics.coding_tool_execution_total.labels(
            tool=tool_name, outcome=metric_outcome
        ).inc()

    def _spawn_spec_name(self, call) -> str:
        raw = call.input if isinstance(getattr(call, "input", None), Mapping) else {}
        return str(raw.get("spec") or "explore")

    def _record_spawn_live_children(self, state, call) -> None:
        from neos.subagent.metrics import record_live_children

        children = state.active_children or _legacy_single(state)
        live_count = len(children)
        record_live_children(
            self._metrics,
            parent_kind="coding",
            spec=self._spawn_spec_name(call),
            count=live_count,
        )
        logger.debug(
            "coding spawn delivery live_count=%s selected_tool_call_id=%s",
            live_count,
            getattr(call, "tool_call_id", ""),
        )

    def _record_policy_capped(self) -> None:
        from neos.subagent.metrics import record_policy_capped

        record_policy_capped(self._metrics, parent_kind="coding")

    def _record_fold_rollup(
        self, input_tokens: int, output_tokens: int, cost_micros: int
    ) -> None:
        from neos.subagent.metrics import record_fold_rollup

        record_fold_rollup(
            self._metrics,
            parent_kind="coding",
            provider=self._config.provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_micros=cost_micros,
        )

    async def _has_pending_interrupt(self, deps, task_id: str) -> bool:
        checker = getattr(deps.repository, "has_pending_interrupt", None)
        if checker is None:
            return False
        return bool(await checker(task_id))

    async def _persist_abort_after_cancel(self, input, state, bound, deps) -> None:
        """Finish the abort checkpoint even if this Task is already cancelled.

        Python 3.12+ re-raises CancelledError at the next await while
        ``Task.cancelling() > 0``. interrupt() uses ``task.cancel()``, so a
        bare ``await _checkpoint_aborted`` never commits. Clear the cancel
        count, shield the write, then restore cancelled state.
        """
        current = asyncio.current_task()
        cleared = 0
        if current is not None:
            while current.cancelling() > 0:
                current.uncancel()
                cleared += 1
        try:
            await asyncio.shield(self._checkpoint_aborted(input, state, bound, deps))
        finally:
            if current is not None:
                for _ in range(cleared):
                    current.cancel()

    async def _checkpoint_aborted(self, input, state, bound, deps) -> None:
        state = await self.fail_all_live_spawn_claims(
            state, deps, bound, reason="aborted", task_id=input.task_id
        )
        remaining = state.pending_tool_calls[state.pending_tool_index :]
        existing = _tool_result_ids(state.transcript)
        pending = [
            call for call in remaining if call.tool_call_id not in existing
        ]
        after = state
        for call in pending:
            after = await self._after_result(
                after,
                ToolResultContent(
                    call.tool_call_id,
                    "error",
                    {"reason_code": "aborted"},
                ),
                tool_name=call.name,
                tool_input=call.input,
            )
        after = self._drain_completed_prefix(after)
        await deps.repository.commit_model_checkpoint(
            lease=deps.lease,
            event_type="tool.completed" if pending else "model.completed",
            event_payload={"reason_code": "aborted"},
            loop_state=self._dump_state(input, after),
            workspace_revision=str(bound.binding.workspace_revision),
            now=self._clock(),
        )

    async def _completed_turn(self, state, text_parts, calls, completion):
        content = []
        raw_text = "".join(text_parts)
        text = _scrub_think_blocks(raw_text)
        if text:
            content.append(TextContent(text))
        calls = _uniquify_tool_calls(calls)
        content.extend(
            ToolUseContent(c.tool_call_id, c.name, dict(c.input)) for c in calls
        )
        transcript = state.transcript
        if content:
            transcript += (CanonicalMessage("assistant", tuple(content)),)
        bodies = dict(state.compacted_bodies)
        transcript = await self._compact_with_hook(
            transcript, preserve_tools=bool(calls), bodies=bodies
        )
        in_tokens, out_tokens = _usage_tokens(completion)
        cost = (
            state.cost_micros
            + (
                in_tokens * self._config.input_cost_micros_per_million
                + out_tokens * self._config.output_cost_micros_per_million
            )
            // 1_000_000
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
            cost_micros=cost,
            terminal_pending=False,
            compacted_bodies=bodies,
            empty_retry_count=0 if reset_empty else state.empty_retry_count,
        )

    def _with_spawn_handoff(self, state: AgentLoopState, call, result) -> AgentLoopState:
        if call.name != "spawn_agent.v1":
            return state
        status = str(result.get("status", "ok"))
        if status != "ok":
            return state
        prompt = call.input.get("prompt") if isinstance(call.input, Mapping) else None
        if not isinstance(prompt, str) or not prompt.strip():
            return state
        text = prompt.strip()
        if state.has_pending_tool:
            existing = state.pending_instruction
            merged = "\n".join(part for part in (existing, text) if part)
            return replace(state, pending_instruction=merged)
        transcript = self._append_user_meta(state.transcript, text)
        return replace(
            state,
            transcript=transcript,
            transcript_digest=self._digest(transcript),
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
            hook_retry_count=0,
            compacted_bodies=bodies,
            last_error_signature=last_error_signature,
            last_error_count=last_error_count,
            last_success_signature=last_success_signature,
            last_success_result_hash=last_success_result_hash,
            last_success_count=last_success_count,
        )

    def _check_usage_budgets(self, state):
        if state.input_tokens + state.output_tokens > self._config.max_total_tokens:
            raise CodingLoopFailure("token_budget_exceeded", retryable=False)
        if state.cost_micros > self._config.max_cost_micros:
            raise CodingLoopFailure("cost_budget_exceeded", retryable=False)

    async def _load_workspace_instructions(self, state, bound) -> AgentLoopState:
        text = None
        session = bound.session
        workspace = getattr(getattr(session, "_record", None), "workspace", None)
        if workspace is not None:
            try:
                from pathlib import Path

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
            return method(**kwargs)
        hidden = hidden_tools_for_phase(state.phase)
        return tuple(item for item in method() if item.name not in hidden)

    def _model_limits(self, state: AgentLoopState) -> ModelLimits:
        max_output_tokens = self._config.max_output_tokens
        if state.output_token_escalations:
            max_output_tokens = min(max_output_tokens * 4, 64_000)
        return ModelLimits(max_output_tokens, self._config.timeout_sec)

    async def _compact_after_prompt_too_long(self, state: AgentLoopState) -> AgentLoopState:
        before = state.transcript
        bodies = dict(state.compacted_bodies)
        after = self._compact(before, force=True, bodies=bodies)
        after, attempts = await self._maybe_llm_compact(state, after)
        if after != before:
            await self._hooks.compact(before, after)
        return replace(
            state,
            transcript=after,
            transcript_digest=self._digest(after),
            prompt_compact_retries=state.prompt_compact_retries + 1,
            llm_compact_attempts=attempts,
            compacted_bodies=bodies,
        )

    def _maybe_prefetch_readonly(self, call: ToolCallCompleted, bound, state):
        if call.name == "spawn_agent.v1":
            return None
        if _is_stall_denied(state, call.name, call.input):
            return None
        if not tool_allowed_in_phase(call.name, state.phase):
            return None
        try:
            validated = self._tools.validate(call.name, call.input)
        except ToolValidationError:
            return None
        if validated.risk is not ToolRisk.READ_ONLY:
            return None
        if self._evaluate_call(validated, state) is not ApprovalPolicyOutcome.ALLOW:
            return None
        return asyncio.create_task(
            self._executor.execute(
                bound.session,
                validated,
                known_reads=state.read_paths,
                known_stamps=state.read_stamps,
            )
        )

    async def _await_prefetch(
        self, tasks: dict[str, asyncio.Task]
    ) -> dict[str, ToolResult]:
        ready: dict[str, ToolResult] = {}
        if not tasks:
            return ready
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for call_id, result in zip(tasks, results):
            if isinstance(result, ToolResult):
                ready[call_id] = result
        return ready

    def _utc_stamp(self) -> str:
        return self._clock().astimezone(UTC).isoformat()

    def _child_ref(self, state, tool_call_id: str) -> ActiveChildRef | None:
        for child in state.active_children:
            if child.tool_call_id == tool_call_id:
                return child
        return None

    def _sync_active_children(
        self, state, children: tuple[ActiveChildRef, ...]
    ) -> AgentLoopState:
        head = children[0] if children else None
        return replace(
            state,
            active_children=children,
            active_child_run_id=head.run_id if head else None,
            active_child_checkpoint_id=head.checkpoint_id if head else None,
            active_child_tool_call_id=head.tool_call_id if head else None,
        )

    def _upsert_active_child(self, state, child: ActiveChildRef) -> AgentLoopState:
        children = list(state.active_children or _legacy_single(state))
        for index, existing in enumerate(children):
            if existing.tool_call_id == child.tool_call_id:
                children[index] = child
                break
        else:
            children.append(child)
        return self._sync_active_children(state, tuple(children))

    def _drain_completed_prefix(self, state: AgentLoopState) -> AgentLoopState:
        done = _tool_result_ids(state.transcript)
        index = state.pending_tool_index
        while index < len(state.pending_tool_calls):
            if state.pending_tool_calls[index].tool_call_id not in done:
                break
            index += 1
        if index == state.pending_tool_index:
            return state
        return replace(state, pending_tool_index=index)

    def _spawn_tool_error(self, bound, reason_code: str) -> dict[str, Any]:
        return ToolResult(
            "error",
            reason_code,
            None,
            None,
            False,
            None,
            str(bound.binding.workspace_revision),
        ).to_mapping()

    def _legacy_explore_handoff(self, bound) -> dict[str, Any]:
        note = (
            "Do not nest an inner agent loop. "
            "Use set_phase.v1 to switch the parent to explore."
        )
        result = dict(
            ToolResult.ok(
                workspace_revision=str(bound.binding.workspace_revision),
                entries=(
                    {
                        "delegated": False,
                        "use_phase": "explore",
                        "note": note,
                    },
                ),
            ).to_mapping()
        )
        result["delegated"] = False
        result["use_phase"] = "explore"
        result["note"] = note
        return result

    async def cancel_active_child_for_task(self, task_id: str) -> None:
        if self._subagents is None:
            return
        from neos.subagent.types import ParentKind

        await self._subagents.cancel_for_parent(ParentKind.CODING, task_id, "cancelled")

    async def _cancel_active_child(
        self, state, *, reason: str, task_id: str | None = None
    ) -> None:
        if self._subagents is None:
            return
        refs = ()
        if state is not None:
            refs = state.active_children or _legacy_single(state)
        for ref in refs:
            await self._subagents.cancel(ref.run_id, reason)
        if task_id:
            from neos.subagent.types import ParentKind

            await self._subagents.cancel_for_parent(
                ParentKind.CODING, task_id, reason
            )

    def _child_lease_horizon(self) -> float:
        return max(self._config.tool_claim_ttl_sec, self._config.timeout_sec + 30)

    async def _renew_parent_lease(self, deps) -> None:
        if deps is None or deps.lease is None:
            return
        renew = getattr(deps.repository, "renew_execution_lease", None)
        if not callable(renew):
            return
        now = self._clock()
        await renew(
            deps.lease,
            now=now,
            expires_at=now + timedelta(seconds=self._child_lease_horizon()),
        )

    async def _mark_spawn_delegated(self, deps, claim, result: DelegatedSpawn) -> None:
        marker = getattr(deps.repository, "mark_tool_delegated", None)
        if not callable(marker):
            return
        now = self._clock()
        await marker(
            claim,
            child_run_id=result.run_id,
            child_checkpoint_id=result.checkpoint_id or "",
            claim_expires_at=now + timedelta(seconds=self._config.timeout_sec + 30),
            now=now,
        )

    async def _fail_delegated_claim(self, deps, claim, bound) -> None:
        if deps is None or claim is None:
            return
        if claim.disposition not in {
            ToolExecutionDisposition.CLAIMED,
            ToolExecutionDisposition.RECLAIMED,
            ToolExecutionDisposition.DELEGATED,
        }:
            return
        try:
            await deps.repository.complete_tool_execution(
                claim,
                result=self._spawn_tool_error(bound, "aborted"),
                now=self._clock(),
            )
        except Exception:
            return

    async def _fail_open_spawn_claim(self, deps, tool_call_id: str, bound) -> None:
        if deps is None or deps.lease is None:
            return
        try:
            claim = await deps.repository.claim_tool_execution(
                lease=deps.lease,
                tool_call_id=tool_call_id,
                now=self._clock(),
                claim_expires_at=self._clock()
                + timedelta(seconds=self._config.timeout_sec + 30),
            )
        except Exception:
            return
        if claim.disposition is ToolExecutionDisposition.DELEGATED:
            await self._fail_delegated_claim(deps, claim, bound)

    async def _adopt_spawn_claim(self, deps, tool_call_id: str):
        if deps is None or deps.lease is None:
            return None
        try:
            return await deps.repository.claim_tool_execution(
                lease=deps.lease,
                tool_call_id=tool_call_id,
                now=self._clock(),
                claim_expires_at=self._clock()
                + timedelta(seconds=self._config.timeout_sec + 30),
            )
        except Exception:
            return None

    async def _adopt_all_live_claims(
        self, state, deps, *, selected_tool_call_id: str | None = None
    ) -> None:
        refs = ()
        if state is not None:
            refs = state.active_children or _legacy_single(state)
        for ref in refs:
            claim = await self._adopt_spawn_claim(deps, ref.tool_call_id)
            if (
                claim is None
                or claim.disposition is not ToolExecutionDisposition.RECLAIMED
                or ref.tool_call_id == selected_tool_call_id
            ):
                continue
            await self._mark_spawn_delegated(
                deps,
                claim,
                DelegatedSpawn(
                    run_id=ref.run_id,
                    checkpoint_id=ref.checkpoint_id,
                    step_kind="continuing",
                ),
            )

    async def _complete_spawn_claim(self, deps, claim, bound, reason: str) -> None:
        if deps is None or claim is None:
            return
        if claim.disposition not in {
            ToolExecutionDisposition.CLAIMED,
            ToolExecutionDisposition.RECLAIMED,
            ToolExecutionDisposition.DELEGATED,
        }:
            return
        try:
            await deps.repository.complete_tool_execution(
                claim,
                result=self._spawn_tool_error(bound, reason),
                now=self._clock(),
            )
        except Exception:
            return

    async def fail_all_live_spawn_claims(
        self,
        state,
        deps,
        bound,
        *,
        reason: str,
        task_id: str | None,
        except_tool_call_id: str | None = None,
    ) -> AgentLoopState:
        """Adopt + complete live delegated claims except except_tool_call_id."""
        refs = state.active_children or _legacy_single(state)
        if self._subagents is not None and task_id:
            from neos.subagent.types import ParentKind

            await self._subagents.cancel_for_parent(
                ParentKind.CODING, task_id, reason
            )
        done = _tool_result_ids(state.transcript)
        kept: list[ActiveChildRef] = []
        after = state
        for ref in refs:
            if (
                except_tool_call_id is not None
                and ref.tool_call_id == except_tool_call_id
            ):
                kept.append(ref)
                continue
            claim = await self._adopt_spawn_claim(deps, ref.tool_call_id)
            if claim is None or claim.disposition is ToolExecutionDisposition.COMPLETED:
                continue
            await self._complete_spawn_claim(deps, claim, bound, reason)
            if ref.tool_call_id not in done:
                advance_index = (
                    after.has_pending_tool
                    and after.pending_tool_calls[after.pending_tool_index].tool_call_id
                    == ref.tool_call_id
                )
                after = await self._after_result(
                    after,
                    ToolResultContent(
                        ref.tool_call_id,
                        "error",
                        {"reason_code": reason},
                    ),
                    tool_name="spawn_agent.v1",
                    tool_input={},
                    advance_index=advance_index,
                )
                done.add(ref.tool_call_id)
        after = self._sync_active_children(after, tuple(kept))
        return self._drain_completed_prefix(after)

    def _bind_child_tools(self, bound, state) -> None:
        if self._subagents is None:
            return
        stepper = getattr(self._subagents, "_stepper", None)
        port = getattr(stepper, "_tools", None) if stepper is not None else None
        bind = getattr(port, "bind", None)
        if callable(bind):
            bind(
                session=bound.session,
                phase=state.phase,
                revealed=state.revealed_tools,
            )

    def _spawn_briefing(self, call):
        from neos.subagent.types import ParentBriefing

        raw = call.input if isinstance(call.input, Mapping) else {}
        already = raw.get("already_tried") or ()
        if isinstance(already, str):
            already = (already,)
        budget = raw.get("report_budget", 4000)
        try:
            budget = int(budget)
        except (TypeError, ValueError):
            budget = 4000
        return ParentBriefing(
            goal=str(raw.get("prompt") or "").strip(),
            why=str(raw.get("why") or ""),
            already_tried=tuple(str(item) for item in already),
            scope=str(raw.get("scope") or ""),
            success=str(raw.get("success") or ""),
            report_budget_chars=max(256, min(16_384, budget)),
        )

    def _price_child_usage(self, folded) -> tuple[int, int, int]:
        if isinstance(folded, Mapping):
            in_tokens = int(folded.get("input_tokens") or 0)
            out_tokens = int(folded.get("output_tokens") or 0)
        else:
            in_tokens = int(folded.input_tokens or 0)
            out_tokens = int(folded.output_tokens or 0)
        priced = (
            in_tokens * self._config.input_cost_micros_per_million
            + out_tokens * self._config.output_cost_micros_per_million
        ) // 1_000_000
        return in_tokens, out_tokens, priced

    def _apply_child_fold_usage(self, state, folded) -> AgentLoopState:
        in_tokens, out_tokens, child_cost = self._price_child_usage(folded)
        self._record_fold_rollup(in_tokens, out_tokens, child_cost)
        return replace(
            state,
            input_tokens=state.input_tokens + in_tokens,
            output_tokens=state.output_tokens + out_tokens,
            cost_micros=state.cost_micros + child_cost,
        )

    def _folded_spawn_result(self, bound, folded) -> dict[str, Any]:
        from neos.subagent.types import SubagentStatus

        ok = folded.status is SubagentStatus.COMPLETED
        status = "ok" if ok else "error"
        reason = "ok" if ok else folded.status.value
        result = dict(
            ToolResult(
                status,
                reason,
                None,
                None,
                bool(folded.truncated),
                None,
                str(bound.binding.workspace_revision),
                entries=(
                    {
                        "summary": folded.summary,
                        "run_id": folded.run_id,
                    },
                ),
            ).to_mapping()
        )
        result["summary"] = folded.summary
        result["run_id"] = folded.run_id
        result["truncated"] = bool(folded.truncated)
        result["citations"] = list(folded.citations)
        result["child_status"] = folded.status.value
        result["turn_count"] = folded.turn_count
        result["input_tokens"] = int(folded.input_tokens or 0)
        result["output_tokens"] = int(folded.output_tokens or 0)
        return result

    async def _run_spawn_agent(
        self, call, bound, state, *, input=None, deps=None
    ) -> dict[str, Any] | DelegatedSpawn:
        task_id = input.task_id if input is not None else ""
        live = state.active_children or _legacy_single(state)
        if deps is not None and await self._has_pending_interrupt(deps, task_id):
            state = await self.fail_all_live_spawn_claims(
                state,
                deps,
                bound,
                reason="aborted",
                task_id=task_id or None,
                except_tool_call_id=call.tool_call_id,
            )
            error = self._spawn_tool_error(bound, "aborted")
            error["_loop_state"] = state
            return error
        if live and not self._config.subagent_enabled:
            state = await self.fail_all_live_spawn_claims(
                state,
                deps,
                bound,
                reason="subagent_disabled",
                task_id=task_id or None,
                except_tool_call_id=call.tool_call_id,
            )
            error = self._spawn_tool_error(bound, "subagent_disabled")
            error["_loop_state"] = state
            return error
        if not self._config.subagent_enabled:
            return self._legacy_explore_handoff(bound)
        max_active = _subagent_max_active(self._config)
        if (
            live
            and call.tool_call_id not in {child.tool_call_id for child in live}
            and len(live) >= max_active
        ):
            self._record_policy_capped()
            return self._spawn_tool_error(bound, "policy_child_already_active")
        if self._subagents is None:
            raise CodingLoopFailure("subagent_runtime_missing", retryable=False)
        if input is None:
            raise CodingLoopFailure("subagent_runtime_missing", retryable=False)
        from neos.subagent.catalog import UnknownSpec, lookup_spec
        from neos.subagent.types import (
            ModelPin,
            ParentKind,
            SandboxMode,
            StepKind,
            SubagentTicket,
        )

        raw = call.input if isinstance(call.input, Mapping) else {}
        spec_name = str(raw.get("spec") or "explore")
        try:
            lookup_spec(spec_name)
        except UnknownSpec:
            return self._spawn_tool_error(bound, "policy_unknown_spec")
        provider = self._config.provider
        if provider not in {"anthropic", "openai", "gemini", "ollama"}:
            return self._spawn_tool_error(bound, "model_pin_mismatch")
        try:
            max_turns = int(raw.get("max_turns", 4))
        except (TypeError, ValueError):
            max_turns = 4
        max_turns = max(1, min(8, max_turns))
        try:
            briefing = self._spawn_briefing(call)
        except ValueError:
            return self._spawn_tool_error(bound, "policy_schema_invalid")
        ref = self._child_ref(state, call.tool_call_id)
        ticket = SubagentTicket(
            parent_kind=ParentKind.CODING,
            parent_id=input.task_id,
            parent_run_id=input.run_id,
            parent_tool_call_id=call.tool_call_id,
            spec=spec_name,
            briefing=briefing,
            model=ModelPin(provider=provider, model=self._config.model),
            max_turns=max_turns,
            sandbox_mode=SandboxMode.PARENT_RO,
            expected_checkpoint_id=ref.checkpoint_id if ref else None,
            run_id=ref.run_id if ref else None,
        )
        self._bind_child_tools(bound, state)
        try:
            await self._renew_parent_lease(deps)
            outcome = await self._subagents.advance(ticket)
            await self._renew_parent_lease(deps)
        except asyncio.CancelledError:
            await self._cancel_active_child(
                state, reason="aborted", task_id=input.task_id
            )
            raise
        if outcome.kind is StepKind.CONTINUING:
            return DelegatedSpawn(
                run_id=outcome.run_id,
                checkpoint_id=outcome.checkpoint_id,
                step_kind=outcome.kind.value,
            )
        folded = await self._subagents.fold(outcome.run_id)
        return self._folded_spawn_result(bound, folded)

    async def _maybe_llm_compact(
        self, state: AgentLoopState, transcript: tuple[CanonicalMessage, ...]
    ) -> tuple[tuple[CanonicalMessage, ...], int]:
        attempts = state.llm_compact_attempts
        if attempts >= 1 or len(transcript) < 3:
            return transcript, attempts
        head = transcript[0]
        tail_start = next(
            (
                index
                for index in range(len(transcript) - 1, -1, -1)
                if transcript[index].role == "assistant"
                and any(
                    isinstance(item, ToolUseContent)
                    for item in transcript[index].content
                )
            ),
            len(transcript),
        )
        prefix = transcript[1:tail_start]
        if not prefix:
            return transcript, attempts
        blob = json.dumps(
            [_message_to_mapping(item) for item in prefix],
            ensure_ascii=False,
        )[:12_000]
        request = ModelRequest(
            system="Summarize prior coding context as facts only. <= 200 words.",
            messages=(
                CanonicalMessage(
                    "user",
                    (TextContent(f"Summarize this transcript prefix:\n{blob}"),),
                ),
            ),
            tools=(),
            model=self._config.model,
            limits=ModelLimits(512, min(self._config.timeout_sec, 30)),
            task_id="compact",
            run_id="compact",
            turn_id=f"compact_{uuid4().hex}",
        )
        parts: list[str] = []
        try:
            async for event in self._model.stream(request):
                if isinstance(event, TextDelta):
                    parts.append(event.text)
        except Exception:
            return transcript, attempts + 1
        summary = "".join(parts).strip()
        if not summary:
            return transcript, attempts + 1
        compacted = (head,) + (
            CanonicalMessage(
                "user",
                (TextContent(f"Prior context summary:\n{summary}"),),
            ),
        ) + transcript[tail_start:]
        return compacted, attempts + 1

    def _restore(self, input, checkpoint):
        if checkpoint is None:
            transcript = (CanonicalMessage("user", (TextContent(input.instruction),)),)
            transcript = self._with_workspace_edits(
                transcript,
                input.workspace_edits,
            )
            return AgentLoopState(
                transcript=transcript,
                turn_count=0,
                tool_count=0,
                consecutive_tool_errors=0,
                pending_tool_calls=(),
                pending_tool_index=0,
                transcript_digest=self._digest(transcript),
            )
        raw = checkpoint.loop_state
        transcript = tuple(
            _message_from_mapping(item) for item in raw.get("transcript", [])
        )
        transcript = self._with_workspace_edits(
            transcript,
            input.workspace_edits,
        )
        pending = tuple(
            ToolCallCompleted(item["tool_call_id"], item["name"], item["input"])
            for item in raw.get("pending_tool_calls", [])
        )
        stored = raw.get("read_paths")
        if stored:
            read_paths = frozenset(
                str(normalize_workspace_path(str(path))) for path in stored
            )
        else:
            read_paths = _read_paths_from_transcript(transcript)
        pending_instruction = raw.get("pending_instruction")
        terminal_pending = bool(raw.get("terminal_pending", False))
        digest = str(raw.get("transcript_digest", self._digest(transcript)))
        pending_index = int(raw.get("pending_tool_index", 0))
        has_open_tool_pair = bool(pending) and pending_index < len(pending)
        empty_retry_count = int(raw.get("empty_retry_count", 0))
        bodies = dict(_string_mapping(raw.get("compacted_bodies")))
        instructions_loaded = bool(raw.get("instructions_loaded", False))
        raw_todos = raw.get("todos") or ()
        todos = tuple(
            dict(item) for item in raw_todos if isinstance(item, Mapping)
        )
        if isinstance(pending_instruction, str) and pending_instruction:
            if not has_open_tool_pair:
                applied = self._apply_pending_command(
                    input,
                    transcript,
                    pending_instruction,
                    bodies=bodies,
                    todos=todos,
                    instructions_loaded=instructions_loaded,
                    cost_micros=int(raw.get("cost_micros", 0)),
                    input_tokens=int(raw.get("input_tokens", 0)),
                    output_tokens=int(raw.get("output_tokens", 0)),
                )
                transcript = applied.transcript
                bodies = applied.bodies
                todos = applied.todos
                instructions_loaded = applied.instructions_loaded
                pending_instruction = None
                terminal_pending = False
                digest = self._digest(transcript)
                empty_retry_count = 0
        else:
            pending_instruction = None
        children = _restore_active_children(raw)
        _warn_stale_active_child_scalars(raw, children)
        state = AgentLoopState(
            transcript=transcript,
            turn_count=int(raw.get("turn_count", 0)),
            tool_count=int(raw.get("tool_count", 0)),
            consecutive_tool_errors=int(raw.get("consecutive_tool_errors", 0)),
            pending_tool_calls=pending,
            pending_tool_index=pending_index,
            transcript_digest=digest,
            input_tokens=int(raw.get("input_tokens", 0)),
            output_tokens=int(raw.get("output_tokens", 0)),
            cost_micros=int(raw.get("cost_micros", 0)),
            terminal_pending=terminal_pending,
            read_paths=read_paths,
            pending_instruction=pending_instruction,
            todos=todos,
            phase=parse_phase(raw.get("phase")).value,
            instructions_loaded=instructions_loaded,
            prompt_compact_retries=int(raw.get("prompt_compact_retries", 0)),
            output_token_escalations=int(raw.get("output_token_escalations", 0)),
            llm_compact_attempts=int(raw.get("llm_compact_attempts", 0)),
            revealed_tools=frozenset(str(name) for name in raw.get("revealed_tools") or ()),
            approved_always=frozenset(
                str(name) for name in raw.get("approved_always") or ()
            ),
            hook_retry_count=int(raw.get("hook_retry_count", 0)),
            compacted_bodies=bodies,
            stop_retry_count=int(raw.get("stop_retry_count", 0)),
            read_stamps=_read_stamps_mapping(raw.get("read_stamps")),
            empty_retry_count=empty_retry_count,
            last_error_signature=str(raw.get("last_error_signature") or ""),
            last_error_count=int(raw.get("last_error_count", 0)),
            last_success_signature=str(raw.get("last_success_signature") or ""),
            last_success_result_hash=str(raw.get("last_success_result_hash") or ""),
            last_success_count=int(raw.get("last_success_count", 0)),
            verdict=restore_verify_verdict(raw.get("verdict")),
            critical_files=restore_plan_critical_files(raw.get("critical_files")),
            active_child_run_id=_optional_str(raw.get("active_child_run_id")),
            active_child_checkpoint_id=_optional_str(
                raw.get("active_child_checkpoint_id")
            ),
            active_child_tool_call_id=_optional_str(
                raw.get("active_child_tool_call_id")
            ),
            active_children=children,
        )
        return self._sync_active_children(state, children)

    def _apply_pending_command(
        self,
        input: LoopInput,
        transcript,
        text: str,
        *,
        bodies: dict[str, str],
        todos: tuple,
        instructions_loaded: bool,
        cost_micros: int,
        input_tokens: int,
        output_tokens: int,
    ):
        from neos.coding.commands.interpret import interpret_coding_command
        from neos.coding.commands.parse import sanitize_command_args
        from neos.coding.commands.types import CommandDisposition

        decision = interpret_coding_command(text)
        if decision.disposition is CommandDisposition.CHAT:
            return _AppliedPendingCommand(
                self._append_user_meta(transcript, text),
                bodies,
                todos,
                instructions_loaded,
            )
        if decision.disposition is CommandDisposition.INJECT:
            return _AppliedPendingCommand(
                self._append_user_meta(transcript, decision.inject_text),
                bodies,
                todos,
                instructions_loaded,
            )
        spec_name = decision.spec.name if decision.spec is not None else ""
        if spec_name == "compact":
            after = self._compact(transcript, force=True, bodies=bodies)
            hint = sanitize_command_args(decision.parsed.args, max_len=240)
            notice = (
                f"Transcript compacted by /compact. Keep: {hint}"
                if hint
                else "Transcript compacted by /compact."
            )
            return _AppliedPendingCommand(
                self._append_user_meta(after, notice),
                bodies,
                todos,
                False,
            )
        if spec_name == "clear":
            return _AppliedPendingCommand(
                self._cleared_transcript(input, transcript),
                {},
                (),
                False,
            )
        if spec_name == "cost":
            notice = (
                f"cost_micros={cost_micros} "
                f"tokens={input_tokens}+{output_tokens}"
            )
            return _AppliedPendingCommand(
                self._append_user_meta(transcript, notice),
                bodies,
                todos,
                instructions_loaded,
            )
        notice = decision.message or "Command was not applied as user work."
        return _AppliedPendingCommand(
            self._append_user_meta(transcript, notice),
            bodies,
            todos,
            instructions_loaded,
        )

    def _cleared_transcript(self, input: LoopInput, transcript=()):
        seed = self._task_seed_text(transcript, input)
        messages: list[CanonicalMessage] = []
        if seed:
            messages.append(CanonicalMessage("user", (TextContent(seed),)))
        messages.append(
            CanonicalMessage(
                "user",
                (TextContent("Conversation context was cleared."),),
            )
        )
        return tuple(messages)

    @staticmethod
    def _task_seed_text(transcript, input: LoopInput) -> str:
        for message in transcript or ():
            if getattr(message, "role", None) != "user":
                continue
            for item in getattr(message, "content", ()):
                text = getattr(item, "text", None)
                if not isinstance(text, str):
                    continue
                candidate = text.strip()
                if DurableCodingLoop._is_task_seed(candidate):
                    return candidate
        fallback = (input.instruction or "").strip()
        if DurableCodingLoop._is_task_seed(fallback):
            return fallback
        return ""

    @staticmethod
    def _is_task_seed(text: str) -> bool:
        from neos.coding.commands.interpret import interpret_coding_command
        from neos.coding.commands.types import CommandDisposition

        if not text or text == "Conversation context was cleared.":
            return False
        return (
            interpret_coding_command(text).disposition is CommandDisposition.CHAT
        )

    @staticmethod
    def _with_workspace_edits(transcript, edits):
        if not edits:
            return transcript
        summary = ", ".join(
            f"{edit.path} @ revision {edit.resulting_revision}"
            for edit in edits
        )
        return transcript + (
            CanonicalMessage(
                "user",
                (
                    TextContent(
                        "The user directly edited these workspace files. "
                        "Treat the listed revisions as authoritative and read "
                        "files before changing them: "
                        f"{summary}"
                    ),
                ),
            ),
        )

    def _dump_state(self, input, state):
        state = self._sync_active_children(state, state.active_children)
        current = (input.instruction or "").strip()
        if not self._is_task_seed(current):
            current = self._task_seed_text(state.transcript, input) or current
        return {
            "phase_index": state.tool_count - 1,
            "current_instruction": current,
            "pending_instruction": state.pending_instruction,
            "transcript": [_message_to_mapping(item) for item in state.transcript],
            "todos": [dict(item) for item in state.todos],
            "turn_count": state.turn_count,
            "tool_count": state.tool_count,
            "consecutive_tool_errors": state.consecutive_tool_errors,
            "pending_tool_calls": [asdict(item) for item in state.pending_tool_calls],
            "pending_tool_index": state.pending_tool_index,
            "transcript_digest": state.transcript_digest,
            "input_tokens": state.input_tokens,
            "output_tokens": state.output_tokens,
            "cost_micros": state.cost_micros,
            "terminal_pending": state.terminal_pending,
            "read_paths": sorted(state.read_paths),
            "phase": state.phase,
            "instructions_loaded": state.instructions_loaded,
            "prompt_compact_retries": state.prompt_compact_retries,
            "output_token_escalations": state.output_token_escalations,
            "llm_compact_attempts": state.llm_compact_attempts,
            "revealed_tools": sorted(state.revealed_tools),
            "approved_always": sorted(state.approved_always),
            "hook_retry_count": state.hook_retry_count,
            "compacted_bodies": dict(state.compacted_bodies),
            "stop_retry_count": state.stop_retry_count,
            "empty_retry_count": state.empty_retry_count,
            "last_error_signature": state.last_error_signature,
            "last_error_count": state.last_error_count,
            "last_success_signature": state.last_success_signature,
            "last_success_result_hash": state.last_success_result_hash,
            "last_success_count": state.last_success_count,
            "verdict": state.verdict,
            "critical_files": list(state.critical_files),
            "active_child_run_id": state.active_child_run_id,
            "active_child_checkpoint_id": state.active_child_checkpoint_id,
            "active_child_tool_call_id": state.active_child_tool_call_id,
            "active_children": [
                {
                    "run_id": child.run_id,
                    "checkpoint_id": child.checkpoint_id,
                    "tool_call_id": child.tool_call_id,
                    "last_advanced_at": child.last_advanced_at,
                }
                for child in state.active_children
            ],
            "read_stamps": {
                path: _dump_read_stamp(stamp)
                for path, stamp in sorted(state.read_stamps.items())
            },
        }

    @staticmethod
    def _with_terminal_pending(state: AgentLoopState) -> AgentLoopState:
        return replace(state, terminal_pending=True)

    async def _compact_with_hook(
        self, transcript, *, preserve_tools: bool = False, bodies=None
    ):
        before = tuple(transcript)
        after = self._compact(before, preserve_tools=preserve_tools, bodies=bodies)
        if after != before:
            await self._hooks.compact(before, after)
        return after

    def _over_budget(self, transcript) -> bool:
        return (
            len(transcript) > self._config.max_transcript_messages
            or self._serialized_bytes(transcript)
            > self._config.max_transcript_bytes
            or self._estimated_tokens(transcript)
            > self._config.max_transcript_tokens
        )

    def _over_bytes(self, transcript) -> bool:
        return (
            self._serialized_bytes(transcript) > self._config.max_transcript_bytes
        )

    def _compact(
        self,
        transcript,
        *,
        preserve_tools: bool = False,
        force: bool = False,
        bodies: dict[str, str] | None = None,
    ):
        del preserve_tools
        transcript = tuple(transcript)
        if not force and not self._over_budget(transcript):
            return transcript
        active_start = next(
            (
                index
                for index in range(len(transcript) - 1, -1, -1)
                if transcript[index].role == "assistant"
                and any(
                    isinstance(item, ToolUseContent)
                    for item in transcript[index].content
                )
            ),
            None,
        )
        if active_start is None:
            prefix = transcript
            active: tuple[CanonicalMessage, ...] = ()
        else:
            prefix = transcript[:active_start]
            active = transcript[active_start:]
        stored = bodies if bodies is not None else {}
        tool_names = _tool_use_names(prefix)
        prefix = tuple(
            self._shrink_old_tool_results(message, stored, tool_names)
            for message in prefix
        )
        candidate = prefix + active
        if not force and not self._over_budget(candidate):
            return candidate
        notice = CanonicalMessage(
            "user",
            (TextContent("Prior transcript compacted; kept tool pairs."),),
        )
        head: tuple[CanonicalMessage, ...] = ()
        remaining = list(prefix)
        if remaining and remaining[0].role == "user":
            head = (remaining.pop(0),)
        if force and remaining:
            remaining = self._drop_oldest_prefix_turn(remaining)
        while remaining and self._over_budget(
            head + (notice,) + tuple(remaining) + active
        ):
            remaining = self._drop_oldest_prefix_turn(remaining)
        if remaining:
            candidate = head + (notice,) + tuple(remaining) + active
        elif active:
            candidate = head + (notice,) + active
        elif head:
            candidate = head
        else:
            candidate = (notice,)
        if not self._over_budget(candidate) or not self._over_bytes(candidate):
            return candidate
        return self._require_transcript_fit(candidate)

    def _require_transcript_fit(self, transcript):
        if self._serialized_bytes(transcript) > self._config.max_transcript_bytes:
            raise CodingLoopFailure(
                "transcript_budget_exceeded", retryable=False
            )
        return tuple(transcript)

    @staticmethod
    def _drop_oldest_prefix_turn(
        remaining: list[CanonicalMessage],
    ) -> list[CanonicalMessage]:
        if not remaining:
            return remaining
        first = remaining.pop(0)
        if first.role != "assistant":
            return remaining
        use_ids = {
            item.tool_call_id
            for item in first.content
            if isinstance(item, ToolUseContent)
        }
        if not use_ids:
            return remaining
        while remaining and remaining[0].role == "tool":
            result_ids = {
                item.tool_call_id
                for item in remaining[0].content
                if isinstance(item, ToolResultContent)
            }
            if result_ids and not result_ids <= use_ids:
                break
            remaining.pop(0)
        return remaining

    @staticmethod
    def _expand_artifact_refs(transcript, bodies: Mapping[str, str]):
        if not bodies:
            return transcript
        expanded = []
        for message in transcript:
            items = []
            changed = False
            for item in message.content:
                if (
                    isinstance(item, ToolResultContent)
                    and item.content.get("compacted")
                ):
                    digest = item.content.get("sha256")
                    raw = bodies.get(str(digest or ""))
                    if raw:
                        try:
                            restored = json.loads(raw)
                        except json.JSONDecodeError:
                            restored = None
                        if isinstance(restored, dict):
                            items.append(
                                ToolResultContent(
                                    item.tool_call_id, item.status, restored
                                )
                            )
                            changed = True
                            continue
                items.append(item)
            expanded.append(
                CanonicalMessage(message.role, tuple(items)) if changed else message
            )
        return tuple(expanded)

    @staticmethod
    def _compact_ref_path(content: Mapping[str, object]) -> str | None:
        raw = content.get("path")
        if isinstance(raw, str) and raw:
            return raw
        entries = content.get("entries")
        if isinstance(entries, (list, tuple)):
            for entry in entries:
                if isinstance(entry, Mapping):
                    path = entry.get("path")
                    if isinstance(path, str) and path:
                        return path
        return None

    @staticmethod
    def _maybe_ref_latest_tool_result(
        transcript: tuple[CanonicalMessage, ...],
        *,
        tool_name: str,
        bodies: dict[str, str],
    ) -> tuple[CanonicalMessage, ...]:
        if not transcript:
            return transcript
        last = transcript[-1]
        if last.role != "tool":
            return transcript
        content = []
        changed = False
        for item in last.content:
            if (
                isinstance(item, ToolResultContent)
                and not item.content.get("compacted")
                and _tool_result_bytes(item.content) >= COMPACT_REF_THRESHOLD_BYTES
            ):
                content.append(_ref_tool_result(item, bodies))
                changed = True
            else:
                content.append(item)
        if not changed:
            return transcript
        return transcript[:-1] + (CanonicalMessage(last.role, tuple(content)),)

    @staticmethod
    def _shrink_old_tool_results(
        message: CanonicalMessage,
        bodies: dict[str, str],
        tool_names: Mapping[str, str] | None = None,
    ) -> CanonicalMessage:
        names = tool_names or {}
        content = []
        changed = False
        for item in message.content:
            if isinstance(item, ToolResultContent) and not item.content.get(
                "compacted"
            ):
                name = names.get(item.tool_call_id)
                if name == "read_file.v1" or (
                    name is None and _looks_like_file_read(item.content)
                ):
                    content.append(item)
                    continue
                content.append(_ref_tool_result(item, bodies))
                changed = True
            else:
                content.append(item)
        if not changed:
            return message
        return CanonicalMessage(message.role, tuple(content))

    @staticmethod
    def _serialized_text(transcript) -> str:
        return json.dumps(
            [_message_to_mapping(item) for item in transcript],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    @staticmethod
    def _serialized_bytes(transcript) -> int:
        return len(DurableCodingLoop._serialized_text(transcript).encode("utf-8"))

    @staticmethod
    def _estimated_tokens(transcript) -> int:
        return (len(DurableCodingLoop._serialized_text(transcript)) + 3) // 4

    @staticmethod
    def _digest(transcript):
        payload = json.dumps(
            [_message_to_mapping(item) for item in transcript],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode()).hexdigest()


def _scrub_think_blocks(text: str) -> str:
    cleaned = _THINK_CLOSED_RE.sub("", text)
    return _THINK_UNCLOSED_RE.sub("", cleaned)


def _is_empty_or_think_only(text: str) -> bool:
    return not _scrub_think_blocks(text).strip()


def _error_signature(name: str, tool_input: Mapping[str, object]) -> str:
    canonical = json.dumps(
        tool_input,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256((name + canonical).encode("utf-8")).hexdigest()


def _result_preview_hash(content: Mapping[str, object]) -> str:
    payload = {
        "preview": content.get("preview"),
        "status": content.get("status"),
    }
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def _is_stall_denied(
    state: AgentLoopState, name: str, tool_input: Mapping[str, object]
) -> bool:
    signature = _error_signature(name, tool_input)
    if (
        state.last_error_count >= STALL_DENY_AFTER
        and state.last_error_signature == signature
    ):
        return True
    return (
        state.last_success_count >= STALL_DENY_AFTER
        and state.last_success_signature == signature
    )


def _next_error_signature(
    state: AgentLoopState, name: str, tool_input: Mapping[str, object]
) -> tuple[str, int]:
    signature = _error_signature(name, tool_input)
    if signature == state.last_error_signature:
        return signature, state.last_error_count + 1
    return signature, 1


def _next_success_signature(
    state: AgentLoopState,
    name: str,
    tool_input: Mapping[str, object],
    result: ToolResultContent,
) -> tuple[str, str, int]:
    signature = _error_signature(name, tool_input)
    content = result.content if isinstance(result.content, Mapping) else {}
    result_hash = _result_preview_hash(content)
    if (
        signature == state.last_success_signature
        and result_hash == state.last_success_result_hash
    ):
        return signature, result_hash, state.last_success_count + 1
    return signature, result_hash, 1


def _uniquify_tool_calls(
    calls: Sequence[ToolCallCompleted],
) -> list[ToolCallCompleted]:
    used: set[str] = set()
    uniquified: list[ToolCallCompleted] = []
    for call in calls:
        candidate = call.tool_call_id
        if candidate not in used:
            used.add(candidate)
            uniquified.append(call)
            continue
        suffix = 2
        while True:
            next_id = f"{call.tool_call_id}_d{suffix}"
            if next_id not in used:
                used.add(next_id)
                uniquified.append(replace(call, tool_call_id=next_id))
                break
            suffix += 1
    return uniquified


def _string_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): str(item)
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, str)
    }


def _read_stamps_mapping(value: object) -> dict[str, dict[str, object]]:
    if not isinstance(value, Mapping):
        return {}
    stamps: dict[str, dict[str, object]] = {}
    for raw_path, raw_stamp in value.items():
        if not isinstance(raw_stamp, Mapping):
            continue
        mtime = raw_stamp.get("mtime")
        digest = raw_stamp.get("digest")
        if not isinstance(mtime, str) or not isinstance(digest, str):
            continue
        path = str(normalize_workspace_path(str(raw_path)))
        stamp: dict[str, object] = {
            "mtime": mtime,
            "digest": digest,
            "full": bool(raw_stamp.get("full", True)),
        }
        offset = raw_stamp.get("offset")
        limit = raw_stamp.get("limit")
        if isinstance(offset, int) and not isinstance(offset, bool):
            stamp["offset"] = offset
        if isinstance(limit, int) and not isinstance(limit, bool):
            stamp["limit"] = limit
        stamps[path] = stamp
    return stamps


def _dump_read_stamp(stamp: Mapping[str, object]) -> dict[str, object]:
    dumped: dict[str, object] = {
        "mtime": stamp["mtime"],
        "digest": stamp["digest"],
        "full": bool(stamp["full"]),
    }
    offset = stamp.get("offset")
    limit = stamp.get("limit")
    if isinstance(offset, int) and not isinstance(offset, bool):
        dumped["offset"] = offset
    if isinstance(limit, int) and not isinstance(limit, bool):
        dumped["limit"] = limit
    return dumped


_LINE_NUMBERED_RE = re.compile(r"^\s*\d+\|", re.MULTILINE)


def _tool_use_names(messages: Sequence[CanonicalMessage]) -> dict[str, str]:
    names: dict[str, str] = {}
    for message in messages:
        for item in message.content:
            if isinstance(item, ToolUseContent):
                names[item.tool_call_id] = item.name
    return names


def _looks_like_file_read(content: Mapping[str, object]) -> bool:
    preview = content.get("preview")
    if not isinstance(preview, str) or not preview:
        return False
    if _LINE_NUMBERED_RE.search(preview):
        return True
    entries = content.get("entries")
    if isinstance(entries, (list, tuple)):
        for entry in entries:
            if isinstance(entry, Mapping):
                text = entry.get("text")
                if isinstance(text, str) and _LINE_NUMBERED_RE.search(text):
                    return True
    return False


def _tool_result_bytes(content: Mapping[str, object]) -> int:
    return len(
        json.dumps(
            dict(content),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    )


def _ref_tool_result(
    item: ToolResultContent, bodies: dict[str, str]
) -> ToolResultContent:
    payload = dict(item.content)
    payload_text = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
    preview_source = payload.get("preview")
    if not isinstance(preview_source, str) or not preview_source:
        preview_source = payload_text
    shrunk: dict[str, object] = {
        "compacted": True,
        "sha256": digest,
        "preview": preview_source[:200],
    }
    path = DurableCodingLoop._compact_ref_path(payload)
    bodies[digest] = payload_text
    if path is None:
        path = f"artifact://{digest}"
    shrunk["path"] = path
    return ToolResultContent(item.tool_call_id, item.status, shrunk)


def _tool_event_preview(name: str, tool_input: Mapping[str, object]) -> str:
    detail = ""
    path = tool_input.get("path")
    if isinstance(path, str) and path:
        detail = path
    else:
        argv = tool_input.get("argv")
        if isinstance(argv, (list, tuple)) and argv:
            detail = str(argv[0])
    summary = f"{name} {detail}".strip() if detail else name
    redacted = redact_sensitive(summary)
    if not isinstance(redacted, str):
        redacted = name
    return redacted[:200]


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _tool_result_ids(transcript) -> set[str]:
    return {
        item.tool_call_id
        for message in transcript
        for item in message.content
        if isinstance(item, ToolResultContent)
    }


def _subagent_max_active(config) -> int:
    return min(4, max(1, getattr(config, "subagent_max_active", 1)))


def _spawn_window(state) -> tuple[ToolCallCompleted, ...]:
    window: list[ToolCallCompleted] = []
    for call in state.pending_tool_calls[state.pending_tool_index :]:
        if call.name != "spawn_agent.v1":
            break
        window.append(call)
    return tuple(window)


def _pending_by_id(state, tool_call_id: str) -> ToolCallCompleted | None:
    for call in state.pending_tool_calls:
        if call.tool_call_id == tool_call_id:
            return call
    return None


def _select_spawn_work(state, *, max_active: int) -> SpawnWork | None:
    window = _spawn_window(state)
    live = list(state.active_children or _legacy_single(state))
    live_ids = {child.tool_call_id for child in live}
    done = _tool_result_ids(state.transcript)
    unstarted = [
        call
        for call in window
        if call.tool_call_id not in live_ids and call.tool_call_id not in done
    ]
    if len(live) < max_active and unstarted:
        return SpawnWork(kind="start", call=unstarted[0], child=None)
    if live:
        picked = min(live, key=lambda child: (child.last_advanced_at, child.tool_call_id))
        call = _pending_by_id(state, picked.tool_call_id)
        return SpawnWork(kind="resume", call=call, child=picked)
    return None


def _legacy_single(state) -> tuple[ActiveChildRef, ...]:
    run_id = getattr(state, "active_child_run_id", None)
    if not run_id:
        return ()
    tool_call_id = getattr(state, "active_child_tool_call_id", None) or ""
    return (
        ActiveChildRef(
            run_id=run_id,
            checkpoint_id=getattr(state, "active_child_checkpoint_id", None),
            tool_call_id=tool_call_id,
            last_advanced_at=_EPOCH_STAMP,
        ),
    )


def _restore_active_children(raw: Mapping[str, Any]) -> tuple[ActiveChildRef, ...]:
    if "active_children" in raw:
        items = raw.get("active_children") or ()
        children: list[ActiveChildRef] = []
        if isinstance(items, Sequence) and not isinstance(items, (str, bytes)):
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                run_id = _optional_str(item.get("run_id"))
                tool_call_id = _optional_str(item.get("tool_call_id"))
                if not run_id or not tool_call_id:
                    continue
                stamp = _optional_str(item.get("last_advanced_at")) or ""
                children.append(
                    ActiveChildRef(
                        run_id=run_id,
                        checkpoint_id=_optional_str(item.get("checkpoint_id")),
                        tool_call_id=tool_call_id,
                        last_advanced_at=stamp,
                    )
                )
        if len(children) > 1:
            children = [
                (
                    child
                    if child.last_advanced_at
                    else replace(child, last_advanced_at=_EPOCH_STAMP)
                )
                for child in children
            ]
        return tuple(children)
    run_id = _optional_str(raw.get("active_child_run_id"))
    if not run_id:
        return ()
    return (
        ActiveChildRef(
            run_id=run_id,
            checkpoint_id=_optional_str(raw.get("active_child_checkpoint_id")),
            tool_call_id=_optional_str(raw.get("active_child_tool_call_id")) or "",
            last_advanced_at=_EPOCH_STAMP,
        ),
    )


def _warn_stale_active_child_scalars(
    raw: Mapping[str, Any], children: tuple[ActiveChildRef, ...]
) -> None:
    if "active_children" not in raw:
        return
    raw_run = _optional_str(raw.get("active_child_run_id"))
    raw_ckpt = _optional_str(raw.get("active_child_checkpoint_id"))
    raw_tool = _optional_str(raw.get("active_child_tool_call_id"))
    if raw_run is None and raw_ckpt is None and raw_tool is None:
        return
    head = children[0] if children else None
    expected = (
        head.run_id if head else None,
        head.checkpoint_id if head else None,
        head.tool_call_id if head else None,
    )
    actual = (raw_run, raw_ckpt, raw_tool)
    if actual == expected:
        return
    logger.warning(
        "active_child scalars disagree with active_children[0]; remirroring "
        "run_id=%s checkpoint_id=%s tool_call_id=%s from list run_id=%s "
        "checkpoint_id=%s tool_call_id=%s",
        raw_run,
        raw_ckpt,
        raw_tool,
        expected[0],
        expected[1],
        expected[2],
    )


def _tool_event_payload(call, **extra: Any) -> dict[str, Any]:
    payload = dict(extra)
    payload["name"] = getattr(call, "name", "")
    payload["preview"] = _tool_event_preview(
        str(payload["name"]),
        dict(getattr(call, "input", {}) or {}),
    )
    return payload


def _executor_read_stamps(executor: object) -> dict[str, dict[str, object]]:
    method = getattr(executor, "export_read_stamps", None)
    if not callable(method):
        return {}
    try:
        exported = method()
    except TypeError:
        return {}
    return _read_stamps_mapping(exported)


def _read_paths_from_transcript(transcript: tuple[CanonicalMessage, ...]) -> frozenset[str]:
    pending: dict[str, str] = {}
    read_paths: set[str] = set()
    for message in transcript:
        for item in message.content:
            if isinstance(item, ToolUseContent) and item.name == "read_file.v1":
                raw_path = item.input.get("path")
                if raw_path:
                    pending[item.tool_call_id] = str(raw_path)
            elif isinstance(item, ToolResultContent) and item.status == "ok":
                raw_path = pending.get(item.tool_call_id)
                if raw_path:
                    read_paths.add(str(normalize_workspace_path(raw_path)))
    return frozenset(read_paths)


def _message_to_mapping(message: CanonicalMessage) -> dict[str, Any]:
    content = []
    for item in message.content:
        if isinstance(item, TextContent):
            content.append({"type": "text", "text": item.text})
        elif isinstance(item, ToolUseContent):
            content.append(
                {
                    "type": "tool_use",
                    "tool_call_id": item.tool_call_id,
                    "name": item.name,
                    "input": dict(item.input),
                }
            )
        else:
            content.append(
                {
                    "type": "tool_result",
                    "tool_call_id": item.tool_call_id,
                    "status": item.status,
                    "content": dict(item.content),
                }
            )
    return {"role": message.role, "content": content}


def _message_from_mapping(value: Mapping[str, Any]) -> CanonicalMessage:
    content = []
    for item in value["content"]:
        if item["type"] == "text":
            content.append(TextContent(item["text"]))
        elif item["type"] == "tool_use":
            content.append(
                ToolUseContent(item["tool_call_id"], item["name"], item["input"])
            )
        else:
            content.append(
                ToolResultContent(item["tool_call_id"], item["status"], item["content"])
            )
    return CanonicalMessage(value["role"], tuple(content))

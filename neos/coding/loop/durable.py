from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from collections.abc import AsyncIterator, Callable, Mapping
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
    evaluate_approval,
)
from neos.coding.domain.phases import CodingCheckpoint
from neos.coding.harness import fold_model_event, iter_model_turn
from neos.coding.instructions import INSTRUCTION_CANDIDATES, load_workspace_instructions
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
    tool_allowed_in_phase,
    write_risk_blocked,
)
from neos.coding.hooks import CodingHookPort, NullCodingHooks
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

PRE_TOOL_HOOK_TIMEOUT_SEC = 5.0
STOP_RETRY_LIMIT = 2
COMPACT_REF_THRESHOLD_BYTES = 4096
DEFAULT_MAX_TRANSCRIPT_TOKENS = 80_000


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

    def __post_init__(self) -> None:
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

    @property
    def has_pending_tool(self) -> bool:
        return self.pending_tool_index < len(self.pending_tool_calls)


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
        if state.turn_count >= self._config.max_turns:
            raise CodingLoopFailure("turn_budget_exceeded", retryable=False)
        if not state.instructions_loaded:
            state = await self._load_workspace_instructions(state, bound)
        request = ModelRequest(
            system=await coding_turn_system(self._config.system, input.owner_id),
            messages=self._expand_artifact_refs(
                state.transcript, state.compacted_bodies
            ),
            tools=self._tool_definitions(state),
            model=self._config.model,
            limits=self._model_limits(state),
            task_id=input.task_id,
            run_id=input.run_id,
            turn_id=f"turn_{uuid4().hex}",
        )
        part_id = f"ctp_{uuid4().hex}"
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
                    yield committed.event
                elif isinstance(model_event, ToolInputDelta):
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
            raise CodingLoopFailure(error.code, retryable=error.retryable) from error
        if completion is None:
            raise CodingLoopFailure("model_stream_incomplete", retryable=True)
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
            if completion.stop_reason != "end_turn":
                raise CodingLoopFailure("model_output_incomplete", retryable=False)
            held = self._hold_incomplete_phase(next_state, "".join(text_parts))
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
            await self._persist_abort_after_cancel(input, current, bound, deps)
            raise

    async def _advance_one_tool_body(self, input, state, bound, deps, prefetch=None):
        prefetch = prefetch or {}
        if state.tool_count >= self._config.max_tools:
            raise CodingLoopFailure("tool_budget_exceeded", retryable=False)
        batch = self._leading_readonly_batch(state)
        if batch is not None:
            hook_blocked = False
            for _call, validated in batch:
                decision, _reason = await self._pre_tool_decision(validated)
                if decision in {"deny", "retry"}:
                    hook_blocked = True
                    break
            if not hook_blocked:
                async for event, current in self._advance_readonly_batch(
                    input, state, bound, deps, batch, prefetch=prefetch
                ):
                    yield event, current
                return
        call = state.pending_tool_calls[state.pending_tool_index]
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
        hook_decision, hook_reason = await self._pre_tool_decision(validated)
        if hook_decision == "deny":
            event, denied_state = await self._commit_denied_tool(
                input, state, bound, deps, call, "policy_hook_denied"
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
                    {"reason_code": reason_code},
                )
                denied_state = await self._after_result(
                    state, denied, tool_name=call.name, tool_input=call.input
                )
                committed = await deps.repository.commit_model_checkpoint(
                    lease=deps.lease,
                    event_type="tool.denied",
                    event_payload={"reason_code": reason_code},
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
        claim = await deps.repository.claim_tool_execution(
            lease=deps.lease,
            tool_call_id=call.tool_call_id,
            now=self._clock(),
            claim_expires_at=self._clock()
            + timedelta(seconds=self._config.tool_claim_ttl_sec),
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
                payload={"result": result, "reused": True},
                run_id=input.run_id,
                tool_call_id=call.tool_call_id,
            )
        else:
            try:
                if call.name == "spawn_agent.v1":
                    result = await self._run_spawn_agent(
                        call, bound, state, input=input, deps=deps
                    )
                else:
                    result = await self._execute_validated(
                        bound,
                        deps,
                        validated,
                        known_reads=state.read_paths,
                        prefetched=prefetch.get(call.tool_call_id),
                    )
            except CodingLoopFailure as error:
                if error.code != "tool_outcome_unknown":
                    raise
                async for item in self._emit_unknown_tool_result(
                    input, state, bound, deps, call, claim=claim, started=started
                ):
                    yield item
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
        self._record_tool_metric(call.name, result)
        yield tool_event, state
        status = str(result.get("status", "ok"))
        canonical_status = status if status in {"ok", "error", "denied"} else "ok"
        after = await self._after_result(
            state,
            ToolResultContent(call.tool_call_id, canonical_status, result),
            tool_name=call.name,
            tool_input=call.input,
        )
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
                    payload={"result": result, "reused": True},
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
            self._record_tool_metric(call.name, result)
            yield tool_event, current
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

    async def _pre_tool_decision(self, validated) -> tuple[str, str]:
        try:
            raw = await asyncio.wait_for(
                self._hooks.pre_tool(validated),
                timeout=PRE_TOOL_HOOK_TIMEOUT_SEC,
            )
        except TimeoutError:
            return "deny", "hook_timeout"
        except Exception:
            return "deny", "hook_error"
        if raw is None:
            return "allow", ""
        if not isinstance(raw, Mapping):
            return "deny", "hook_error"
        decision = raw.get("decision")
        if decision not in {"allow", "deny", "retry"}:
            return "deny", "hook_error"
        reason = raw.get("reason")
        return str(decision), str(reason) if reason is not None else ""

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
                payload={"result": result, "reason_code": "tool_outcome_unknown"},
                run_id=input.run_id,
                tool_call_id=call.tool_call_id,
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
        self, bound, deps, validated, *, known_reads, prefetched=None
    ):
        try:
            if prefetched is not None:
                executed = prefetched
            else:
                executed = await self._executor.execute(
                    bound.session,
                    validated,
                    known_reads=known_reads,
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
        await self._hooks.post_tool(validated, result)
        return result

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

    async def _commit_denied_tool(self, input, state, bound, deps, call, reason_code):
        await self._audit.emit(
            CodingToolAuditEvent.from_result(
                provider=bound.binding.provider,
                tool=call.name,
                operation="validate",
                outcome="denied",
                error_code=reason_code,
            )
        )
        denied = ToolResultContent(
            call.tool_call_id, "denied", {"reason_code": reason_code}
        )
        denied_state = await self._after_result(
            state, denied, tool_name=call.name, tool_input=call.input
        )
        committed = await deps.repository.commit_model_checkpoint(
            lease=deps.lease,
            event_type="tool.denied",
            event_payload={"reason_code": reason_code},
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
        remaining = state.pending_tool_calls[state.pending_tool_index :]
        existing = {
            item.tool_call_id
            for message in state.transcript
            for item in message.content
            if isinstance(item, ToolResultContent)
        }
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
        text = "".join(text_parts)
        if text:
            content.append(TextContent(text))
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
        )

    async def _after_result(
        self, state, result, *, tool_name: str, tool_input: Mapping[str, object]
    ):
        has_more_tools = state.pending_tool_index + 1 < len(state.pending_tool_calls)
        bodies = dict(state.compacted_bodies)
        transcript = await self._compact_with_hook(
            state.transcript + (CanonicalMessage("tool", (result,)),),
            preserve_tools=has_more_tools,
            bodies=bodies,
        )
        reason = ""
        if isinstance(result.content, Mapping):
            reason = str(result.content.get("reason_code") or "")
        if result.status == "ok":
            errors = 0
        elif reason == "tool_outcome_unknown":
            errors = state.consecutive_tool_errors
        else:
            errors = state.consecutive_tool_errors + 1
        read_paths = state.read_paths
        if tool_name == "read_file.v1" and result.status == "ok":
            raw_path = tool_input.get("path")
            if raw_path:
                read_paths = read_paths | {
                    str(normalize_workspace_path(str(raw_path)))
                }
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
            pending_tool_index=state.pending_tool_index + 1,
            transcript_digest=self._digest(transcript),
            terminal_pending=False,
            read_paths=read_paths,
            todos=todos,
            phase=phase,
            revealed_tools=revealed,
            hook_retry_count=0,
            compacted_bodies=bodies,
        )

    def _check_usage_budgets(self, state):
        if state.input_tokens + state.output_tokens > self._config.max_total_tokens:
            raise CodingLoopFailure("token_budget_exceeded", retryable=False)
        if state.cost_micros > self._config.max_cost_micros:
            raise CodingLoopFailure("cost_budget_exceeded", retryable=False)

    async def _load_workspace_instructions(self, state, bound) -> AgentLoopState:
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
        if not tool_allowed_in_phase(call.name, state.phase):
            return None
        try:
            validated = self._tools.validate(call.name, call.input)
        except ToolValidationError:
            return None
        if validated.risk is not ToolRisk.READ_ONLY:
            return None
        return asyncio.create_task(
            self._executor.execute(
                bound.session, validated, known_reads=state.read_paths
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

    async def _run_spawn_agent(
        self, call, bound, state, *, input=None, deps=None
    ) -> dict[str, Any]:
        del call, state
        task_id = input.task_id if input is not None else ""
        if deps is not None and await self._has_pending_interrupt(deps, task_id):
            return self._spawn_tool_error(bound, "aborted")
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
            return AgentLoopState(transcript, 0, 0, 0, (), 0, self._digest(transcript))
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
        if isinstance(pending_instruction, str) and pending_instruction:
            transcript = transcript + (
                CanonicalMessage("user", (TextContent(pending_instruction),)),
            )
            pending_instruction = None
            terminal_pending = False
            digest = self._digest(transcript)
        else:
            pending_instruction = None
        raw_todos = raw.get("todos") or ()
        todos = tuple(
            dict(item) for item in raw_todos if isinstance(item, Mapping)
        )
        return AgentLoopState(
            transcript,
            int(raw.get("turn_count", 0)),
            int(raw.get("tool_count", 0)),
            int(raw.get("consecutive_tool_errors", 0)),
            pending,
            int(raw.get("pending_tool_index", 0)),
            digest,
            int(raw.get("input_tokens", 0)),
            int(raw.get("output_tokens", 0)),
            int(raw.get("cost_micros", 0)),
            terminal_pending,
            read_paths,
            pending_instruction,
            todos,
            parse_phase(raw.get("phase")).value,
            bool(raw.get("instructions_loaded", False)),
            int(raw.get("prompt_compact_retries", 0)),
            int(raw.get("output_token_escalations", 0)),
            int(raw.get("llm_compact_attempts", 0)),
            frozenset(str(name) for name in raw.get("revealed_tools") or ()),
            frozenset(str(name) for name in raw.get("approved_always") or ()),
            int(raw.get("hook_retry_count", 0)),
            _string_mapping(raw.get("compacted_bodies")),
            int(raw.get("stop_retry_count", 0)),
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
        return {
            "phase_index": state.tool_count - 1,
            "current_instruction": input.instruction,
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
        prefix = tuple(
            self._shrink_old_tool_results(message, stored) for message in prefix
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
    def _shrink_old_tool_results(
        message: CanonicalMessage, bodies: dict[str, str]
    ) -> CanonicalMessage:
        content = []
        changed = False
        for item in message.content:
            if isinstance(item, ToolResultContent) and not item.content.get(
                "compacted"
            ):
                payload = dict(item.content)
                payload_text = json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
                payload_bytes = payload_text.encode("utf-8")
                digest = hashlib.sha256(payload_bytes).hexdigest()
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
                content.append(
                    ToolResultContent(item.tool_call_id, item.status, shrunk)
                )
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


def _string_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): str(item)
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, str)
    }


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

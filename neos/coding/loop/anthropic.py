from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from neos.coding.domain.events import CodingEvent
from neos.coding.domain.text_parts import TextPartConflict
from neos.coding.domain.approvals import (
    ApprovalPolicyOutcome,
    ApprovalStatus,
    evaluate_approval,
)
from neos.coding.domain.phases import CodingCheckpoint, CodingPhaseKind
from neos.coding.instructions import INSTRUCTION_CANDIDATES, load_workspace_instructions
from neos.coding.loop.base import LoopDependencies, LoopInput
from neos.coding.model.anthropic import CodingModelError
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
from neos.coding.phases import hidden_tools_for_phase, parse_phase, tool_allowed_in_phase
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


class CodingLoopFailure(RuntimeError):
    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class CodingLoopWaitingApproval(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AnthropicLoopConfig:
    model: str
    system: str
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
    max_text_delta_bytes: int = 16_384
    max_public_text_bytes: int = 1_048_576
    approval_ttl_sec: float = 900

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
            self.max_text_delta_bytes,
            self.max_public_text_bytes,
            self.approval_ttl_sec,
        )
        if not self.model or not self.system or any(value <= 0 for value in numeric):
            raise ValueError("anthropic loop configuration limits must be positive")
        if not (
            self.max_text_delta_bytes
            <= self.max_public_text_bytes
            <= self.max_transcript_bytes
        ):
            raise ValueError("anthropic public text byte limits are invalid")
        if (
            self.input_cost_micros_per_million < 0
            or self.output_cost_micros_per_million < 0
        ):
            raise ValueError("anthropic model prices cannot be negative")


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

    @property
    def has_pending_tool(self) -> bool:
        return self.pending_tool_index < len(self.pending_tool_calls)


class AnthropicCodingLoop:
    def __init__(
        self,
        *,
        model: CodingModel,
        tools: CodingToolRegistry,
        executor: SandboxToolExecutor,
        bindings: SandboxBindingService,
        config: AnthropicLoopConfig,
        metrics=None,
        audit=None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        approval_evaluator: Callable[
            [ValidatedToolCall], ApprovalPolicyOutcome
        ] = evaluate_approval,
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
            system=self._config.system,
            messages=state.transcript,
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
            async for model_event in self._model.stream(request):
                if isinstance(model_event, TextDelta):
                    delta_bytes = len(model_event.text.encode("utf-8"))
                    if delta_bytes > self._config.max_text_delta_bytes:
                        raise CodingLoopFailure(
                            "model_text_delta_too_large", retryable=False
                        )
                    text_parts.append(model_event.text)
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
                    calls.append(model_event)
                    task = self._maybe_prefetch_readonly(
                        model_event, bound, state
                    )
                    if task is not None:
                        prefetch_tasks[model_event.tool_call_id] = task
                elif isinstance(model_event, ModelCompleted):
                    completion = model_event
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
                provider="anthropic", outcome=outcome
            ).inc()
        if (
            not calls
            and completion.stop_reason == "max_tokens"
            and state.output_token_escalations < 1
        ):
            retry_state = replace(
                state,
                instructions_loaded=True,
                output_token_escalations=state.output_token_escalations + 1,
                input_tokens=state.input_tokens + completion.usage.input_tokens,
                output_tokens=state.output_tokens + completion.usage.output_tokens,
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
            await self._hooks.stop(completion.stop_reason)
            return
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
        await self._audit.emit(
            CodingToolAuditEvent.from_result(
                provider=bound.binding.provider,
                tool=call.name,
                operation="validate",
                outcome="allowed",
            )
        )
        approval_outcome = self._approval_evaluator(validated)
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
            raise CodingLoopFailure("tool_outcome_unknown", retryable=False)
        started = await deps.repository.begin_phase(
            lease=deps.lease, kind=CodingPhaseKind.IMPLEMENT, now=self._clock()
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
            if call.name == "spawn_agent.v1":
                result = await self._run_spawn_agent(call, bound, state)
            else:
                result = await self._execute_validated(
                    bound,
                    deps,
                    validated,
                    known_reads=state.read_paths,
                    prefetched=prefetch.get(call.tool_call_id),
                )
            if validated.risk is not ToolRisk.READ_ONLY:
                try:
                    await self._bindings.record_mutation(
                        deps.lease,
                        workspace_revision=(
                            await bound.session.workspace_revision()
                        ),
                    )
                except Exception as error:
                    await self._audit.emit(
                        CodingToolAuditEvent.from_result(
                            provider=bound.binding.provider,
                            tool=validated.name,
                            operation="execute",
                            outcome="error",
                            error_code="tool_outcome_unknown",
                        )
                    )
                    raise CodingLoopFailure(
                        "tool_outcome_unknown", retryable=False
                    ) from error
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
            lease=deps.lease, kind=CodingPhaseKind.IMPLEMENT, now=self._clock()
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

    async def _execute_validated(
        self, bound, deps, validated, *, known_reads, prefetched=None
    ):
        await self._hooks.pre_tool(validated)
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
        if not pending:
            return
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
            event_type="tool.completed",
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
        transcript = await self._compact_with_hook(
            transcript, preserve_tools=bool(calls)
        )
        usage = completion.usage
        cost = (
            state.cost_micros
            + (
                usage.input_tokens * self._config.input_cost_micros_per_million
                + usage.output_tokens * self._config.output_cost_micros_per_million
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
            input_tokens=state.input_tokens + usage.input_tokens,
            output_tokens=state.output_tokens + usage.output_tokens,
            cost_micros=cost,
            terminal_pending=False,
        )

    async def _after_result(
        self, state, result, *, tool_name: str, tool_input: Mapping[str, object]
    ):
        has_more_tools = state.pending_tool_index + 1 < len(state.pending_tool_calls)
        transcript = await self._compact_with_hook(
            state.transcript + (CanonicalMessage("tool", (result,)),),
            preserve_tools=has_more_tools,
        )
        errors = 0 if result.status == "ok" else state.consecutive_tool_errors + 1
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
        after = self._compact(before, force=True)
        after, attempts = await self._maybe_llm_compact(state, after)
        if after != before:
            await self._hooks.compact(before, after)
        return replace(
            state,
            transcript=after,
            transcript_digest=self._digest(after),
            prompt_compact_retries=state.prompt_compact_retries + 1,
            llm_compact_attempts=attempts,
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

    async def _run_spawn_agent(self, call, bound, state) -> dict[str, Any]:
        prompt = str(call.input.get("prompt") or "")
        try:
            max_turns = int(call.input.get("max_turns") or 4)
        except (TypeError, ValueError):
            max_turns = 4
        max_turns = min(8, max(1, max_turns))
        child_messages: tuple[CanonicalMessage, ...] = (
            CanonicalMessage("user", (TextContent(prompt),)),
        )
        last_text = ""
        explore_tools = self._tools.definitions(phase="explore")
        for _ in range(max_turns):
            request = ModelRequest(
                system=self._config.system,
                messages=child_messages,
                tools=explore_tools,
                model=self._config.model,
                limits=ModelLimits(
                    min(self._config.max_output_tokens, 2048),
                    self._config.timeout_sec,
                ),
                task_id="spawn",
                run_id="spawn",
                turn_id=f"spawn_{uuid4().hex}",
            )
            text_parts: list[str] = []
            child_calls: list[ToolCallCompleted] = []
            try:
                async for event in self._model.stream(request):
                    if isinstance(event, TextDelta):
                        text_parts.append(event.text)
                    elif isinstance(event, ToolCallCompleted):
                        child_calls.append(event)
            except Exception:
                break
            last_text = "".join(text_parts)
            if not child_calls:
                break
            assistant_items = []
            tool_items = []
            for child in child_calls:
                if not tool_allowed_in_phase(child.name, "explore"):
                    continue
                try:
                    validated = self._tools.validate(child.name, child.input)
                except ToolValidationError:
                    continue
                executed = await self._executor.execute(
                    bound.session, validated, known_reads=state.read_paths
                )
                mapping = executed.to_mapping()
                assistant_items.append(
                    ToolUseContent(child.tool_call_id, child.name, child.input)
                )
                tool_items.append(
                    ToolResultContent(
                        child.tool_call_id,
                        str(mapping.get("status", "ok")),
                        mapping,
                    )
                )
            if not assistant_items:
                break
            child_messages = child_messages + (
                CanonicalMessage("assistant", tuple(assistant_items)),
                CanonicalMessage("tool", tuple(tool_items)),
            )
        return ToolResult.ok(
            workspace_revision=str(bound.binding.workspace_revision),
            entries=({"summary": last_text or "no output"},),
        ).to_mapping()

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
        }

    @staticmethod
    def _with_terminal_pending(state: AgentLoopState) -> AgentLoopState:
        return replace(state, terminal_pending=True)

    async def _compact_with_hook(self, transcript, *, preserve_tools: bool = False):
        before = tuple(transcript)
        after = self._compact(before, preserve_tools=preserve_tools)
        if after != before:
            await self._hooks.compact(before, after)
        return after

    def _over_budget(self, transcript) -> bool:
        return (
            len(transcript) > self._config.max_transcript_messages
            or self._serialized_bytes(transcript)
            > self._config.max_transcript_bytes
        )

    def _over_bytes(self, transcript) -> bool:
        return (
            self._serialized_bytes(transcript) > self._config.max_transcript_bytes
        )

    def _compact(self, transcript, *, preserve_tools: bool = False, force: bool = False):
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
        prefix = tuple(self._shrink_old_tool_results(message) for message in prefix)
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
            remaining.pop(0)
        while remaining and self._over_budget(
            head + (notice,) + tuple(remaining) + active
        ):
            remaining.pop(0)
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
    def _shrink_old_tool_results(message: CanonicalMessage) -> CanonicalMessage:
        content = []
        changed = False
        for item in message.content:
            if isinstance(item, ToolResultContent) and not item.content.get(
                "compacted"
            ):
                digest = hashlib.sha256(
                    json.dumps(
                        dict(item.content),
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode("utf-8")
                ).hexdigest()
                content.append(
                    ToolResultContent(
                        item.tool_call_id,
                        item.status,
                        {"compacted": True, "sha256": digest},
                    )
                )
                changed = True
            else:
                content.append(item)
        if not changed:
            return message
        return CanonicalMessage(message.role, tuple(content))

    @staticmethod
    def _serialized_bytes(transcript) -> int:
        return len(
            json.dumps(
                [_message_to_mapping(item) for item in transcript],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        )

    @staticmethod
    def _digest(transcript):
        payload = json.dumps(
            [_message_to_mapping(item) for item in transcript],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode()).hexdigest()


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

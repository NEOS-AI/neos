from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from neos.coding.domain.events import CodingEvent
from neos.coding.domain.phases import CodingCheckpoint, CodingPhaseKind
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
from neos.coding.sandbox.bindings import SandboxBindingService
from neos.coding.tools.executor import SandboxToolExecutor
from neos.coding.tools.registry import CodingToolRegistry, ToolRisk, ToolValidationError
from neos.coding.domain.durability import ToolExecutionDisposition


class CodingLoopFailure(RuntimeError):
    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


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
        )
        if not self.model or not self.system or any(value <= 0 for value in numeric):
            raise ValueError("anthropic loop configuration limits must be positive")


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
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._model = model
        self._tools = tools
        self._executor = executor
        self._bindings = bindings
        self._config = config
        self._clock = clock

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
        bound = await self._bindings.resolve(input.task_id, input.run_id)
        if state.has_pending_tool:
            async for event in self._advance_one_tool(input, state, bound, deps):
                yield event
            return
        async for event in self._advance_one_model_turn(input, state, bound, deps):
            yield event

    async def _advance_one_model_turn(self, input, state, bound, deps):
        if state.turn_count >= self._config.max_turns:
            raise CodingLoopFailure("turn_budget_exceeded", retryable=False)
        request = ModelRequest(
            system=self._config.system,
            messages=state.transcript,
            tools=self._tools.definitions(),
            model=self._config.model,
            limits=ModelLimits(
                self._config.max_output_tokens, self._config.timeout_sec
            ),
            task_id=input.task_id,
            run_id=input.run_id,
            turn_id=f"turn_{uuid4().hex}",
        )
        text_parts: list[str] = []
        calls: list[ToolCallCompleted] = []
        completion: ModelCompleted | None = None
        try:
            async for model_event in self._model.stream(request):
                if isinstance(model_event, TextDelta):
                    text_parts.append(model_event.text)
                    yield await deps.events.append(
                        task_id=input.task_id,
                        event_type="model.text_delta",
                        payload={"bytes": len(model_event.text.encode("utf-8"))},
                        run_id=input.run_id,
                        turn_id=request.turn_id,
                    )
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
                elif isinstance(model_event, ModelCompleted):
                    completion = model_event
        except asyncio.CancelledError:
            raise
        except CodingModelError as error:
            raise CodingLoopFailure(error.code, retryable=error.retryable) from error
        if completion is None:
            raise CodingLoopFailure("model_stream_incomplete", retryable=True)
        next_state = self._completed_turn(state, text_parts, calls, completion)
        self._check_usage_budgets(next_state)
        if not calls:
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
        async for event in self._advance_one_tool(input, next_state, bound, deps):
            yield event

    async def _advance_one_tool(self, input, state, bound, deps):
        if state.tool_count >= self._config.max_tools:
            raise CodingLoopFailure("tool_budget_exceeded", retryable=False)
        call = state.pending_tool_calls[state.pending_tool_index]
        try:
            validated = self._tools.validate(call.name, call.input)
        except ToolValidationError as error:
            denied = ToolResultContent(
                call.tool_call_id, "denied", {"reason_code": error.reason_code}
            )
            denied_state = self._after_result(state, denied)
            committed = await deps.repository.commit_model_checkpoint(
                lease=deps.lease,
                event_type="tool.denied",
                event_payload={"reason_code": error.reason_code},
                loop_state=self._dump_state(input, denied_state),
                workspace_revision=str(bound.binding.workspace_revision),
                now=self._clock(),
            )
            yield committed.event
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
        started = await deps.repository.begin_phase(
            lease=deps.lease, kind=CodingPhaseKind.IMPLEMENT, now=self._clock()
        )
        if started.event is not None:
            yield started.event
        if claim.disposition is ToolExecutionDisposition.COMPLETED:
            result = dict(claim.result or {})
            tool_event = await deps.events.append(
                task_id=input.task_id,
                event_type="tool.completed",
                payload={"result": result, "reused": True},
                run_id=input.run_id,
                tool_call_id=call.tool_call_id,
            )
        else:
            try:
                executed = await self._executor.execute(bound.session, validated)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                code = (
                    "tool_outcome_unknown"
                    if validated.risk is not ToolRisk.READ_ONLY
                    else "tool_execution_failed"
                )
                raise CodingLoopFailure(
                    code, retryable=validated.risk is ToolRisk.READ_ONLY
                ) from error
            result = dict(executed.to_mapping())
            try:
                tool_event = await deps.repository.complete_tool_execution(
                    claim, result=result, now=self._clock()
                )
            except Exception as error:
                raise CodingLoopFailure(
                    "tool_outcome_unknown", retryable=False
                ) from error
        yield tool_event
        status = str(result.get("status", "ok"))
        canonical_status = status if status in {"ok", "error", "denied"} else "ok"
        after = self._after_result(
            state,
            ToolResultContent(call.tool_call_id, canonical_status, result),
        )
        if after.consecutive_tool_errors > self._config.max_consecutive_tool_errors:
            raise CodingLoopFailure("tool_error_budget_exceeded", retryable=False)
        revision = str(
            result.get("workspace_revision", bound.binding.workspace_revision)
        )
        committed = await deps.repository.commit_phase_checkpoint(
            lease=deps.lease,
            phase=started.phase,
            tool_call_id=call.tool_call_id,
            result=result,
            loop_state=self._dump_state(input, after),
            workspace_revision=revision,
            now=self._clock(),
        )
        yield committed.event

    def _completed_turn(self, state, text_parts, calls, completion):
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
        usage = completion.usage
        cost = (
            state.cost_micros
            + (
                usage.input_tokens * self._config.input_cost_micros_per_million
                + usage.output_tokens * self._config.output_cost_micros_per_million
            )
            // 1_000_000
        )
        return AgentLoopState(
            transcript,
            state.turn_count + 1,
            state.tool_count,
            state.consecutive_tool_errors,
            tuple(calls),
            0,
            self._digest(transcript),
            state.input_tokens + usage.input_tokens,
            state.output_tokens + usage.output_tokens,
            cost,
        )

    def _after_result(self, state, result):
        transcript = state.transcript + (CanonicalMessage("tool", (result,)),)
        if state.pending_tool_index + 1 >= len(state.pending_tool_calls):
            transcript = self._compact(transcript)
        errors = 0 if result.status == "ok" else state.consecutive_tool_errors + 1
        return AgentLoopState(
            transcript,
            state.turn_count,
            state.tool_count + 1,
            errors,
            state.pending_tool_calls,
            state.pending_tool_index + 1,
            self._digest(transcript),
            state.input_tokens,
            state.output_tokens,
            state.cost_micros,
        )

    def _check_usage_budgets(self, state):
        if state.input_tokens + state.output_tokens > self._config.max_total_tokens:
            raise CodingLoopFailure("token_budget_exceeded", retryable=False)
        if state.cost_micros > self._config.max_cost_micros:
            raise CodingLoopFailure("cost_budget_exceeded", retryable=False)

    def _restore(self, input, checkpoint):
        if checkpoint is None:
            transcript = (CanonicalMessage("user", (TextContent(input.instruction),)),)
            return AgentLoopState(transcript, 0, 0, 0, (), 0, self._digest(transcript))
        raw = checkpoint.loop_state
        transcript = tuple(
            _message_from_mapping(item) for item in raw.get("transcript", [])
        )
        pending = tuple(
            ToolCallCompleted(item["tool_call_id"], item["name"], item["input"])
            for item in raw.get("pending_tool_calls", [])
        )
        return AgentLoopState(
            transcript,
            int(raw.get("turn_count", 0)),
            int(raw.get("tool_count", 0)),
            int(raw.get("consecutive_tool_errors", 0)),
            pending,
            int(raw.get("pending_tool_index", 0)),
            str(raw.get("transcript_digest", self._digest(transcript))),
            int(raw.get("input_tokens", 0)),
            int(raw.get("output_tokens", 0)),
            int(raw.get("cost_micros", 0)),
        )

    def _dump_state(self, input, state):
        return {
            "phase_index": state.tool_count - 1,
            "current_instruction": input.instruction,
            "pending_instruction": None,
            "transcript": [_message_to_mapping(item) for item in state.transcript],
            "turn_count": state.turn_count,
            "tool_count": state.tool_count,
            "consecutive_tool_errors": state.consecutive_tool_errors,
            "pending_tool_calls": [asdict(item) for item in state.pending_tool_calls],
            "pending_tool_index": state.pending_tool_index,
            "transcript_digest": state.transcript_digest,
            "input_tokens": state.input_tokens,
            "output_tokens": state.output_tokens,
            "cost_micros": state.cost_micros,
        }

    def _compact(self, transcript):
        if len(transcript) <= self._config.max_transcript_messages:
            return tuple(transcript)
        digest = self._digest(transcript)
        return (
            CanonicalMessage(
                "user",
                (TextContent(f"Prior transcript compacted; sha256={digest}"),),
            ),
        )

    @staticmethod
    def _digest(transcript):
        payload = json.dumps(
            [_message_to_mapping(item) for item in transcript],
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()


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

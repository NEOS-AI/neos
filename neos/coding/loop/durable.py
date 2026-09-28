"""The durable coding loop: one model turn or one tool call per delivery.

Each `run` restores state from the last checkpoint, advances exactly one step,
and commits a checkpoint before yielding the event that ends it. The concerns
live in `neos.coding.loop._durable`:

- `model_turn`   -- prepare, stream, and settle one model turn
- `tools`        -- the gate chain one pending tool call passes through
- `transitions`  -- how a turn or a tool result changes loop state
- `spawn` · `spawn_claims` · `spawn_results` -- parent-mediated subagents
- `compaction` · `artifact_refs` -- keeping the transcript inside budget
- `checkpoint` · `codec` -- restoring and dumping state
- `tool_catalog` -- which tools the model is offered

This module keeps assembly, approval, and the hook calls whose timeout tests
patch here. Import the loop's public names from this module, not from
`_durable`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from neos.coding.domain.approvals import (
    ApprovalGate,
    ApprovalMode,
    ApprovalPolicyOutcome,
    evaluate_approval,
)
from neos.coding.domain.events import CodingEvent
from neos.coding.domain.phases import CodingCheckpoint
from neos.coding.hooks import CodingHookPort, NullCodingHooks, post_tool_prevented
from neos.coding.loop.base import LoopDependencies, LoopInput
from neos.coding.model.base import CodingModel
from neos.coding.redact import redact_sensitive, strip_binary_payloads
from neos.coding.sandbox.bindings import SandboxBindingService
from neos.coding.sandbox.observability import CodingToolAuditEvent, NullCodingAuditSink
from neos.coding.tools.executor import SandboxToolExecutor
from neos.coding.tools.registry import CodingToolRegistry, ToolRisk
from neos.config.model_identity import usable_window_tokens
from neos.jev.gate import evaluate_approval_with_jev
from neos.coding.loop._durable.checkpoint import CheckpointMixin
from neos.coding.loop._durable.children import _select_spawn_work as _select_spawn_work
from neos.coding.loop._durable.compaction import CompactionMixin
from neos.coding.loop._durable.hook_decisions import (
    PreToolDecision,
    parse_pre_tool_decision,
)
from neos.coding.loop._durable.model_turn import (
    THINKING_PREVIEW_CHARS as THINKING_PREVIEW_CHARS,
    ModelTurnMixin,
    _request_fingerprint as _request_fingerprint,
)
from neos.coding.loop._durable.spawn import SubagentSpawnMixin
from neos.coding.loop._durable.spawn_claims import SpawnClaimsMixin
from neos.coding.loop._durable.state import (
    COMPACT_REF_THRESHOLD_BYTES as COMPACT_REF_THRESHOLD_BYTES,
    DEFAULT_MAX_TRANSCRIPT_TOKENS as DEFAULT_MAX_TRANSCRIPT_TOKENS,
    EMPTY_RETRY_LIMIT as EMPTY_RETRY_LIMIT,
    STALL_DENY_AFTER as STALL_DENY_AFTER,
    STOP_RETRY_LIMIT as STOP_RETRY_LIMIT,
    ActiveChildRef as ActiveChildRef,
    AgentLoopState as AgentLoopState,
    CodingLoopConfig as CodingLoopConfig,
    CodingLoopFailure as CodingLoopFailure,
    CodingLoopWaitingApproval as CodingLoopWaitingApproval,
    DelegatedSpawn as DelegatedSpawn,
    SpawnWork as SpawnWork,
)
from neos.coding.loop._durable.tool_catalog import ToolCatalogMixin
from neos.coding.loop._durable.tools import ToolExecutionMixin
from neos.coding.loop._durable.transcript import (
    _uniquify_tool_calls as _uniquify_tool_calls,
)
from neos.coding.loop._durable.transitions import TurnTransitionsMixin
from neos.coding.loop._durable.usage import check_usage_budgets, price_tokens
from neos.coding.loop._durable.worktree import (
    _session_on_workspace as _session_on_workspace,
)


# Read by `_pre_tool_decision` and `_execute_validated` on the core class.
# Keep both readers in this module: tests monkeypatch it on this module object.
PRE_TOOL_HOOK_TIMEOUT_SEC = 5.0


class DurableCodingLoop(
    ModelTurnMixin,
    ToolExecutionMixin,
    SubagentSpawnMixin,
    SpawnClaimsMixin,
    TurnTransitionsMixin,
    CompactionMixin,
    CheckpointMixin,
    ToolCatalogMixin,
):
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
        jev=None,
    ) -> None:
        # Mixins read these through `self` on every use, never a copy: tests
        # reassign `_config`, `_clock`, and `_metrics` after construction.
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
        # `None` 이 off 다. 루프는 설정을 읽지 않는다 -- 조립하는 쪽이 정한다.
        self._jev = jev

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

    async def _commit_model(
        self,
        input,
        bound,
        deps,
        state: AgentLoopState,
        payload: Mapping[str, Any],
        *,
        event_type: str = "model.completed",
    ):
        """Commit `state` as a model-step checkpoint. Every such commit goes here."""
        return await deps.repository.commit_model_checkpoint(
            lease=deps.lease,
            event_type=event_type,
            event_payload=payload,
            loop_state=self._dump_state(input, state),
            workspace_revision=str(bound.binding.workspace_revision),
            now=self._clock(),
        )

    # -- approval ----------------------------------------------------------

    def _approval_gate(
        self, state: AgentLoopState, *, unattended: bool = False
    ) -> ApprovalGate:
        """`unattended=True` 는 좁히기만 한다 -- 설정이 이미 unattended 면 그대로다.

        자식(CHILD-GATE)은 승인할 사람에게 닿을 수 없으므로 늘 이것으로 판정한다.
        """
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
            unattended=self._config.approval_unattended or unattended,
        )

    def _evaluate_static_call(
        self, validated, state: AgentLoopState, *, unattended: bool = False
    ) -> ApprovalPolicyOutcome:
        """주입된 평가기로 내는 판정. Jev 가 꺼져 있을 때의 유일한 경로다."""
        gate = self._approval_gate(state, unattended=unattended)
        try:
            return self._approval_evaluator(validated, gate)
        except TypeError:
            return self._approval_evaluator(validated)

    async def _evaluate_call(
        self,
        validated,
        state: AgentLoopState,
        deps=None,
        task_id: str | None = None,
        tool_call_id: str | None = None,
        *,
        unattended: bool = False,
    ) -> ApprovalPolicyOutcome:
        """정적 판정에 Jev 밴딩을 얹는다. 꺼져 있으면 정적 판정 그대로다.

        이벤트는 **부르는 쪽이 아니라 여기서** 단다. 판정이 만들어지는 자리와
        그 판정을 기록하는 자리가 갈라지면, 호출부 하나가 기록을 빠뜨려도
        아무것도 빨개지지 않는다 -- 이 저장소의 전례가 정확히 그것이다.

        `event_type=kind` 는 이 파일에 한 번만 있어야 한다:
        `tests/coding/test_event_kinds.py` 가 경로와 이름으로 이 자리를 짚는다.
        """
        if self._jev is None:
            return self._evaluate_static_call(validated, state, unattended=unattended)

        decision = await evaluate_approval_with_jev(
            validated,
            self._approval_gate(state, unattended=unattended),
            scorer=self._jev.scorer,
            thresholds=self._jev.thresholds,
            enforce=self._jev.enforce,
            static_evaluator=lambda call, _gate: self._evaluate_static_call(
                call, state, unattended=unattended
            ),
        )
        if decision.event is not None and deps is not None and task_id is not None:
            payload = dict(decision.event)
            kind = payload.pop("kind")
            await deps.events.append(
                task_id=task_id,
                event_type=kind,
                payload={
                    **payload,
                    "tool": validated.name,
                    "tool_call_id": tool_call_id,
                },
                tool_call_id=tool_call_id,
            )
        return decision.outcome

    def _jev_blocks_speculation(self) -> bool:
        return self._jev is not None and self._jev.enforce

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

    # -- hooks around execution --------------------------------------------

    async def _pre_tool_decision(self, validated) -> PreToolDecision:
        try:
            raw = await asyncio.wait_for(
                self._hooks.pre_tool(validated),
                timeout=PRE_TOOL_HOOK_TIMEOUT_SEC,
            )
        except TimeoutError:
            return "deny", "hook_timeout", None
        except Exception:
            return "deny", "hook_error", None
        return parse_pre_tool_decision(raw)

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
            # A read-only failure is a failure; anything else may have
            # changed the workspace before it failed.
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

    # -- budgets and windows -----------------------------------------------

    def _price_tokens(
        self,
        input_tokens: int,
        output_tokens: int,
        *,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> int:
        return price_tokens(
            self._config,
            input_tokens,
            output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
        )

    def _check_usage_budgets(self, state):
        check_usage_budgets(self._config, state)

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

    def _utc_stamp(self) -> str:
        return self._clock().astimezone(UTC).isoformat()

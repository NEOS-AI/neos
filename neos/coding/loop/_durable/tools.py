"""Tool-call advancement for the durable coding loop (one tool per delivery).

A pending call passes a chain of gates before it runs, and any gate may end
the step with its own checkpoint:

    stall -> [read-only batch] -> phase/skill/schema -> pre-tool hook
          -> approval -> claim -> execute -> settle

A gate returns `_Halt` to end the step, or the value the next gate needs.
Events yielded from a halt are produced after all of its side effects, so
collecting them first changes nothing a consumer sees. `tool.started` is the
exception, and it is yielded from the body before the call runs.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any

from neos.coding.domain.approvals import (
    ApprovalPolicyOutcome,
    ApprovalStatus,
    approval_remember_key,
    denial_envelope,
    policy_denial_reason,
)
from neos.coding.bridge.catalog import is_device_command_tool, is_device_tool
from neos.coding.domain.durability import ToolExecutionDisposition
from neos.coding.model.base import (
    ToolCallCompleted,
    ToolResultContent,
)
from neos.coding.phases import (
    durable_phase_kind,
    tool_allowed_in_phase,
    write_risk_blocked,
)
from neos.coding.sandbox.observability import CodingToolAuditEvent
from neos.coding.tools.executor import ToolResult
from neos.coding.tools.orchestrator import partition_leading_readonly, speculation_safe
from neos.coding.tools.registry import (
    _CONTROL_PLANE_TOOLS,
    ToolRisk,
    ToolValidationError,
    ValidatedToolCall,
)
from neos.coding.loop._durable.children import (
    _child_ref,
    _drain_completed_prefix,
    _is_pending_head,
    _parked_child_ref,
    _select_spawn_work,
    _subagent_max_active,
    _upsert_active_child,
    _without_child,
)
from neos.coding.loop._durable.signatures import _is_stall_denied
from neos.coding.loop._durable.state import (
    CodingLoopFailure,
    CodingLoopWaitingApproval,
    CodingLoopWaitingUser,
    DelegatedSpawn,
)
from neos.coding.loop._durable.tool_results import (
    _outcome_status,
    _tool_event_payload,
    _transcript_status,
)
from neos.coding.loop._durable.transcript import _tool_result_ids, _tool_use_names

logger = logging.getLogger("neos.coding.loop.durable")

_UNKNOWN = "tool_outcome_unknown"
_REMEMBERED_RISKS = frozenset({ToolRisk.WORKSPACE_WRITE, ToolRisk.COMMAND})
_APPROVAL_DENIALS = {
    ApprovalStatus.DENIED: "approval_denied",
    ApprovalStatus.EXPIRED: "approval_expired",
    ApprovalStatus.INVALIDATED: "approval_invalidated",
}
#: 트랙 Q9 -- 닫힌 질문을 다시 만난 루프의 거절 사유(설계 §5 의 2).
_ASK_DENIALS = {
    "expired": "ask_expired",
    "cancelled": "ask_cancelled",
}
_MAX_HOOK_RETRIES = 2
_MAX_BATCH = 10


@dataclass(frozen=True, slots=True)
class _Halt:
    """A gate ended the step. `items` are its `(event, state)` pairs."""

    items: tuple[tuple[Any, Any], ...]


#: Control-plane tools run on the loop, not in the sandbox.
#: (loop, call, bound, state, input, deps) -> awaitable (result, state).
_CONTROL_PLANE_DISPATCH = {
    "spawn_agent.v1": lambda loop, call, bound, state, input, deps: (
        loop._run_spawn_agent(call, bound, state, input=input, deps=deps)
    ),
    "subagent_list.v1": lambda loop, call, bound, state, input, deps: (
        loop._run_subagent_list(bound, state, input=input)
    ),
    "await_subagent.v1": lambda loop, call, bound, state, input, deps: (
        loop._run_await_subagent(call, bound, state, input=input, deps=deps)
    ),
    "subagent_steer.v1": lambda loop, call, bound, state, input, deps: (
        loop._run_subagent_steer(call, bound, state, input=input)
    ),
}


def _with_payload_preview(tool_event, call):
    return replace(tool_event, payload=_tool_event_payload(call, **dict(tool_event.payload)))


class ToolExecutionMixin:
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
        call, spawn_selected = self._next_tool_call(state)
        if _is_stall_denied(state, call.name, call.input):
            yield await self._commit_denied_tool(
                input, state, bound, deps, call, "policy_stall_denied"
            )
            return
        if not spawn_selected:
            batch = await self._cleared_readonly_batch(input, state, deps)
            if batch is not None:
                async for item in self._advance_readonly_batch(
                    input, state, bound, deps, batch, prefetch=prefetch
                ):
                    yield item
                return
        admitted = await self._admit_tool_call(input, state, bound, deps, call)
        if isinstance(admitted, _Halt):
            for item in admitted.items:
                yield item
            return
        validated, state = admitted
        async for item in self._run_admitted_call(
            input, state, bound, deps, call, validated, prefetch
        ):
            yield item

    def _next_tool_call(self, state) -> tuple[ToolCallCompleted, bool]:
        """The call this step serves, and whether spawn scheduling chose it."""
        head = state.pending_tool_calls[state.pending_tool_index]
        if head.name in _CONTROL_PLANE_TOOLS:
            return head, False
        work = _select_spawn_work(state, max_active=_subagent_max_active(self._config))
        if work is not None and work.call is not None:
            return work.call, True
        # resume with a missing pending id (mutation / corruption) uses
        # pending[index] so the existing cap guard still fails closed
        return head, False

    # -- gates -----------------------------------------------------------------

    async def _admit_tool_call(self, input, state, bound, deps, call):
        """Policy, hook, and approval gates. `_Halt`, or `(validated, state)`."""
        reason, validated = self._static_denial(call, state)
        if reason is not None:
            return _Halt(
                (await self._commit_denied_tool(input, state, bound, deps, call, reason),)
            )
        await self._audit_tool(bound, call.name, operation="validate", outcome="allowed")
        hooked = await self._pre_tool_gate(input, state, bound, deps, call, validated)
        if isinstance(hooked, _Halt):
            return hooked
        return await self._approval_gate_step(input, state, bound, deps, call, hooked)

    def _static_denial(self, call, state) -> tuple[str | None, ValidatedToolCall | None]:
        if not tool_allowed_in_phase(call.name, state.phase):
            return "policy_phase_denied", None
        if not self._catalog.allowed_by_skills(call.name, state):
            return "policy_skill_denied", None
        try:
            validated = self._tools.validate(call.name, call.input)
        except ToolValidationError as error:
            return error.reason_code, None
        if write_risk_blocked(validated.risk, state.phase):
            return "policy_phase_denied", None
        return None, validated

    async def _pre_tool_gate(self, input, state, bound, deps, call, validated):
        decision, reason, updated_input = await self._pre_tool_decision(validated)
        if decision == "allow" and updated_input is not None:
            try:
                validated = self._tools.validate(validated.name, dict(updated_input))
            except ToolValidationError:
                decision, reason = "deny", "hook_updated_input_invalid"
        if decision == "deny" or (
            decision == "retry" and state.hook_retry_count >= _MAX_HOOK_RETRIES
        ):
            return _Halt(
                (
                    await self._commit_denied_tool(
                        input, state, bound, deps, call, "policy_hook_denied"
                    ),
                )
            )
        if decision == "prevent":
            return _Halt(
                (
                    await self._commit_denied_tool(
                        input, state, bound, deps, call, "hook_prevented", terminal=True
                    ),
                )
            )
        if decision == "retry":
            retry_state = self._with_hook_retry(state, validated, reason)
            committed = await self._commit_model(
                input, bound, deps, retry_state, {"reason_code": "hook_retry"}
            )
            return _Halt(((committed.event, retry_state),))
        return validated

    async def _approval_gate_step(self, input, state, bound, deps, call, validated):
        if self._answerable_ask(input, validated):
            return await self._ask_gate_step(input, state, bound, deps, call, validated)
        outcome = await self._evaluate_call(
            validated,
            state,
            deps,
            input.task_id,
            call.tool_call_id,
            unattended=_unattended(input),
            read_only_ceiling=_background(input),
        )
        if outcome is ApprovalPolicyOutcome.DENY:
            return _Halt(
                (
                    await self._commit_denied_tool(
                        input,
                        state,
                        bound,
                        deps,
                        call,
                        policy_denial_reason(
                            validated,
                            self._approval_gate(
                                state,
                                unattended=_unattended(input),
                                read_only_ceiling=_background(input),
                            ),
                        ),
                    ),
                )
            )
        if outcome is not ApprovalPolicyOutcome.REQUIRE_APPROVAL:
            return validated, state
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
            return _Halt(tuple((event, state) for event in committed.events))
        if approval.status is ApprovalStatus.PENDING:
            raise CodingLoopWaitingApproval(approval.approval_id)
        if approval.status is not ApprovalStatus.APPROVED:
            return _Halt(
                (
                    await self._commit_denied_tool(
                        input,
                        state,
                        bound,
                        deps,
                        call,
                        _APPROVAL_DENIALS[approval.status],
                        audit=False,
                    ),
                )
            )
        validated = self._with_answers(validated, approval.display_summary.get("answers"))
        if (
            bool(approval.display_summary.get("remember"))
            and validated.risk in _REMEMBERED_RISKS
        ):
            state = replace(
                state,
                approved_always=state.approved_always
                | {approval_remember_key(validated)},
            )
        return validated, state

    # -- ask and wait (track Q9) ------------------------------------------------

    def _answerable_ask(self, input, validated) -> bool:
        """에이전트 autonomous 태스크의 `ask_user.v1` -- 답할 사람이 채널에 있다(Q9).

        interactive 는 승인 카드 그대로다(결정 Q9-2). background 는 이 갈래로 오지 않고
        천장(`policy_mode_ceiling`)이 거절한다(결정 Q9-1). 사람이 연 autonomous 태스크
        (`agent_id` 없음)는 답할 채널이 없으므로 지금처럼 무인 DENY 다.
        """
        return (
            validated.name == "ask_user.v1"
            and getattr(input, "mode", "interactive") == "autonomous"
            and getattr(input, "agent_id", None) is not None
            and getattr(self, "_asks", None) is not None
            and self._asks.enabled()
        )

    async def _ask_gate_step(self, input, state, bound, deps, call, validated):
        """질문 갈래(설계 §5). 승인 갈래와 같은 뼈대 -- 판정이 먼저, 기록 조회가 나중이다.

        무인 접기(`fold_for_unattended`)를 **부르지 않는** 길이다: `unattended=False` 로
        판정하므로 사용자 block · deny 목록 · Jev 밴딩은 그대로 걸리고, 접기만 빠진다.
        운영자의 전역 `approval_unattended` 는 `_approval_gate` 가 계속 OR 한다 -- 운영자가
        좁힌 것을 Q9 가 넓히지 않는다. ALLOW 도 질문으로 보낸다: 답 없는 `ask_user` 실행은
        빈 답이다.
        """
        outcome = await self._evaluate_call(
            validated,
            state,
            deps,
            input.task_id,
            call.tool_call_id,
            unattended=False,
            read_only_ceiling=_background(input),
        )
        if outcome is ApprovalPolicyOutcome.DENY:
            return _Halt(
                (
                    await self._commit_denied_tool(
                        input,
                        state,
                        bound,
                        deps,
                        call,
                        policy_denial_reason(
                            validated,
                            self._approval_gate(
                                state,
                                unattended=False,
                                read_only_ceiling=_background(input),
                            ),
                        ),
                    ),
                )
            )
        asks = self._asks
        existing = await asks.for_call(input.task_id, input.run_id, call.tool_call_id)
        if existing is not None:
            if existing.status == "answered":
                return self._with_answers(validated, list(existing.answers or ())), state
            if existing.status == "waiting":
                raise CodingLoopWaitingUser(existing.ask_id)
            return _Halt(
                (
                    await self._commit_denied_tool(
                        input,
                        state,
                        bound,
                        deps,
                        call,
                        _ASK_DENIALS.get(existing.status, "ask_expired"),
                        audit=False,
                    ),
                )
            )
        destination = await asks.reply_destination(
            input.agent_id, getattr(input, "owner_id", None)
        )
        from neos.standing.asks import count_ask, new_ask_id

        if destination is None:
            count_ask("refused_no_channel")
            return _Halt(
                (
                    await self._commit_denied_tool(
                        input, state, bound, deps, call, "no_reply_channel"
                    ),
                )
            )

        ask_id = new_ask_id()
        # 알림은 질문 커밋과 같은 트랜잭션에서 적힌다(Q9b) -- 워커는 게이트웨이를 부르지 않는다.
        notice, notice_target = asks.notice_for(
            ask_id,
            input.agent_id,
            list(validated.input.get("questions") or ()),
            destination,
        )
        now = self._clock()
        committed = await deps.repository.request_user_answer(
            lease=deps.lease,
            tool_call=call,
            validated=validated,
            loop_state=self._dump_state(input, state),
            workspace_revision=str(bound.binding.workspace_revision),
            agent_id=input.agent_id,
            reply_session_id=destination.session_id,
            reply_channel_type=destination.channel_type,
            asked_at=now,
            expires_at=now + timedelta(hours=asks.expire_hours),
            ask_id=ask_id,
            notice=notice,
            notice_target=notice_target,
        )
        if committed is None:
            # 이 에이전트에 이미 대기 질문이 있다(095 의 부분 unique 인덱스). 이 태스크는
            # 멈추지 않는다 -- 거절을 받고 다음 단계를 계속 돈다(Review Focus 3).
            count_ask("refused_pending")
            return _Halt(
                (
                    await self._commit_denied_tool(
                        input, state, bound, deps, call, "ask_pending"
                    ),
                )
            )
        count_ask("asked")
        return _Halt(tuple((event, state) for event in committed.events))

    # -- claim, execute, settle ----------------------------------------------

    async def _claim_call(self, deps, call):
        claim_ttl = self._config.tool_claim_ttl_sec
        if call.name == "spawn_agent.v1" and self._config.subagent_enabled:
            claim_ttl = self._config.timeout_sec + 30
        bridge = getattr(self, "_device_bridge", None)
        if bridge is not None and is_device_command_tool(call.name):
            # 트랙 Q16c: 기기 명령은 자기 시간 제한까지 돈다 -- claim 이 그보다 먼저 끝나 다른
            # 시도가 결과를 `tool_outcome_unknown` 으로 덮지 않게 그만큼 쥔다(다시 돌지는 않는다).
            claim_ttl = max(claim_ttl, float(getattr(bridge, "command_claim_seconds", 0) or 0))
        claim = await deps.repository.claim_tool_execution(
            lease=deps.lease,
            tool_call_id=call.tool_call_id,
            now=self._clock(),
            claim_expires_at=self._clock() + timedelta(seconds=claim_ttl),
        )
        if claim.disposition is ToolExecutionDisposition.BUSY:
            raise CodingLoopFailure("tool_execution_busy", retryable=True)
        return claim

    async def _run_admitted_call(
        self, input, state, bound, deps, call, validated, prefetch
    ):
        claim = await self._claim_call(deps, call)
        if (
            claim.disposition is ToolExecutionDisposition.RECLAIMED
            and validated.risk is not ToolRisk.READ_ONLY
            and call.name != "spawn_agent.v1"
        ):
            # A lost execution that may have mutated the workspace: never
            # run it twice.
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
        if claim.disposition is ToolExecutionDisposition.COMPLETED:
            result, tool_event = await self._reuse_completed(input, bound, deps, call, claim)
        else:
            resume_spawn = (
                call.name == "spawn_agent.v1"
                and self._config.subagent_enabled
                and claim.disposition
                in {ToolExecutionDisposition.DELEGATED, ToolExecutionDisposition.RECLAIMED}
            )
            if not resume_spawn:
                yield await self._emit_tool_started(input, deps, call), state
            try:
                result, state = await self._dispatch_call(
                    input, state, bound, deps, call, validated, prefetch
                )
            except asyncio.CancelledError:
                await self._cancel_active_child(
                    state, reason="aborted", task_id=input.task_id
                )
                await self._fail_delegated_claim(deps, claim, bound)
                raise
            except CodingLoopFailure as error:
                if error.code != _UNKNOWN:
                    raise
                async for item in self._emit_unknown_tool_result(
                    input, state, bound, deps, call, claim=claim, started=started
                ):
                    yield item
                return
            ran_spawn = call.name == "spawn_agent.v1"
            if isinstance(result, DelegatedSpawn):
                yield await self._park_delegated_spawn(
                    input, state, bound, deps, call, claim, started, result
                )
                return
            finished = await self._record_execution(
                input, state, bound, deps, call, validated, claim, started, result
            )
            if isinstance(finished, _Halt):
                for item in finished.items:
                    yield item
                return
            tool_event = finished
        self._record_tool_metric(call.name, result)
        yield tool_event, state
        async for item in self._settle_call(
            input, state, bound, deps, call, claim, started, result, ran_spawn
        ):
            yield item

    async def _reuse_completed(self, input, bound, deps, call, claim):
        """A claim already finished by an earlier step: replay, don't run."""
        result = dict(claim.result or {})
        await self._audit_tool(bound, call.name, operation="execute", outcome="reused")
        tool_event = await deps.events.append(
            task_id=input.task_id,
            event_type="tool.completed",
            payload=_tool_event_payload(call, result=result, reused=True),
            run_id=input.run_id,
            tool_call_id=call.tool_call_id,
        )
        return result, tool_event

    async def _dispatch_call(self, input, state, bound, deps, call, validated, prefetch):
        handler = _CONTROL_PLANE_DISPATCH.get(call.name)
        if handler is None:
            result = await self._execute_validated(
                bound,
                deps,
                validated,
                known_reads=state.read_paths,
                known_stamps=state.read_stamps,
                prefetched=prefetch.get(call.tool_call_id),
                owner_id=getattr(input, "owner_id", None),
                task_id=getattr(input, "task_id", None),
                unattended=self._config.approval_unattended or _unattended(input),
            )
            return result, state
        if call.name == "spawn_agent.v1":
            await self._adopt_all_live_claims(
                state, deps, selected_tool_call_id=call.tool_call_id
            )
        return await handler(self, call, bound, state, input, deps)

    async def _park_delegated_spawn(
        self, input, state, bound, deps, call, claim, started, parked_step: DelegatedSpawn
    ):
        """The child is still running: keep the claim open and remember it."""
        if claim.disposition in {
            ToolExecutionDisposition.CLAIMED,
            ToolExecutionDisposition.RECLAIMED,
        }:
            await self._mark_spawn_delegated(deps, claim, parked_step)
        ref_call_id = parked_step.tool_call_id or call.tool_call_id
        existing = _child_ref(state, ref_call_id)
        charged, rolled_in, rolled_out = self._roll_in_child_usage(
            state, existing, parked_step.input_tokens, parked_step.output_tokens
        )
        parked = _upsert_active_child(
            charged,
            _parked_child_ref(
                existing,
                parked_step,
                tool_call_id=ref_call_id,
                stamp=self._utc_stamp(),
                rolled_in=rolled_in,
                rolled_out=rolled_out,
            ),
        )
        payload = {
            "child_run_id": parked_step.run_id,
            "child_checkpoint_id": parked_step.checkpoint_id,
            "step_kind": parked_step.step_kind,
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
        await self._enforce_usage_budgets_after_child_spend(
            parked,
            deps,
            bound,
            input,
            except_tool_call_id=call.tool_call_id,
        )
        return committed.event, parked

    async def _record_execution(
        self, input, state, bound, deps, call, validated, claim, started, result
    ):
        """Record the mutation and complete the claim. `_Halt`, or the event."""
        if validated.risk is not ToolRisk.READ_ONLY:
            try:
                await self._bindings.record_mutation(
                    deps.lease,
                    workspace_revision=await bound.session.workspace_revision(),
                )
            except Exception:
                return await self._halt_unknown(
                    input, state, bound, deps, call, claim, started, validated.name
                )
        if isinstance(result, dict) and result.pop("_post_tool_prevent", False):
            envelope = dict(denial_envelope(call, "hook_prevented"))
            envelope["denied_by"] = "hook"
            try:
                await deps.repository.complete_tool_execution(
                    claim, result=envelope, now=self._clock()
                )
            except Exception:
                pass
            return _Halt(
                (
                    await self._commit_denied_tool(
                        input, state, bound, deps, call, "hook_prevented", terminal=True
                    ),
                )
            )
        try:
            tool_event = await deps.repository.complete_tool_execution(
                claim, result=result, now=self._clock()
            )
        except Exception:
            return await self._halt_unknown(
                input, state, bound, deps, call, claim, started, call.name
            )
        await self._audit_execute_result(bound, call.name, result)
        return _with_payload_preview(tool_event, call)

    async def _halt_unknown(
        self, input, state, bound, deps, call, claim, started, audited_name
    ) -> _Halt:
        await self._audit_tool(
            bound, audited_name, operation="execute", outcome="error", error_code=_UNKNOWN
        )
        return _Halt(
            tuple(
                [
                    item
                    async for item in self._emit_unknown_tool_result(
                        input, state, bound, deps, call, claim=claim, started=started
                    )
                ]
            )
        )

    async def _settle_call(
        self, input, state, bound, deps, call, claim, started, result, ran_spawn
    ):
        after, child_fold = await self._state_after_call(
            state, call, claim, result, ran_spawn
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
        if child_fold:
            await self._enforce_usage_budgets_after_child_spend(
                after, deps, bound, input
            )
        yield committed.event, after
        if after.consecutive_tool_errors >= self._config.max_consecutive_tool_errors:
            raise CodingLoopFailure("tool_error_budget_exceeded", retryable=False)

    async def _state_after_call(self, state, call, claim, result, ran_spawn):
        """Fold a finished call's result into state. Returns (state, child_fold)."""
        reused = claim.disposition is ToolExecutionDisposition.COMPLETED
        is_spawn = call.name == "spawn_agent.v1"
        dropped_fold = is_spawn and str(result.get("exit_reason") or "") == "dropped"
        child_fold = is_spawn and "child_status" in result
        if (
            child_fold
            and not dropped_fold
            and (not reused or _child_ref(state, call.tool_call_id) is not None)
        ):
            state = self._apply_child_fold_usage(state, result, call.tool_call_id)
        advance_index = _is_pending_head(state, call.tool_call_id)
        if call.tool_call_id in _tool_result_ids(state.transcript):
            # Already answered (a detached spawn, or a replay): just move on.
            after = _drain_completed_prefix(state)
        elif dropped_fold and call.tool_call_id not in _tool_use_names(state.transcript):
            # The call itself was compacted away; there is nothing to answer.
            after = state
            if advance_index:
                after = replace(after, pending_tool_index=after.pending_tool_index + 1)
        else:
            content = (
                {"exit_reason": "dropped"} if dropped_fold else result
            )
            status = "error" if dropped_fold else _transcript_status(result)
            after = await self._after_result(
                state,
                ToolResultContent(call.tool_call_id, status, content),
                tool_name=call.name,
                tool_input=call.input,
                advance_index=advance_index,
            )
        if ran_spawn and not self._config.subagent_enabled:
            after = self._with_spawn_handoff(after, call, result)
        ref = _child_ref(after, call.tool_call_id)
        # A parked child's tool result *is* its fold, so writing one means the
        # child is done and the ref goes. A detached child (K3) already had its
        # result written at spawn time -- dropping it here would strand a run
        # nobody advances and lose the report.
        if ran_spawn or child_fold or ref is not None:
            if ref is None or not ref.detached:
                after = _without_child(after, call.tool_call_id)
            after = _drain_completed_prefix(after)
            self._record_spawn_live_children(after, call)
        return after, child_fold

    # -- read-only batches -----------------------------------------------------

    async def _cleared_readonly_batch(self, input, state, deps):
        """A leading read-only batch every hook and the gate let through, or None."""
        batch = self._leading_readonly_batch(state)
        if batch is None or self._jev_blocks_speculation():
            # 차단 중인 게이트를 배치가 앞지르지 않는다. 본 판정이 대신 본다.
            return None
        for call, validated in batch:
            decision, _reason, updated = await self._pre_tool_decision(validated)
            if decision in {"deny", "retry", "prevent"} or updated:
                return None
            outcome = await self._evaluate_call(
                validated,
                state,
                deps,
                input.task_id,
                call.tool_call_id,
                unattended=_unattended(input),
                read_only_ceiling=_background(input),
            )
            if outcome is not ApprovalPolicyOutcome.ALLOW:
                return None
        return batch

    def _leading_readonly_batch(self, state):
        remaining = state.pending_tool_calls[state.pending_tool_index :]
        remaining_budget = self._config.max_tools - state.tool_count
        if len(remaining) < 2 or remaining_budget < 2:
            return None
        pairs: list[tuple[ToolCallCompleted, ValidatedToolCall]] = []
        for call in remaining:
            if call.name in {"spawn_agent.v1", "set_phase.v1"} | _CONTROL_PLANE_TOOLS:
                break
            if is_device_tool(call.name):
                # 트랙 Q16a: 기기 호출은 투기적으로 돌지 않는다 -- 본 경로가 소유자·무인
                # 여부를 싣고 한 번에 하나씩 부른다.
                break
            if not tool_allowed_in_phase(call.name, state.phase):
                break
            if not self._catalog.allowed_by_skills(call.name, state):
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
            max_batch=min(_MAX_BATCH, remaining_budget),
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
            await self._audit_tool(
                bound, call.name, operation="validate", outcome="allowed"
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
                await self._audit_tool(
                    bound, call.name, operation="execute", outcome="reused"
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
            *(run_one(call, validated, claim) for call, validated, claim in claims)
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
                    await self._audit_tool(
                        bound,
                        call.name,
                        operation="execute",
                        outcome="error",
                        error_code=_UNKNOWN,
                    )
                    raise CodingLoopFailure(_UNKNOWN, retryable=False) from error
                tool_event = _with_payload_preview(tool_event, call)
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
            current = await self._after_result(
                current,
                ToolResultContent(call.tool_call_id, _transcript_status(result), result),
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

    # -- events, audit, metrics ------------------------------------------------

    async def _emit_tool_started(self, input, deps, call):
        return await deps.events.append(
            task_id=input.task_id,
            event_type="tool.started",
            payload=_tool_event_payload(call),
            run_id=input.run_id,
            tool_call_id=call.tool_call_id,
        )

    async def _emit_unknown_tool_result(
        self, input, state, bound, deps, call, *, claim=None, started=None
    ):
        result = self._spawn_tool_error(bound, _UNKNOWN)
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
                payload=_tool_event_payload(call, result=result, reason_code=_UNKNOWN),
                run_id=input.run_id,
                tool_call_id=call.tool_call_id,
            )
        else:
            tool_event = _with_payload_preview(tool_event, call)
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
            committed = await self._commit_model(
                input,
                bound,
                deps,
                after,
                {"reason_code": _UNKNOWN},
                event_type="tool.completed",
            )
        yield tool_event, state
        yield committed.event, after

    async def _audit_tool(
        self, bound, tool: str, *, operation: str, outcome: str, error_code=None
    ) -> None:
        await self._audit.emit(
            CodingToolAuditEvent.from_result(
                provider=bound.binding.provider,
                tool=tool,
                operation=operation,
                outcome=outcome,
                error_code=error_code,
            )
        )

    async def _audit_execute_result(self, bound, tool_name, result) -> None:
        raw_status = str(result.get("status", "ok"))
        await self._audit_tool(
            bound,
            tool_name,
            operation="execute",
            outcome=_outcome_status(result),
            error_code=str(result.get("reason_code")) if raw_status != "ok" else None,
        )

    async def _commit_denied_tool(
        self,
        input,
        state,
        bound,
        deps,
        call,
        reason_code,
        *,
        terminal: bool = False,
        audit: bool = True,
    ):
        """Answer `call` with a denial and end the step.

        `audit=False` is for denials the policy did not make (an approval a
        human denied or let expire): those are not validation outcomes.
        """
        if audit:
            await self._audit_tool(
                bound,
                call.name,
                operation="validate",
                outcome="denied",
                error_code=reason_code,
            )
        envelope = dict(denial_envelope(call, reason_code))
        if reason_code == "hook_prevented":
            envelope["denied_by"] = "hook"
        denied_state = await self._after_result(
            state,
            ToolResultContent(call.tool_call_id, "denied", envelope),
            tool_name=call.name,
            tool_input=call.input,
            advance_index=_is_pending_head(state, call.tool_call_id),
        )
        denied_state = _drain_completed_prefix(denied_state)
        if terminal:
            denied_state = replace(denied_state, terminal_pending=True)
        committed = await self._commit_model(
            input,
            bound,
            deps,
            denied_state,
            _tool_event_payload(call, reason_code=reason_code),
            event_type="tool.denied",
        )
        return committed.event, denied_state

    def _record_tool_metric(self, tool_name, result) -> None:
        if self._metrics is None:
            return
        self._metrics.coding_tool_execution_total.labels(
            tool=tool_name, outcome=_outcome_status(result)
        ).inc()

    # -- speculative prefetch --------------------------------------------------

    def _maybe_prefetch_readonly(self, call: ToolCallCompleted, bound, state):
        if call.name == "spawn_agent.v1":
            return None
        if is_device_tool(call.name):
            # 트랙 Q16a: 사람의 기기를 게이트 판정 전에 미리 읽지 않는다.
            return None
        if _is_stall_denied(state, call.name, call.input):
            return None
        if not tool_allowed_in_phase(call.name, state.phase):
            return None
        if not self._catalog.allowed_by_skills(call.name, state):
            return None
        try:
            validated = self._tools.validate(call.name, call.input)
        except ToolValidationError:
            return None
        if not speculation_safe(validated):
            return None
        if self._jev_blocks_speculation():
            # 차단 중인 게이트를 앞지르지 않는다. 본 판정 경로가 대신 본다.
            return None
        if self._evaluate_static_call(validated, state) is not ApprovalPolicyOutcome.ALLOW:
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


def _unattended(input) -> bool:
    """Nobody is watching this task (K9): an approval request would wait forever.

    The gate step is where this matters: REQUIRE_APPROVAL folds to DENY
    instead of parking. The speculative read-only batch passes it too, but
    there it cannot change anything -- the fold only turns REQUIRE_APPROVAL
    into DENY, and the batch already declines both (it prefetches on ALLOW
    only). It is passed so the two sites judge with the same gate, not
    because a test could tell the difference; a mutation removing it there
    survives, and that is why.
    """
    return getattr(input, "mode", "interactive") in {"autonomous", "background"}


def _background(input) -> bool:
    """트랙 Q1: 아무도 시키지 않은 일 -- 천장이 READ_ONLY 다."""
    return getattr(input, "mode", "interactive") == "background"

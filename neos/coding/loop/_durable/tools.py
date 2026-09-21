"""Tool-call advancement for the durable coding loop (one tool per delivery)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import timedelta
from typing import Any

from neos.coding.domain.approvals import (
    ApprovalPolicyOutcome,
    ApprovalStatus,
    approval_remember_key,
    denial_envelope,
)
from neos.coding.model.base import (
    ToolCallCompleted,
    ToolResultContent,
)
from neos.coding.phases import (
    durable_phase_kind,
    tool_allowed_in_phase,
    write_risk_blocked,
)
from neos.coding.sandbox.observability import (
    CodingToolAuditEvent,
)
from neos.coding.tools.executor import ToolResult
from neos.coding.tools.orchestrator import partition_leading_readonly
from neos.coding.tools.registry import (
    _CONTROL_PLANE_TOOLS,
    ToolRisk,
    ToolValidationError,
    ValidatedToolCall,
)
from neos.coding.domain.durability import ToolExecutionDisposition
from neos.coding.loop._durable.state import (
    ActiveChildRef,
    CodingLoopFailure,
    CodingLoopWaitingApproval,
    DelegatedSpawn,
)
from neos.coding.loop._durable.support import (
    _is_stall_denied,
    _select_spawn_work,
    _subagent_max_active,
    _tool_event_payload,
    _tool_result_ids,
    _tool_use_names,
)

logger = logging.getLogger("neos.coding.loop.durable")


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
        max_active = _subagent_max_active(self._config)
        head = state.pending_tool_calls[state.pending_tool_index]
        if head.name in _CONTROL_PLANE_TOOLS:
            work = None
            call = head
        else:
            work = _select_spawn_work(state, max_active=max_active)
            if work is not None and work.call is not None:
                call = work.call
            else:
                # resume with a missing pending id (mutation / corruption) uses
                # pending[index] so the existing cap guard still fails closed
                call = head
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
        if not self._tool_allowed_by_skills(call.name, state):
            event, denied_state = await self._commit_denied_tool(
                input, state, bound, deps, call, "policy_skill_denied"
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
            if bool(approval.display_summary.get("remember")) and validated.risk in {
                ToolRisk.WORKSPACE_WRITE,
                ToolRisk.COMMAND,
            }:
                state = replace(
                    state,
                    approved_always=state.approved_always
                    | {approval_remember_key(validated)},
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
            and call.name != "spawn_agent.v1"
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
                elif call.name == "subagent_list.v1":
                    result = await self._run_subagent_list(
                        bound, state, input=input
                    )
                elif call.name == "await_subagent.v1":
                    result = await self._run_await_subagent(
                        call, bound, state, input=input, deps=deps
                    )
                    if isinstance(result, dict):
                        updated = result.pop("_loop_state", None)
                        if updated is not None:
                            state = updated
                elif call.name == "subagent_steer.v1":
                    result = await self._run_subagent_steer(
                        call, bound, state, input=input
                    )
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
                ref_call_id = result.tool_call_id or call.tool_call_id
                existing = self._child_ref(state, ref_call_id)
                in_delta, out_delta, rolled_in, rolled_out = self._unrolled_child_usage(
                    existing, result.input_tokens, result.output_tokens
                )
                parked = self._upsert_active_child(
                    self._apply_child_usage_delta(state, in_delta, out_delta),
                    ActiveChildRef(
                        run_id=result.run_id,
                        checkpoint_id=result.checkpoint_id,
                        tool_call_id=ref_call_id,
                        last_advanced_at=self._utc_stamp(),
                        rolled_input_tokens=rolled_in,
                        rolled_output_tokens=rolled_out,
                        pending_steer=existing.pending_steer if existing else "",
                        spec=result.spec or (existing.spec if existing else "explore"),
                        spawn_depth=(
                            result.spawn_depth
                            if result.spawn_depth
                            else (existing.spawn_depth if existing else 0)
                        ),
                        worktree_repo=result.worktree_repo
                        or (existing.worktree_repo if existing else ""),
                        worktree_path=result.worktree_path
                        or (existing.worktree_path if existing else ""),
                        worktree_branch=result.worktree_branch
                        or (existing.worktree_branch if existing else ""),
                        worktree_base_sha=result.worktree_base_sha
                        or (existing.worktree_base_sha if existing else ""),
                        # park 이 자식의 배달 방식을 바꾸지는 않는다.
                        delivery=existing.delivery if existing else "tool_result",
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
                await self._enforce_usage_budgets_after_child_spend(
                    parked,
                    deps,
                    bound,
                    input,
                    except_tool_call_id=call.tool_call_id,
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
        dropped_fold = (
            call.name == "spawn_agent.v1"
            and str(result.get("exit_reason") or "") == "dropped"
        )
        child_fold = call.name == "spawn_agent.v1" and "child_status" in result
        if (
            child_fold
            and not dropped_fold
            and (not reused or self._child_ref(state, call.tool_call_id) is not None)
        ):
            state = self._apply_child_fold_usage(state, result, call.tool_call_id)
        advance_index = (
            state.has_pending_tool
            and state.pending_tool_calls[state.pending_tool_index].tool_call_id
            == call.tool_call_id
        )
        if dropped_fold:
            if call.tool_call_id in _tool_result_ids(state.transcript):
                after = self._drain_completed_prefix(state)
            elif call.tool_call_id in _tool_use_names(state.transcript):
                after = await self._after_result(
                    state,
                    ToolResultContent(
                        call.tool_call_id,
                        "error",
                        {"exit_reason": "dropped"},
                    ),
                    tool_name=call.name,
                    tool_input=call.input,
                    advance_index=advance_index,
                )
            else:
                after = state
                if advance_index:
                    after = replace(
                        after, pending_tool_index=after.pending_tool_index + 1
                    )
        elif call.tool_call_id in _tool_result_ids(state.transcript):
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
        ref = self._child_ref(after, call.tool_call_id)
        still_live = ref is not None
        # A parked child's tool result *is* its fold, so writing one means the
        # child is done and the ref goes. A detached child (K3) already had its
        # result written at spawn time -- dropping it here would strand a run
        # nobody advances and lose the report.
        if ran_spawn or child_fold or still_live:
            if ref is None or not ref.detached:
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
            await self._enforce_usage_budgets_after_child_spend(
                after, deps, bound, input
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
            if call.name in {"spawn_agent.v1", "set_phase.v1"} | _CONTROL_PLANE_TOOLS:
                break
            if not tool_allowed_in_phase(call.name, state.phase):
                break
            if not self._tool_allowed_by_skills(call.name, state):
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

    def _maybe_prefetch_readonly(self, call: ToolCallCompleted, bound, state):
        if call.name == "spawn_agent.v1":
            return None
        if _is_stall_denied(state, call.name, call.input):
            return None
        if not tool_allowed_in_phase(call.name, state.phase):
            return None
        if not self._tool_allowed_by_skills(call.name, state):
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

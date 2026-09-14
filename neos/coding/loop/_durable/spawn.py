"""Parent-mediated subagent spawn, fold, and claim handling for the durable loop."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import replace
from datetime import timedelta
from typing import Any

from neos.coding.model.base import (
    ToolResultContent,
)
from neos.coding.tools.executor import ToolResult
from neos.coding.domain.durability import ToolExecutionDisposition
from neos.coding.loop._durable.state import (
    ActiveChildRef,
    AgentLoopState,
    CodingLoopFailure,
    DelegatedSpawn,
    _BRIEF_PLACEHOLDER_RE,
    _STALE_SLACK_SEC,
    _STUB_GOALS,
)
from neos.coding.loop._durable.support import (
    _discard_lease,
    _lease_from_ref,
    _legacy_single,
    _open_implement_worktree,
    _restore_active_children,
    _session_on_workspace,
    _stamp_is_stale,
    _subagent_max_active,
    _tool_result_ids,
)

logger = logging.getLogger("neos.coding.loop.durable")


class SubagentSpawnMixin:
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

    def _record_adopt_error(self, op: str) -> None:
        from neos.subagent.metrics import record_adopt_error

        record_adopt_error(self._metrics, parent_kind="coding", op=op)

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

    async def _fold_child(self, run_id: str, state: AgentLoopState):
        return await self._subagents.fold(
            run_id,
            parent_headroom_chars=self._parent_headroom_chars(state),
            sibling_count=max(1, len(state.active_children or ())),
        )

    def _child_stale_after_sec(self, max_turns: int) -> float:
        timeout = float(getattr(self._config, "timeout_sec", 120) or 120)
        return max(1, min(8, max_turns)) * timeout + _STALE_SLACK_SEC

    async def _fold_if_stale_child(
        self, ref: ActiveChildRef, *, max_turns: int, bound, state
    ) -> dict[str, Any] | None:
        if self._subagents is None:
            return None
        from neos.subagent.types import SubagentStatus

        now = self._clock()
        horizon = self._child_stale_after_sec(max_turns)
        parent_stale = _stamp_is_stale(ref.last_advanced_at, now, horizon)
        fail_if_stale = getattr(self._subagents, "fail_if_stale", None)
        if not callable(fail_if_stale):
            return None
        # Parent last_advanced_at is the no-progress clock; 0 forces store fail.
        snap = await fail_if_stale(
            ref.run_id,
            now=now,
            stale_after_sec=0 if parent_stale else horizon,
        )
        store_stale = (
            snap.status is SubagentStatus.FAILED and snap.error_code == "stalled"
        )
        if not parent_stale and not store_stale:
            return None
        folded = await self._fold_child(ref.run_id, state)
        return self._folded_spawn_result(bound, folded)

    def _child_ref(self, state, tool_call_id: str) -> ActiveChildRef | None:
        for child in state.active_children:
            if child.tool_call_id == tool_call_id:
                return child
        return None

    def _child_ref_by_run(self, state, run_id: str) -> ActiveChildRef | None:
        for child in state.active_children or _legacy_single(state):
            if child.run_id == run_id:
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

    def discard_child_worktrees(self, loop_state) -> None:
        if not isinstance(loop_state, Mapping):
            return
        for ref in _restore_active_children(loop_state):
            _discard_lease(_lease_from_ref(ref))

    async def _cancel_active_child(
        self, state, *, reason: str, task_id: str | None = None
    ) -> None:
        if self._subagents is None:
            return
        refs = ()
        if state is not None:
            refs = state.active_children or _legacy_single(state)
        for ref in refs:
            _discard_lease(_lease_from_ref(ref))
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
            logger.warning(
                "adopt spawn claim failed tool_call_id=%s",
                tool_call_id,
                exc_info=True,
            )
            self._record_adopt_error("adopt")
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
            logger.warning(
                "complete spawn claim failed reason=%s tool_call_id=%s",
                reason,
                getattr(claim, "tool_call_id", None),
                exc_info=True,
            )
            self._record_adopt_error("complete")
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
            _discard_lease(_lease_from_ref(ref))
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

    def _bind_child_tools(
        self,
        bound,
        state,
        *,
        spec_name: str = "explore",
        worktree_path: str = "",
    ) -> None:
        if self._subagents is None:
            return
        stepper = getattr(self._subagents, "_stepper", None)
        port = getattr(stepper, "_tools", None) if stepper is not None else None
        bind = getattr(port, "bind", None)
        use_spec = getattr(port, "use_spec", None)
        if callable(use_spec):
            use_spec(spec_name)
        session = bound.session
        if worktree_path:
            session = _session_on_workspace(session, worktree_path)
        if callable(bind):
            bind(session=session)

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
        goal = str(raw.get("prompt") or "").strip()
        if goal.upper() in _STUB_GOALS or _BRIEF_PLACEHOLDER_RE.search(goal):
            raise ValueError("briefing.goal is a placeholder")
        return ParentBriefing(
            goal=goal,
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
        priced = self._price_tokens(in_tokens, out_tokens)
        return in_tokens, out_tokens, priced

    def _unrolled_child_usage(
        self, child: ActiveChildRef | None, input_tokens: int, output_tokens: int
    ) -> tuple[int, int, int, int]:
        rolled_in = child.rolled_input_tokens if child is not None else 0
        rolled_out = child.rolled_output_tokens if child is not None else 0
        in_delta = max(0, int(input_tokens or 0) - rolled_in)
        out_delta = max(0, int(output_tokens or 0) - rolled_out)
        return in_delta, out_delta, rolled_in + in_delta, rolled_out + out_delta

    def _apply_child_usage_delta(
        self, state, input_tokens: int, output_tokens: int
    ) -> AgentLoopState:
        in_tokens = max(0, int(input_tokens or 0))
        out_tokens = max(0, int(output_tokens or 0))
        child_cost = self._price_tokens(in_tokens, out_tokens)
        self._record_fold_rollup(in_tokens, out_tokens, child_cost)
        return replace(
            state,
            input_tokens=state.input_tokens + in_tokens,
            output_tokens=state.output_tokens + out_tokens,
            cost_micros=state.cost_micros + child_cost,
        )

    def _apply_child_fold_usage(
        self, state, folded, tool_call_id: str
    ) -> AgentLoopState:
        in_tokens, out_tokens, _ = self._price_child_usage(folded)
        in_delta, out_delta, _, _ = self._unrolled_child_usage(
            self._child_ref(state, tool_call_id), in_tokens, out_tokens
        )
        return self._apply_child_usage_delta(state, in_delta, out_delta)

    def _folded_spawn_result(self, bound, folded) -> dict[str, Any]:
        from neos.subagent.types import SubagentStatus

        ok = folded.status is SubagentStatus.COMPLETED
        status = "ok" if ok else "error"
        exit_reason = str(getattr(folded, "exit_reason", "") or "")
        reason = "ok" if ok else (exit_reason or folded.status.value)
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
                        "exit_reason": exit_reason,
                    },
                ),
            ).to_mapping()
        )
        result["summary"] = folded.summary
        result["run_id"] = folded.run_id
        result["truncated"] = bool(folded.truncated)
        result["citations"] = list(folded.citations)
        result["child_status"] = folded.status.value
        result["exit_reason"] = exit_reason
        result["turn_count"] = folded.turn_count
        result["input_tokens"] = int(folded.input_tokens or 0)
        result["output_tokens"] = int(folded.output_tokens or 0)
        result["exit_reason"] = exit_reason
        result.pop("full_summary", None)
        return result

    def _dropped_spawn_result(self, bound, snapshot) -> dict[str, Any]:
        result = dict(
            ToolResult(
                "error",
                "dropped",
                None,
                None,
                False,
                None,
                str(bound.binding.workspace_revision),
                entries=(
                    {
                        "run_id": snapshot.run_id,
                        "exit_reason": "dropped",
                    },
                ),
            ).to_mapping()
        )
        result["run_id"] = snapshot.run_id
        result["exit_reason"] = "dropped"
        result["child_status"] = snapshot.status.value
        result["truncated"] = False
        result["turn_count"] = int(getattr(snapshot, "turn_count", 0) or 0)
        result["input_tokens"] = int(snapshot.input_tokens or 0)
        result["output_tokens"] = int(snapshot.output_tokens or 0)
        return result

    def _subagent_list_result(self, bound, children: list[dict[str, Any]]) -> dict[str, Any]:
        result = dict(
            ToolResult.ok(
                workspace_revision=str(bound.binding.workspace_revision),
                entries=tuple(children),
            ).to_mapping()
        )
        result["children"] = children
        return result

    async def _run_subagent_list(self, bound, state, *, input=None) -> dict[str, Any]:
        if not self._config.subagent_enabled or self._subagents is None:
            return self._subagent_list_result(bound, [])
        parent_id = input.task_id if input is not None else ""
        children: list[dict[str, Any]] = []
        for ref in state.active_children or _legacy_single(state):
            try:
                snapshot = await self._subagents.status(ref.run_id)
            except Exception:
                continue
            if snapshot.parent_id != parent_id:
                continue
            status = snapshot.status.value
            if status not in {"pending", "running"}:
                continue
            children.append(
                {
                    "run_id": snapshot.run_id,
                    "spec": snapshot.spec,
                    "status": status,
                    "turn_count": snapshot.turn_count,
                }
            )
        return self._subagent_list_result(bound, children)

    async def _run_subagent_steer(
        self, call, bound, state, *, input=None
    ) -> dict[str, Any]:
        if not self._config.subagent_enabled or self._subagents is None:
            return self._spawn_tool_error(bound, "subagent_disabled")
        raw = call.input if isinstance(call.input, Mapping) else {}
        run_id = str(raw.get("run_id") or "")
        text = str(raw.get("text") or "").strip()
        if not run_id or not text or len(text) > 2000:
            return self._spawn_tool_error(bound, "policy_schema_invalid")
        try:
            snapshot = await self._subagents.status(run_id)
        except Exception:
            return self._spawn_tool_error(bound, "policy_not_owner")
        parent_id = input.task_id if input is not None else ""
        if snapshot.parent_id != parent_id:
            return self._spawn_tool_error(bound, "policy_not_owner")
        existing = self._child_ref_by_run(state, run_id)
        if existing is None:
            return self._spawn_tool_error(bound, "policy_not_owner")
        merged = "\n".join(
            part for part in (existing.pending_steer, text) if part
        )
        if len(merged) > 2000:
            return self._spawn_tool_error(bound, "policy_schema_invalid")
        updated = self._upsert_active_child(
            state, replace(existing, pending_steer=merged)
        )
        result = dict(
            ToolResult.ok(
                workspace_revision=str(bound.binding.workspace_revision),
                entries=({"run_id": run_id, "steered": True},),
            ).to_mapping()
        )
        result["_loop_state"] = updated
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
            spec = lookup_spec(spec_name)
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
        if ref is not None and ref.run_id:
            snapshot = await self._subagents.status(ref.run_id)
            if snapshot.parent_id != input.task_id:
                return self._dropped_spawn_result(bound, snapshot)
        lease = _lease_from_ref(ref)
        if spec.sandbox_mode is SandboxMode.WORKTREE and lease is None:
            try:
                lease = _open_implement_worktree(bound.session, call.tool_call_id)
            except Exception:
                return self._spawn_tool_error(bound, "policy_worktree_unavailable")
        ticket = SubagentTicket(
            parent_kind=ParentKind.CODING,
            parent_id=input.task_id,
            parent_run_id=input.run_id,
            parent_tool_call_id=call.tool_call_id,
            spec=spec_name,
            briefing=briefing,
            model=ModelPin(provider=provider, model=self._config.model),
            max_turns=max_turns,
            sandbox_mode=spec.sandbox_mode,
            expected_checkpoint_id=ref.checkpoint_id if ref else None,
            run_id=ref.run_id if ref else None,
            pending_steer=ref.pending_steer if ref else "",
            spawn_depth=ref.spawn_depth if ref else 0,
        )
        if ref is not None:
            folded = await self._fold_if_stale_child(
                ref, max_turns=max_turns, bound=bound, state=state
            )
            if folded is not None:
                return self._finish_implement_child(bound, folded, lease)
        try:
            self._bind_child_tools(
                bound,
                state,
                spec_name=spec_name,
                worktree_path=str(lease.path) if lease is not None else "",
            )
        except Exception:
            if lease is not None:
                _discard_lease(lease)
            return self._spawn_tool_error(bound, "policy_worktree_unavailable")
        try:
            await self._renew_parent_lease(deps)
            outcome = await self._subagents.advance(ticket)
            await self._renew_parent_lease(deps)
        except asyncio.CancelledError:
            if lease is not None:
                _discard_lease(lease)
            await self._cancel_active_child(
                state, reason="aborted", task_id=input.task_id
            )
            raise
        if outcome.kind is StepKind.CONTINUING:
            return DelegatedSpawn(
                run_id=outcome.run_id,
                checkpoint_id=outcome.checkpoint_id,
                step_kind=outcome.kind.value,
                input_tokens=int(outcome.input_tokens or 0),
                output_tokens=int(outcome.output_tokens or 0),
                spec=spec_name,
                spawn_depth=ticket.spawn_depth,
                worktree_repo=str(lease.repo) if lease else "",
                worktree_path=str(lease.path) if lease else "",
                worktree_branch=lease.branch if lease else "",
                worktree_base_sha=lease.base_sha if lease else "",
            )
        folded = await self._fold_child(outcome.run_id, state)
        return self._finish_implement_child(bound, folded, lease)

    def _finish_implement_child(self, bound, folded, lease) -> dict[str, Any]:
        if isinstance(folded, dict):
            result = dict(folded)
        else:
            result = self._folded_spawn_result(bound, folded)
        if lease is None:
            return result
        from neos.coding.subagent_worktree import (
            commit_worktree,
            merge_worktree,
        )

        try:
            commit_worktree(lease)
            merged = merge_worktree(lease)
        except Exception as error:
            result["merge_status"] = "failed"
            result["merge_applied"] = False
            result["merge_message"] = str(error)
            return result
        result["merge_status"] = merged.status.value
        result["merge_applied"] = bool(merged.applied)
        result["merge_conflicts"] = list(merged.conflict_paths)
        result["merge_message"] = merged.message
        if merged.status.value in {"fast_forward", "empty"}:
            _discard_lease(lease)
        return result

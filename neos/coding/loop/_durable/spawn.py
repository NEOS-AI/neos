"""Parent-mediated subagents: the control-plane tools and the K3 safe point.

Two delivery modes share one child runtime:

- **park** (`delivery="tool_result"`, the default): `spawn_agent.v1` stays
  pending while the child runs; each parent step advances it once, and the
  fold becomes the call's tool result.
- **detached** (`subagent_async_spawn`): the tool result is written at spawn
  time, and the parent's safe point (`_advance_detached_children`) advances
  the child once per parent turn and appends its report as a user message.

Control-plane handlers return `(result, state)`; the tool path commits both.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from neos.coding.loop._durable import spawn_results
from neos.coding.loop._durable.children import (
    _STALE_SLACK_SEC,
    _child_ref,
    _child_ref_by_run,
    _detached_children,
    _live_children,
    _stamp_is_stale,
    _subagent_max_active,
    _unrolled_child_usage,
    _upsert_active_child,
    _without_child,
)
from neos.coding.loop._durable.state import (
    ActiveChildRef,
    AgentLoopState,
    CodingLoopFailure,
    DelegatedSpawn,
)
from neos.coding.loop._durable.transcript import _append_user_text
from neos.coding.loop._durable.usage import price_tokens
from neos.coding.loop._durable.worktree import (
    _discard_lease,
    _lease_fields,
    _lease_from_ref,
    _open_implement_worktree,
    _ref_worktree_fields,
    _session_on_workspace,
)

logger = logging.getLogger("neos.coding.loop.durable")

_SPAWN_PROVIDERS = frozenset({"anthropic", "openai", "gemini", "ollama"})
#: Kebab prefixes whose specs belong to other parents (FSI, Univer).
_FOREIGN_SPEC_PREFIXES = ("fsi-", "univer-")
_STEER_MAX_CHARS = 2000

SpawnOutcome = tuple["dict[str, Any] | DelegatedSpawn", AgentLoopState]


@dataclass(frozen=True, slots=True)
class _SpawnRequest:
    spec_name: str
    spec: Any
    provider: str
    max_turns: int
    briefing: Any


def _call_input(call) -> Mapping[str, Any]:
    return call.input if isinstance(getattr(call, "input", None), Mapping) else {}


def _delegated(
    outcome,
    *,
    spec: str,
    spawn_depth: int,
    worktree: Mapping[str, str],
    tool_call_id: str = "",
) -> DelegatedSpawn:
    return DelegatedSpawn(
        run_id=outcome.run_id,
        checkpoint_id=outcome.checkpoint_id,
        step_kind=outcome.kind.value,
        tool_call_id=tool_call_id,
        input_tokens=int(outcome.input_tokens or 0),
        output_tokens=int(outcome.output_tokens or 0),
        spec=spec,
        spawn_depth=spawn_depth,
        **worktree,
    )


class SubagentSpawnMixin:
    # Result builders are pure; they are reachable here for the tool path
    # and for tests. See `spawn_results`.
    _spawn_tool_error = staticmethod(spawn_results._spawn_tool_error)
    _legacy_explore_handoff = staticmethod(spawn_results._legacy_explore_handoff)
    _folded_spawn_result = staticmethod(spawn_results._folded_spawn_result)
    _dropped_spawn_result = staticmethod(spawn_results._dropped_spawn_result)
    _subagent_list_result = staticmethod(spawn_results._subagent_list_result)
    _finish_implement_child = staticmethod(spawn_results._finish_implement_child)
    _spawn_briefing = staticmethod(spawn_results._spawn_briefing)

    # -- metrics -----------------------------------------------------------

    def _spawn_spec_name(self, call) -> str:
        return str(_call_input(call).get("spec") or "explore")

    def _record_spawn_live_children(self, state, call) -> None:
        from neos.subagent.metrics import record_live_children

        live_count = len(_live_children(state))
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

    # -- usage roll-in -----------------------------------------------------

    def _price_child_usage(self, folded) -> tuple[int, int, int]:
        if isinstance(folded, Mapping):
            in_tokens = int(folded.get("input_tokens") or 0)
            out_tokens = int(folded.get("output_tokens") or 0)
        else:
            in_tokens = int(folded.input_tokens or 0)
            out_tokens = int(folded.output_tokens or 0)
        return in_tokens, out_tokens, price_tokens(self._config, in_tokens, out_tokens)

    def _apply_child_usage_delta(
        self, state, input_tokens: int, output_tokens: int
    ) -> AgentLoopState:
        in_tokens = max(0, int(input_tokens or 0))
        out_tokens = max(0, int(output_tokens or 0))
        child_cost = price_tokens(self._config, in_tokens, out_tokens)
        self._record_fold_rollup(in_tokens, out_tokens, child_cost)
        return replace(
            state,
            input_tokens=state.input_tokens + in_tokens,
            output_tokens=state.output_tokens + out_tokens,
            cost_micros=state.cost_micros + child_cost,
        )

    def _roll_in_child_usage(
        self, state, ref: ActiveChildRef | None, input_tokens: int, output_tokens: int
    ) -> tuple[AgentLoopState, int, int]:
        """Charge what the child spent since the last roll-in.

        Returns the charged state and the ref's new rolled totals.
        """
        in_delta, out_delta, rolled_in, rolled_out = _unrolled_child_usage(
            ref, input_tokens, output_tokens
        )
        return self._apply_child_usage_delta(state, in_delta, out_delta), rolled_in, rolled_out

    def _apply_child_fold_usage(
        self, state, folded, tool_call_id: str
    ) -> AgentLoopState:
        in_tokens, out_tokens, _ = self._price_child_usage(folded)
        charged, _, _ = self._roll_in_child_usage(
            state, _child_ref(state, tool_call_id), in_tokens, out_tokens
        )
        return charged

    # -- child lifecycle ---------------------------------------------------

    @property
    def _async_spawn(self) -> bool:
        return bool(
            self._config.subagent_enabled
            and getattr(self._config, "subagent_async_spawn", False)
        )

    def _with_spawn_handoff(self, state: AgentLoopState, call, result) -> AgentLoopState:
        """With subagents off, a spawn's prompt becomes the parent's next work."""
        if call.name != "spawn_agent.v1":
            return state
        if str(result.get("status", "ok")) != "ok":
            return state
        prompt = call.input.get("prompt") if isinstance(call.input, Mapping) else None
        if not isinstance(prompt, str) or not prompt.strip():
            return state
        text = prompt.strip()
        if state.has_pending_tool:
            existing = state.pending_instruction
            merged = "\n".join(part for part in (existing, text) if part)
            return replace(state, pending_instruction=merged)
        return self._with_transcript(state, _append_user_text(state.transcript, text))

    async def _fold_child(self, run_id: str, state: AgentLoopState):
        return await self._subagents.fold(
            run_id,
            parent_headroom_chars=self._parent_headroom_chars(state),
            sibling_count=max(1, len(state.active_children or ())),
        )

    async def _fold_and_finish(self, bound, run_id: str, state, lease) -> dict[str, Any]:
        folded = await self._fold_child(run_id, state)
        return self._finish_implement_child(bound, folded, lease)

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

    def _bind_child_tools(
        self,
        bound,
        state,
        *,
        deps=None,
        spec_name: str = "explore",
        worktree_path: str = "",
        spawn_call_id: str = "",
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

            async def authorize(validated):
                return await self._authorize_child_call(
                    validated,
                    state=state,
                    deps=deps,
                    spec_name=spec_name,
                    spawn_call_id=spawn_call_id,
                )

            bind(session=session, authorize=authorize)

    def _rebind_child(self, ref: ActiveChildRef, bound, state, deps) -> None:
        """A resumed child gets the gate of *this* parent step, not the last spawn's.

        The port is shared by every child of the runtime. Without this, a child
        stepped at the safe point or by `await_subagent.v1` would run under
        whatever spec, worktree and gate the most recent spawn left bound.
        """
        lease = _lease_from_ref(ref)
        self._bind_child_tools(
            bound,
            state,
            deps=deps,
            spec_name=ref.spec,
            worktree_path=str(lease.path) if lease is not None else "",
            spawn_call_id=ref.tool_call_id,
        )

    async def _authorize_child_call(
        self, validated, *, state, deps, spec_name: str, spawn_call_id: str
    ):
        """The parent's gate, applied to one child call (roadmap CHILD-GATE).

        Same hooks, same static policy, same Jev banding as the parent's own
        calls -- this calls the parent's methods rather than restating them.
        What differs is that a child cannot ask anyone: specs carry
        `can_approve=False`, so the judgement runs unattended and
        REQUIRE_APPROVAL folds to DENY (D-L1's fold, not a new rule). A hook
        that asks to retry is a deny for the same reason -- the child has no
        retry turn to spend it on.
        """
        from neos.coding.domain.approvals import ApprovalPolicyOutcome
        from neos.coding.tools.registry import ToolValidationError

        reason: str | None = None
        decision, _hook_reason, updated_input = await self._pre_tool_decision(
            validated
        )
        if decision == "allow" and updated_input is not None:
            try:
                validated = self._tools.validate(validated.name, dict(updated_input))
            except ToolValidationError:
                reason = "hook_updated_input_invalid"
        elif decision == "prevent":
            reason = "hook_prevented"
        elif decision != "allow":
            reason = "policy_hook_denied"
        if reason is None:
            task_id = getattr(getattr(deps, "lease", None), "task_id", None)
            outcome = await self._evaluate_call(
                validated, state, deps, task_id, None, unattended=True
            )
            if outcome is not ApprovalPolicyOutcome.ALLOW:
                reason = "policy_approval_denied"
        if reason is None:
            return validated, None
        await self._record_child_denial(
            deps,
            name=validated.name,
            reason_code=reason,
            spec_name=spec_name,
            spawn_call_id=spawn_call_id,
        )
        return None, reason

    async def _record_child_denial(
        self, deps, *, name: str, reason_code: str, spec_name: str, spawn_call_id: str
    ) -> None:
        """Put the child's denial in the parent's ledger.

        The child's own transcript already carries the error; this is for the
        person reading the run. The denial stands whether or not the write
        lands -- a ledger outage must not turn a refused call into an allowed one.
        """
        lease = getattr(deps, "lease", None)
        events = getattr(deps, "events", None)
        task_id = getattr(lease, "task_id", None)
        if events is None or not task_id:
            return
        try:
            await events.append(
                task_id=task_id,
                event_type="tool.denied",
                payload={
                    "name": name,
                    "denied_by": "hook"
                    if reason_code in {"hook_prevented", "policy_hook_denied"}
                    else "approval_policy",
                    "reason_code": reason_code,
                    "subagent_spec": spec_name,
                    "parent_tool_call_id": spawn_call_id,
                },
            )
        except Exception:
            logger.warning(
                "child denial event failed task_id=%s tool=%s", task_id, name,
                exc_info=True,
            )

    # -- control-plane tools -----------------------------------------------

    async def _run_subagent_list(self, bound, state, *, input=None) -> SpawnOutcome:
        if not self._config.subagent_enabled or self._subagents is None:
            return self._subagent_list_result(bound, []), state
        parent_id = input.task_id if input is not None else ""
        children: list[dict[str, Any]] = []
        for ref in _live_children(state):
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
        return self._subagent_list_result(bound, children), state

    async def _run_subagent_steer(
        self, call, bound, state, *, input=None
    ) -> SpawnOutcome:
        if not self._config.subagent_enabled or self._subagents is None:
            return self._spawn_tool_error(bound, "subagent_disabled"), state
        raw = _call_input(call)
        run_id = str(raw.get("run_id") or "")
        text = str(raw.get("text") or "").strip()
        if not run_id or not text or len(text) > _STEER_MAX_CHARS:
            return self._spawn_tool_error(bound, "policy_schema_invalid"), state
        try:
            snapshot = await self._subagents.status(run_id)
        except Exception:
            return self._spawn_tool_error(bound, "policy_not_owner"), state
        parent_id = input.task_id if input is not None else ""
        if snapshot.parent_id != parent_id:
            return self._spawn_tool_error(bound, "policy_not_owner"), state
        existing = _child_ref_by_run(state, run_id)
        if existing is None:
            return self._spawn_tool_error(bound, "policy_not_owner"), state
        merged = "\n".join(part for part in (existing.pending_steer, text) if part)
        if len(merged) > _STEER_MAX_CHARS:
            return self._spawn_tool_error(bound, "policy_schema_invalid"), state
        updated = _upsert_active_child(state, replace(existing, pending_steer=merged))
        return spawn_results._steer_ack(bound, run_id), updated

    async def _refuse_spawn_closing_live(
        self, call, bound, state, deps, task_id: str, reason: str
    ) -> SpawnOutcome:
        state = await self.fail_all_live_spawn_claims(
            state,
            deps,
            bound,
            reason=reason,
            task_id=task_id or None,
            except_tool_call_id=call.tool_call_id,
        )
        return self._spawn_tool_error(bound, reason), state

    def _parse_spawn_request(self, call, bound) -> _SpawnRequest | dict[str, Any]:
        """Validate a spawn call's input; an error result if it is refused."""
        from neos.subagent.catalog import UnknownSpec, lookup_spec

        raw = _call_input(call)
        spec_name = str(raw.get("spec") or "explore")
        if spec_name.startswith(_FOREIGN_SPEC_PREFIXES):
            return self._spawn_tool_error(bound, "policy_unknown_spec")
        try:
            spec = lookup_spec(spec_name)
        except UnknownSpec:
            return self._spawn_tool_error(bound, "policy_unknown_spec")
        provider = self._config.provider
        if provider not in _SPAWN_PROVIDERS:
            return self._spawn_tool_error(bound, "model_pin_mismatch")
        try:
            max_turns = int(raw.get("max_turns", 4))
        except (TypeError, ValueError):
            max_turns = 4
        try:
            briefing = self._spawn_briefing(call)
        except ValueError:
            return self._spawn_tool_error(bound, "policy_schema_invalid")
        return _SpawnRequest(
            spec_name=spec_name,
            spec=spec,
            provider=provider,
            max_turns=max(1, min(8, max_turns)),
            briefing=briefing,
        )

    async def _run_spawn_agent(
        self, call, bound, state, *, input=None, deps=None
    ) -> SpawnOutcome:
        task_id = input.task_id if input is not None else ""
        live = _live_children(state)
        if deps is not None and await self._has_pending_interrupt(deps, task_id):
            return await self._refuse_spawn_closing_live(
                call, bound, state, deps, task_id, "aborted"
            )
        if live and not self._config.subagent_enabled:
            return await self._refuse_spawn_closing_live(
                call, bound, state, deps, task_id, "subagent_disabled"
            )
        if not self._config.subagent_enabled:
            return self._legacy_explore_handoff(bound), state
        if (
            live
            and call.tool_call_id not in {child.tool_call_id for child in live}
            and len(live) >= _subagent_max_active(self._config)
        ):
            self._record_policy_capped()
            return self._spawn_tool_error(bound, "policy_child_already_active"), state
        if self._subagents is None or input is None:
            raise CodingLoopFailure("subagent_runtime_missing", retryable=False)
        from neos.subagent.types import (
            ModelPin,
            ParentKind,
            SandboxMode,
            StepKind,
            SubagentTicket,
        )

        request = self._parse_spawn_request(call, bound)
        if isinstance(request, dict):
            return request, state
        ref = _child_ref(state, call.tool_call_id)
        if ref is not None and ref.run_id:
            snapshot = await self._subagents.status(ref.run_id)
            if snapshot.parent_id != input.task_id:
                return self._dropped_spawn_result(bound, snapshot), state
        lease = _lease_from_ref(ref)
        if request.spec.sandbox_mode is SandboxMode.WORKTREE and lease is None:
            try:
                lease = _open_implement_worktree(bound.session, call.tool_call_id)
            except Exception:
                return self._spawn_tool_error(bound, "policy_worktree_unavailable"), state
        ticket = SubagentTicket(
            parent_kind=ParentKind.CODING,
            parent_id=input.task_id,
            parent_run_id=input.run_id,
            parent_tool_call_id=call.tool_call_id,
            spec=request.spec_name,
            briefing=request.briefing,
            model=ModelPin(provider=request.provider, model=self._config.model),
            max_turns=request.max_turns,
            sandbox_mode=request.spec.sandbox_mode,
            expected_checkpoint_id=ref.checkpoint_id if ref else None,
            run_id=ref.run_id if ref else None,
            pending_steer=ref.pending_steer if ref else "",
            spawn_depth=ref.spawn_depth if ref else 0,
        )
        if ref is not None:
            folded = await self._fold_if_stale_child(
                ref, max_turns=request.max_turns, bound=bound, state=state
            )
            if folded is not None:
                return self._finish_implement_child(bound, folded, lease), state
        try:
            self._bind_child_tools(
                bound,
                state,
                deps=deps,
                spec_name=request.spec_name,
                worktree_path=str(lease.path) if lease is not None else "",
                spawn_call_id=call.tool_call_id,
            )
        except Exception:
            _discard_lease(lease)
            return self._spawn_tool_error(bound, "policy_worktree_unavailable"), state
        try:
            await self._renew_parent_lease(deps)
            outcome = await self._subagents.advance(ticket)
            await self._renew_parent_lease(deps)
        except asyncio.CancelledError:
            _discard_lease(lease)
            await self._cancel_active_child(
                state, reason="aborted", task_id=input.task_id
            )
            raise
        if outcome.kind is StepKind.CONTINUING and self._async_spawn:
            return self._detached_spawn_result(
                bound,
                state,
                call,
                outcome,
                spec_name=request.spec_name,
                spawn_depth=ticket.spawn_depth,
                lease=lease,
            )
        if outcome.kind is StepKind.CONTINUING:
            return (
                _delegated(
                    outcome,
                    spec=request.spec_name,
                    spawn_depth=ticket.spawn_depth,
                    worktree=_lease_fields(lease),
                ),
                state,
            )
        return await self._fold_and_finish(bound, outcome.run_id, state, lease), state

    def _detached_spawn_result(
        self,
        bound,
        state,
        call,
        outcome,
        *,
        spec_name: str,
        spawn_depth: int,
        lease,
    ) -> SpawnOutcome:
        """Write the tool result now; the report comes back as a user message.

        The child took its first step already -- that is what minted the run id
        the parent is about to hand the model. What changes is only who waits:
        nobody. `delivery="user_message"` is the whole switch, and the safe
        point in `_advance_one_model_turn` reads it.
        """
        existing = _child_ref(state, call.tool_call_id)
        charged, rolled_in, rolled_out = self._roll_in_child_usage(
            state, existing, outcome.input_tokens, outcome.output_tokens
        )
        updated = _upsert_active_child(
            charged,
            ActiveChildRef(
                run_id=outcome.run_id,
                checkpoint_id=outcome.checkpoint_id,
                tool_call_id=call.tool_call_id,
                last_advanced_at=self._utc_stamp(),
                rolled_input_tokens=rolled_in,
                rolled_output_tokens=rolled_out,
                pending_steer=existing.pending_steer if existing else "",
                spec=spec_name,
                spawn_depth=spawn_depth,
                delivery="user_message",
                **_lease_fields(lease),
            ),
        )
        return spawn_results._detached_spawn_ack(bound, outcome.run_id, spec_name), updated

    async def _run_await_subagent(
        self, call, bound, state, *, input=None, deps=None
    ) -> SpawnOutcome:
        """The explicit park: wait for one child, take its report here.

        Async spawn's default delivery is an append at the safe point, which
        the model does not get to ask for. This is the other half of R-03 --
        the model says it wants to wait, so the report becomes this call's
        result instead of a message, and nothing is appended for it.

        Parking reuses the machinery `spawn_agent.v1` already had: returning a
        `DelegatedSpawn` ends the durable step with the claim still open, and
        the next step re-enters this same call. What it does *not* reuse is the
        ref identity -- `tool_call_id` points the update back at the ref this
        child already has, or the run ends up with two.
        """
        if not self._async_spawn or self._subagents is None:
            return self._spawn_tool_error(bound, "subagent_disabled"), state
        from neos.subagent.types import StepKind

        run_id = str(_call_input(call).get("run_id") or "")
        if not run_id:
            return self._spawn_tool_error(bound, "policy_schema_invalid"), state
        ref = _child_ref_by_run(state, run_id)
        if ref is None or not ref.detached:
            # The safe point may have delivered this child already, or it was
            # never this parent's. Saying "not live" beats silence: the model
            # can go look for the report it was handed.
            return self._spawn_tool_error(bound, "policy_not_live"), state
        self._rebind_child(ref, bound, state, deps)
        outcome = await self._resume_child(ref, deps)
        if outcome.kind is StepKind.CONTINUING:
            return (
                _delegated(
                    outcome,
                    spec=ref.spec,
                    spawn_depth=ref.spawn_depth,
                    worktree=_ref_worktree_fields(ref),
                    tool_call_id=ref.tool_call_id,
                ),
                state,
            )
        result = await self._fold_and_finish(
            bound, outcome.run_id, state, _lease_from_ref(ref)
        )
        return result, _without_child(state, ref.tool_call_id)

    # -- the K3 safe point -------------------------------------------------

    async def _resume_child(self, ref: ActiveChildRef, deps):
        await self._renew_parent_lease(deps)
        outcome = await self._subagents.resume(
            ref.run_id,
            expected_checkpoint_id=ref.checkpoint_id,
            pending_steer=ref.pending_steer,
            spawn_depth=ref.spawn_depth,
        )
        await self._renew_parent_lease(deps)
        return outcome

    def _hold_for_detached_children(self, state):
        """Don't let the parent walk away from a report it asked for.

        Park could never reach this state -- the parent was blocked on the
        child. Async spawn can: the model says "done" while a child it started
        is still running, and the report lands in a transcript nobody reads.

        The hold is bounded without a counter. Each held turn costs one parent
        turn and pushes every child one step at the safe point, so a child with
        `max_turns` steps left can hold the parent at most that many times, and
        `max_turns` on the parent is the backstop underneath that. That is the
        difference between this and a drain loop: the parent keeps taking real
        turns and may still call tools, steer, or give up.
        """
        live = _detached_children(state)
        if not live:
            return None
        names = ", ".join(f"{child.spec}:{child.run_id}" for child in live)
        note = (
            f"Still running: {names}. Their reports arrive as messages here. "
            "Wait for them, or say what you concluded without them."
        )
        return self._with_note(state, note, terminal_pending=False)

    async def _advance_detached_children(self, state, bound, deps):
        """The safe point: push every detached child one step, deliver the done.

        This is the whole of K3's "parent keeps working". There is no loop and
        no mailbox -- the parent's own durable step pushes its children once on
        the way to its next turn, which is why children still live and die
        under the parent lease.

        A child advances at most one step per parent turn on purpose. The
        alternative, draining a child to completion here, is the `while(true)`
        parent loop PLAN_260913 §2.1 still forbids.

        Crash safety rides on the CAS. If this step dies after a child commits
        but before the parent does, the retry resumes from a stale checkpoint
        id, the store refuses the step, and `_outcome` hands back where the
        child actually is -- so the ref re-syncs and the next turn moves it.
        `last_advanced_at` only moves when the checkpoint does, so a child that
        stops progressing still goes stale on schedule.
        """
        if self._subagents is None or not self._async_spawn:
            return state
        # An awaited child never reaches here: parking leaves the tool call
        # pending, so the loop re-enters the tool path and no model turn --
        # and so no safe point -- happens until the await resolves.
        for ref in _detached_children(state):
            state = await self._advance_one_detached_child(ref, state, bound, deps)
        return state

    async def _advance_one_detached_child(self, ref, state, bound, deps):
        from neos.subagent.types import StepKind

        await self._renew_parent_lease(deps)
        try:
            self._rebind_child(ref, bound, state, deps)
            outcome = await self._subagents.resume(
                ref.run_id,
                expected_checkpoint_id=ref.checkpoint_id,
                pending_steer=ref.pending_steer,
                spawn_depth=ref.spawn_depth,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            # A child that cannot be stepped must not take the parent's turn
            # down with it. Leaving the ref alone lets the staleness clock
            # reach it.
            logger.warning(
                "detached child resume failed run_id=%s", ref.run_id, exc_info=True
            )
            return state
        state, rolled_in, rolled_out = self._roll_in_child_usage(
            state, ref, outcome.input_tokens, outcome.output_tokens
        )
        if outcome.kind is StepKind.CONTINUING:
            moved = outcome.checkpoint_id != ref.checkpoint_id
            return _upsert_active_child(
                state,
                replace(
                    ref,
                    checkpoint_id=outcome.checkpoint_id,
                    last_advanced_at=(
                        self._utc_stamp() if moved else ref.last_advanced_at
                    ),
                    rolled_input_tokens=rolled_in,
                    rolled_output_tokens=rolled_out,
                ),
            )
        report = await self._fold_and_finish(
            bound, outcome.run_id, state, _lease_from_ref(ref)
        )
        state = _without_child(state, ref.tool_call_id)
        return self._with_note(
            state, spawn_results._detached_report_text(ref, report)
        )

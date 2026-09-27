"""Execution claims and leases for delegated `spawn_agent.v1` calls.

A spawn claim outlives the durable step that opened it: the child keeps
running across parent steps, so the claim is marked delegated instead of
completed, and each later step re-adopts it. Everything that ends a parent
early -- abort, budget, disabled subagents -- must close every live claim,
or a reclaimed step later reads a delegated claim as a lost execution.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import timedelta

from neos.coding.domain.durability import ToolExecutionDisposition
from neos.coding.model.base import ToolResultContent
from neos.coding.loop._durable.children import (
    _drain_completed_prefix,
    _is_pending_head,
    _live_children,
    _sync_active_children,
)
from neos.coding.loop._durable.codec import _restore_active_children
from neos.coding.loop._durable.state import (
    ActiveChildRef,
    AgentLoopState,
    DelegatedSpawn,
)
from neos.coding.loop._durable.transcript import _tool_result_ids
from neos.coding.loop._durable.worktree import _discard_lease, _lease_from_ref

logger = logging.getLogger("neos.coding.loop.durable")

_OPEN_CLAIMS = frozenset(
    {
        ToolExecutionDisposition.CLAIMED,
        ToolExecutionDisposition.RECLAIMED,
        ToolExecutionDisposition.DELEGATED,
    }
)


class SpawnClaimsMixin:
    def _record_adopt_error(self, op: str) -> None:
        from neos.subagent.metrics import record_adopt_error

        record_adopt_error(self._metrics, parent_kind="coding", op=op)

    def _spawn_claim_ttl(self) -> timedelta:
        return timedelta(seconds=self._config.timeout_sec + 30)

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
            claim_expires_at=now + self._spawn_claim_ttl(),
            now=now,
        )

    async def _complete_spawn_claim(
        self, deps, claim, bound, reason: str, *, report_failure: bool = True
    ) -> None:
        """Close an open claim with an error result. Never raises."""
        if deps is None or claim is None:
            return
        if claim.disposition not in _OPEN_CLAIMS:
            return
        try:
            await deps.repository.complete_tool_execution(
                claim,
                result=self._spawn_tool_error(bound, reason),
                now=self._clock(),
            )
        except Exception:
            if not report_failure:
                return
            logger.warning(
                "complete spawn claim failed reason=%s tool_call_id=%s",
                reason,
                getattr(claim, "tool_call_id", None),
                exc_info=True,
            )
            self._record_adopt_error("complete")

    async def _fail_delegated_claim(self, deps, claim, bound) -> None:
        # On cancellation: best effort, and quiet -- the abort path reports.
        await self._complete_spawn_claim(
            deps, claim, bound, "aborted", report_failure=False
        )

    async def _adopt_spawn_claim(self, deps, tool_call_id: str):
        if deps is None or deps.lease is None:
            return None
        try:
            return await deps.repository.claim_tool_execution(
                lease=deps.lease,
                tool_call_id=tool_call_id,
                now=self._clock(),
                claim_expires_at=self._clock() + self._spawn_claim_ttl(),
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
        """Re-take every live child's claim; re-delegate the ones not stepping now."""
        refs = _live_children(state) if state is not None else ()
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
        refs = _live_children(state)
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
                after = await self._after_result(
                    after,
                    ToolResultContent(
                        ref.tool_call_id,
                        "error",
                        {"reason_code": reason},
                    ),
                    tool_name="spawn_agent.v1",
                    tool_input={},
                    advance_index=_is_pending_head(after, ref.tool_call_id),
                )
                done.add(ref.tool_call_id)
        after = _sync_active_children(after, tuple(kept))
        return _drain_completed_prefix(after)

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
        refs = _live_children(state) if state is not None else ()
        for ref in refs:
            _discard_lease(_lease_from_ref(ref))
            await self._subagents.cancel(ref.run_id, reason)
        if task_id:
            from neos.subagent.types import ParentKind

            await self._subagents.cancel_for_parent(
                ParentKind.CODING, task_id, reason
            )

"""Checkpoint restore delegation and the abort checkpoint.

The wire format is `codec`; what a restore does with a stored state is
`neos.coding.loop.checkpoint.restore_state`.
"""

from __future__ import annotations

import asyncio
import logging

from neos.coding.model.base import ToolResultContent
from neos.coding.loop._durable.children import _drain_completed_prefix
from neos.coding.loop._durable.transcript import _tool_result_ids
from neos.coding.loop.checkpoint import initial_state, restore_state

logger = logging.getLogger("neos.coding.loop.durable")


class CheckpointMixin:
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
        existing = _tool_result_ids(state.transcript)
        pending = [
            call
            for call in state.pending_tool_calls[state.pending_tool_index :]
            if call.tool_call_id not in existing
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
        after = _drain_completed_prefix(after)
        await self._commit_model(
            input,
            bound,
            deps,
            after,
            {"reason_code": "aborted"},
            event_type="tool.completed" if pending else "model.completed",
        )

    def _restore(self, input, checkpoint):
        if checkpoint is None:
            return initial_state(input)
        return restore_state(
            input, checkpoint, catalog=self._catalog, compactor=self._compactor
        )

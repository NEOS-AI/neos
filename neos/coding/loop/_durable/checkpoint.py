"""Checkpoint restore, pending slash commands, and the abort checkpoint.

The wire format itself is `codec`; this mixin decides what a restore *does*
with a stored state -- apply workspace edits, run a queued command -- and
what the dump records as the task's instruction.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace

from neos.coding.loop.base import LoopInput
from neos.coding.model.base import (
    CanonicalMessage,
    TextContent,
    ToolResultContent,
)
from neos.coding.loop._durable.children import (
    _drain_completed_prefix,
    _sync_active_children,
)
from neos.coding.loop._durable.codec import (
    _dump_loop_state,
    _message_from_mapping,
    _state_from_mapping,
)
from neos.coding.loop._durable.state import AgentLoopState
from neos.coding.loop._durable.transcript import _append_user_text, _tool_result_ids

logger = logging.getLogger("neos.coding.loop.durable")

_CLEARED_NOTICE = "Conversation context was cleared."


def _note(state: AgentLoopState, text: str) -> AgentLoopState:
    return replace(state, transcript=_append_user_text(state.transcript, text))


def _compact_command(loop, input, state: AgentLoopState, decision) -> AgentLoopState:
    from neos.coding.commands.parse import sanitize_command_args

    bodies = dict(state.compacted_bodies)
    after = loop._compact(state.transcript, force=True, bodies=bodies)
    hint = sanitize_command_args(decision.parsed.args, max_len=240)
    notice = (
        f"Transcript compacted by /compact. Keep: {hint}"
        if hint
        else "Transcript compacted by /compact."
    )
    return replace(
        state,
        transcript=_append_user_text(after, notice),
        compacted_bodies=bodies,
        instructions_loaded=False,
    )


def _clear_command(loop, input, state: AgentLoopState, decision) -> AgentLoopState:
    return replace(
        state,
        transcript=loop._cleared_transcript(input, state.transcript),
        compacted_bodies={},
        todos=(),
        instructions_loaded=False,
    )


def _cost_command(loop, input, state: AgentLoopState, decision) -> AgentLoopState:
    from neos.coding.commands.service import format_cost_parts

    usage = {
        "cost_micros": state.cost_micros,
        "input_tokens": state.input_tokens,
        "output_tokens": state.output_tokens,
        "cache_read_tokens": state.cache_read_tokens,
        "cache_write_tokens": state.cache_write_tokens,
        "reasoning_tokens": state.reasoning_tokens,
    }
    return _note(state, " ".join(format_cost_parts(usage)))


#: Slash commands a restore applies itself. Anything else the interpreter
#: recognizes as a command is answered with its message and not run.
_PENDING_COMMANDS = {
    "compact": _compact_command,
    "clear": _clear_command,
    "cost": _cost_command,
}


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
            transcript = self._with_workspace_edits(
                (CanonicalMessage("user", (TextContent(input.instruction),)),),
                input.workspace_edits,
            )
            return AgentLoopState(
                transcript=transcript,
                turn_count=0,
                tool_count=0,
                consecutive_tool_errors=0,
                pending_tool_calls=(),
                pending_tool_index=0,
                transcript_digest=self._digest(transcript),
            )
        raw = checkpoint.loop_state
        transcript = self._with_workspace_edits(
            tuple(_message_from_mapping(item) for item in raw.get("transcript", [])),
            input.workspace_edits,
        )
        state = _state_from_mapping(
            raw,
            transcript=transcript,
            revealed=self._revealed_from_transcript(transcript),
        )
        # A queued instruction waits while a tool call is still open: it
        # would otherwise land between the call and its result.
        open_tool = bool(state.pending_tool_calls) and state.has_pending_tool
        if state.pending_instruction is not None and not open_tool:
            state = self._apply_pending_command(input, state, state.pending_instruction)
            state = replace(
                state,
                pending_instruction=None,
                terminal_pending=False,
                transcript_digest=self._digest(state.transcript),
                empty_retry_count=0,
            )
        return _sync_active_children(state, state.active_children)

    def _apply_pending_command(
        self, input: LoopInput, state: AgentLoopState, text: str
    ) -> AgentLoopState:
        from neos.coding.commands.interpret import interpret_coding_command
        from neos.coding.commands.types import CommandDisposition

        decision = interpret_coding_command(text)
        if decision.disposition is CommandDisposition.CHAT:
            return _note(state, text)
        if decision.disposition is CommandDisposition.INJECT:
            return _note(state, decision.inject_text)
        spec_name = decision.spec.name if decision.spec is not None else ""
        handler = _PENDING_COMMANDS.get(spec_name)
        if handler is not None:
            return handler(self, input, state, decision)
        return _note(state, decision.message or "Command was not applied as user work.")

    def _cleared_transcript(self, input: LoopInput, transcript=()):
        seed = self._task_seed_text(transcript, input)
        messages: list[CanonicalMessage] = []
        if seed:
            messages.append(CanonicalMessage("user", (TextContent(seed),)))
        messages.append(CanonicalMessage("user", (TextContent(_CLEARED_NOTICE),)))
        return tuple(messages)

    @staticmethod
    def _task_seed_text(transcript, input: LoopInput) -> str:
        for message in transcript or ():
            if getattr(message, "role", None) != "user":
                continue
            for item in getattr(message, "content", ()):
                text = getattr(item, "text", None)
                if not isinstance(text, str):
                    continue
                candidate = text.strip()
                if CheckpointMixin._is_task_seed(candidate):
                    return candidate
        fallback = (input.instruction or "").strip()
        if CheckpointMixin._is_task_seed(fallback):
            return fallback
        return ""

    @staticmethod
    def _is_task_seed(text: str) -> bool:
        from neos.coding.commands.interpret import interpret_coding_command
        from neos.coding.commands.types import CommandDisposition

        if not text or text == _CLEARED_NOTICE:
            return False
        return (
            interpret_coding_command(text).disposition is CommandDisposition.CHAT
        )

    @staticmethod
    def _with_workspace_edits(transcript, edits):
        if not edits:
            return transcript
        summary = ", ".join(
            f"{edit.path} @ revision {edit.resulting_revision}"
            for edit in edits
        )
        return _append_user_text(
            transcript,
            "The user directly edited these workspace files. "
            "Treat the listed revisions as authoritative and read "
            f"files before changing them: {summary}",
        )

    def _dump_state(self, input, state):
        state = _sync_active_children(state, state.active_children)
        current = (input.instruction or "").strip()
        if not self._is_task_seed(current):
            current = self._task_seed_text(state.transcript, input) or current
        return _dump_loop_state(state, current_instruction=current)

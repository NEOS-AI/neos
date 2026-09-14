"""Checkpoint restore, pending commands, and state serialization for the durable loop."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import asdict, replace

from neos.coding.loop.base import LoopInput
from neos.coding.model.base import (
    CanonicalMessage,
    TextContent,
    ToolCallCompleted,
    ToolResultContent,
)
from neos.coding.phases import (
    parse_phase,
    restore_plan_critical_files,
    restore_verify_verdict,
)
from neos.coding.sandbox.paths import normalize_workspace_path
from neos.coding.loop._durable.state import (
    AgentLoopState,
    _AppliedPendingCommand,
)
from neos.coding.loop._durable.support import (
    _dump_read_stamp,
    _message_from_mapping,
    _message_to_mapping,
    _nonneg_int,
    _optional_str,
    _read_paths_from_transcript,
    _read_stamps_mapping,
    _restore_active_children,
    _string_mapping,
    _tool_result_ids,
    _warn_stale_active_child_scalars,
)

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
        remaining = state.pending_tool_calls[state.pending_tool_index :]
        existing = _tool_result_ids(state.transcript)
        pending = [
            call for call in remaining if call.tool_call_id not in existing
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
        after = self._drain_completed_prefix(after)
        await deps.repository.commit_model_checkpoint(
            lease=deps.lease,
            event_type="tool.completed" if pending else "model.completed",
            event_payload={"reason_code": "aborted"},
            loop_state=self._dump_state(input, after),
            workspace_revision=str(bound.binding.workspace_revision),
            now=self._clock(),
        )

    def _restore(self, input, checkpoint):
        if checkpoint is None:
            transcript = (CanonicalMessage("user", (TextContent(input.instruction),)),)
            transcript = self._with_workspace_edits(
                transcript,
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
        pending_index = int(raw.get("pending_tool_index", 0))
        has_open_tool_pair = bool(pending) and pending_index < len(pending)
        empty_retry_count = int(raw.get("empty_retry_count", 0))
        bodies = dict(_string_mapping(raw.get("compacted_bodies")))
        instructions_loaded = bool(raw.get("instructions_loaded", False))
        raw_todos = raw.get("todos") or ()
        todos = tuple(
            dict(item) for item in raw_todos if isinstance(item, Mapping)
        )
        pre_revealed = self._revealed_from_transcript(transcript)
        if isinstance(pending_instruction, str) and pending_instruction:
            if not has_open_tool_pair:
                applied = self._apply_pending_command(
                    input,
                    transcript,
                    pending_instruction,
                    bodies=bodies,
                    todos=todos,
                    instructions_loaded=instructions_loaded,
                    cost_micros=int(raw.get("cost_micros", 0)),
                    input_tokens=int(raw.get("input_tokens", 0)),
                    output_tokens=int(raw.get("output_tokens", 0)),
                    cache_read_tokens=_nonneg_int(raw.get("cache_read_tokens")),
                    cache_write_tokens=_nonneg_int(raw.get("cache_write_tokens")),
                    reasoning_tokens=_nonneg_int(raw.get("reasoning_tokens")),
                )
                transcript = applied.transcript
                bodies = applied.bodies
                todos = applied.todos
                instructions_loaded = applied.instructions_loaded
                pending_instruction = None
                terminal_pending = False
                digest = self._digest(transcript)
                empty_retry_count = 0
        else:
            pending_instruction = None
        children = _restore_active_children(raw)
        _warn_stale_active_child_scalars(raw, children)
        state = AgentLoopState(
            transcript=transcript,
            turn_count=int(raw.get("turn_count", 0)),
            tool_count=int(raw.get("tool_count", 0)),
            consecutive_tool_errors=int(raw.get("consecutive_tool_errors", 0)),
            pending_tool_calls=pending,
            pending_tool_index=pending_index,
            transcript_digest=digest,
            input_tokens=int(raw.get("input_tokens", 0)),
            output_tokens=int(raw.get("output_tokens", 0)),
            cache_read_tokens=_nonneg_int(raw.get("cache_read_tokens")),
            cache_write_tokens=_nonneg_int(raw.get("cache_write_tokens")),
            reasoning_tokens=_nonneg_int(raw.get("reasoning_tokens")),
            last_prompt_tokens=_nonneg_int(raw.get("last_prompt_tokens")),
            cost_micros=int(raw.get("cost_micros", 0)),
            terminal_pending=terminal_pending,
            read_paths=read_paths,
            pending_instruction=pending_instruction,
            todos=todos,
            phase=parse_phase(raw.get("phase")).value,
            instructions_loaded=instructions_loaded,
            prompt_compact_retries=int(raw.get("prompt_compact_retries", 0)),
            output_token_escalations=int(raw.get("output_token_escalations", 0)),
            llm_compact_attempts=int(raw.get("llm_compact_attempts", 0)),
            summary=str(raw.get("summary") or ""),
            revealed_tools=frozenset(str(name) for name in raw.get("revealed_tools") or ())
            | pre_revealed,
            allowed_tools=frozenset(str(name) for name in raw.get("allowed_tools") or ()),
            approved_always=frozenset(
                str(name) for name in raw.get("approved_always") or ()
            ),
            hook_retry_count=int(raw.get("hook_retry_count", 0)),
            compacted_bodies=bodies,
            stop_retry_count=int(raw.get("stop_retry_count", 0)),
            read_stamps=_read_stamps_mapping(raw.get("read_stamps")),
            empty_retry_count=empty_retry_count,
            last_error_signature=str(raw.get("last_error_signature") or ""),
            last_error_count=int(raw.get("last_error_count", 0)),
            last_success_signature=str(raw.get("last_success_signature") or ""),
            last_success_result_hash=str(raw.get("last_success_result_hash") or ""),
            last_success_count=int(raw.get("last_success_count", 0)),
            verdict=restore_verify_verdict(raw.get("verdict")),
            critical_files=restore_plan_critical_files(raw.get("critical_files")),
            active_child_run_id=_optional_str(raw.get("active_child_run_id")),
            active_child_checkpoint_id=_optional_str(
                raw.get("active_child_checkpoint_id")
            ),
            active_child_tool_call_id=_optional_str(
                raw.get("active_child_tool_call_id")
            ),
            active_children=children,
        )
        return self._sync_active_children(state, children)

    def _apply_pending_command(
        self,
        input: LoopInput,
        transcript,
        text: str,
        *,
        bodies: dict[str, str],
        todos: tuple,
        instructions_loaded: bool,
        cost_micros: int,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        reasoning_tokens: int = 0,
    ):
        from neos.coding.commands.interpret import interpret_coding_command
        from neos.coding.commands.parse import sanitize_command_args
        from neos.coding.commands.types import CommandDisposition

        decision = interpret_coding_command(text)
        if decision.disposition is CommandDisposition.CHAT:
            return _AppliedPendingCommand(
                self._append_user_meta(transcript, text),
                bodies,
                todos,
                instructions_loaded,
            )
        if decision.disposition is CommandDisposition.INJECT:
            return _AppliedPendingCommand(
                self._append_user_meta(transcript, decision.inject_text),
                bodies,
                todos,
                instructions_loaded,
            )
        spec_name = decision.spec.name if decision.spec is not None else ""
        if spec_name == "compact":
            after = self._compact(transcript, force=True, bodies=bodies)
            hint = sanitize_command_args(decision.parsed.args, max_len=240)
            notice = (
                f"Transcript compacted by /compact. Keep: {hint}"
                if hint
                else "Transcript compacted by /compact."
            )
            return _AppliedPendingCommand(
                self._append_user_meta(after, notice),
                bodies,
                todos,
                False,
            )
        if spec_name == "clear":
            return _AppliedPendingCommand(
                self._cleared_transcript(input, transcript),
                {},
                (),
                False,
            )
        if spec_name == "cost":
            from neos.coding.commands.service import format_cost_parts

            notice = " ".join(
                format_cost_parts(
                    {
                        "cost_micros": cost_micros,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cache_read_tokens": cache_read_tokens,
                        "cache_write_tokens": cache_write_tokens,
                        "reasoning_tokens": reasoning_tokens,
                    }
                )
            )
            return _AppliedPendingCommand(
                self._append_user_meta(transcript, notice),
                bodies,
                todos,
                instructions_loaded,
            )
        notice = decision.message or "Command was not applied as user work."
        return _AppliedPendingCommand(
            self._append_user_meta(transcript, notice),
            bodies,
            todos,
            instructions_loaded,
        )

    def _cleared_transcript(self, input: LoopInput, transcript=()):
        seed = self._task_seed_text(transcript, input)
        messages: list[CanonicalMessage] = []
        if seed:
            messages.append(CanonicalMessage("user", (TextContent(seed),)))
        messages.append(
            CanonicalMessage(
                "user",
                (TextContent("Conversation context was cleared."),),
            )
        )
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

        if not text or text == "Conversation context was cleared.":
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
        state = self._sync_active_children(state, state.active_children)
        current = (input.instruction or "").strip()
        if not self._is_task_seed(current):
            current = self._task_seed_text(state.transcript, input) or current
        return {
            "phase_index": state.tool_count - 1,
            "current_instruction": current,
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
            "cache_read_tokens": state.cache_read_tokens,
            "cache_write_tokens": state.cache_write_tokens,
            "reasoning_tokens": state.reasoning_tokens,
            "last_prompt_tokens": state.last_prompt_tokens,
            "cost_micros": state.cost_micros,
            "terminal_pending": state.terminal_pending,
            "read_paths": sorted(state.read_paths),
            "phase": state.phase,
            "instructions_loaded": state.instructions_loaded,
            "prompt_compact_retries": state.prompt_compact_retries,
            "output_token_escalations": state.output_token_escalations,
            "llm_compact_attempts": state.llm_compact_attempts,
            "summary": state.summary,
            "revealed_tools": sorted(state.revealed_tools),
            "allowed_tools": sorted(state.allowed_tools),
            "approved_always": sorted(state.approved_always),
            "hook_retry_count": state.hook_retry_count,
            "compacted_bodies": dict(state.compacted_bodies),
            "stop_retry_count": state.stop_retry_count,
            "empty_retry_count": state.empty_retry_count,
            "last_error_signature": state.last_error_signature,
            "last_error_count": state.last_error_count,
            "last_success_signature": state.last_success_signature,
            "last_success_result_hash": state.last_success_result_hash,
            "last_success_count": state.last_success_count,
            "verdict": state.verdict,
            "critical_files": list(state.critical_files),
            "active_child_run_id": state.active_child_run_id,
            "active_child_checkpoint_id": state.active_child_checkpoint_id,
            "active_child_tool_call_id": state.active_child_tool_call_id,
            "active_children": [
                {
                    "run_id": child.run_id,
                    "checkpoint_id": child.checkpoint_id,
                    "tool_call_id": child.tool_call_id,
                    "last_advanced_at": child.last_advanced_at,
                    "rolled_input_tokens": child.rolled_input_tokens,
                    "rolled_output_tokens": child.rolled_output_tokens,
                    "pending_steer": child.pending_steer,
                    "spec": child.spec,
                    "spawn_depth": child.spawn_depth,
                    "worktree_repo": child.worktree_repo,
                    "worktree_path": child.worktree_path,
                    "worktree_branch": child.worktree_branch,
                    "worktree_base_sha": child.worktree_base_sha,
                }
                for child in state.active_children
            ],
            "read_stamps": {
                path: _dump_read_stamp(stamp)
                for path, stamp in sorted(state.read_stamps.items())
            },
        }

    @staticmethod
    def _with_terminal_pending(state: AgentLoopState) -> AgentLoopState:
        return replace(state, terminal_pending=True)

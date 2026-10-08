"""The two state transitions every step ends in: a model turn, a tool result.

`_completed_turn` folds an assistant turn into the transcript and charges its
usage. `_after_result` folds one tool result in, updates the error and stall
counters, and applies the tool's own effect on loop state -- see
`_OK_EFFECTS`, which is where a tool that changes loop state registers.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from neos.coding.model.base import (
    CanonicalMessage,
    TextContent,
    ThinkingContent,
    ToolResultContent,
    ToolUseContent,
)
from neos.coding.phases import parse_phase
from neos.coding.sandbox.paths import normalize_workspace_path
from neos.coding.loop._durable import artifact_refs
from neos.coding.loop._durable.codec import _transcript_digest
from neos.coding.loop._durable.signatures import _stall_fields
from neos.coding.loop._durable.state import AgentLoopState
from neos.coding.loop._durable.tool_catalog import _entry_names
from neos.coding.loop._durable.tool_results import _executor_read_stamps
from neos.coding.loop._durable.transcript import (
    _is_empty_or_think_only,
    _scrub_think_blocks,
    _uniquify_tool_calls,
)
from neos.coding.loop._durable.usage import with_turn_usage

#: (loop, state, tool_input, result) -> fields for `replace(state, ...)`.
ToolEffect = Callable[[Any, AgentLoopState, Mapping[str, object], ToolResultContent], dict]


def _track_read_path(loop, state, tool_input, result) -> dict:
    raw_path = tool_input.get("path")
    if not raw_path:
        return {}
    path = str(normalize_workspace_path(str(raw_path)))
    return {"read_paths": state.read_paths | {path}}


def _refresh_read_stamps(loop, state, tool_input, result) -> dict:
    stamps = dict(state.read_stamps)
    stamps.update(_executor_read_stamps(loop._executor))
    return {"read_stamps": stamps}


def _record_todos(loop, state, tool_input, result) -> dict:
    raw_todos = tool_input.get("todos")
    if not isinstance(raw_todos, (list, tuple)):
        return {}
    return {
        "todos": tuple(dict(item) for item in raw_todos if isinstance(item, Mapping))
    }


def _enter_phase(loop, state, tool_input, result) -> dict:
    return {"phase": parse_phase(tool_input.get("phase")).value}


def _reveal_tools(loop, state, tool_input, result) -> dict:
    return {"revealed_tools": state.revealed_tools | _entry_names(result.content)}


def _allow_skill_tools(loop, state, tool_input, result) -> dict:
    return {
        "allowed_tools": loop._catalog.union_skill_allowed_tools(
            state.allowed_tools, result.content
        )
    }


#: What a successful call of each tool does to loop state, beyond the
#: transcript. Effects of one tool are independent of each other.
_OK_EFFECTS: dict[str, tuple[ToolEffect, ...]] = {
    "read_file.v1": (_track_read_path, _refresh_read_stamps),
    "write_file.v1": (_refresh_read_stamps,),
    "edit_file.v1": (_refresh_read_stamps,),
    "todo_write.v1": (_record_todos,),
    "set_phase.v1": (_enter_phase,),
    "search_tools.v1": (_reveal_tools,),
    "load_skill.v1": (_allow_skill_tools,),
}


def _assistant_content(text: str, calls, thinking) -> list:
    content: list = []
    if text:
        content.append(TextContent(text))
    content.extend(
        ToolUseContent(c.tool_call_id, c.name, dict(c.input)) for c in calls
    )
    if not content:
        # A thinking-only turn is not appended: it is the empty turn the
        # retry path handles.
        return content
    # Thinking leads the turn, in stream order.
    return [
        ThinkingContent(block.thinking, block.signature) for block in thinking
    ] + content


class TurnTransitionsMixin:
    def _with_transcript(self, state: AgentLoopState, transcript, **changes):
        """Set the transcript and its digest together -- never one alone."""
        return replace(
            state,
            transcript=transcript,
            transcript_digest=_transcript_digest(transcript),
            **changes,
        )

    def _with_note(self, state: AgentLoopState, text: str, **changes):
        """Append a user-role note from the loop itself."""
        return self._with_transcript(
            state,
            tuple(state.transcript) + (CanonicalMessage("user", (TextContent(text),)),),
            **changes,
        )

    def _with_hook_retry(self, state: AgentLoopState, validated, reason: str):
        del validated, reason
        return replace(
            state,
            hook_retry_count=state.hook_retry_count + 1,
            terminal_pending=False,
        )

    async def _completed_turn(self, state, text_parts, calls, completion, thinking=()):
        text = _scrub_think_blocks("".join(text_parts))
        calls = _uniquify_tool_calls(calls)
        content = _assistant_content(text, calls, thinking)
        transcript = state.transcript
        if content:
            transcript += (CanonicalMessage("assistant", tuple(content)),)
        bodies = dict(state.compacted_bodies)
        before_compact = transcript
        transcript = await self._compactor.compact_with_hook(
            transcript, preserve_tools=bool(calls), bodies=bodies
        )
        revealed = state.revealed_tools | self._catalog.revealed_from(
            before_compact
        )
        # Catches a reveal re-derived from the transcript, which is what a
        # resume does. Announcing only the delta keeps this from repeating
        # what the tool-result path already announced.
        transcript = self._catalog.announce_reveals(
            transcript, state.revealed_tools, revealed
        )
        reset_empty = bool(calls) or not _is_empty_or_think_only(text)
        return self._with_transcript(
            with_turn_usage(self._config, state, completion),
            transcript,
            turn_count=state.turn_count + 1,
            pending_tool_calls=tuple(calls),
            pending_tool_index=0,
            terminal_pending=False,
            compacted_bodies=bodies,
            revealed_tools=revealed,
            empty_retry_count=0 if reset_empty else state.empty_retry_count,
        )

    async def _after_result(
        self,
        state,
        result,
        *,
        tool_name: str,
        tool_input: Mapping[str, object],
        advance_index: bool = True,
    ):
        has_more_tools = state.pending_tool_index + 1 < len(state.pending_tool_calls)
        bodies = dict(state.compacted_bodies)
        transcript = artifact_refs._maybe_ref_latest_tool_result(
            state.transcript + (CanonicalMessage("tool", (result,)),),
            tool_name=tool_name,
            bodies=bodies,
        )
        transcript = await self._compactor.compact_with_hook(
            transcript,
            preserve_tools=has_more_tools,
            bodies=bodies,
        )
        reason = ""
        if isinstance(result.content, Mapping):
            reason = str(result.content.get("reason_code") or "")
        if result.status == "ok":
            errors = 0
        elif reason == "tool_outcome_unknown":
            # Not the model's error: the call may well have worked.
            errors = state.consecutive_tool_errors
        else:
            errors = state.consecutive_tool_errors + 1
        effects: dict[str, object] = {"read_stamps": dict(state.read_stamps)}
        if result.status == "ok":
            for effect in _OK_EFFECTS.get(tool_name, ()):
                effects.update(effect(self, state, tool_input, result))
        # The primary path: the search result that revealed the tool has
        # just been appended, so the announcement follows it directly.
        transcript = self._catalog.announce_reveals(
            transcript,
            state.revealed_tools,
            effects.get("revealed_tools", state.revealed_tools),
        )
        return self._with_transcript(
            state,
            transcript,
            tool_count=state.tool_count + 1,
            consecutive_tool_errors=errors,
            pending_tool_index=state.pending_tool_index + (1 if advance_index else 0),
            terminal_pending=False,
            hook_retry_count=0,
            compacted_bodies=bodies,
            **_stall_fields(state, tool_name, tool_input, result, reason),
            **effects,
        )

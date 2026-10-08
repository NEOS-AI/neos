"""A run's first state and its stored form, seen from outside the loop.

`loop_state` is a persisted format: it is stored on every model and tool step
and resumed across deploys. These three functions are its public seam -- the
loop delegates to them, so callers that build or read a state go through the
same code a run does.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from neos.coding.loop.base import LoopInput
from neos.coding.loop._durable.children import _sync_active_children
from neos.coding.loop._durable.codec import (
    _dump_loop_state,
    _message_from_mapping,
    _state_from_mapping,
    _transcript_digest,
)
from neos.coding.loop._durable.state import AgentLoopState
from neos.coding.loop._durable.transcript import _append_user_text
from neos.coding.model.base import CanonicalMessage, TextContent

if TYPE_CHECKING:
    from neos.coding.domain.phases import CodingCheckpoint
    from neos.coding.loop._durable.compaction import Compactor
    from neos.coding.loop._durable.tool_catalog import ToolCatalog

__all__ = ["encode_state", "initial_state", "restore_state"]

_CLEARED_NOTICE = "Conversation context was cleared."


def initial_state(input: LoopInput) -> AgentLoopState:
    """The state a run starts from when it has no checkpoint."""
    transcript = _with_workspace_edits(
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
        transcript_digest=_transcript_digest(transcript),
    )


def encode_state(input: LoopInput, state: AgentLoopState) -> dict[str, Any]:
    """`state` as the `loop_state` mapping a checkpoint stores."""
    state = _sync_active_children(state, state.active_children)
    current = (input.instruction or "").strip()
    if not _is_task_seed(current):
        current = _task_seed_text(state.transcript, input) or current
    return _dump_loop_state(state, current_instruction=current)


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


def _task_seed_text(transcript, input: LoopInput) -> str:
    for message in transcript or ():
        if getattr(message, "role", None) != "user":
            continue
        for item in getattr(message, "content", ()):
            text = getattr(item, "text", None)
            if not isinstance(text, str):
                continue
            candidate = text.strip()
            if _is_task_seed(candidate):
                return candidate
    fallback = (input.instruction or "").strip()
    if _is_task_seed(fallback):
        return fallback
    return ""


def _is_task_seed(text: str) -> bool:
    from neos.coding.commands.interpret import interpret_coding_command
    from neos.coding.commands.types import CommandDisposition

    if not text or text == _CLEARED_NOTICE:
        return False
    return (
        interpret_coding_command(text).disposition is CommandDisposition.CHAT
    )


def restore_state(
    input: LoopInput,
    checkpoint: CodingCheckpoint,
    *,
    catalog: ToolCatalog,
    compactor: Compactor,
) -> AgentLoopState:
    """The state a run resumes into from a stored `checkpoint`."""
    raw = checkpoint.loop_state
    transcript = _with_workspace_edits(
        tuple(_message_from_mapping(item) for item in raw.get("transcript", [])),
        input.workspace_edits,
    )
    state = _state_from_mapping(
        raw,
        transcript=transcript,
        revealed=catalog.revealed_from(transcript),
    )
    # A queued instruction waits while a tool call is still open: it
    # would otherwise land between the call and its result.
    open_tool = bool(state.pending_tool_calls) and state.has_pending_tool
    if state.pending_instruction is not None and not open_tool:
        state = _apply_pending_command(
            input, state, state.pending_instruction, compactor=compactor
        )
        state = replace(
            state,
            pending_instruction=None,
            terminal_pending=False,
            transcript_digest=_transcript_digest(state.transcript),
            empty_retry_count=0,
        )
    return _sync_active_children(state, state.active_children)


def _note(state: AgentLoopState, text: str) -> AgentLoopState:
    return replace(state, transcript=_append_user_text(state.transcript, text))


def _compact_command(compactor, input, state: AgentLoopState, decision) -> AgentLoopState:
    from neos.coding.commands.parse import sanitize_command_args

    bodies = dict(state.compacted_bodies)
    after = compactor.compact(state.transcript, force=True, bodies=bodies)
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


def _clear_command(compactor, input, state: AgentLoopState, decision) -> AgentLoopState:
    return replace(
        state,
        transcript=_cleared_transcript(input, state.transcript),
        compacted_bodies={},
        todos=(),
        instructions_loaded=False,
    )


def _cost_command(compactor, input, state: AgentLoopState, decision) -> AgentLoopState:
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


def _apply_pending_command(
    input: LoopInput, state: AgentLoopState, text: str, *, compactor: Compactor
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
        return handler(compactor, input, state, decision)
    return _note(state, decision.message or "Command was not applied as user work.")


def _cleared_transcript(input: LoopInput, transcript=()):
    seed = _task_seed_text(transcript, input)
    messages: list[CanonicalMessage] = []
    if seed:
        messages.append(CanonicalMessage("user", (TextContent(seed),)))
    messages.append(CanonicalMessage("user", (TextContent(_CLEARED_NOTICE),)))
    return tuple(messages)

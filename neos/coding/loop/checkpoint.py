"""A run's first state and its stored form, seen from outside the loop.

`loop_state` is a persisted format: it is stored on every model and tool step
and resumed across deploys. These two functions are its public seam -- the
loop delegates to them, so callers that build or read a state go through the
same code a run does. What a *restore* does with a stored state (apply edits,
run a queued command) still belongs to the loop.
"""

from __future__ import annotations

from typing import Any

from neos.coding.loop.base import LoopInput
from neos.coding.loop._durable.children import _sync_active_children
from neos.coding.loop._durable.codec import _dump_loop_state, _transcript_digest
from neos.coding.loop._durable.state import AgentLoopState
from neos.coding.loop._durable.transcript import _append_user_text
from neos.coding.model.base import CanonicalMessage, TextContent

__all__ = ["encode_state", "initial_state"]

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

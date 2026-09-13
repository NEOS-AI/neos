"""User-visible halt / cancel / drop codes. Do not collapse cancel to failed."""

from __future__ import annotations

from enum import StrEnum

_HALT_STATUSES = frozenset({"paused", "pausing"})
_CANCEL_STATUSES = frozenset({"cancelled", "cancelling"})


class ChannelOutcome(StrEnum):
    HALT = "halt"
    CANCEL = "cancel"
    DROP = "drop"
    PARK = "park"
    FAILED = "failed"


def channel_reply(code: ChannelOutcome | str, message: str) -> str:
    return f"{code}: {message}"


def format_coding_status_reply(task_id: str, status: str) -> str:
    state = (status or "").strip()
    if state in _HALT_STATUSES:
        return channel_reply(ChannelOutcome.HALT, f"{task_id} {state}")
    if state in _CANCEL_STATUSES:
        return channel_reply(ChannelOutcome.CANCEL, f"{task_id} {state}")
    return f"{task_id} {state}"


def annotate_status_reply(text: str) -> str:
    """Prefix halt/cancel when a port returns `{task_id} {status}`."""
    stripped = (text or "").strip()
    if stripped.startswith(("halt:", "cancel:", "drop:", "park:")):
        return stripped
    parts = stripped.split()
    if len(parts) < 2:
        return stripped
    task_id, state = parts[0], parts[1]
    if state in _HALT_STATUSES or state in _CANCEL_STATUSES:
        return format_coding_status_reply(task_id, state)
    return stripped

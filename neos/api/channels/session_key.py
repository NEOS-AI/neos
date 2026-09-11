"""Versioned channel session keys (Phase 3)."""

from __future__ import annotations


def build_session_key(
    channel: str,
    scope: str | None,
    chat: str,
    thread: str | None = None,
) -> str:
    return "v2:{channel}:{scope}:{chat}:{thread}".format(
        channel=_part(channel, "unknown"),
        scope=_part(scope, "dm"),
        chat=_part(chat, "unknown"),
        thread=_part(thread, "-"),
    )


def session_key_is_thread(session_id: str) -> bool:
    """True when the v2 key names a real thread, not the parent-room '-' slot."""
    parts = (session_id or "").split(":")
    if len(parts) < 5 or parts[0] != "v2":
        return False
    return parts[-1] not in {"", "-"}


def _part(value: str | None, default: str) -> str:
    text = (value or "").strip()
    if not text:
        return default
    return text.replace(":", "_")

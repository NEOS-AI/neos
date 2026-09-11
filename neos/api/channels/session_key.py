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


def _part(value: str | None, default: str) -> str:
    text = (value or "").strip()
    if not text:
        return default
    return text.replace(":", "_")

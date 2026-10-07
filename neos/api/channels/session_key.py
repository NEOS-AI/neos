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


def session_key_destination(session_id: str) -> tuple[str, str] | None:
    """`(channel_type, chat)` read back from a v2 key -- the DM address an agent asks at
    (track Q9b, decision Q-E). `None` for anything that is not a v2 key.

    The thread slot is ignored on purpose: questions go to the DM top level. `_part`
    replaced `:` with `_` when the key was built, so a chat id that contained `:` would
    read back wrong; Slack, Discord and Telegram ids do not contain one.
    """
    parts = (session_id or "").split(":")
    if len(parts) != 5 or parts[0] != "v2":
        return None
    channel, chat = parts[1], parts[3]
    if not channel or not chat or chat == "unknown":
        return None
    return channel, chat

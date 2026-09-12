"""Parse channel slash/bang commands after mention stripping."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

_LEADING_MENTION = re.compile(
    r"^(?:<@!?[A-Za-z0-9_]+(?:\|[^>]+)?>|@[\w]+)\s+",
    re.UNICODE,
)
_NEWLINES = frozenset("\n\r\v\f\u0085\u2028\u2029")
_DISPLAY_NAME_KEYS = (
    "slack_user_name",
    "discord_user_name",
    "telegram_user_name",
    "discord_username",
    "telegram_username",
    "display_name",
)


class ChannelCommandKind(StrEnum):
    CHAT = "chat"
    CODE = "code"
    STOP = "stop"
    STATUS = "status"
    APPROVE = "approve"
    DENY = "deny"
    LEARN = "learn"
    NEW = "new"
    COMPACT = "compact"
    CLEAR = "clear"
    COST = "cost"
    EXPORT = "export"


def neutralize_untrusted_inline(text: str, max_len: int = 240) -> str:
    """Strip controls/bidi, flatten newlines to spaces, then cap length."""
    if text is None:
        return ""
    chars: list[str] = []
    for ch in str(text):
        if ch in _NEWLINES:
            chars.append(" ")
            continue
        if unicodedata.category(ch) in {"Cc", "Cf"}:
            continue
        if ch in "[]":
            chars.append(" ")
            continue
        chars.append(ch)
    cleaned = " ".join("".join(chars).split())
    if max_len <= 0:
        return ""
    return cleaned[:max_len]


def display_name_from_metadata(
    metadata: dict | None, channel_type: str = ""
) -> str:
    meta = metadata or {}
    keys: list[str] = []
    if channel_type:
        keys.append(f"{channel_type}_user_name")
        keys.append(f"{channel_type}_username")
    keys.extend(_DISPLAY_NAME_KEYS)
    seen: set[str] = set()
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        value = meta.get(key)
        if value:
            return str(value)
    return ""


def sender_prefix(platform_user_id: str, display_name: str = "") -> str:
    """`[name | id]` when a display name exists, otherwise `[id]`. Never mint mentions."""
    pid = neutralize_untrusted_inline(platform_user_id)
    name = neutralize_untrusted_inline(display_name)
    if name and pid:
        return f"[{name} | {pid}]"
    if pid:
        return f"[{pid}]"
    if name:
        return f"[{name}]"
    return ""


@dataclass(frozen=True, slots=True)
class ChannelCommand:
    kind: ChannelCommandKind
    rest: str


def strip_leading_mentions(text: str) -> str:
    remaining = text.lstrip()
    while True:
        updated = _LEADING_MENTION.sub("", remaining, count=1)
        if updated == remaining:
            return remaining.strip()
        remaining = updated


def parse_channel_command(text: str) -> ChannelCommand:
    stripped = strip_leading_mentions(text)
    if not stripped:
        return ChannelCommand(ChannelCommandKind.CHAT, "")
    head, _, tail = stripped.partition(" ")
    token = head.lower()
    if token.startswith("/") and "@" in token:
        token = token.split("@", 1)[0]
    rest = tail.strip()
    mapping = {
        "/code": ChannelCommandKind.CODE,
        "!code": ChannelCommandKind.CODE,
        "/stop": ChannelCommandKind.STOP,
        "!stop": ChannelCommandKind.STOP,
        "/status": ChannelCommandKind.STATUS,
        "!status": ChannelCommandKind.STATUS,
        "/approve": ChannelCommandKind.APPROVE,
        "!approve": ChannelCommandKind.APPROVE,
        "/deny": ChannelCommandKind.DENY,
        "!deny": ChannelCommandKind.DENY,
        "/learn": ChannelCommandKind.LEARN,
        "!learn": ChannelCommandKind.LEARN,
        "/new": ChannelCommandKind.NEW,
        "/reset": ChannelCommandKind.NEW,
        "!new": ChannelCommandKind.NEW,
        "!reset": ChannelCommandKind.NEW,
        "/compact": ChannelCommandKind.COMPACT,
        "!compact": ChannelCommandKind.COMPACT,
        "/clear": ChannelCommandKind.CLEAR,
        "!clear": ChannelCommandKind.CLEAR,
        "/cost": ChannelCommandKind.COST,
        "!cost": ChannelCommandKind.COST,
        "/export": ChannelCommandKind.EXPORT,
        "!export": ChannelCommandKind.EXPORT,
    }
    kind = mapping.get(token)
    if kind is None:
        return ChannelCommand(ChannelCommandKind.CHAT, stripped)
    return ChannelCommand(kind, rest)

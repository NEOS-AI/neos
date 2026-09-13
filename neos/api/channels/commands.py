"""Parse channel slash/bang commands after mention stripping."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from neos.coding.commands.interpret import interpret_coding_command
from neos.coding.commands.parse import sanitize_command_args, strip_leading_mentions
from neos.coding.commands.types import CommandDisposition

__all__ = (
    "ChannelCommand",
    "ChannelCommandKind",
    "display_name_from_metadata",
    "neutralize_untrusted_inline",
    "parse_channel_command",
    "sender_prefix",
    "strip_leading_mentions",
)

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
    HELP = "help"
    LOOP = "loop"
    PROMPT = "prompt"
    DIFF = "diff"
    UNKNOWN = "unknown"


def neutralize_untrusted_inline(text: str, max_len: int = 240) -> str:
    """Strip controls/bidi, flatten newlines to spaces, then cap length."""
    if text is None:
        return ""
    flattened = str(text).replace("[", " ").replace("]", " ")
    return sanitize_command_args(flattened, max_len=max_len)


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


_KIND_BY_NAME = {
    "code": ChannelCommandKind.CODE,
    "stop": ChannelCommandKind.STOP,
    "status": ChannelCommandKind.STATUS,
    "approve": ChannelCommandKind.APPROVE,
    "deny": ChannelCommandKind.DENY,
    "learn": ChannelCommandKind.LEARN,
    "new": ChannelCommandKind.NEW,
    "reset": ChannelCommandKind.NEW,
    "compact": ChannelCommandKind.COMPACT,
    "clear": ChannelCommandKind.CLEAR,
    "cost": ChannelCommandKind.COST,
    "export": ChannelCommandKind.EXPORT,
    "help": ChannelCommandKind.HELP,
    "loop": ChannelCommandKind.LOOP,
}


def parse_channel_command(text: str) -> ChannelCommand:
    decision = interpret_coding_command(text)
    parsed = decision.parsed
    if parsed.slash and parsed.name == "diff":
        return ChannelCommand(ChannelCommandKind.DIFF, parsed.args)
    if decision.disposition is CommandDisposition.CHAT:
        return ChannelCommand(ChannelCommandKind.CHAT, parsed.raw.strip())
    if decision.disposition is CommandDisposition.UNKNOWN:
        return ChannelCommand(ChannelCommandKind.UNKNOWN, parsed.args)
    if decision.disposition is CommandDisposition.INJECT:
        return ChannelCommand(ChannelCommandKind.PROMPT, parsed.args)
    spec = decision.spec
    name = spec.name if spec is not None else parsed.name
    kind = _KIND_BY_NAME.get(name)
    if kind is None and spec is not None and not spec.enabled:
        return ChannelCommand(ChannelCommandKind.LOOP, parsed.args)
    if kind is None:
        return ChannelCommand(ChannelCommandKind.UNKNOWN, parsed.args)
    return ChannelCommand(kind, parsed.args)

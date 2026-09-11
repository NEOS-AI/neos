"""Parse channel slash/bang commands after mention stripping."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

_LEADING_MENTION = re.compile(
    r"^(?:<@!?[A-Za-z0-9_]+(?:\|[^>]+)?>|@[\w]+)\s+",
    re.UNICODE,
)


class ChannelCommandKind(StrEnum):
    CHAT = "chat"
    CODE = "code"
    STOP = "stop"
    STATUS = "status"
    APPROVE = "approve"
    DENY = "deny"


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
    }
    kind = mapping.get(token)
    if kind is None:
        return ChannelCommand(ChannelCommandKind.CHAT, stripped)
    return ChannelCommand(kind, rest)

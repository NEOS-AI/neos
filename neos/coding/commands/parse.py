"""Pure slash-command tokenizer. No I/O, no settings."""

from __future__ import annotations

import re
import unicodedata

from neos.coding.commands.types import ParsedCommand

_NEWLINES = frozenset("\n\r\v\f\u0085\u2028\u2029")
_LEADING_MENTION = re.compile(
    r"^(?:<@!?[A-Za-z0-9_]+(?:\|[^>]+)?>|@[\w]+)\s+",
    re.UNICODE,
)


def strip_leading_mentions(text: str) -> str:
    remaining = (text or "").lstrip()
    while True:
        updated = _LEADING_MENTION.sub("", remaining, count=1)
        if updated == remaining:
            return remaining.strip()
        remaining = updated


def sanitize_command_args(text: str, *, max_len: int = 400) -> str:
    if text is None:
        return ""
    chars: list[str] = []
    for ch in str(text):
        if ch in _NEWLINES:
            chars.append(" ")
            continue
        if unicodedata.category(ch) in {"Cc", "Cf"}:
            continue
        chars.append(ch)
    cleaned = " ".join("".join(chars).split())
    if max_len <= 0:
        return ""
    return cleaned[:max_len]


def parse_slash_command(text: str) -> ParsedCommand:
    raw = text if isinstance(text, str) else ""
    stripped = strip_leading_mentions(raw)
    if not stripped:
        return ParsedCommand(name="", args="", raw=raw, token="", slash=False)
    head, _, tail = stripped.partition(" ")
    token = head.lower()
    if token.startswith("/") and "@" in token:
        token = token.split("@", 1)[0]
    slash = token.startswith("/") or token.startswith("!")
    name = token[1:] if slash else ""
    if not slash or not name:
        return ParsedCommand(
            name="", args="", raw=raw, token=token, slash=False
        )
    return ParsedCommand(
        name=name,
        args=tail.strip(),
        raw=raw,
        token=token,
        slash=True,
    )

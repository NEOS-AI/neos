"""Read-only queries over a transcript, and the edits that only append.

Anything that rewrites earlier messages lives in `artifact_refs` or
`compaction`, because those edits invalidate replayed thinking and the
thinking guard has to see them.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace

from neos.coding.model.base import (
    CanonicalMessage,
    TextContent,
    ToolCallCompleted,
    ToolResultContent,
    ToolUseContent,
)
from neos.coding.sandbox.paths import normalize_workspace_path

_THINK_CLOSED_RE = re.compile(
    r"<(think|thinking|reasoning)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_THINK_UNCLOSED_RE = re.compile(
    r"<(think|thinking|reasoning)\b[^>]*>.*\Z",
    re.IGNORECASE | re.DOTALL,
)


def _scrub_think_blocks(text: str) -> str:
    cleaned = _THINK_CLOSED_RE.sub("", text)
    return _THINK_UNCLOSED_RE.sub("", cleaned)


def _is_empty_or_think_only(text: str) -> bool:
    return not _scrub_think_blocks(text).strip()


def _append_user_text(
    transcript: Sequence[CanonicalMessage], text: str
) -> tuple[CanonicalMessage, ...]:
    return tuple(transcript) + (CanonicalMessage("user", (TextContent(text),)),)


def _has_open_tool_pair(transcript: Sequence[CanonicalMessage]) -> bool:
    for message in reversed(transcript):
        if message.role == "tool":
            return False
        if message.role == "assistant":
            return any(isinstance(item, ToolUseContent) for item in message.content)
        if message.role == "user":
            return False
    return False


def _last_tool_use_index(transcript: Sequence[CanonicalMessage]) -> int | None:
    """Index of the newest assistant message that calls a tool."""
    for index in range(len(transcript) - 1, -1, -1):
        message = transcript[index]
        if message.role == "assistant" and any(
            isinstance(item, ToolUseContent) for item in message.content
        ):
            return index
    return None


def _uniquify_tool_calls(
    calls: Sequence[ToolCallCompleted],
) -> list[ToolCallCompleted]:
    used: set[str] = set()
    uniquified: list[ToolCallCompleted] = []
    for call in calls:
        candidate = call.tool_call_id
        if candidate not in used:
            used.add(candidate)
            uniquified.append(call)
            continue
        suffix = 2
        while True:
            next_id = f"{call.tool_call_id}_d{suffix}"
            if next_id not in used:
                used.add(next_id)
                uniquified.append(replace(call, tool_call_id=next_id))
                break
            suffix += 1
    return uniquified


def _tool_use_names(messages: Sequence[CanonicalMessage]) -> dict[str, str]:
    names: dict[str, str] = {}
    for message in messages:
        for item in message.content:
            if isinstance(item, ToolUseContent):
                names[item.tool_call_id] = item.name
    return names


def _tool_result_ids(transcript) -> set[str]:
    return {
        item.tool_call_id
        for message in transcript
        for item in message.content
        if isinstance(item, ToolResultContent)
    }


def _successful_read_paths(
    transcript: Sequence[CanonicalMessage],
) -> list[str]:
    """Normalized paths of `read_file.v1` calls that returned ok, in order.

    A path read twice appears twice; callers decide whether order matters.
    """
    pending: dict[str, str] = {}
    paths: list[str] = []
    for message in transcript:
        for item in message.content:
            if isinstance(item, ToolUseContent) and item.name == "read_file.v1":
                raw_path = item.input.get("path")
                if raw_path:
                    pending[item.tool_call_id] = str(raw_path)
            elif isinstance(item, ToolResultContent) and item.status == "ok":
                raw_path = pending.get(item.tool_call_id)
                if raw_path:
                    paths.append(str(normalize_workspace_path(raw_path)))
    return paths


def _read_paths_from_transcript(
    transcript: tuple[CanonicalMessage, ...],
) -> frozenset[str]:
    return frozenset(_successful_read_paths(transcript))

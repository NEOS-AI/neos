"""Shrinking tool results to content-addressed refs, and expanding them back.

A shrunk result keeps a 200-char preview and a sha256; the full body goes
into `bodies` (persisted as `compacted_bodies`) under that digest. File
reads are never stored -- re-reading the file is the cheaper restore.

These edits rewrite earlier messages, so each one invalidates replayed
thinking; `_guard_thinking_prefix` on the loop is what notices.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from neos.coding.model.base import CanonicalMessage, ToolResultContent
from neos.coding.loop._durable.state import COMPACT_REF_THRESHOLD_BYTES
from neos.coding.loop._durable.tool_results import (
    _is_unchanged_stub,
    _looks_like_file_read,
    _tool_result_bytes,
    _unchanged_stub_content,
)


def _compact_ref_path(content: Mapping[str, object]) -> str | None:
    raw = content.get("path")
    if isinstance(raw, str) and raw:
        return raw
    entries = content.get("entries")
    if isinstance(entries, (list, tuple)):
        for entry in entries:
            if isinstance(entry, Mapping):
                path = entry.get("path")
                if isinstance(path, str) and path:
                    return path
    return None


def _ref_tool_result(
    item: ToolResultContent,
    bodies: dict[str, str],
    *,
    tool_name: str = "",
) -> ToolResultContent:
    payload = dict(item.content)
    payload_text = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
    preview_source = payload.get("preview")
    if not isinstance(preview_source, str) or not preview_source:
        preview_source = payload_text
    shrunk: dict[str, object] = {
        "compacted": True,
        "sha256": digest,
        "preview": preview_source[:200],
    }
    if _is_unchanged_stub(payload):
        shrunk["unchanged"] = True
    if tool_name != "read_file.v1":
        bodies[digest] = payload_text
    shrunk["path"] = _compact_ref_path(payload) or f"artifact://{digest}"
    return ToolResultContent(item.tool_call_id, item.status, shrunk)


def _replace_results(message: CanonicalMessage, rewrite) -> CanonicalMessage:
    """Apply `rewrite` to each tool result; `None` from it means keep as is."""
    content = []
    changed = False
    for item in message.content:
        replaced = rewrite(item) if isinstance(item, ToolResultContent) else None
        if replaced is None:
            content.append(item)
        else:
            content.append(replaced)
            changed = True
    if not changed:
        return message
    return CanonicalMessage(message.role, tuple(content))


def _maybe_ref_latest_tool_result(
    transcript: tuple[CanonicalMessage, ...],
    *,
    tool_name: str,
    bodies: dict[str, str],
) -> tuple[CanonicalMessage, ...]:
    """Shrink a just-appended oversized result before it is ever sent."""
    if not transcript or transcript[-1].role != "tool":
        return transcript

    def rewrite(item: ToolResultContent) -> ToolResultContent | None:
        if (
            item.content.get("compacted")
            or _is_unchanged_stub(item.content)
            or _tool_result_bytes(item.content) < COMPACT_REF_THRESHOLD_BYTES
        ):
            return None
        return _ref_tool_result(item, bodies, tool_name=tool_name)

    last = _replace_results(transcript[-1], rewrite)
    if last is transcript[-1]:
        return transcript
    return transcript[:-1] + (last,)


def _shrink_old_tool_results(
    message: CanonicalMessage,
    bodies: dict[str, str],
    tool_names: Mapping[str, str] | None = None,
) -> CanonicalMessage:
    names = tool_names or {}

    def rewrite(item: ToolResultContent) -> ToolResultContent | None:
        if item.content.get("compacted"):
            return None
        name = names.get(item.tool_call_id)
        if (
            name == "read_file.v1"
            or _is_unchanged_stub(item.content)
            or (name is None and _looks_like_file_read(item.content))
        ):
            return None
        return _ref_tool_result(item, bodies)

    return _replace_results(message, rewrite)


def _expand_artifact_refs(transcript, bodies: Mapping[str, str]):
    if not bodies:
        return transcript

    def rewrite(item: ToolResultContent) -> ToolResultContent | None:
        if not item.content.get("compacted") or _is_unchanged_stub(item.content):
            return None
        raw = bodies.get(str(item.content.get("sha256") or ""))
        if not raw:
            return None
        try:
            restored = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(restored, dict):
            return None
        payload = (
            _unchanged_stub_content(restored, item.content)
            if _is_unchanged_stub(restored)
            else restored
        )
        return ToolResultContent(item.tool_call_id, item.status, payload)

    return tuple(_replace_results(message, rewrite) for message in transcript)

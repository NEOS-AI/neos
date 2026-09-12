"""Redacted transcript export. Never returns raw loop_state."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from neos.coding.redact import redact_sensitive

_MAX_MESSAGES = 200
_MAX_TEXT = 800


def export_transcript(loop_state: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = loop_state if isinstance(loop_state, Mapping) else {}
    transcript = raw.get("transcript")
    if not isinstance(transcript, list):
        transcript = []
    messages: list[dict[str, Any]] = []
    for item in transcript[:_MAX_MESSAGES]:
        if not isinstance(item, Mapping):
            continue
        role = str(item.get("role") or "")
        content = item.get("content")
        exported_content: list[dict[str, Any]] = []
        if isinstance(content, list):
            for part in content:
                exported_content.append(_export_part(part))
        messages.append({"role": role, "content": exported_content})
    return {
        "messages": messages,
        "truncated": len(transcript) > _MAX_MESSAGES,
        "message_count": len(transcript),
    }


def _export_part(part: object) -> dict[str, Any]:
    if not isinstance(part, Mapping):
        return {"type": "unknown"}
    kind = str(part.get("type") or "")
    if kind == "text" or "text" in part:
        text = redact_sensitive(str(part.get("text") or ""))
        if isinstance(text, str) and len(text) > _MAX_TEXT:
            text = text[:_MAX_TEXT] + "…"
        return {"type": "text", "text": text}
    if kind == "tool_use" or "name" in part and "input" in part:
        return {
            "type": "tool_use",
            "name": str(part.get("name") or ""),
            "tool_call_id": str(part.get("tool_call_id") or ""),
        }
    if kind == "tool_result" or "status" in part:
        preview = ""
        content = part.get("content")
        if isinstance(content, Mapping):
            raw_preview = content.get("preview")
            if isinstance(raw_preview, str):
                preview = redact_sensitive(raw_preview)
                if isinstance(preview, str) and len(preview) > _MAX_TEXT:
                    preview = preview[:_MAX_TEXT] + "…"
        return {
            "type": "tool_result",
            "status": str(part.get("status") or ""),
            "tool_call_id": str(part.get("tool_call_id") or ""),
            "preview": preview,
        }
    return {"type": kind or "unknown"}

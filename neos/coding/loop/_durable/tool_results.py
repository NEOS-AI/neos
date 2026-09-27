"""Shapes of tool results: status normalization, event payloads, read stubs."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from neos.coding.redact import redact_sensitive
from neos.coding.loop._durable.codec import _read_stamps_mapping

_UNCHANGED_PREVIEW = "File unchanged since last read."
_LINE_NUMBERED_RE = re.compile(r"^\s*\d+\|", re.MULTILINE)
_KNOWN_STATUSES = frozenset({"ok", "error", "denied"})


def _transcript_status(result: Mapping[str, object]) -> str:
    """The status a tool result carries into the transcript.

    An unknown status reads as "ok" here -- the model sees the body anyway --
    but as "error" in `_outcome_status`, which feeds audit and metrics.
    """
    status = str(result.get("status", "ok"))
    return status if status in _KNOWN_STATUSES else "ok"


def _outcome_status(result: Mapping[str, object]) -> str:
    status = str(result.get("status", "ok"))
    return status if status in _KNOWN_STATUSES else "error"


def _is_unchanged_stub(content: Mapping[str, object]) -> bool:
    if content.get("unchanged") is True:
        return True
    preview = content.get("preview")
    return isinstance(preview, str) and preview.strip() == _UNCHANGED_PREVIEW


def _unchanged_stub_content(
    restored: Mapping[str, object],
    stub: Mapping[str, object],
) -> dict[str, object]:
    preview = restored.get("preview")
    if not isinstance(preview, str) or not preview.strip():
        preview = stub.get("preview")
    if not isinstance(preview, str) or not preview.strip():
        preview = _UNCHANGED_PREVIEW
    kept: dict[str, object] = {
        "preview": preview,
        "unchanged": True,
    }
    for key in ("checksum", "start_line", "total_lines", "path"):
        value = restored.get(key, stub.get(key))
        if value is not None:
            kept[key] = value
    return kept


def _looks_like_file_read(content: Mapping[str, object]) -> bool:
    if _is_unchanged_stub(content):
        return True
    preview = content.get("preview")
    if not isinstance(preview, str) or not preview:
        return False
    if _LINE_NUMBERED_RE.search(preview):
        return True
    entries = content.get("entries")
    if isinstance(entries, (list, tuple)):
        for entry in entries:
            if isinstance(entry, Mapping):
                text = entry.get("text")
                if isinstance(text, str) and _LINE_NUMBERED_RE.search(text):
                    return True
    return False


def _tool_result_bytes(content: Mapping[str, object]) -> int:
    return len(
        json.dumps(
            dict(content),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    )


def _tool_event_preview(name: str, tool_input: Mapping[str, object]) -> str:
    detail = ""
    path = tool_input.get("path")
    if isinstance(path, str) and path:
        detail = path
    else:
        argv = tool_input.get("argv")
        if isinstance(argv, (list, tuple)) and argv:
            detail = str(argv[0])
    summary = f"{name} {detail}".strip() if detail else name
    redacted = redact_sensitive(summary)
    if not isinstance(redacted, str):
        redacted = name
    return redacted[:200]


def _tool_event_payload(call, **extra: Any) -> dict[str, Any]:
    payload = dict(extra)
    payload["name"] = getattr(call, "name", "")
    payload["preview"] = _tool_event_preview(
        str(payload["name"]),
        dict(getattr(call, "input", {}) or {}),
    )
    return payload


def _executor_read_stamps(executor: object) -> dict[str, dict[str, object]]:
    method = getattr(executor, "export_read_stamps", None)
    if not callable(method):
        return {}
    try:
        exported = method()
    except TypeError:
        return {}
    return _read_stamps_mapping(exported)

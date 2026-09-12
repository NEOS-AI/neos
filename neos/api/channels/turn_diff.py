"""Last model+tool step file dump. Not a workspace snapshot."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from neos.coding.redact import redact_sensitive

_MUTATE_MARKERS = ("write_file", "edit_file")


def format_turn_diff(snapshot: Any) -> str:
    task_id = _task_id(snapshot)
    loop_state = _loop_state(snapshot)
    explicit = loop_state.get("turn_diff") or loop_state.get("last_turn_changes")
    if isinstance(explicit, str) and explicit.strip():
        return str(redact_sensitive(explicit, clip=False))
    if isinstance(explicit, Mapping):
        return str(redact_sensitive(_format_mapping(explicit), clip=False))

    transcript = loop_state.get("transcript")
    if not isinstance(transcript, list):
        return f"{task_id} no file changes in the last turn."

    assistant_idx = _last_assistant_index(transcript)
    if assistant_idx is None:
        return f"{task_id} no file changes in the last turn."

    uses = [
        part
        for part in _parts(transcript[assistant_idx])
        if _is_mutate_use(part)
    ]
    if not uses:
        return f"{task_id} no file changes in the last turn."

    results = _results_after(transcript, assistant_idx)
    lines = [f"{task_id} last turn:"]
    for use in uses:
        name = str(use.get("name") or "tool")
        path = ""
        raw_input = use.get("input")
        if isinstance(raw_input, Mapping):
            path = str(raw_input.get("path") or "")
        line = f"{name} {path}".strip()
        result = results.get(str(use.get("tool_call_id") or ""))
        preview = _result_preview(result)
        if preview:
            line = f"{line}\n{preview}"
        lines.append(line)
    return str(redact_sensitive("\n".join(lines), clip=False))


def _task_id(snapshot: Any) -> str:
    task = getattr(snapshot, "task", None)
    if task is None and isinstance(snapshot, Mapping):
        task = snapshot.get("task")
    value = getattr(task, "task_id", None)
    if value is None and isinstance(task, Mapping):
        value = task.get("task_id")
    return str(value or "task")


def _loop_state(snapshot: Any) -> dict[str, Any]:
    if snapshot is None:
        return {}
    checkpoint = getattr(snapshot, "latest_checkpoint", None)
    if checkpoint is None and isinstance(snapshot, Mapping):
        checkpoint = snapshot.get("latest_checkpoint")
    if checkpoint is None:
        return {}
    loop_state = getattr(checkpoint, "loop_state", None)
    if loop_state is None and isinstance(checkpoint, Mapping):
        loop_state = checkpoint.get("loop_state")
    return loop_state if isinstance(loop_state, dict) else {}


def _last_assistant_index(transcript: list[Any]) -> int | None:
    for index in range(len(transcript) - 1, -1, -1):
        item = transcript[index]
        if isinstance(item, Mapping) and item.get("role") == "assistant":
            return index
    return None


def _parts(message: Any) -> list[Mapping[str, Any]]:
    if not isinstance(message, Mapping):
        return []
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [part for part in content if isinstance(part, Mapping)]


def _is_mutate_use(part: Mapping[str, Any]) -> bool:
    name = str(part.get("name") or "")
    kind = str(part.get("type") or "")
    if kind and kind not in {"tool_use", ""}:
        return False
    return any(marker in name for marker in _MUTATE_MARKERS)


def _results_after(
    transcript: list[Any], assistant_idx: int
) -> dict[str, Mapping[str, Any]]:
    found: dict[str, Mapping[str, Any]] = {}
    for message in transcript[assistant_idx + 1 :]:
        if isinstance(message, Mapping) and message.get("role") == "assistant":
            break
        for part in _parts(message):
            tool_call_id = part.get("tool_call_id")
            if isinstance(tool_call_id, str) and tool_call_id:
                found[tool_call_id] = part
    return found


def _result_preview(result: Mapping[str, Any] | None) -> str:
    if not result:
        return ""
    content = result.get("content")
    if isinstance(content, Mapping):
        preview = content.get("preview")
        if isinstance(preview, str) and preview.strip():
            return preview.strip()
    preview = result.get("preview")
    if isinstance(preview, str) and preview.strip():
        return preview.strip()
    return ""


def _format_mapping(payload: Mapping[str, Any]) -> str:
    lines = []
    for key, value in payload.items():
        lines.append(f"{key}: {value}")
    return "\n".join(lines)

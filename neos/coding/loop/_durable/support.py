"""Pure helpers shared by the durable coding loop concern modules."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from pathlib import Path

from neos.coding.model.base import (
    CanonicalMessage,
    ModelCompleted,
    SystemNoteContent,
    TextContent,
    ThinkingContent,
    ToolAdditionContent,
    ToolCallCompleted,
    ToolResultContent,
    ToolUseContent,
)
from neos.coding.redact import redact_sensitive
from neos.coding.sandbox.paths import normalize_workspace_path
from neos.coding.loop._durable.state import (
    ActiveChildRef,
    AgentLoopState,
    STALL_DENY_AFTER,
    SpawnWork,
    _EPOCH_STAMP,
    _THINK_CLOSED_RE,
    _THINK_UNCLOSED_RE,
    _UNCHANGED_PREVIEW,
)

logger = logging.getLogger("neos.coding.loop.durable")


def _usage_tokens(completion: ModelCompleted) -> tuple[int, int]:
    usage = completion.usage
    if usage is None:
        return 0, 0
    return usage.input_tokens, usage.output_tokens


def _usage_window(completion: ModelCompleted) -> tuple[int, int, int]:
    usage = completion.usage
    if usage is None:
        return 0, 0, 0
    return (
        _nonneg_int(getattr(usage, "cache_read_tokens", 0)),
        _nonneg_int(getattr(usage, "cache_write_tokens", 0)),
        _nonneg_int(getattr(usage, "reasoning_tokens", 0)),
    )


def _scrub_think_blocks(text: str) -> str:
    cleaned = _THINK_CLOSED_RE.sub("", text)
    return _THINK_UNCLOSED_RE.sub("", cleaned)


def _is_empty_or_think_only(text: str) -> bool:
    return not _scrub_think_blocks(text).strip()


def _error_signature(name: str, tool_input: Mapping[str, object]) -> str:
    canonical = json.dumps(
        tool_input,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256((name + canonical).encode("utf-8")).hexdigest()


def _result_preview_hash(content: Mapping[str, object]) -> str:
    payload = {
        "preview": content.get("preview"),
        "status": content.get("status"),
    }
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def _is_stall_denied(
    state: AgentLoopState, name: str, tool_input: Mapping[str, object]
) -> bool:
    signature = _error_signature(name, tool_input)
    if (
        state.last_error_count >= STALL_DENY_AFTER
        and state.last_error_signature == signature
    ):
        return True
    return (
        state.last_success_count >= STALL_DENY_AFTER
        and state.last_success_signature == signature
    )


def _next_error_signature(
    state: AgentLoopState, name: str, tool_input: Mapping[str, object]
) -> tuple[str, int]:
    signature = _error_signature(name, tool_input)
    if signature == state.last_error_signature:
        return signature, state.last_error_count + 1
    return signature, 1


def _next_success_signature(
    state: AgentLoopState,
    name: str,
    tool_input: Mapping[str, object],
    result: ToolResultContent,
) -> tuple[str, str, int]:
    signature = _error_signature(name, tool_input)
    content = result.content if isinstance(result.content, Mapping) else {}
    result_hash = _result_preview_hash(content)
    if (
        signature == state.last_success_signature
        and result_hash == state.last_success_result_hash
    ):
        return signature, result_hash, state.last_success_count + 1
    return signature, result_hash, 1


def _has_open_tool_pair(transcript: Sequence[CanonicalMessage]) -> bool:
    for message in reversed(transcript):
        if message.role == "tool":
            return False
        if message.role == "assistant":
            return any(isinstance(item, ToolUseContent) for item in message.content)
        if message.role == "user":
            return False
    return False


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


def _string_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): str(item)
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, str)
    }


def _read_stamps_mapping(value: object) -> dict[str, dict[str, object]]:
    if not isinstance(value, Mapping):
        return {}
    stamps: dict[str, dict[str, object]] = {}
    for raw_path, raw_stamp in value.items():
        if not isinstance(raw_stamp, Mapping):
            continue
        mtime = raw_stamp.get("mtime")
        digest = raw_stamp.get("digest")
        if not isinstance(mtime, str) or not isinstance(digest, str):
            continue
        path = str(normalize_workspace_path(str(raw_path)))
        stamp: dict[str, object] = {
            "mtime": mtime,
            "digest": digest,
            "full": bool(raw_stamp.get("full", True)),
        }
        offset = raw_stamp.get("offset")
        limit = raw_stamp.get("limit")
        if isinstance(offset, int) and not isinstance(offset, bool):
            stamp["offset"] = offset
        if isinstance(limit, int) and not isinstance(limit, bool):
            stamp["limit"] = limit
        stamps[path] = stamp
    return stamps


def _dump_read_stamp(stamp: Mapping[str, object]) -> dict[str, object]:
    dumped: dict[str, object] = {
        "mtime": stamp["mtime"],
        "digest": stamp["digest"],
        "full": bool(stamp["full"]),
    }
    offset = stamp.get("offset")
    limit = stamp.get("limit")
    if isinstance(offset, int) and not isinstance(offset, bool):
        dumped["offset"] = offset
    if isinstance(limit, int) and not isinstance(limit, bool):
        dumped["limit"] = limit
    return dumped


_LINE_NUMBERED_RE = re.compile(r"^\s*\d+\|", re.MULTILINE)


def _tool_use_names(messages: Sequence[CanonicalMessage]) -> dict[str, str]:
    names: dict[str, str] = {}
    for message in messages:
        for item in message.content:
            if isinstance(item, ToolUseContent):
                names[item.tool_call_id] = item.name
    return names


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


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _nonneg_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _parse_utc_stamp(stamp: str) -> datetime | None:
    text = (stamp or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _stamp_is_stale(stamp: str, now: datetime, stale_after_sec: float) -> bool:
    # Epoch is unknown last-advance, not age 0.
    if stamp == _EPOCH_STAMP:
        return False
    parsed = _parse_utc_stamp(stamp)
    if parsed is None:
        return False
    age = (now.astimezone(UTC) - parsed).total_seconds()
    return age >= stale_after_sec


def _tool_result_ids(transcript) -> set[str]:
    return {
        item.tool_call_id
        for message in transcript
        for item in message.content
        if isinstance(item, ToolResultContent)
    }


def _subagent_max_active(config) -> int:
    return min(4, max(1, getattr(config, "subagent_max_active", 1)))


def _spawn_window(state) -> tuple[ToolCallCompleted, ...]:
    window: list[ToolCallCompleted] = []
    for call in state.pending_tool_calls[state.pending_tool_index :]:
        if call.name != "spawn_agent.v1":
            break
        window.append(call)
    return tuple(window)


def _pending_by_id(state, tool_call_id: str) -> ToolCallCompleted | None:
    for call in state.pending_tool_calls:
        if call.tool_call_id == tool_call_id:
            return call
    return None


def _select_spawn_work(state, *, max_active: int) -> SpawnWork | None:
    window = _spawn_window(state)
    live = list(state.active_children or _legacy_single(state))
    live_ids = {child.tool_call_id for child in live}
    # Detached children (K3) have no pending call to resume through -- the
    # parent's safe point advances them. They still count against `max_active`,
    # which is a cap on live children, not on parked ones.
    parked = [child for child in live if not child.detached]
    done = _tool_result_ids(state.transcript)
    unstarted = [
        call
        for call in window
        if call.tool_call_id not in live_ids and call.tool_call_id not in done
    ]
    if len(live) < max_active and unstarted:
        return SpawnWork(kind="start", call=unstarted[0], child=None)
    if parked:
        picked = min(
            parked, key=lambda child: (child.last_advanced_at, child.tool_call_id)
        )
        call = _pending_by_id(state, picked.tool_call_id)
        return SpawnWork(kind="resume", call=call, child=picked)
    return None


def _legacy_single(state) -> tuple[ActiveChildRef, ...]:
    run_id = getattr(state, "active_child_run_id", None)
    if not run_id:
        return ()
    tool_call_id = getattr(state, "active_child_tool_call_id", None) or ""
    return (
        ActiveChildRef(
            run_id=run_id,
            checkpoint_id=getattr(state, "active_child_checkpoint_id", None),
            tool_call_id=tool_call_id,
            last_advanced_at=_EPOCH_STAMP,
        ),
    )


def _restore_active_children(raw: Mapping[str, Any]) -> tuple[ActiveChildRef, ...]:
    if "active_children" in raw:
        items = raw.get("active_children") or ()
        children: list[ActiveChildRef] = []
        if isinstance(items, Sequence) and not isinstance(items, (str, bytes)):
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                run_id = _optional_str(item.get("run_id"))
                tool_call_id = _optional_str(item.get("tool_call_id"))
                if not run_id or not tool_call_id:
                    continue
                stamp = _optional_str(item.get("last_advanced_at")) or ""
                children.append(
                    ActiveChildRef(
                        run_id=run_id,
                        checkpoint_id=_optional_str(item.get("checkpoint_id")),
                        tool_call_id=tool_call_id,
                        last_advanced_at=stamp,
                        rolled_input_tokens=_nonneg_int(
                            item.get("rolled_input_tokens")
                        ),
                        rolled_output_tokens=_nonneg_int(
                            item.get("rolled_output_tokens")
                        ),
                        pending_steer=str(item.get("pending_steer") or ""),
                        spec=str(item.get("spec") or "explore"),
                        spawn_depth=max(0, min(1, _nonneg_int(item.get("spawn_depth")))),
                        worktree_repo=str(item.get("worktree_repo") or ""),
                        worktree_path=str(item.get("worktree_path") or ""),
                        worktree_branch=str(item.get("worktree_branch") or ""),
                        worktree_base_sha=str(item.get("worktree_base_sha") or ""),
                        # 모르는 값은 park 로 떨어뜨린다 -- 키가 없는 옛
                        # 체크포인트가 전부 여기로 온다.
                        delivery=(
                            "user_message"
                            if str(item.get("delivery") or "") == "user_message"
                            else "tool_result"
                        ),
                    )
                )
        if len(children) > 1:
            children = [
                (
                    child
                    if child.last_advanced_at
                    else replace(child, last_advanced_at=_EPOCH_STAMP)
                )
                for child in children
            ]
        return tuple(children)
    run_id = _optional_str(raw.get("active_child_run_id"))
    if not run_id:
        return ()
    return (
        ActiveChildRef(
            run_id=run_id,
            checkpoint_id=_optional_str(raw.get("active_child_checkpoint_id")),
            tool_call_id=_optional_str(raw.get("active_child_tool_call_id")) or "",
            last_advanced_at=_EPOCH_STAMP,
        ),
    )


def _warn_stale_active_child_scalars(
    raw: Mapping[str, Any], children: tuple[ActiveChildRef, ...]
) -> None:
    if "active_children" not in raw:
        return
    raw_run = _optional_str(raw.get("active_child_run_id"))
    raw_ckpt = _optional_str(raw.get("active_child_checkpoint_id"))
    raw_tool = _optional_str(raw.get("active_child_tool_call_id"))
    if raw_run is None and raw_ckpt is None and raw_tool is None:
        return
    head = children[0] if children else None
    expected = (
        head.run_id if head else None,
        head.checkpoint_id if head else None,
        head.tool_call_id if head else None,
    )
    actual = (raw_run, raw_ckpt, raw_tool)
    if actual == expected:
        return
    logger.warning(
        "active_child scalars disagree with active_children[0]; remirroring "
        "run_id=%s checkpoint_id=%s tool_call_id=%s from list run_id=%s "
        "checkpoint_id=%s tool_call_id=%s",
        raw_run,
        raw_ckpt,
        raw_tool,
        expected[0],
        expected[1],
        expected[2],
    )


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


def _read_paths_from_transcript(transcript: tuple[CanonicalMessage, ...]) -> frozenset[str]:
    pending: dict[str, str] = {}
    read_paths: set[str] = set()
    for message in transcript:
        for item in message.content:
            if isinstance(item, ToolUseContent) and item.name == "read_file.v1":
                raw_path = item.input.get("path")
                if raw_path:
                    pending[item.tool_call_id] = str(raw_path)
            elif isinstance(item, ToolResultContent) and item.status == "ok":
                raw_path = pending.get(item.tool_call_id)
                if raw_path:
                    read_paths.add(str(normalize_workspace_path(raw_path)))
    return frozenset(read_paths)


def _message_to_mapping(message: CanonicalMessage) -> dict[str, Any]:
    content = []
    for item in message.content:
        if isinstance(item, TextContent):
            content.append({"type": "text", "text": item.text})
        elif isinstance(item, ToolUseContent):
            content.append(
                {
                    "type": "tool_use",
                    "tool_call_id": item.tool_call_id,
                    "name": item.name,
                    "input": dict(item.input),
                }
            )
        elif isinstance(item, ThinkingContent):
            content.append(
                {
                    "type": "thinking",
                    "thinking": item.thinking,
                    "signature": item.signature,
                }
            )
        elif isinstance(item, SystemNoteContent):
            content.append(
                {"type": "system_note", "text": item.text, "clear_at": item.clear_at}
            )
        elif isinstance(item, ToolAdditionContent):
            content.append({"type": "tool_addition", "name": item.name})
        else:
            content.append(
                {
                    "type": "tool_result",
                    "tool_call_id": item.tool_call_id,
                    "status": item.status,
                    "content": dict(item.content),
                }
            )
    return {"role": message.role, "content": content}


def _message_from_mapping(value: Mapping[str, Any]) -> CanonicalMessage:
    content = []
    for item in value["content"]:
        if item["type"] == "text":
            content.append(TextContent(item["text"]))
        elif item["type"] == "tool_use":
            content.append(
                ToolUseContent(item["tool_call_id"], item["name"], item["input"])
            )
        elif item["type"] == "thinking":
            content.append(ThinkingContent(item["thinking"], item["signature"]))
        elif item["type"] == "system_note":
            content.append(SystemNoteContent(item["text"], item["clear_at"]))
        elif item["type"] == "tool_addition":
            # Needs its own branch: the `else` below assumes a tool result
            # and raises KeyError on anything else, and the loop resumes
            # from a checkpoint on every step.
            content.append(ToolAdditionContent(item["name"]))
        else:
            content.append(
                ToolResultContent(item["tool_call_id"], item["status"], item["content"])
            )
    return CanonicalMessage(value["role"], tuple(content))


def _session_workspace(session) -> Path | None:
    from pathlib import Path as _Path

    raw = getattr(session, "workspace", None)
    if raw:
        return _Path(raw)
    record = getattr(session, "_record", None)
    workspace = getattr(record, "workspace", None)
    return _Path(workspace) if workspace else None


def _session_on_workspace(session, workspace: str):
    from pathlib import Path as _Path

    from neos.coding.sandbox.memory import MemorySandboxSession

    root = _Path(workspace)
    if isinstance(session, MemorySandboxSession):
        from dataclasses import replace as _replace

        return MemorySandboxSession(
            session._provider, _replace(session._record, workspace=root)
        )
    clone = getattr(session, "clone_with_workspace", None)
    if callable(clone):
        return clone(root)
    from neos.coding.subagent_worktree import WorktreeError

    raise WorktreeError("worktree_session_not_cloneable")


def _lease_from_ref(ref: ActiveChildRef | None):
    if ref is None or not ref.worktree_path or not ref.worktree_repo:
        return None
    from pathlib import Path as _Path

    from neos.coding.subagent_worktree import WorktreeLease

    return WorktreeLease(
        run_id=ref.tool_call_id,
        repo=_Path(ref.worktree_repo),
        path=_Path(ref.worktree_path),
        branch=ref.worktree_branch,
        base_sha=ref.worktree_base_sha,
    )


def _open_implement_worktree(session, tool_call_id: str):
    from neos.coding.subagent_worktree import WorktreeError, create_worktree

    workspace = _session_workspace(session)
    if workspace is None:
        raise WorktreeError("worktree_parent_not_git")
    return create_worktree(workspace, tool_call_id)


def _discard_lease(lease) -> None:
    if lease is None:
        return
    from neos.coding.subagent_worktree import discard_worktree

    discard_worktree(lease)

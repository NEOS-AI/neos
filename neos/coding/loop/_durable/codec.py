"""Checkpoint wire format: transcript messages, read stamps, child refs, scalars.

Everything here is pure and total over whatever a stored checkpoint holds --
the loop restores from one on every step, so a malformed field degrades to a
default instead of raising.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import asdict, replace
from typing import Any

from neos.coding.model.base import (
    CanonicalMessage,
    SystemNoteContent,
    TextContent,
    ThinkingContent,
    ToolAdditionContent,
    ToolCallCompleted,
    ToolResultContent,
    ToolUseContent,
)
from neos.coding.phases import (
    parse_phase,
    restore_plan_critical_files,
    restore_verify_verdict,
)
from neos.coding.sandbox.paths import normalize_workspace_path
from neos.coding.loop._durable.children import _EPOCH_STAMP
from neos.coding.loop._durable.state import ActiveChildRef, AgentLoopState
from neos.coding.loop._durable.transcript import _read_paths_from_transcript

logger = logging.getLogger("neos.coding.loop.durable")


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


def _string_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): str(item)
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, str)
    }


def _is_plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


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
        for key in ("offset", "limit"):
            if _is_plain_int(raw_stamp.get(key)):
                stamp[key] = raw_stamp[key]
        stamps[path] = stamp
    return stamps


def _dump_read_stamp(stamp: Mapping[str, object]) -> dict[str, object]:
    dumped: dict[str, object] = {
        "mtime": stamp["mtime"],
        "digest": stamp["digest"],
        "full": bool(stamp["full"]),
    }
    for key in ("offset", "limit"):
        if _is_plain_int(stamp.get(key)):
            dumped[key] = stamp[key]
    return dumped


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


def _serialized_text(transcript) -> str:
    return json.dumps(
        [_message_to_mapping(item) for item in transcript],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _serialized_bytes(transcript) -> int:
    return len(_serialized_text(transcript).encode("utf-8"))


def _estimated_tokens(transcript) -> int:
    return (len(_serialized_text(transcript)) + 3) // 4


def _transcript_digest(transcript) -> str:
    return hashlib.sha256(_serialized_text(transcript).encode()).hexdigest()


def _dump_active_child(child: ActiveChildRef) -> dict[str, Any]:
    """Explicit on purpose: a new `ActiveChildRef` field is a format change,
    and `_active_child_from_mapping` below must learn it in the same edit."""
    return {
        "run_id": child.run_id,
        "checkpoint_id": child.checkpoint_id,
        "tool_call_id": child.tool_call_id,
        "last_advanced_at": child.last_advanced_at,
        "rolled_input_tokens": child.rolled_input_tokens,
        "rolled_output_tokens": child.rolled_output_tokens,
        "pending_steer": child.pending_steer,
        "spec": child.spec,
        "spawn_depth": child.spawn_depth,
        "worktree_repo": child.worktree_repo,
        "worktree_path": child.worktree_path,
        "worktree_branch": child.worktree_branch,
        "worktree_base_sha": child.worktree_base_sha,
        "delivery": child.delivery,
    }


def _active_child_from_mapping(item: object) -> ActiveChildRef | None:
    if not isinstance(item, Mapping):
        return None
    run_id = _optional_str(item.get("run_id"))
    tool_call_id = _optional_str(item.get("tool_call_id"))
    if not run_id or not tool_call_id:
        return None
    return ActiveChildRef(
        run_id=run_id,
        checkpoint_id=_optional_str(item.get("checkpoint_id")),
        tool_call_id=tool_call_id,
        last_advanced_at=_optional_str(item.get("last_advanced_at")) or "",
        rolled_input_tokens=_nonneg_int(item.get("rolled_input_tokens")),
        rolled_output_tokens=_nonneg_int(item.get("rolled_output_tokens")),
        pending_steer=str(item.get("pending_steer") or ""),
        spec=str(item.get("spec") or "explore"),
        spawn_depth=max(0, min(1, _nonneg_int(item.get("spawn_depth")))),
        worktree_repo=str(item.get("worktree_repo") or ""),
        worktree_path=str(item.get("worktree_path") or ""),
        worktree_branch=str(item.get("worktree_branch") or ""),
        worktree_base_sha=str(item.get("worktree_base_sha") or ""),
        # 모르는 값은 park 로 떨어뜨린다 -- 키가 없는 옛 체크포인트가 전부
        # 여기로 온다.
        delivery=(
            "user_message"
            if str(item.get("delivery") or "") == "user_message"
            else "tool_result"
        ),
    )


def _restore_active_children(raw: Mapping[str, Any]) -> tuple[ActiveChildRef, ...]:
    if "active_children" in raw:
        items = raw.get("active_children") or ()
        children: list[ActiveChildRef] = []
        if isinstance(items, Sequence) and not isinstance(items, (str, bytes)):
            for item in items:
                child = _active_child_from_mapping(item)
                if child is not None:
                    children.append(child)
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


def _state_from_mapping(
    raw: Mapping[str, Any],
    *,
    transcript: tuple[CanonicalMessage, ...],
    revealed: frozenset[str],
) -> AgentLoopState:
    """Everything a checkpoint restores as stored. `transcript` is decoded and
    edited by the caller; `revealed` is what that transcript already shows."""
    pending = tuple(
        ToolCallCompleted(item["tool_call_id"], item["name"], item["input"])
        for item in raw.get("pending_tool_calls", [])
    )
    stored_paths = raw.get("read_paths")
    if stored_paths:
        read_paths = frozenset(
            str(normalize_workspace_path(str(path))) for path in stored_paths
        )
    else:
        read_paths = _read_paths_from_transcript(transcript)
    pending_instruction = raw.get("pending_instruction")
    if not (isinstance(pending_instruction, str) and pending_instruction):
        pending_instruction = None
    children = _restore_active_children(raw)
    _warn_stale_active_child_scalars(raw, children)

    def names(key: str) -> frozenset[str]:
        return frozenset(str(name) for name in raw.get(key) or ())

    return AgentLoopState(
        transcript=transcript,
        turn_count=int(raw.get("turn_count", 0)),
        tool_count=int(raw.get("tool_count", 0)),
        consecutive_tool_errors=int(raw.get("consecutive_tool_errors", 0)),
        pending_tool_calls=pending,
        pending_tool_index=int(raw.get("pending_tool_index", 0)),
        transcript_digest=str(
            raw.get("transcript_digest", _transcript_digest(transcript))
        ),
        input_tokens=int(raw.get("input_tokens", 0)),
        output_tokens=int(raw.get("output_tokens", 0)),
        cache_read_tokens=_nonneg_int(raw.get("cache_read_tokens")),
        cache_write_tokens=_nonneg_int(raw.get("cache_write_tokens")),
        reasoning_tokens=_nonneg_int(raw.get("reasoning_tokens")),
        last_prompt_tokens=_nonneg_int(raw.get("last_prompt_tokens")),
        cost_micros=int(raw.get("cost_micros", 0)),
        terminal_pending=bool(raw.get("terminal_pending", False)),
        read_paths=read_paths,
        pending_instruction=pending_instruction,
        todos=tuple(
            dict(item) for item in raw.get("todos") or () if isinstance(item, Mapping)
        ),
        phase=parse_phase(raw.get("phase")).value,
        instructions_loaded=bool(raw.get("instructions_loaded", False)),
        prompt_compact_retries=int(raw.get("prompt_compact_retries", 0)),
        output_token_escalations=int(raw.get("output_token_escalations", 0)),
        llm_compact_attempts=int(raw.get("llm_compact_attempts", 0)),
        summary=str(raw.get("summary") or ""),
        sent_prefix_count=int(raw.get("sent_prefix_count", 0)),
        sent_prefix_digest=str(raw.get("sent_prefix_digest") or ""),
        revealed_tools=names("revealed_tools") | revealed,
        allowed_tools=names("allowed_tools"),
        approved_always=names("approved_always"),
        hook_retry_count=int(raw.get("hook_retry_count", 0)),
        compacted_bodies=_string_mapping(raw.get("compacted_bodies")),
        stop_retry_count=int(raw.get("stop_retry_count", 0)),
        read_stamps=_read_stamps_mapping(raw.get("read_stamps")),
        empty_retry_count=int(raw.get("empty_retry_count", 0)),
        last_error_signature=str(raw.get("last_error_signature") or ""),
        last_error_count=int(raw.get("last_error_count", 0)),
        last_success_signature=str(raw.get("last_success_signature") or ""),
        last_success_result_hash=str(raw.get("last_success_result_hash") or ""),
        last_success_count=int(raw.get("last_success_count", 0)),
        verdict=restore_verify_verdict(raw.get("verdict")),
        critical_files=restore_plan_critical_files(raw.get("critical_files")),
        active_child_run_id=_optional_str(raw.get("active_child_run_id")),
        active_child_checkpoint_id=_optional_str(
            raw.get("active_child_checkpoint_id")
        ),
        active_child_tool_call_id=_optional_str(raw.get("active_child_tool_call_id")),
        active_children=children,
    )


def _dump_loop_state(
    state: AgentLoopState, *, current_instruction: str
) -> dict[str, Any]:
    """The inverse of `_state_from_mapping`. Key order is the stored order."""
    return {
        "phase_index": state.tool_count - 1,
        "current_instruction": current_instruction,
        "pending_instruction": state.pending_instruction,
        "transcript": [_message_to_mapping(item) for item in state.transcript],
        "todos": [dict(item) for item in state.todos],
        "turn_count": state.turn_count,
        "tool_count": state.tool_count,
        "consecutive_tool_errors": state.consecutive_tool_errors,
        "pending_tool_calls": [asdict(item) for item in state.pending_tool_calls],
        "pending_tool_index": state.pending_tool_index,
        "transcript_digest": state.transcript_digest,
        "input_tokens": state.input_tokens,
        "output_tokens": state.output_tokens,
        "cache_read_tokens": state.cache_read_tokens,
        "cache_write_tokens": state.cache_write_tokens,
        "reasoning_tokens": state.reasoning_tokens,
        "last_prompt_tokens": state.last_prompt_tokens,
        "cost_micros": state.cost_micros,
        "terminal_pending": state.terminal_pending,
        "read_paths": sorted(state.read_paths),
        "phase": state.phase,
        "instructions_loaded": state.instructions_loaded,
        "prompt_compact_retries": state.prompt_compact_retries,
        "output_token_escalations": state.output_token_escalations,
        "llm_compact_attempts": state.llm_compact_attempts,
        "summary": state.summary,
        "sent_prefix_count": state.sent_prefix_count,
        "sent_prefix_digest": state.sent_prefix_digest,
        "revealed_tools": sorted(state.revealed_tools),
        "allowed_tools": sorted(state.allowed_tools),
        "approved_always": sorted(state.approved_always),
        "hook_retry_count": state.hook_retry_count,
        "compacted_bodies": dict(state.compacted_bodies),
        "stop_retry_count": state.stop_retry_count,
        "empty_retry_count": state.empty_retry_count,
        "last_error_signature": state.last_error_signature,
        "last_error_count": state.last_error_count,
        "last_success_signature": state.last_success_signature,
        "last_success_result_hash": state.last_success_result_hash,
        "last_success_count": state.last_success_count,
        "verdict": state.verdict,
        "critical_files": list(state.critical_files),
        "active_child_run_id": state.active_child_run_id,
        "active_child_checkpoint_id": state.active_child_checkpoint_id,
        "active_child_tool_call_id": state.active_child_tool_call_id,
        "active_children": [_dump_active_child(child) for child in state.active_children],
        "read_stamps": {
            path: _dump_read_stamp(stamp)
            for path, stamp in sorted(state.read_stamps.items())
        },
    }


def _warn_stale_active_child_scalars(
    raw: Mapping[str, Any], children: tuple[ActiveChildRef, ...]
) -> None:
    if "active_children" not in raw:
        return
    actual = (
        _optional_str(raw.get("active_child_run_id")),
        _optional_str(raw.get("active_child_checkpoint_id")),
        _optional_str(raw.get("active_child_tool_call_id")),
    )
    if actual == (None, None, None):
        return
    head = children[0] if children else None
    expected = (
        head.run_id if head else None,
        head.checkpoint_id if head else None,
        head.tool_call_id if head else None,
    )
    if actual == expected:
        return
    logger.warning(
        "active_child scalars disagree with active_children[0]; remirroring "
        "run_id=%s checkpoint_id=%s tool_call_id=%s from list run_id=%s "
        "checkpoint_id=%s tool_call_id=%s",
        *actual,
        *expected,
    )

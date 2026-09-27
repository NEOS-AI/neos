"""Stall detection: the same call failing, or succeeding identically, again.

A call is identified by name + canonical input. After `STALL_DENY_AFTER`
identical errors, or identical successes with an identical preview, the loop
denies the call instead of running it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from neos.coding.model.base import ToolResultContent
from neos.coding.loop._durable.state import STALL_DENY_AFTER, AgentLoopState


def _canonical_json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _error_signature(name: str, tool_input: Mapping[str, object]) -> str:
    return hashlib.sha256(
        (name + _canonical_json(tool_input)).encode("utf-8")
    ).hexdigest()


def _result_preview_hash(content: Mapping[str, object]) -> str:
    payload = {
        "preview": content.get("preview"),
        "status": content.get("status"),
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


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


def _stall_fields(
    state: AgentLoopState,
    name: str,
    tool_input: Mapping[str, object],
    result: ToolResultContent,
    reason_code: str,
) -> dict[str, object]:
    """The five stall counters after `result`, as `replace()` keywords.

    An error resets the success streak -- except a stall denial, which is the
    loop's own verdict on the streak and must not clear the evidence for it.
    """
    if result.status == "ok":
        signature, result_hash, count = _next_success_signature(
            state, name, tool_input, result
        )
        return {
            "last_error_signature": "",
            "last_error_count": 0,
            "last_success_signature": signature,
            "last_success_result_hash": result_hash,
            "last_success_count": count,
        }
    error_signature, error_count = _next_error_signature(state, name, tool_input)
    fields: dict[str, object] = {
        "last_error_signature": error_signature,
        "last_error_count": error_count,
    }
    if reason_code == "policy_stall_denied":
        fields.update(
            last_success_signature=state.last_success_signature,
            last_success_result_hash=state.last_success_result_hash,
            last_success_count=state.last_success_count,
        )
    else:
        fields.update(
            last_success_signature="",
            last_success_result_hash="",
            last_success_count=0,
        )
    return fields

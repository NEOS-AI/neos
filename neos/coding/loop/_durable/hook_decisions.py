"""Reading what a hook returned. Pure; the calls and timeouts stay on the loop.

The two hooks fail in opposite directions on purpose. A malformed pre-tool
answer denies the call -- a hook that cannot say "allow" has not allowed
anything. A malformed stop answer allows the stop -- a broken hook must not
keep the parent running.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

PreToolDecision = tuple[str, str, Mapping[str, Any] | None]

_PRE_TOOL_DECISIONS = frozenset({"allow", "deny", "retry", "prevent"})
_STOP_DECISIONS = frozenset({"allow", "prevent", "retry"})
_HOOK_ERROR: PreToolDecision = ("deny", "hook_error", None)


def _reason_text(raw: Mapping[str, Any]) -> str:
    reason = raw.get("reason")
    return str(reason) if reason is not None else ""


def parse_pre_tool_decision(raw: object) -> PreToolDecision:
    """(decision, reason, updated input). Updated input only rides an allow."""
    if raw is None:
        return "allow", "", None
    if not isinstance(raw, Mapping):
        return _HOOK_ERROR
    decision = raw.get("decision")
    if decision not in _PRE_TOOL_DECISIONS:
        return _HOOK_ERROR
    updated = raw.get("updatedInput")
    if updated is not None and not isinstance(updated, Mapping):
        return _HOOK_ERROR
    return (
        str(decision),
        _reason_text(raw),
        updated if decision == "allow" else None,
    )


def parse_stop_decision(raw: object) -> tuple[str, str]:
    if not isinstance(raw, Mapping):
        return "allow", ""
    decision = raw.get("decision")
    if decision not in _STOP_DECISIONS:
        return "allow", ""
    return str(decision), _reason_text(raw)

"""Tool results the subagent control plane hands back to the model.

Pure builders. Each result carries its key facts twice -- inside `entries`,
which is what the model reads, and flat at the top level, which is what the
loop and the ledger read back.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from neos.coding.tools.executor import ToolResult
from neos.coding.loop._durable.state import ActiveChildRef
from neos.coding.loop._durable.worktree import _discard_lease

_BRIEF_PLACEHOLDER_RE = re.compile(r"<[A-Za-z_][A-Za-z0-9_]*>")
_STUB_GOALS = frozenset({"TODO", "TBD"})
_EXPLORE_HANDOFF_NOTE = (
    "Do not nest an inner agent loop. "
    "Use set_phase.v1 to switch the parent to explore."
)


def _revision(bound) -> str:
    return str(bound.binding.workspace_revision)


def _ok_result(bound, entries, **flat: Any) -> dict[str, Any]:
    result = dict(
        ToolResult.ok(workspace_revision=_revision(bound), entries=entries).to_mapping()
    )
    result.update(flat)
    return result


def _spawn_tool_error(bound, reason_code: str) -> dict[str, Any]:
    return ToolResult(
        "error", reason_code, None, None, False, None, _revision(bound)
    ).to_mapping()


def _legacy_explore_handoff(bound) -> dict[str, Any]:
    fields = {"delegated": False, "use_phase": "explore", "note": _EXPLORE_HANDOFF_NOTE}
    return _ok_result(bound, (dict(fields),), **fields)


def _detached_spawn_ack(bound, run_id: str, spec_name: str) -> dict[str, Any]:
    """No summary, deliberately. A child one step in has nothing to report,
    and an empty `summary` key would read like an empty report rather than a
    pending one."""
    return _ok_result(
        bound,
        ({"run_id": run_id, "spec": spec_name, "delivery": "user_message"},),
        reason_code="spawned",
        run_id=run_id,
        spec=spec_name,
        delivery="user_message",
    )


def _steer_ack(bound, run_id: str) -> dict[str, Any]:
    return _ok_result(bound, ({"run_id": run_id, "steered": True},))


def _subagent_list_result(bound, children: list[dict[str, Any]]) -> dict[str, Any]:
    return _ok_result(bound, tuple(children), children=children)


def _folded_spawn_result(bound, folded) -> dict[str, Any]:
    from neos.subagent.types import SubagentStatus

    ok = folded.status is SubagentStatus.COMPLETED
    exit_reason = str(getattr(folded, "exit_reason", "") or "")
    reason = "ok" if ok else (exit_reason or folded.status.value)
    result = dict(
        ToolResult(
            "ok" if ok else "error",
            reason,
            None,
            None,
            bool(folded.truncated),
            None,
            _revision(bound),
            entries=(
                {
                    "summary": folded.summary,
                    "run_id": folded.run_id,
                    "exit_reason": exit_reason,
                },
            ),
        ).to_mapping()
    )
    result["summary"] = folded.summary
    result["run_id"] = folded.run_id
    result["truncated"] = bool(folded.truncated)
    result["citations"] = list(folded.citations)
    result["child_status"] = folded.status.value
    result["exit_reason"] = exit_reason
    result["turn_count"] = folded.turn_count
    result["input_tokens"] = int(folded.input_tokens or 0)
    result["output_tokens"] = int(folded.output_tokens or 0)
    result.pop("full_summary", None)
    return result


def _dropped_spawn_result(bound, snapshot) -> dict[str, Any]:
    result = dict(
        ToolResult(
            "error",
            "dropped",
            None,
            None,
            False,
            None,
            _revision(bound),
            entries=({"run_id": snapshot.run_id, "exit_reason": "dropped"},),
        ).to_mapping()
    )
    result["run_id"] = snapshot.run_id
    result["exit_reason"] = "dropped"
    result["child_status"] = snapshot.status.value
    result["truncated"] = False
    result["turn_count"] = int(getattr(snapshot, "turn_count", 0) or 0)
    result["input_tokens"] = int(snapshot.input_tokens or 0)
    result["output_tokens"] = int(snapshot.output_tokens or 0)
    return result


def _with_merge_outcome(result: dict[str, Any], lease) -> dict[str, Any]:
    """Commit and merge an implement child's worktree into the parent's.

    A clean merge (or nothing to merge) discards the worktree; a conflict
    keeps it so the ref still points at the child's work.
    """
    if lease is None:
        return result
    from neos.coding.subagent_worktree import commit_worktree, merge_worktree

    try:
        commit_worktree(lease)
        merged = merge_worktree(lease)
    except Exception as error:
        result["merge_status"] = "failed"
        result["merge_applied"] = False
        result["merge_message"] = str(error)
        return result
    result["merge_status"] = merged.status.value
    result["merge_applied"] = bool(merged.applied)
    result["merge_conflicts"] = list(merged.conflict_paths)
    result["merge_message"] = merged.message
    if merged.status.value in {"fast_forward", "empty"}:
        _discard_lease(lease)
    return result


def _finish_implement_child(bound, folded, lease) -> dict[str, Any]:
    if isinstance(folded, dict):
        result = dict(folded)
    else:
        result = _folded_spawn_result(bound, folded)
    return _with_merge_outcome(result, lease)


def _spawn_briefing(call):
    from neos.subagent.types import ParentBriefing

    raw = call.input if isinstance(call.input, Mapping) else {}
    already = raw.get("already_tried") or ()
    if isinstance(already, str):
        already = (already,)
    budget = raw.get("report_budget", 4000)
    try:
        budget = int(budget)
    except (TypeError, ValueError):
        budget = 4000
    goal = str(raw.get("prompt") or "").strip()
    if goal.upper() in _STUB_GOALS or _BRIEF_PLACEHOLDER_RE.search(goal):
        raise ValueError("briefing.goal is a placeholder")
    return ParentBriefing(
        goal=goal,
        why=str(raw.get("why") or ""),
        already_tried=tuple(str(item) for item in already),
        scope=str(raw.get("scope") or ""),
        success=str(raw.get("success") or ""),
        report_budget_chars=max(256, min(16_384, budget)),
    )


def _detached_report_text(ref: ActiveChildRef, report: Mapping[str, Any]) -> str:
    """The child's report, labelled so the parent can tell it from a user.

    It is a user message because that is the only append-only slot the parent
    has -- K1's thinking guard strips every block behind a non-append edit, and
    re-opening a settled tool result is exactly that. The label is what keeps
    the model from reading a subagent's words as its operator's.
    """
    status = str(report.get("child_status") or report.get("reason_code") or "")
    head = f"[subagent {ref.spec} {ref.run_id} {status}]".rstrip()
    body = str(report.get("summary") or "").strip()
    if not body:
        body = f"(no report: {report.get('exit_reason') or status or 'unknown'})"
    merge = str(report.get("merge_status") or "")
    if merge:
        body = f"{body}\n[merge {merge}]"
    return f"{head}\n{body}"

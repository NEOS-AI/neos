"""Budgeted report-only fold. Fail-closed unless the run is terminal."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from neos.subagent.store import RunRecord
from neos.subagent.types import FoldedResult, SubagentStatus

_TERMINAL = frozenset(
    {SubagentStatus.COMPLETED, SubagentStatus.FAILED, SubagentStatus.KILLED}
)
_SPILL_SEPARATOR = "\n…\n"


class FoldNotReady(RuntimeError):
    def __init__(self, run_id: str, status: SubagentStatus) -> None:
        super().__init__(f"{run_id} is {status.value}")
        self.run_id = run_id
        self.status = status


def fold_run(
    record: RunRecord,
    loop_state: Mapping[str, Any] | None,
    *,
    parent_headroom_chars: int | None = None,
    sibling_count: int | None = None,
) -> FoldedResult:
    if record.status not in _TERMINAL:
        raise FoldNotReady(record.run_id, record.status)
    briefing = record.briefing if isinstance(record.briefing, Mapping) else {}
    budget = _report_budget(briefing)
    headroom = _optional_int(parent_headroom_chars)
    if headroom is None:
        headroom = _optional_int(briefing.get("parent_headroom_chars"))
    siblings = _optional_int(sibling_count)
    if siblings is None:
        siblings = _optional_int(briefing.get("sibling_count"))
    if headroom is not None:
        budget = min(budget, max(256, headroom // max(1, siblings or 1)))
    text = ""
    citations: tuple[str, ...] = ()
    if isinstance(loop_state, Mapping):
        text = str(loop_state.get("last_assistant_text") or "")
        raw_cites = loop_state.get("citations") or ()
        citations = tuple(str(item) for item in raw_cites)
    if not text.strip():
        if record.status is SubagentStatus.KILLED:
            text = "cancelled"
        elif record.status is SubagentStatus.FAILED:
            text = "failed"
        elif record.error_code == "turns_exhausted":
            text = "turns_exhausted"
        else:
            text = record.status.value
    summary, truncated, full_summary = _spill(text, budget)
    return FoldedResult(
        run_id=record.run_id,
        status=record.status,
        summary=summary,
        truncated=truncated,
        citations=citations,
        turn_count=record.turn_count,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        cost_micros=record.cost_micros,
        exit_reason=_exit_reason(record),
        full_summary=full_summary,
    )


def _report_budget(briefing: Mapping[str, Any]) -> int:
    raw_budget = briefing.get("report_budget_chars", 4000)
    try:
        budget = int(raw_budget)
    except (TypeError, ValueError):
        budget = 4000
    return max(256, min(16_384, budget))


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _exit_reason(record: RunRecord) -> str:
    if record.status is SubagentStatus.COMPLETED:
        return "completed"
    if record.status is SubagentStatus.KILLED:
        return "cancelled"
    if record.status is SubagentStatus.FAILED:
        if record.error_code == "turns_exhausted":
            return "turns_exhausted"
        if record.error_code == "stalled":
            return "stalled"
        return "failed"
    return record.status.value


def _spill(text: str, budget: int) -> tuple[str, bool, str]:
    if len(text) <= budget:
        return text, False, ""
    usable = budget - len(_SPILL_SEPARATOR)
    if usable < 2:
        return text[:budget], True, text
    head_len = (usable * 3) // 4
    tail_len = usable - head_len
    return text[:head_len] + _SPILL_SEPARATOR + text[-tail_len:], True, text

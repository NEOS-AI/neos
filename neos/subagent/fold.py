"""Budgeted report-only fold. Fail-closed unless the run is terminal."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from neos.subagent.store import RunRecord
from neos.subagent.types import FoldedResult, SubagentStatus

_TERMINAL = frozenset(
    {SubagentStatus.COMPLETED, SubagentStatus.FAILED, SubagentStatus.KILLED}
)


class FoldNotReady(RuntimeError):
    def __init__(self, run_id: str, status: SubagentStatus) -> None:
        super().__init__(f"{run_id} is {status.value}")
        self.run_id = run_id
        self.status = status


def fold_run(record: RunRecord, loop_state: Mapping[str, Any] | None) -> FoldedResult:
    if record.status not in _TERMINAL:
        raise FoldNotReady(record.run_id, record.status)
    budget = 4000
    if isinstance(record.briefing, Mapping):
        raw_budget = record.briefing.get("report_budget_chars", 4000)
        try:
            budget = int(raw_budget)
        except (TypeError, ValueError):
            budget = 4000
    budget = max(256, min(16_384, budget))
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
    return FoldedResult(
        run_id=record.run_id,
        status=record.status,
        summary=text[:budget],
        truncated=len(text) > budget,
        citations=citations,
        turn_count=record.turn_count,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        cost_micros=record.cost_micros,
    )

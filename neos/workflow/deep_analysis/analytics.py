"""L5 improvement-signal analytics over the deep_analysis event log.

Read-only aggregation of the append-only ``deep_analysis_events`` log into
improvement signals for human review (P4). This service NEVER writes to the
event log; the periodic report task persists to ``deep_analysis_reports``.

Aggregation is global (across all runs), not run-scoped. Malformed JSON
payloads still count toward per-kind totals/denominators but never poison
numeric aggregates (averages, per-code rates).
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from neos.database.deep_analysis_models import DAEvent

_OVERCLAIM_CODES = ("E_OVERCLAIM", "E_CONFIDENCE_INFLATED")


def _to_naive_utc(value: datetime) -> datetime:
    """The events ``ts`` column is ``timestamp without time zone`` (naive UTC).

    Normalize an aware ``since`` bound to naive UTC so asyncpg can bind it.
    """
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


class DeepAnalysisAnalyticsService:
    """Mines improvement signals from the deep_analysis event log (read-only)."""

    def __init__(self, session) -> None:
        self.db = session

    async def _events(self, since: datetime | None) -> list[tuple[str, str]]:
        stmt = select(DAEvent.kind, DAEvent.payload)
        if since is not None:
            stmt = stmt.where(DAEvent.ts >= _to_naive_utc(since))
        result = await self.db.execute(stmt)
        return [(kind, payload) for kind, payload in result.all()]

    @staticmethod
    def _payload(raw: str) -> dict[str, Any] | None:
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    async def signals(self, *, since: datetime | None = None) -> dict[str, Any]:
        rows = await self._events(since)
        totals: Counter[str] = Counter(kind for kind, _ in rows)

        # reject_rate_by_code: code -> fraction of ALL claim_rejected events.
        reject_total = totals.get("claim_rejected", 0)
        code_counts: Counter[str] = Counter()
        for kind, payload in rows:
            if kind != "claim_rejected":
                continue
            data = self._payload(payload)
            if data and data.get("code"):
                code_counts[str(data["code"])] += 1
        reject_rate_by_code = (
            {code: count / reject_total for code, count in code_counts.items()}
            if reject_total
            else {}
        )

        # overclaim_rate: (E_OVERCLAIM + E_CONFIDENCE_INFLATED) / all rejects.
        overclaim = sum(code_counts.get(code, 0) for code in _OVERCLAIM_CODES)
        overclaim_rate = overclaim / reject_total if reject_total else 0.0

        # dead_end_rate: dead_end events per question opened.
        questions = totals.get("question_opened", 0)
        dead_end_rate = totals.get("dead_end", 0) / questions if questions else 0.0

        # unverified_rate: claim_unverified / (verified + rejected + unverified).
        verified = totals.get("claim_verified", 0)
        unverified = totals.get("claim_unverified", 0)
        claim_total = verified + reject_total + unverified
        unverified_rate = unverified / claim_total if claim_total else 0.0

        reinvestigation_count = totals.get("conflict_reinvestigation", 0)

        # avg_verified_per_pass: mean of well-formed pass_completed.verified.
        verified_per_pass: list[float] = []
        for kind, payload in rows:
            if kind != "pass_completed":
                continue
            data = self._payload(payload)
            if data is None or "verified" not in data:
                continue
            try:
                verified_per_pass.append(float(data["verified"]))
            except (ValueError, TypeError):
                continue
        avg_verified_per_pass = (
            sum(verified_per_pass) / len(verified_per_pass)
            if verified_per_pass
            else 0.0
        )

        # report_retry_rate: failed report_graded / all report_graded.
        report_total = totals.get("report_graded", 0)
        report_failures = 0
        for kind, payload in rows:
            if kind != "report_graded":
                continue
            data = self._payload(payload)
            if data is not None and data.get("ok") is False:
                report_failures += 1
        report_retry_rate = report_failures / report_total if report_total else 0.0

        return {
            "reject_rate_by_code": reject_rate_by_code,
            "overclaim_rate": overclaim_rate,
            "dead_end_rate": dead_end_rate,
            "unverified_rate": unverified_rate,
            "reinvestigation_count": reinvestigation_count,
            "avg_verified_per_pass": avg_verified_per_pass,
            "report_retry_rate": report_retry_rate,
            "totals": dict(totals),
        }

    async def summary(self, *, since: datetime | None = None) -> dict[str, Any]:
        return {
            "signals": await self.signals(since=since),
            "since": since,
            "generated_at": datetime.now(timezone.utc),
        }

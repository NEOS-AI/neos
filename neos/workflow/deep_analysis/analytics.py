"""L5 improvement-signal analytics over the deep_analysis event log.

Read-only aggregation of the append-only ``deep_analysis_events`` log into
improvement signals for human review (P4). This service NEVER writes to the
event log; the periodic report task persists to ``deep_analysis_reports``.

Aggregation is global (across all runs), not run-scoped. **All rates are
event-based**, not distinct-claim-based: a claim rejected on two attempts then
capped contributes two ``claim_rejected`` + one ``claim_unverified`` event, and
each is counted independently. Interpret the signals as event-frequency trends,
not per-claim outcome distributions.

Per-kind totals come from a cheap ``GROUP BY kind`` (no payload parsing, so
malformed JSON never breaks the count). Payload-derived signals fetch only the
three kinds that carry the relevant fields and tolerate malformed payloads
(they still count toward the ``GROUP BY`` totals/denominators, but are skipped
in numeric aggregates).
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from neos.database.deep_analysis_models import DAEvent
from neos.utils.time_utils import to_naive_utc

_OVERCLAIM_CODES = ("E_OVERCLAIM", "E_CONFIDENCE_INFLATED")
# Only these kinds carry payload fields the signals read.
_PAYLOAD_KINDS = ("claim_rejected", "pass_completed", "report_graded")


class DeepAnalysisAnalyticsService:
    """Mines improvement signals from the deep_analysis event log (read-only)."""

    def __init__(self, session) -> None:
        self.db = session

    async def _totals(self, since: datetime | None) -> dict[str, int]:
        stmt = select(DAEvent.kind, func.count()).group_by(DAEvent.kind)
        if since is not None:
            stmt = stmt.where(DAEvent.ts >= to_naive_utc(since))
        result = await self.db.execute(stmt)
        return {kind: int(count) for kind, count in result.all()}

    async def _payload_rows(
        self, since: datetime | None
    ) -> list[tuple[str, str]]:
        stmt = select(DAEvent.kind, DAEvent.payload).where(
            DAEvent.kind.in_(_PAYLOAD_KINDS)
        )
        if since is not None:
            stmt = stmt.where(DAEvent.ts >= to_naive_utc(since))
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
        totals = await self._totals(since)
        reject_total = totals.get("claim_rejected", 0)
        report_total = totals.get("report_graded", 0)
        questions = totals.get("question_opened", 0)
        verified = totals.get("claim_verified", 0)
        unverified = totals.get("claim_unverified", 0)

        # Single pass over only the payload-bearing kinds.
        code_counts: Counter[str] = Counter()
        verified_per_pass: list[float] = []
        report_failures = 0
        for kind, payload in await self._payload_rows(since):
            data = self._payload(payload)
            if kind == "claim_rejected":
                if data and data.get("code"):
                    code_counts[str(data["code"])] += 1
            elif kind == "pass_completed":
                if data is not None and "verified" in data:
                    try:
                        verified_per_pass.append(float(data["verified"]))
                    except (ValueError, TypeError):
                        continue
            elif kind == "report_graded":
                if data is not None and data.get("ok") is False:
                    report_failures += 1

        reject_rate_by_code = (
            {code: count / reject_total for code, count in code_counts.items()}
            if reject_total
            else {}
        )
        overclaim = sum(code_counts.get(code, 0) for code in _OVERCLAIM_CODES)
        overclaim_rate = overclaim / reject_total if reject_total else 0.0
        dead_end_rate = totals.get("dead_end", 0) / questions if questions else 0.0
        claim_total = verified + reject_total + unverified
        unverified_rate = unverified / claim_total if claim_total else 0.0
        avg_verified_per_pass = (
            sum(verified_per_pass) / len(verified_per_pass)
            if verified_per_pass
            else 0.0
        )
        report_retry_rate = (
            report_failures / report_total if report_total else 0.0
        )

        return {
            "reject_rate_by_code": reject_rate_by_code,
            "overclaim_rate": overclaim_rate,
            "dead_end_rate": dead_end_rate,
            "unverified_rate": unverified_rate,
            "reinvestigation_count": totals.get("conflict_reinvestigation", 0),
            "avg_verified_per_pass": avg_verified_per_pass,
            "report_retry_rate": report_retry_rate,
            "totals": totals,
        }

    async def summary(self, *, since: datetime | None = None) -> dict[str, Any]:
        return {
            "signals": await self.signals(since=since),
            "since": since,
            "generated_at": datetime.now(timezone.utc),
        }

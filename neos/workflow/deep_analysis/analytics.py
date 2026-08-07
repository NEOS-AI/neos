"""L5 improvement-signal analytics over the deep_analysis event log.

Read-only aggregation of the append-only ``deep_analysis_events`` log into
improvement signals for human review (P4). This service NEVER writes to the
event log; the periodic report task persists to ``deep_analysis_reports``.

Aggregation is global (across all runs) by default and can optionally be scoped
to one run. **All rates are event-based**, not distinct-claim-based: a claim
rejected on two attempts then capped contributes two ``claim_rejected`` + one
``claim_unverified`` event, and each is counted independently. Interpret the
signals as event-frequency trends, not per-claim outcome distributions.

Per-kind totals come from a cheap ``GROUP BY kind`` (no payload parsing, so
malformed JSON never breaks the count). Payload-derived signals fetch only the
three kinds that carry the relevant fields and tolerate malformed payloads
(they still count toward the ``GROUP BY`` totals/denominators, but are skipped
in numeric aggregates).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Select, func, select

from neos.database.deep_analysis_models import DAEvent
from neos.utils.time_utils import to_naive_utc

_OVERCLAIM_CODES = ("E_OVERCLAIM", "E_CONFIDENCE_INFLATED")
_CONFIDENCE_CLAMP_BUCKETS = ("0", "1", "2", "3_plus")
# Only these kinds carry payload fields the signals read.
_PAYLOAD_KINDS = (
    "claim_rejected",
    "claim_graded",
    "pass_completed",
    "report_graded",
)


class DeepAnalysisAnalyticsService:
    """Mines improvement signals from the deep_analysis event log (read-only)."""

    def __init__(self, session) -> None:
        self.db = session

    @staticmethod
    def _scope(
        stmt: Select,
        *,
        since: datetime | None,
        run_id: str | None,
    ) -> Select:
        if since is not None:
            stmt = stmt.where(DAEvent.ts >= to_naive_utc(since))
        if run_id is not None:
            stmt = stmt.where(DAEvent.run_id == run_id)
        return stmt

    async def _totals(
        self,
        since: datetime | None,
        run_id: str | None,
    ) -> dict[str, int]:
        stmt = select(DAEvent.kind, func.count()).group_by(DAEvent.kind)
        result = await self.db.execute(
            self._scope(stmt, since=since, run_id=run_id)
        )
        return {kind: int(count) for kind, count in result.all()}

    async def _payload_rows(
        self,
        since: datetime | None,
        run_id: str | None,
    ) -> list[tuple[str, str]]:
        stmt = select(DAEvent.kind, DAEvent.payload).where(
            DAEvent.kind.in_(_PAYLOAD_KINDS)
        )
        result = await self.db.execute(
            self._scope(stmt, since=since, run_id=run_id)
        )
        return [(kind, payload) for kind, payload in result.all()]

    @staticmethod
    def _payload(raw: str) -> dict[str, Any] | None:
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    async def report_bodies(
        self, run_ids: Sequence[str]
    ) -> dict[str, str]:
        """Map run_id -> final report body, for the runs that have one.

        The batch form exists because report-gate recalibration walks
        hundreds of runs at once; looping `Ledger.report_markdown()` would
        cost one round trip per run. Runs with no completed job -- or a
        payload without a body -- are simply absent from the result rather
        than mapping to None, so callers iterate what exists.
        """
        if not run_ids:
            return {}
        result = await self.db.execute(
            select(DAEvent.run_id, DAEvent.payload).where(
                DAEvent.run_id.in_(list(run_ids)),
                DAEvent.kind == "job_completed",
            )
        )
        bodies: dict[str, str] = {}
        for run_id, raw in result.all():
            payload = (
                raw if isinstance(raw, dict) else self._payload(raw)
            )
            if not isinstance(payload, dict):
                continue
            body = payload.get("report_markdown")
            if isinstance(body, str):
                bodies[run_id] = body
        return bodies

    @staticmethod
    def _valid_claim_grade(data: dict[str, Any]) -> bool:
        if data.get("outcome") not in {"verified", "rejected", "unverified"}:
            return False
        if data.get("deterministic") not in {"passed", "rejected"}:
            return False
        if data.get("agentic") not in {
            "not_configured",
            "skipped",
            "attempted_passed",
            "attempted_rejected",
            "exhausted",
        }:
            return False
        for key in (
            "evidence_count",
            "source_count",
            "fetched_source_count",
            "dead_source_count",
            "excerpt_chars",
        ):
            value = data.get(key)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                return False
        threshold = data.get("quote_threshold")
        if (
            not isinstance(threshold, (int, float))
            or isinstance(threshold, bool)
            or not 0 <= threshold <= 1
        ):
            return False
        score = data.get("best_quote_score")
        return score is None or (
            isinstance(score, (int, float))
            and not isinstance(score, bool)
            and 0 <= score <= 1
        )

    async def signals(
        self,
        *,
        since: datetime | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        totals = await self._totals(since, run_id)
        reject_total = totals.get("claim_rejected", 0)
        report_total = totals.get("report_graded", 0)
        questions = totals.get("question_opened", 0)
        verified = totals.get("claim_verified", 0)
        unverified = totals.get("claim_unverified", 0)

        # Single pass over only the payload-bearing kinds.
        code_counts: Counter[str] = Counter()
        verified_per_pass: list[float] = []
        report_failures = 0
        funnel = {
            "proposed": 0,
            "graded": 0,
            "deterministic_passed": 0,
            "deterministic_rejected": 0,
            "agentic_attempted": 0,
            "agentic_passed": 0,
            "agentic_rejected": 0,
            "agentic_skipped": 0,
            "agentic_exhausted": 0,
            "verified": 0,
            "rejected": 0,
            "unverified": 0,
            "evidence_missing_rate": 0.0,
            "source_dead_rate": 0.0,
            "quote_score_buckets": {
                "exact": 0,
                "above_threshold": 0,
                "near_miss": 0,
                "low": 0,
                "unavailable": 0,
            },
            "avg_evidence_count": 0.0,
            "avg_source_count": 0.0,
            "avg_excerpt_chars": 0.0,
            "confidence_clamped_count": 0,
            "confidence_clamped_by_source_count": {
                key: 0 for key in _CONFIDENCE_CLAMP_BUCKETS
            },
        }
        evidence_total = 0
        source_total = 0
        excerpt_chars_total = 0
        evidence_missing = 0
        source_dead = 0
        for kind, payload in await self._payload_rows(since, run_id):
            data = self._payload(payload)
            if kind == "claim_rejected":
                if data and data.get("code"):
                    code_counts[str(data["code"])] += 1
            elif kind == "pass_completed":
                raw_clamp_counts = (
                    data.get("confidence_clamped_by_source_count")
                    if data
                    else None
                )
                if isinstance(raw_clamp_counts, dict):
                    clamp_counts = funnel[
                        "confidence_clamped_by_source_count"
                    ]
                    for bucket in _CONFIDENCE_CLAMP_BUCKETS:
                        count = raw_clamp_counts.get(bucket)
                        if (
                            isinstance(count, int)
                            and not isinstance(count, bool)
                            and count >= 0
                        ):
                            clamp_counts[bucket] += count
                new_claims = data.get("new_claims") if data else None
                if (
                    isinstance(new_claims, int)
                    and not isinstance(new_claims, bool)
                    and new_claims >= 0
                ):
                    funnel["proposed"] += new_claims
                if data is not None and "verified" in data:
                    try:
                        verified_per_pass.append(float(data["verified"]))
                    except (ValueError, TypeError):
                        continue
            elif kind == "report_graded":
                if data is not None and data.get("ok") is False:
                    report_failures += 1
            elif kind == "claim_graded":
                if data is None or not self._valid_claim_grade(data):
                    continue
                funnel["graded"] += 1
                deterministic = data["deterministic"]
                funnel[f"deterministic_{deterministic}"] += 1

                agentic = data["agentic"]
                if agentic.startswith("attempted_"):
                    funnel["agentic_attempted"] += 1
                    result = agentic.removeprefix("attempted_")
                    funnel[f"agentic_{result}"] += 1
                elif agentic == "skipped":
                    funnel["agentic_skipped"] += 1
                elif agentic == "exhausted":
                    funnel["agentic_exhausted"] += 1

                funnel[data["outcome"]] += 1
                evidence_total += data["evidence_count"]
                source_total += data["source_count"]
                excerpt_chars_total += data["excerpt_chars"]
                deterministic_code = data.get("deterministic_code")
                evidence_missing += deterministic_code == "E_NO_EVIDENCE"
                source_dead += deterministic_code == "E_SOURCE_DEAD"

                score = data["best_quote_score"]
                threshold = data["quote_threshold"]
                buckets = funnel["quote_score_buckets"]
                if score is None:
                    buckets["unavailable"] += 1
                elif score == 1.0:
                    buckets["exact"] += 1
                elif score >= threshold:
                    buckets["above_threshold"] += 1
                elif score >= max(0.0, threshold - 0.05):
                    buckets["near_miss"] += 1
                else:
                    buckets["low"] += 1

        funnel["confidence_clamped_count"] = sum(
            funnel["confidence_clamped_by_source_count"].values()
        )
        graded = funnel["graded"]
        if graded:
            funnel["evidence_missing_rate"] = evidence_missing / graded
            funnel["source_dead_rate"] = source_dead / graded
            funnel["avg_evidence_count"] = evidence_total / graded
            funnel["avg_source_count"] = source_total / graded
            funnel["avg_excerpt_chars"] = excerpt_chars_total / graded

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
            "claim_funnel": funnel,
            "totals": totals,
        }

    async def summary(
        self,
        *,
        since: datetime | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "signals": await self.signals(since=since, run_id=run_id),
            "since": since,
            "generated_at": datetime.now(timezone.utc),
        }

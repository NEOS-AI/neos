from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from neos.workflow.harness.models import (
    HarnessCheckResult,
    HarnessContract,
    HarnessMode,
)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            normalized = value.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None
    return None


def _source_date(source: dict) -> datetime | None:
    for key in ("published_at", "published_date", "date", "timestamp"):
        parsed = _parse_datetime(source.get(key))
        if parsed is not None:
            return parsed
    metadata = source.get("metadata") or {}
    if isinstance(metadata, dict):
        for key in ("published_at", "published_date", "date", "timestamp"):
            parsed = _parse_datetime(metadata.get(key))
            if parsed is not None:
                return parsed
    return None


class FreshnessChecker:
    name = "freshness"

    def run(
        self,
        *,
        report: str,
        sources: list[dict],
        contract: HarnessContract,
        context: dict | None = None,
    ) -> HarnessCheckResult:
        if not contract.freshness_required:
            return HarnessCheckResult(
                name=self.name,
                passed=True,
                score=1.0,
                severity="info",
                summary="Freshness was not required for this contract.",
            )

        now = _parse_datetime((context or {}).get("now")) or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        window_days = contract.freshness_window_days or 30

        dated_sources = []
        stale_sources = []
        for source in sources:
            published = _source_date(source)
            if published is None:
                continue
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            dated_sources.append(source)
            age_days = (now - published).days
            if age_days > window_days:
                stale_sources.append({"url": source.get("url"), "age_days": age_days})

        if not dated_sources:
            severity = "critical" if contract.mode == HarnessMode.GATE else "warning"
            return HarnessCheckResult(
                name=self.name,
                passed=False,
                score=0.5,
                severity=severity,
                summary="Freshness is required, but no source dates were available.",
                repairable=True,
                metadata={"freshness_window_days": window_days},
            )

        score = (len(dated_sources) - len(stale_sources)) / len(dated_sources)
        passed = score >= 1.0
        severity = "info" if passed else "critical" if contract.mode == HarnessMode.GATE else "warning"
        return HarnessCheckResult(
            name=self.name,
            passed=passed,
            score=float(score),
            severity=severity,
            summary=(
                "All dated sources satisfy the freshness window."
                if passed
                else f"{len(stale_sources)} dated source(s) exceed the freshness window."
            ),
            failed_items=stale_sources,
            repairable=not passed,
            metadata={
                "dated_source_count": len(dated_sources),
                "freshness_window_days": window_days,
            },
        )

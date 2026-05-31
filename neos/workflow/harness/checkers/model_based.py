from __future__ import annotations

from neos.workflow.harness.models import HarnessCheckResult, HarnessContract


class TopicCoverageChecker:
    name = "topic_coverage"

    def run(
        self,
        *,
        report: str,
        sources: list[dict],
        contract: HarnessContract,
        context: dict | None = None,
    ) -> HarnessCheckResult:
        topics = list(
            (contract.metadata or {}).get("coverage_requirements")
            or (context or {}).get("coverage_requirements")
            or []
        )
        if not topics:
            return HarnessCheckResult(
                name=self.name,
                passed=True,
                score=1.0,
                severity="info",
                summary="No topic coverage requirements configured.",
                metadata={"skipped": True},
            )

        lowered = report.lower()
        missing = [
            {"topic": topic}
            for topic in topics
            if str(topic).lower() not in lowered
        ]
        score = 1.0 - (len(missing) / max(1, len(topics)))
        return HarnessCheckResult(
            name=self.name,
            passed=not missing,
            score=max(score, 0.0),
            severity="warning",
            summary="Topic coverage requirements checked.",
            failed_items=missing,
            repairable=bool(missing),
            metadata={"required_topics": topics},
        )

from __future__ import annotations

from typing import Any

from neos.workflow.harness.models import HarnessCheckResult


CRITICAL_GRADERS = {
    "factual_accuracy",
    "factuality",
    "metadata_validation",
}

REPAIRABLE_GRADERS = {
    "citation_accuracy",
    "source_diversity",
    "structure_completeness",
    "topic_coverage",
    "quality_assessment",
    "factual_accuracy",
    "factuality",
    "bias_perspective",
}


def grader_result_to_harness_check(result: Any) -> HarnessCheckResult:
    grader_id = str(result.grader_id)
    severity = "critical" if grader_id in CRITICAL_GRADERS else "warning"
    details = dict(getattr(result, "details", {}) or {})
    return HarnessCheckResult(
        name=grader_id,
        passed=bool(result.passed),
        score=float(result.score),
        severity=severity,
        summary=str(getattr(result, "feedback", "") or grader_id),
        evidence=list(details.get("evidence") or []),
        failed_items=list(details.get("failed_items") or []),
        repairable=grader_id in REPAIRABLE_GRADERS,
        metadata=details,
    )

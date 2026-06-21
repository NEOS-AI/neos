from __future__ import annotations

from typing import Any

from neos.workflow.harness.models import HarnessCheckResult


def hyper_deep_metadata_checks(metadata: dict[str, Any]) -> list[HarnessCheckResult]:
    average_quality = float(metadata.get("average_section_quality") or 0.0)
    sections_refined = int(metadata.get("sections_refined") or 0)
    total_iterations = int(metadata.get("total_section_iterations") or 0)
    passed = average_quality >= 0.80

    return [
        HarnessCheckResult(
            name="hyperdeep_section_quality",
            passed=passed,
            score=average_quality,
            severity="info" if passed else "warning",
            summary=(
                "HyperDeep section quality meets the refinement threshold."
                if passed
                else "HyperDeep section quality is below the refinement threshold."
            ),
            failed_items=[] if passed else [{"average_section_quality": average_quality}],
            repairable=not passed,
            metadata={
                "sections_refined": sections_refined,
                "total_section_iterations": total_iterations,
                "threshold": 0.80,
            },
        )
    ]

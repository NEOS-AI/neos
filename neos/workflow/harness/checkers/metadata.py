from __future__ import annotations

from neos.workflow.harness.models import (
    HarnessCheckResult,
    HarnessContract,
    HarnessMode,
)


class MetadataIntegrityChecker:
    name = "metadata_integrity"

    def run(
        self,
        *,
        report: str,
        sources: list[dict],
        contract: HarnessContract,
        context: dict | None = None,
    ) -> HarnessCheckResult:
        context = context or {}
        if not (report or "").strip():
            return HarnessCheckResult(
                name=self.name,
                passed=False,
                score=0.0,
                severity="critical" if contract.mode == HarnessMode.GATE else "warning",
                summary="Final report text is empty.",
                repairable=False,
            )

        errors = context.get("errors") or []
        if errors:
            return HarnessCheckResult(
                name=self.name,
                passed=False,
                score=0.2,
                severity="critical" if contract.mode == HarnessMode.GATE else "warning",
                summary="Workflow metadata contains errors.",
                failed_items=[{"error": str(error)} for error in errors],
                repairable=False,
            )

        missing_metadata = [
            index
            for index, source in enumerate(sources)
            if not (source.get("url") or source.get("title") or source.get("id"))
        ]
        score = 1.0 if not missing_metadata else 0.8
        return HarnessCheckResult(
            name=self.name,
            passed=True,
            score=score,
            severity="info",
            summary="Workflow metadata is sufficient for harness verification.",
            evidence=[{"sources_missing_identity": len(missing_metadata)}],
        )


from __future__ import annotations

import uuid
from datetime import datetime

from .checkers import (
    CitationCoverageChecker,
    CitationValidityChecker,
    FreshnessChecker,
    MetadataIntegrityChecker,
    SourceCountChecker,
    SourceDiversityChecker,
)
from .models import (
    HarnessCheckResult,
    HarnessContract,
    HarnessMode,
    HarnessRun,
    HarnessVerdict,
)


DEFAULT_WEIGHTS = {
    "citation_coverage": 0.18,
    "citation_validity": 0.12,
    "source_diversity": 0.10,
    "source_count": 0.08,
    "freshness": 0.07,
    "metadata_integrity": 0.02,
}


class HarnessRunner:
    def __init__(self, checkers: list | None = None) -> None:
        self.checkers = checkers or [
            SourceCountChecker(),
            SourceDiversityChecker(),
            CitationValidityChecker(),
            CitationCoverageChecker(),
            FreshnessChecker(),
            MetadataIntegrityChecker(),
        ]

    def run(
        self,
        *,
        report: str,
        sources: list[dict],
        contract: HarnessContract,
        context: dict | None = None,
        repair_attempts: int = 0,
    ) -> HarnessRun:
        started_at = datetime.now()
        if contract.mode == HarnessMode.OFF:
            return HarnessRun(
                run_id=self._run_id(),
                mode=contract.mode,
                verdict=HarnessVerdict.SKIPPED,
                score=0.0,
                checks=[],
                failed_checks=[],
                repair_attempts=repair_attempts,
                started_at=started_at,
                completed_at=datetime.now(),
                metadata={"reason": "harness_off"},
            )

        checks = self._run_checks(
            report=report,
            sources=sources,
            contract=contract,
            context=context or {},
        )
        score = self._weighted_score(checks)
        failed_checks = [check.name for check in checks if not check.passed]
        verdict = self._determine_verdict(
            contract=contract,
            score=score,
            checks=checks,
            repair_attempts=repair_attempts,
        )

        return HarnessRun(
            run_id=self._run_id(),
            mode=contract.mode,
            verdict=verdict,
            score=score,
            checks=checks,
            failed_checks=failed_checks,
            repair_attempts=repair_attempts,
            started_at=started_at,
            completed_at=datetime.now(),
        )

    def _run_checks(
        self,
        *,
        report: str,
        sources: list[dict],
        contract: HarnessContract,
        context: dict,
    ) -> list[HarnessCheckResult]:
        selected = set(contract.required_checks or [])
        selected.update(contract.optional_checks or [])
        results: list[HarnessCheckResult] = []
        for checker in self.checkers:
            if selected and checker.name not in selected:
                continue
            results.append(
                checker.run(
                    report=report,
                    sources=sources,
                    contract=contract,
                    context=context,
                )
            )
        return results

    def _weighted_score(self, checks: list[HarnessCheckResult]) -> float:
        if not checks:
            return 0.0
        weights = [DEFAULT_WEIGHTS.get(check.name, 1.0) for check in checks]
        total_weight = sum(weights)
        if total_weight <= 0:
            return 0.0
        score = sum(check.score * weight for check, weight in zip(checks, weights))
        return float(score / total_weight)

    def _determine_verdict(
        self,
        *,
        contract: HarnessContract,
        score: float,
        checks: list[HarnessCheckResult],
        repair_attempts: int,
    ) -> HarnessVerdict:
        critical_failures = [
            check for check in checks if not check.passed and check.severity == "critical"
        ]
        required_failures = [
            check
            for check in checks
            if not check.passed and check.name in set(contract.required_checks or [])
        ]
        repairable_failures = [
            check for check in checks if not check.passed and check.repairable
        ]
        attempts_remaining = repair_attempts < contract.max_repair_attempts

        if contract.mode == HarnessMode.GATE and required_failures:
            if any(check.repairable for check in required_failures) and attempts_remaining:
                return HarnessVerdict.NEEDS_REPAIR
            return HarnessVerdict.FAIL
        if critical_failures and repairable_failures and attempts_remaining:
            return HarnessVerdict.NEEDS_REPAIR
        if critical_failures:
            return HarnessVerdict.FAIL
        if repairable_failures and attempts_remaining:
            return HarnessVerdict.NEEDS_REPAIR
        if contract.mode == HarnessMode.GATE:
            return HarnessVerdict.PASS if score >= contract.min_score else HarnessVerdict.FAIL
        if contract.mode == HarnessMode.ADVISORY:
            return (
                HarnessVerdict.ADVISORY_PASS
                if score >= contract.min_score
                else HarnessVerdict.FAIL
            )
        return HarnessVerdict.ADVISORY_PASS

    def _run_id(self) -> str:
        return f"harness-{uuid.uuid4()}"

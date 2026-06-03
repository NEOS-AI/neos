from __future__ import annotations

import uuid
from datetime import datetime

from .checkers import (
    CitationCoverageChecker,
    CitationValidityChecker,
    BiasPerspectiveChecker,
    FreshnessChecker,
    FactualityChecker,
    MetadataIntegrityChecker,
    PerformanceBudgetChecker,
    SourceCountChecker,
    SourceDiversityChecker,
    TopicCoverageChecker,
)
from .events import HarnessEventType
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
    "performance_budget": 0.03,
}


class HarnessRunner:
    def __init__(self, checkers: list | None = None) -> None:
        self.checkers = checkers if checkers is not None else [
            SourceCountChecker(),
            SourceDiversityChecker(),
            CitationValidityChecker(),
            CitationCoverageChecker(),
            FreshnessChecker(),
            MetadataIntegrityChecker(),
            PerformanceBudgetChecker(),
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
            return self._skipped_run(started_at, contract, repair_attempts)

        checks = self._run_checks(
            report=report,
            sources=sources,
            contract=contract,
            context=context or {},
        )
        return self._build_run(
            started_at=started_at,
            contract=contract,
            checks=checks,
            repair_attempts=repair_attempts,
        )

    async def arun(
        self,
        *,
        report: str,
        sources: list[dict],
        contract: HarnessContract,
        context: dict | None = None,
        repair_attempts: int = 0,
        event_callback: object | None = None,
    ) -> HarnessRun:
        started_at = datetime.now()
        if contract.mode == HarnessMode.OFF:
            return self._skipped_run(started_at, contract, repair_attempts)

        checks = await self._arun_checks(
            report=report,
            sources=sources,
            contract=contract,
            context=context or {},
            event_callback=event_callback,
        )
        return self._build_run(
            started_at=started_at,
            contract=contract,
            checks=checks,
            repair_attempts=repair_attempts,
        )

    def _run_checks(
        self,
        *,
        report: str,
        sources: list[dict],
        contract: HarnessContract,
        context: dict,
    ) -> list[HarnessCheckResult]:
        checkers, missing_results = self._selected_checkers(contract)
        results: list[HarnessCheckResult] = list(missing_results)
        for checker in checkers:
            results.append(
                checker.run(
                    report=report,
                    sources=sources,
                    contract=contract,
                    context=context,
                )
            )
        return results

    async def _arun_checks(
        self,
        *,
        report: str,
        sources: list[dict],
        contract: HarnessContract,
        context: dict,
        event_callback: object | None = None,
    ) -> list[HarnessCheckResult]:
        checkers, missing_results = self._selected_checkers(contract)
        results: list[HarnessCheckResult] = list(missing_results)
        for checker in checkers:
            if event_callback is not None:
                await event_callback(
                    HarnessEventType.CHECK_STARTED,
                    {
                        "check": checker.name,
                        "mode": contract.mode.value,
                    },
                )
            arun = getattr(checker, "arun", None)
            if arun is not None:
                result = await arun(
                    report=report,
                    sources=sources,
                    contract=contract,
                    context=context,
                )
            else:
                result = checker.run(
                    report=report,
                    sources=sources,
                    contract=contract,
                    context=context,
                )
            results.append(result)
            if event_callback is not None:
                await event_callback(
                    HarnessEventType.CHECK_COMPLETED,
                    {
                        "check": result.name,
                        "passed": result.passed,
                        "score": float(result.score),
                        "severity": result.severity,
                    },
                )
        return results

    def _selected_checkers(
        self, contract: HarnessContract
    ) -> tuple[list[object], list[HarnessCheckResult]]:
        selected = set(contract.required_checks or [])
        selected.update(contract.optional_checks or [])
        checkers = list(self.checkers)
        if selected and "topic_coverage" in selected and not any(
            checker.name == "topic_coverage" for checker in checkers
        ):
            checkers.append(TopicCoverageChecker())
        if selected and "factuality" in selected and not any(
            checker.name == "factuality" for checker in checkers
        ):
            checkers.append(FactualityChecker())
        if selected and "bias_perspective" in selected and not any(
            checker.name == "bias_perspective" for checker in checkers
        ):
            checkers.append(BiasPerspectiveChecker())
        available = set(self._checkers_by_name(checkers))
        results: list[HarnessCheckResult] = []
        results.extend(
            self._missing_required_check_results(
                selected=selected,
                available=available,
                contract=contract,
            )
        )
        selected_checkers = [
            checker for checker in checkers if not selected or checker.name in selected
        ]
        return selected_checkers, results

    def _skipped_run(
        self,
        started_at: datetime,
        contract: HarnessContract,
        repair_attempts: int,
    ) -> HarnessRun:
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

    def _build_run(
        self,
        *,
        started_at: datetime,
        contract: HarnessContract,
        checks: list[HarnessCheckResult],
        repair_attempts: int,
    ) -> HarnessRun:
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

    def _checkers_by_name(self, checkers: list) -> dict[str, object]:
        return {checker.name: checker for checker in checkers}

    def _missing_required_check_results(
        self,
        *,
        selected: set[str],
        available: set[str],
        contract: HarnessContract,
    ) -> list[HarnessCheckResult]:
        missing = sorted(set(contract.required_checks or []) - available)
        return [
            HarnessCheckResult(
                name=name,
                passed=False,
                score=0.0,
                severity="critical" if contract.mode == HarnessMode.GATE else "warning",
                summary=f"Required harness check is not available: {name}",
                repairable=False,
                metadata={"missing_required_check": True},
            )
            for name in missing
            if not selected or name in selected
        ]

    def _weighted_score(self, checks: list[HarnessCheckResult]) -> float:
        if not checks:
            return 0.0
        scored_checks = [
            check for check in checks if not check.metadata.get("skipped")
        ]
        if not scored_checks:
            return 1.0 if all(check.passed for check in checks) else 0.0
        checks = scored_checks
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

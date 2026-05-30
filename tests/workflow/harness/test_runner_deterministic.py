from neos.workflow.harness.models import (
    HarnessCheckResult,
    HarnessContract,
    HarnessMode,
    HarnessRiskLevel,
    HarnessVerdict,
)
from neos.workflow.harness.runner import HarnessRunner


class StaticChecker:
    def __init__(self, result):
        self.name = result.name
        self._result = result

    def run(self, *, report, sources, contract, context=None):
        return self._result


def gate_contract(**overrides):
    values = {
        "mode": HarnessMode.GATE,
        "risk_level": HarnessRiskLevel.MEDIUM,
        "min_score": 0.82,
        "max_repair_attempts": 1,
    }
    values.update(overrides)
    return HarnessContract(**values)


def check(name, *, passed=True, score=1.0, severity="info", repairable=False):
    return HarnessCheckResult(
        name=name,
        passed=passed,
        score=score,
        severity=severity,
        summary=f"{name} summary",
        repairable=repairable,
    )


def test_runner_passes_when_required_checks_pass():
    runner = HarnessRunner(checkers=[StaticChecker(check("source_count", score=0.95))])

    run = runner.run(
        report="answer [1]",
        sources=[{"id": "1", "url": "https://a.com"}],
        contract=gate_contract(),
    )

    assert run.verdict == HarnessVerdict.PASS
    assert run.score >= 0.82


def test_runner_returns_needs_repair_for_repairable_gate_failure():
    runner = HarnessRunner(
        checkers=[
            StaticChecker(
                check(
                    "citation_coverage",
                    passed=False,
                    score=0.4,
                    severity="critical",
                    repairable=True,
                )
            )
        ]
    )

    run = runner.run(
        report="answer",
        sources=[],
        contract=gate_contract(max_repair_attempts=1),
        repair_attempts=0,
    )

    assert run.verdict == HarnessVerdict.NEEDS_REPAIR
    assert "citation_coverage" in run.failed_checks


def test_runner_fails_gate_when_score_below_threshold_after_attempts_exhausted():
    runner = HarnessRunner(
        checkers=[
            StaticChecker(
                check(
                    "citation_coverage",
                    passed=False,
                    score=0.4,
                    severity="critical",
                    repairable=True,
                )
            )
        ]
    )

    run = runner.run(
        report="answer",
        sources=[],
        contract=gate_contract(max_repair_attempts=1),
        repair_attempts=1,
    )

    assert run.verdict == HarnessVerdict.FAIL


def test_failed_required_warning_check_cannot_pass_gate_by_weighted_score():
    runner = HarnessRunner(
        checkers=[
            StaticChecker(
                check(
                    "freshness",
                    passed=False,
                    score=0.99,
                    severity="warning",
                    repairable=False,
                )
            )
        ]
    )

    run = runner.run(
        report="latest answer [1]",
        sources=[{"id": "1", "url": "https://a.com"}],
        contract=gate_contract(required_checks=["freshness"]),
        repair_attempts=1,
    )

    assert run.verdict == HarnessVerdict.FAIL


def test_failed_required_repairable_check_requests_repair_when_attempts_remain():
    runner = HarnessRunner(
        checkers=[
            StaticChecker(
                check(
                    "freshness",
                    passed=False,
                    score=0.99,
                    severity="warning",
                    repairable=True,
                )
            )
        ]
    )

    run = runner.run(
        report="latest answer [1]",
        sources=[{"id": "1", "url": "https://a.com"}],
        contract=gate_contract(required_checks=["freshness"], max_repair_attempts=1),
        repair_attempts=0,
    )

    assert run.verdict == HarnessVerdict.NEEDS_REPAIR

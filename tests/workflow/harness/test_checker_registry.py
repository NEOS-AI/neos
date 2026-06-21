from neos.workflow.harness.models import (
    HarnessContract,
    HarnessMode,
    HarnessRiskLevel,
    HarnessVerdict,
)
from neos.workflow.harness.runner import HarnessRunner


def test_gate_fails_explicitly_when_required_checker_is_missing():
    run = HarnessRunner(checkers=[]).run(
        report="Claim [1].",
        sources=[{"id": "1", "title": "Source", "url": "https://example.com"}],
        contract=HarnessContract(
            mode=HarnessMode.GATE,
            risk_level=HarnessRiskLevel.HIGH,
            min_score=0.82,
            required_checks=["unregistered_check"],
            max_repair_attempts=0,
        ),
        context={},
    )

    assert run.verdict == HarnessVerdict.FAIL
    assert run.failed_checks == ["unregistered_check"]
    assert run.checks[0].name == "unregistered_check"
    assert run.checks[0].severity == "critical"
    assert "not available" in run.checks[0].summary


def test_optional_missing_checker_is_not_materialized_as_failure():
    run = HarnessRunner(checkers=[]).run(
        report="Claim [1].",
        sources=[{"id": "1", "title": "Source", "url": "https://example.com"}],
        contract=HarnessContract(
            mode=HarnessMode.ADVISORY,
            risk_level=HarnessRiskLevel.LOW,
            min_score=0.0,
            optional_checks=["bias_perspective"],
        ),
        context={},
    )

    assert run.failed_checks == []
    assert run.verdict == HarnessVerdict.ADVISORY_PASS

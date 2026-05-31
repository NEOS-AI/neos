from neos.workflow.harness.checkers.model_based import (
    TopicCoverageChecker,
)
from neos.workflow.harness.models import (
    HarnessContract,
    HarnessMode,
    HarnessRiskLevel,
)


def test_topic_coverage_checker_skips_without_coverage_requirements():
    checker = TopicCoverageChecker()
    result = checker.run(
        report="A complete answer",
        sources=[],
        contract=HarnessContract(
            mode=HarnessMode.ADVISORY,
            risk_level=HarnessRiskLevel.LOW,
            min_score=0.7,
        ),
        context={},
    )

    assert result.name == "topic_coverage"
    assert result.passed is True
    assert result.metadata["skipped"] is True


def test_topic_coverage_checker_fails_missing_required_topics():
    checker = TopicCoverageChecker()
    result = checker.run(
        report="This only discusses pricing.",
        sources=[],
        contract=HarnessContract(
            mode=HarnessMode.GATE,
            risk_level=HarnessRiskLevel.MEDIUM,
            min_score=0.82,
            required_checks=["topic_coverage"],
            metadata={"coverage_requirements": ["pricing", "security"]},
        ),
        context={},
    )

    assert result.passed is False
    assert result.repairable is True
    assert "security" in result.failed_items[0]["topic"]

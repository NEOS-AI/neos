from neos.workflow.harness.checkers.model_based import (
    BiasPerspectiveChecker,
    FactualityChecker,
    TopicCoverageChecker,
)
from neos.workflow.harness.checkers.model_judge import parse_judge_json
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


class PassingJudge:
    async def judge(self, prompt, *, timeout_seconds):
        return {
            "score": 0.94,
            "passed": True,
            "failed_items": [],
            "evidence": [{"claim": "The cited claim is supported."}],
            "summary": "All sampled claims are supported.",
        }


class FailingJudge:
    async def judge(self, prompt, *, timeout_seconds):
        return {
            "score": 0.35,
            "passed": False,
            "failed_items": [
                {
                    "claim": "Unsupported market-share claim",
                    "reason": "No source supports this claim.",
                }
            ],
            "evidence": [],
            "summary": "Unsupported claims were found.",
        }


def factuality_contract(**overrides):
    values = {
        "mode": HarnessMode.GATE,
        "risk_level": HarnessRiskLevel.HIGH,
        "min_score": 0.82,
        "required_checks": ["factuality"],
    }
    values.update(overrides)
    return HarnessContract(**values)


def bias_contract(**overrides):
    values = {
        "mode": HarnessMode.ADVISORY,
        "risk_level": HarnessRiskLevel.HIGH,
        "min_score": 0.7,
        "optional_checks": ["bias_perspective"],
        "high_risk_categories": ["market_analysis"],
    }
    values.update(overrides)
    return HarnessContract(**values)


async def test_factuality_checker_passes_with_fake_judge():
    result = await FactualityChecker(judge=PassingJudge()).arun(
        report="Supported claim [1].",
        sources=[
            {
                "id": "1",
                "title": "Source",
                "url": "https://example.com",
                "content": "Supported claim.",
            }
        ],
        contract=factuality_contract(),
        context={},
    )

    assert result.name == "factuality"
    assert result.passed is True
    assert result.score == 0.94
    assert result.evidence[0]["claim"] == "The cited claim is supported."


async def test_factuality_checker_fails_gate_with_repairable_unsupported_claims():
    result = await FactualityChecker(judge=FailingJudge()).arun(
        report="Unsupported market-share claim [1].",
        sources=[
            {
                "id": "1",
                "title": "Source",
                "url": "https://example.com",
                "content": "Different evidence.",
            }
        ],
        contract=factuality_contract(),
        context={},
    )

    assert result.passed is False
    assert result.severity == "critical"
    assert result.repairable is True
    assert result.failed_items[0]["claim"] == "Unsupported market-share claim"


async def test_factuality_checker_optional_gate_fail_is_warning():
    result = await FactualityChecker(judge=FailingJudge()).arun(
        report="Unsupported market-share claim [1].",
        sources=[
            {
                "id": "1",
                "title": "Source",
                "url": "https://example.com",
                "content": "Different evidence.",
            }
        ],
        contract=factuality_contract(
            required_checks=[],
            optional_checks=["factuality"],
        ),
        context={},
    )

    assert result.passed is False
    assert result.severity == "warning"
    assert result.repairable is True
    assert result.failed_items[0]["claim"] == "Unsupported market-share claim"


async def test_factuality_checker_required_gate_fails_when_model_checks_disabled():
    result = await FactualityChecker(
        judge=PassingJudge(),
        model_checks_enabled=False,
    ).arun(
        report="Supported claim [1].",
        sources=[],
        contract=factuality_contract(),
        context={},
    )

    assert result.passed is False
    assert result.severity == "critical"
    assert result.metadata["reason"] == "model_checks_disabled"


async def test_factuality_checker_optional_skips_when_model_checks_disabled():
    result = await FactualityChecker(
        judge=PassingJudge(),
        model_checks_enabled=False,
    ).arun(
        report="Supported claim [1].",
        sources=[],
        contract=factuality_contract(
            mode=HarnessMode.ADVISORY,
            risk_level=HarnessRiskLevel.LOW,
            min_score=0.0,
            required_checks=[],
            optional_checks=["factuality"],
        ),
        context={},
    )

    assert result.passed is True
    assert result.metadata == {"skipped": True, "reason": "model_checks_disabled"}


def test_parse_judge_json_accepts_fenced_json():
    parsed = parse_judge_json(
        """```json
        {"score": 0.9, "passed": true, "failed_items": [], "evidence": [], "summary": "ok"}
        ```"""
    )

    assert parsed["passed"] is True
    assert parsed["score"] == 0.9


class PassingBiasJudge:
    async def judge(self, prompt, *, timeout_seconds):
        return {
            "score": 0.88,
            "passed": True,
            "failed_items": [],
            "evidence": [{"perspective": "Multiple stakeholder perspectives represented."}],
            "summary": "Perspective balance is acceptable.",
        }


class FailingBiasJudge:
    async def judge(self, prompt, *, timeout_seconds):
        return {
            "score": 0.45,
            "passed": False,
            "failed_items": [
                {
                    "issue": "single_perspective",
                    "reason": "Report relies on vendor claims without independent counterpoints.",
                }
            ],
            "summary": "The report lacks perspective diversity.",
        }


async def test_bias_perspective_checker_passes_with_fake_judge():
    result = await BiasPerspectiveChecker(judge=PassingBiasJudge()).arun(
        report="The report compares vendors, customers, and regulators.",
        sources=[{"id": "1", "domain": "example.com", "content": "balanced view"}],
        contract=bias_contract(),
        context={},
    )

    assert result.name == "bias_perspective"
    assert result.passed is True
    assert result.score == 0.88
    assert result.evidence[0]["perspective"] == "Multiple stakeholder perspectives represented."


async def test_bias_perspective_checker_fails_with_repairable_balance_issue():
    result = await BiasPerspectiveChecker(judge=FailingBiasJudge()).arun(
        report="The report repeats one vendor's claims.",
        sources=[{"id": "1", "domain": "vendor.example", "content": "vendor view"}],
        contract=bias_contract(mode=HarnessMode.GATE, required_checks=["bias_perspective"], optional_checks=[]),
        context={},
    )

    assert result.passed is False
    assert result.severity == "critical"
    assert result.repairable is True
    assert result.failed_items[0]["issue"] == "single_perspective"

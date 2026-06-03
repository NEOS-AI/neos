from neos.workflow.harness.adapters.neos_evals import (
    grader_result_to_harness_check,
)
from neos_evals.graders.base import GraderResult


def test_converts_grader_result_to_harness_check_result():
    result = GraderResult(
        grader_id="citation_accuracy",
        score=0.92,
        passed=True,
        feedback="citations valid",
        details={"total_citations": 10},
    )

    check = grader_result_to_harness_check(result)

    assert check.name == "citation_accuracy"
    assert check.passed is True
    assert check.score == 0.92
    assert check.summary == "citations valid"
    assert check.metadata["total_citations"] == 10


def test_failed_model_grader_is_repairable_warning_by_default():
    result = GraderResult(
        grader_id="topic_coverage",
        score=0.55,
        passed=False,
        feedback="missing competitor section",
        details={"grader_type": "model"},
    )

    check = grader_result_to_harness_check(result)

    assert check.severity == "warning"
    assert check.repairable is True


def test_factuality_grader_is_critical_and_repairable():
    result = GraderResult(
        grader_id="factuality",
        score=0.3,
        passed=False,
        feedback="unsupported claims",
        details={"failed_items": [{"claim": "unsupported"}]},
    )

    check = grader_result_to_harness_check(result)

    assert check.severity == "critical"
    assert check.repairable is True


def test_bias_perspective_grader_is_repairable_warning():
    result = GraderResult(
        grader_id="bias_perspective",
        score=0.45,
        passed=False,
        feedback="single perspective",
        details={"failed_items": [{"issue": "single_perspective"}]},
    )

    check = grader_result_to_harness_check(result)

    assert check.severity == "warning"
    assert check.repairable is True

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

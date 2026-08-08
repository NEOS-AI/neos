from dataclasses import dataclass, field
from typing import Any

from neos.workflow.harness.adapters.neos_evals import (
    grader_result_to_harness_check,
)


@dataclass
class GraderResult:
    """`neos_evals.graders.base.GraderResult` 를 대신하는 최소 스텁.

    `neos_evals` 패키지는 2026-08-08 에 저장소에서 제거됐다(`6b397713`).
    어댑터(`adapters/neos_evals.py`)는 그 패키지를 import 하지 않고 `Any` 를
    형태로만 읽으므로 살아 있다 -- 그래서 이 테스트도 살릴 수 있다.
    스텁이 노출하는 필드가 곧 어댑터가 의존하는 계약이다.
    """

    grader_id: str
    score: float
    passed: bool
    feedback: str = ""
    details: dict[str, Any] = field(default_factory=dict)


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

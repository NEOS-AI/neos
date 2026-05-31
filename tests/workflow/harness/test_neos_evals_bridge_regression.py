from neos.workflow.harness.adapters.neos_evals import (
    grader_result_to_harness_check,
)
from neos.workflow.harness.models import (
    HarnessContract,
    HarnessMode,
    HarnessRiskLevel,
    HarnessVerdict,
)
from neos.workflow.harness.runner import HarnessRunner
from neos_evals.graders.base import GraderResult


class StaticChecker:
    def __init__(self, result):
        self.name = result.name
        self.result = result

    def run(self, **kwargs):
        return self.result


def test_offline_grader_results_drive_gate_failure():
    checks = [
        grader_result_to_harness_check(
            GraderResult(
                grader_id="factual_accuracy",
                score=0.4,
                passed=False,
                feedback="unsupported claims",
                details={},
            )
        )
    ]
    runner = HarnessRunner(checkers=[StaticChecker(check) for check in checks])

    run = runner.run(
        report="answer",
        sources=[],
        contract=HarnessContract(
            mode=HarnessMode.GATE,
            risk_level=HarnessRiskLevel.HIGH,
            min_score=0.9,
            max_repair_attempts=0,
        ),
    )

    assert run.verdict == HarnessVerdict.FAIL

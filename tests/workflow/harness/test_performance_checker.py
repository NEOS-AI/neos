from neos.workflow.harness.adapters.workflow_state import extract_context
from neos.workflow.harness.checkers.performance import PerformanceBudgetChecker
from neos.workflow.harness.models import HarnessContract, HarnessMode, HarnessRiskLevel


def budget_contract(**metadata):
    return HarnessContract(
        mode=HarnessMode.GATE,
        risk_level=HarnessRiskLevel.MEDIUM,
        min_score=0.82,
        optional_checks=["performance_budget"],
        metadata=metadata,
    )


def test_performance_checker_fails_when_context_exceeds_budget():
    result = PerformanceBudgetChecker().run(
        report="Report",
        sources=[],
        contract=budget_contract(
            max_processing_time_ms=120000,
            max_validation_latency_ms=30000,
            max_repair_attempts_observed=1,
        ),
        context={
            "processing_time_ms": 150000,
            "validation_latency_ms": 18000,
            "repair_attempts": 0,
        },
    )

    assert result.name == "performance_budget"
    assert result.passed is False
    assert result.failed_items[0]["metric"] == "processing_time_ms"
    assert result.repairable is False


def test_performance_checker_skips_when_no_budgets_configured():
    result = PerformanceBudgetChecker().run(
        report="Report",
        sources=[],
        contract=budget_contract(),
        context={"processing_time_ms": 150000},
    )

    assert result.passed is True
    assert result.metadata["skipped"] is True


def test_workflow_context_includes_operational_metadata():
    context = extract_context(
        {
            "processing_time_ms": 1234,
            "token_usage": {"total_tokens": 99},
            "llm_call_count": 3,
            "harness_repair_attempts": 1,
        }
    )

    assert context["processing_time_ms"] == 1234
    assert context["token_usage"] == {"total_tokens": 99}
    assert context["llm_call_count"] == 3
    assert context["harness_repair_attempts"] == 1

from neos.workflow.harness.models import (
    HarnessCheckResult,
    HarnessContract,
    HarnessMode,
    HarnessRiskLevel,
)
from neos.workflow.harness.repair import HarnessRepairPlanner


def gate_contract(**overrides):
    values = {
        "mode": HarnessMode.GATE,
        "risk_level": HarnessRiskLevel.MEDIUM,
        "min_score": 0.82,
        "max_repair_attempts": 2,
    }
    values.update(overrides)
    return HarnessContract(**values)


def failed_check(name, *, repairable=True, severity="warning"):
    return HarnessCheckResult(
        name=name,
        passed=False,
        score=0.2,
        severity=severity,
        summary=f"{name} failed",
        failed_items=[{"reason": f"{name}_reason"}],
        repairable=repairable,
    )


def test_planner_maps_source_count_to_more_sources_action():
    planner = HarnessRepairPlanner()
    plan = planner.plan(
        contract=gate_contract(min_sources=5),
        failed_checks=[failed_check("source_count")],
        attempt=1,
        context={"original_query": "AI browser market"},
    )

    assert plan is not None
    assert plan.attempt == 1
    assert [action.action_type for action in plan.actions] == ["request_more_sources"]
    assert plan.actions[0].params["min_sources"] == 5


def test_planner_maps_source_diversity_to_independent_domain_search():
    planner = HarnessRepairPlanner()
    plan = planner.plan(
        contract=gate_contract(),
        failed_checks=[failed_check("source_diversity")],
        attempt=1,
        context={"dominant_domains": ["example.com"]},
    )

    assert plan is not None
    assert plan.actions[0].action_type == "search_independent_domains"
    assert plan.actions[0].params["avoid_domains"] == ["example.com"]


def test_planner_maps_citation_failures_to_citation_regeneration():
    planner = HarnessRepairPlanner()
    plan = planner.plan(
        contract=gate_contract(),
        failed_checks=[
            failed_check("citation_validity"),
            failed_check("citation_coverage"),
        ],
        attempt=1,
        context={},
    )

    assert plan is not None
    assert [action.action_type for action in plan.actions] == [
        "rebuild_citation_map",
        "regenerate_cited_sections",
    ]


def test_planner_maps_freshness_to_date_constrained_search():
    planner = HarnessRepairPlanner()
    plan = planner.plan(
        contract=gate_contract(freshness_required=True, freshness_window_days=30),
        failed_checks=[failed_check("freshness", severity="critical")],
        attempt=1,
        context={"original_query": "latest AI regulation"},
    )

    assert plan is not None
    assert plan.actions[0].action_type == "date_constrained_freshness_search"
    assert plan.actions[0].params["freshness_window_days"] == 30


def test_planner_returns_none_when_failures_are_not_repairable():
    planner = HarnessRepairPlanner()
    plan = planner.plan(
        contract=gate_contract(),
        failed_checks=[failed_check("metadata_integrity", repairable=False)],
        attempt=1,
        context={},
    )

    assert plan is None

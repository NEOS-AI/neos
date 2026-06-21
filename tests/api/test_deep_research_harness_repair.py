import pytest

from neos.api.services.deep_research_repair_service import (
    DeepResearchRepairService,
    RepairActionResult,
)
from neos.workflow.harness.models import (
    HarnessCheckResult,
    HarnessContract,
    HarnessMode,
    HarnessRiskLevel,
)


def gate_contract(**overrides):
    values = {
        "mode": HarnessMode.GATE,
        "risk_level": HarnessRiskLevel.HIGH,
        "min_score": 0.82,
        "required_checks": ["citation_coverage"],
        "max_repair_attempts": 1,
    }
    values.update(overrides)
    return HarnessContract(**values)


def failed_check(name="citation_coverage", *, repairable=True):
    return HarnessCheckResult(
        name=name,
        passed=False,
        score=0.2,
        severity="critical",
        summary=f"{name} failed",
        failed_items=[{"section": "Summary"}],
        repairable=repairable,
    )


@pytest.mark.asyncio
async def test_repair_service_executes_planned_actions_with_injected_executor():
    calls = []

    async def fake_executor(*, report_id, action, context):
        calls.append((report_id, action.action_type, context["research_topic"]))
        return {"status": "executed", "updated_sections": ["Summary"]}

    result = await DeepResearchRepairService(action_executor=fake_executor).repair(
        report_id="report-1",
        research_topic="AI market",
        contract=gate_contract(),
        failed_checks=[failed_check()],
        attempt=1,
        context={"research_topic": "AI market"},
    )

    assert calls == [("report-1", "regenerate_cited_sections", "AI market")]
    assert result["executed_actions"][0]["action_type"] == "regenerate_cited_sections"
    assert result["executed_actions"][0]["status"] == "executed"


@pytest.mark.asyncio
async def test_repair_service_normalizes_structured_action_result():
    async def fake_executor(*, report_id, action, context):
        return RepairActionResult(
            status="executed",
            added_sources=1,
            updated_sections=["section-1"],
            metadata={"provider": "fake-search"},
        )

    result = await DeepResearchRepairService(action_executor=fake_executor).repair(
        report_id="report-1",
        research_topic="AI market",
        contract=gate_contract(),
        failed_checks=[failed_check()],
        attempt=1,
        context={"research_topic": "AI market"},
    )

    action = result["executed_actions"][0]
    assert action["action_type"] == "regenerate_cited_sections"
    assert action["target_check"] == "citation_coverage"
    assert action["status"] == "executed"
    assert action["added_sources"] == 1
    assert action["updated_sections"] == ["section-1"]
    assert action["provider"] == "fake-search"


@pytest.mark.asyncio
async def test_repair_service_skips_when_attempts_are_exhausted():
    result = await DeepResearchRepairService().repair(
        report_id="report-1",
        research_topic="AI market",
        contract=gate_contract(max_repair_attempts=1),
        failed_checks=[failed_check()],
        attempt=2,
        context={},
    )

    assert result["executed_actions"] == []
    assert result["skipped_actions"][0]["reason"] == "attempts_exhausted"


@pytest.mark.asyncio
async def test_repair_service_skips_unrepairable_failures():
    result = await DeepResearchRepairService().repair(
        report_id="report-1",
        research_topic="AI market",
        contract=gate_contract(),
        failed_checks=[failed_check(repairable=False)],
        attempt=1,
        context={},
    )

    assert result["executed_actions"] == []
    assert result["skipped_actions"] == []

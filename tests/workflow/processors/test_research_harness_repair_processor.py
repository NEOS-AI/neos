import pytest

from neos.workflow.processors.research_harness_repair_processor import (
    ResearchHarnessRepairProcessor,
)


@pytest.mark.asyncio
async def test_repair_processor_builds_plan_and_increments_attempts():
    processor = ResearchHarnessRepairProcessor()
    state = {
        "original_query": "latest AI policy",
        "harness_mode": "gate",
        "harness_verdict": "needs_repair",
        "harness_contract": {
            "mode": "gate",
            "risk_level": "medium",
            "min_score": 0.82,
            "min_sources": 3,
            "freshness_required": True,
            "freshness_window_days": 30,
            "max_repair_attempts": 2,
        },
        "harness_metadata": {
            "check_results": [
                {
                    "name": "freshness",
                    "passed": False,
                    "score": 0.0,
                    "severity": "critical",
                    "summary": "freshness failed",
                    "repairable": True,
                    "failed_items": [],
                    "metadata": {},
                }
            ]
        },
        "harness_repair_attempts": 0,
        "execution_steps": [],
        "required_agents": [],
    }

    updates = await processor.process(state)

    assert updates["harness_repair_attempts"] == 1
    assert updates["harness_repair_plan"]["actions"][0]["action_type"] == (
        "date_constrained_freshness_search"
    )
    assert "realtime_info_search" in updates["required_agents"]


@pytest.mark.asyncio
async def test_repair_processor_does_not_plan_after_budget_exhausted():
    processor = ResearchHarnessRepairProcessor()
    state = {
        "original_query": "topic",
        "harness_mode": "gate",
        "harness_verdict": "needs_repair",
        "harness_contract": {
            "mode": "gate",
            "risk_level": "medium",
            "min_score": 0.82,
            "max_repair_attempts": 1,
        },
        "harness_metadata": {"check_results": []},
        "harness_repair_attempts": 1,
        "execution_steps": [],
        "required_agents": [],
    }

    updates = await processor.process(state)

    assert updates["harness_repair_plan"] is None
    assert "research_harness_repair_exhausted" in updates["errors"]

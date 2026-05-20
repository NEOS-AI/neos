import pytest

from neos.workflow.enums import AutonomyLevel, IntentType
from neos.workflow.mission.approval import build_mission_approval_request
from neos.workflow.mission.planner import MissionPlanner


@pytest.mark.asyncio
async def test_planner_creates_plan_and_contract_for_comparison_request():
    planner = MissionPlanner()
    state = {
        "session_id": "session-1",
        "user_id": "user-1",
        "original_query": "2026 AI browser market compare and analyze",
        "query_intent": IntentType.COMPLEX_ANALYSIS.value,
        "query_classification": {"complexity_score": 0.82},
        "required_agents": ["realtime_info_search", "comparative_analysis"],
        "selected_skills": [],
        "selected_tools": [],
        "autonomy_level": AutonomyLevel.ASSISTED.value,
    }

    result = await planner.plan(state)

    assert result["mission"]["status"] == "planned"
    assert result["mission_plan"]["tasks"][0]["required_capability"] == "web_search"
    assert result["validation_contract"]["required_sources"] >= 3
    assert result["mission_plan"]["execution_policy"]["mode"] == "serial"


@pytest.mark.asyncio
async def test_manual_plan_status_awaits_approval():
    planner = MissionPlanner()
    state = {
        "session_id": "session-1",
        "user_id": "user-1",
        "original_query": "latest AI news",
        "query_intent": IntentType.REALTIME_INFO.value,
        "query_classification": {"complexity_score": 0.3},
        "required_agents": ["realtime_info_search"],
        "autonomy_level": AutonomyLevel.MANUAL.value,
    }

    result = await planner.plan(state)

    assert result["mission"]["status"] == "awaiting_approval"
    assert result["pending_approvals"][0]["skill_name"] == "mission_runtime"


@pytest.mark.asyncio
async def test_planner_maps_recursive_intent_to_recursive_task_capability():
    planner = MissionPlanner()
    state = {
        "session_id": "session-1",
        "user_id": "user-1",
        "original_query": "recursively research the market structure",
        "query_intent": IntentType.RECURSIVE_RESEARCH.value,
        "query_classification": {"complexity_score": 0.9},
        "required_agents": ["deep_research"],
        "autonomy_level": AutonomyLevel.ASSISTED.value,
    }

    result = await planner.plan(state)

    assert result["mission"]["mission_type"] == "recursive"
    assert result["mission_plan"]["tasks"][0]["required_capability"] == "recursive"


@pytest.mark.asyncio
async def test_planner_maps_hyper_deep_intent_to_hyper_deep_task_capability():
    planner = MissionPlanner()
    state = {
        "session_id": "session-1",
        "user_id": "user-1",
        "original_query": "hyper deep research the whole AI browser market",
        "query_intent": IntentType.HYPER_DEEP_RESEARCH.value,
        "query_classification": {"complexity_score": 0.95},
        "required_agents": ["deep_research"],
        "autonomy_level": AutonomyLevel.ASSISTED.value,
    }

    result = await planner.plan(state)

    assert result["mission"]["mission_type"] == "hyper_deep"
    assert result["mission_plan"]["tasks"][0]["required_capability"] == "hyper_deep"


def test_mission_approval_payload_includes_plan_and_contract():
    pending = build_mission_approval_request(
        mission_id="mission-1",
        plan={
            "user_visible_summary": "Search, compare, validate.",
            "tasks": [
                {
                    "task_id": "task-1",
                    "description": "Collect sources",
                    "suggested_agent": "realtime_info_search",
                    "risk_level": "low",
                }
            ],
        },
        contract={
            "success_criteria": ["Include citations."],
            "required_sources": 3,
            "min_quality_score": 0.8,
        },
        timeout_seconds=300,
    )

    assert pending["skill_name"] == "mission_runtime"
    assert pending["params"]["mission_id"] == "mission-1"
    assert pending["params"]["validation_contract"]["required_sources"] == 3

from neos.workflow.enums import AutonomyLevel
from neos.workflow.mission.models import (
    Mission,
    MissionPlan,
    MissionStatus,
    MissionTask,
    MissionTaskStatus,
    MissionType,
    RiskLevel,
    ValidationContract,
)
from neos.workflow.mission.events import MissionEventName, build_mission_event


def test_mission_plan_serializes_to_plain_dict():
    task = MissionTask(
        task_id="task-1",
        mission_id="mission-1",
        parent_task_id=None,
        description="Collect current product information",
        required_capability="web_search",
        suggested_agent="realtime_info_search",
        inputs={"query": "AI browser market"},
        depends_on=[],
        expected_output_type="search_results",
        expected_artifact="current product facts",
        risk_level=RiskLevel.LOW,
        status=MissionTaskStatus.PLANNED,
    )
    plan = MissionPlan(
        mission_id="mission-1",
        objective="Compare AI browser products",
        assumptions=["Current information must be verified."],
        constraints=["Use serial execution in v1."],
        tasks=[task],
        execution_policy={"mode": "serial"},
        budget={"max_tasks": 5},
        timeout=300,
        user_visible_summary="Collect sources, compare products, validate citations.",
    )

    data = plan.to_state()

    assert data["mission_id"] == "mission-1"
    assert data["tasks"][0]["required_capability"] == "web_search"
    assert data["tasks"][0]["risk_level"] == "low"


def test_validation_contract_hash_changes_when_criteria_change():
    base = ValidationContract(
        contract_id="contract-1",
        mission_id="mission-1",
        success_criteria=["Include a comparison table."],
        required_sources=3,
        freshness_requirement="current",
        citation_requirement="major_claims",
        factuality_checks=["No unsupported market-share claims."],
        coverage_checks=["Include all named products."],
        artifact_checks=[],
        safety_checks=[],
        min_quality_score=0.8,
        allowed_repair_attempts=1,
        failure_policy="return_partial",
    )
    changed = base.model_copy(
        update={
            "success_criteria": [
                "Include a comparison table.",
                "Include pricing.",
            ]
        }
    )

    assert base.contract_hash() != changed.contract_hash()


def test_mission_tracks_autonomy_and_status():
    mission = Mission(
        mission_id="mission-1",
        session_id="session-1",
        user_id="user-1",
        original_query="Compare products",
        intent="complex_analysis",
        autonomy_level=AutonomyLevel.MANUAL.value,
        status=MissionStatus.PLANNED,
        mission_type=MissionType.STANDARD,
        plan_hash="plan-hash",
        validation_contract_hash="contract-hash",
    )

    assert mission.to_state()["status"] == "planned"
    assert mission.to_state()["autonomy_level"] == 0


def test_build_mission_event_includes_correlation_fields():
    event = build_mission_event(
        name=MissionEventName.TASK_STARTED,
        mission_id="mission-1",
        task_id="task-1",
        correlation_id="session-1",
        role="worker",
        data={"capability": "web_search"},
    )

    assert event["event"] == "mission.task.started"
    assert event["mission_id"] == "mission-1"
    assert event["task_id"] == "task-1"
    assert event["correlation_id"] == "session-1"
    assert event["role"] == "worker"

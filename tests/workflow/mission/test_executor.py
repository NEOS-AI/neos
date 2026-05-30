import pytest
from unittest.mock import AsyncMock

from neos.workflow.mission.executor import MissionExecutor
from neos.workflow.mission.integrator import MissionIntegrator


@pytest.mark.asyncio
async def test_executor_runs_search_task_then_records_result():
    search = AsyncMock()
    search.orchestrate = AsyncMock(
        return_value={
            "search_results": ["result-1"],
            "execution_steps": [
                {"step": "search_orchestration", "result": "completed"}
            ],
        }
    )
    executor = MissionExecutor(
        search_orchestrator=search,
        analysis_orchestrator=AsyncMock(),
        generation_orchestrator=AsyncMock(),
        recursive_orchestrator=lambda: None,
        hyper_deep_orchestrator=lambda: None,
    )
    state = {
        "mission_id": "mission-1",
        "mission_plan": {
            "tasks": [
                {
                    "task_id": "task-1",
                    "required_capability": "web_search",
                    "suggested_agent": "realtime_info_search",
                    "depends_on": [],
                }
            ]
        },
        "required_agents": [],
        "search_results": [],
        "analysis_results": [],
        "generation_results": [],
        "execution_steps": [],
        "errors": [],
    }

    result = await executor.execute(state)

    assert result["mission_task_results"][0]["task_id"] == "task-1"
    assert result["mission_task_results"][0]["status"] == "completed"
    assert result["mission_status"] == "completed"
    search.orchestrate.assert_awaited_once()


@pytest.mark.asyncio
async def test_executor_merges_only_list_deltas_between_serial_tasks():
    search = AsyncMock()
    analysis = AsyncMock()

    async def run_search(state):
        return {
            **state,
            "search_results": [*state.get("search_results", []), "source-1"],
            "execution_steps": [
                *state.get("execution_steps", []),
                {"step": "search_orchestration", "result": "completed"},
            ],
        }

    async def run_analysis(state):
        return {
            **state,
            "search_results": list(state.get("search_results", [])),
            "analysis_results": [
                *state.get("analysis_results", []),
                "analysis-1",
            ],
            "execution_steps": [
                *state.get("execution_steps", []),
                {"step": "analysis_orchestration", "result": "completed"},
            ],
        }

    search.orchestrate = AsyncMock(side_effect=run_search)
    analysis.orchestrate = AsyncMock(side_effect=run_analysis)
    executor = MissionExecutor(
        search_orchestrator=search,
        analysis_orchestrator=analysis,
        generation_orchestrator=AsyncMock(),
        recursive_orchestrator=lambda: None,
        hyper_deep_orchestrator=lambda: None,
    )
    state = {
        "mission_id": "mission-1",
        "mission_plan": {
            "tasks": [
                {
                    "task_id": "task-1",
                    "required_capability": "web_search",
                    "suggested_agent": "realtime_info_search",
                    "depends_on": [],
                },
                {
                    "task_id": "task-2",
                    "required_capability": "comparative_analysis",
                    "suggested_agent": "comparative_analysis",
                    "depends_on": ["task-1"],
                },
            ]
        },
        "required_agents": [],
        "search_results": [],
        "analysis_results": [],
        "generation_results": [],
        "execution_steps": [],
        "errors": [],
    }

    result = await executor.execute(state)

    assert result["search_results"] == ["source-1"]
    assert result["analysis_results"] == ["analysis-1"]
    assert len(result["execution_steps"]) == 2


@pytest.mark.asyncio
async def test_integrator_adds_validation_summary_to_response_metadata():
    integrator = MissionIntegrator()
    state = {
        "response_metadata": {"total_sources": 2},
        "mission_id": "mission-1",
        "mission_status": "completed",
        "mission_plan": {"user_visible_summary": "Search and validate."},
        "validation_summary": {"passed": True, "score": 0.9, "failed_checks": []},
        "mission_task_results": [{"task_id": "task-1", "status": "completed"}],
    }

    result = await integrator.integrate(state)

    assert result["response_metadata"]["mission_id"] == "mission-1"
    assert result["response_metadata"]["validation_summary"]["passed"] is True

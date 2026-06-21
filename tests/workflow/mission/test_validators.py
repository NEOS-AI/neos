import pytest

from neos.workflow.mission.validators import ContractCoverageValidator, MissionValidator


def test_contract_coverage_fails_missing_required_sources():
    validator = ContractCoverageValidator()
    state = {
        "mission_id": "mission-1",
        "validation_contract": {
            "success_criteria": ["Use at least 3 sources."],
            "required_sources": 3,
            "min_quality_score": 0.8,
        },
        "search_results": [object()],
        "quality_score": 0.9,
    }

    run = validator.validate(state)

    assert run["status"] == "failed"
    assert run["score"] < 1.0
    assert "required_sources" in run["findings"][0]


@pytest.mark.asyncio
async def test_mission_validator_summarizes_runs():
    validator = MissionValidator(fact_check_processor=None, quality_validator=None)
    state = {
        "mission_id": "mission-1",
        "validation_contract": {
            "success_criteria": ["Use at least 1 source."],
            "required_sources": 1,
            "min_quality_score": 0.5,
        },
        "search_results": [object()],
        "quality_score": 0.8,
        "validator_runs": [],
    }

    result = await validator.validate(state)

    assert result["validation_summary"]["passed"] is True
    assert result["validation_summary"]["score"] >= 0.8


@pytest.mark.asyncio
async def test_mission_validator_runs_quality_adapter_when_score_missing():
    class FakeQualityValidator:
        async def validate_quality(self, state):
            state["quality_score"] = 0.91
            state["quality_feedback"] = "품질이 우수합니다."
            state["execution_steps"].append(
                {"step": "quality_validation", "result": "completed - score: 0.91"}
            )
            return state

    validator = MissionValidator(
        fact_check_processor=None,
        quality_validator=FakeQualityValidator(),
    )
    state = {
        "mission_id": "mission-1",
        "validation_contract": {
            "success_criteria": ["Use enough sources."],
            "required_sources": 1,
            "min_quality_score": 0.8,
        },
        "required_agents": [],
        "search_results": [object()],
        "analysis_results": [],
        "generation_results": [],
        "execution_steps": [],
        "errors": [],
        "quality_score": None,
        "validator_runs": [],
    }

    result = await validator.validate(state)

    assert result["quality_score"] == 0.91
    assert result["quality_feedback"] == "품질이 우수합니다."
    assert result["validation_summary"]["passed"] is True


@pytest.mark.asyncio
async def test_mission_validator_includes_harness_summary_when_present():
    validator = MissionValidator(fact_check_processor=None, quality_validator=None)
    state = {
        "mission_id": "mission-1",
        "validation_contract": {"required_sources": 1, "min_quality_score": 0.8},
        "quality_score": 0.9,
        "search_results": [{"url": "https://a.com"}],
        "harness_verdict": "pass",
        "harness_score": 0.91,
        "harness_failed_checks": [],
        "harness_mode": "gate",
    }

    updates = await validator.validate(state)

    assert updates["validation_summary"]["harness"]["verdict"] == "pass"
    assert updates["validation_summary"]["harness"]["score"] == 0.91

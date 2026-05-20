from datetime import datetime

import pytest

from neos.workflow.processors.response_generator import ResponseGenerator


@pytest.mark.asyncio
async def test_response_generator_preserves_existing_final_response():
    generator = ResponseGenerator()
    state = {
        "original_query": "Run approved action",
        "detected_language": "ko",
        "search_results": [],
        "analysis_results": [],
        "generation_results": [],
        "fact_check_result": None,
        "mission_id": "mission-1",
        "mission_status": "approval_unavailable",
        "mission_plan": {"user_visible_summary": "Plan requires approval."},
        "validation_summary": None,
        "mission_task_results": [],
        "quality_score": None,
        "errors": [],
        "execution_steps": [],
        "execution_start": datetime.now(),
        "final_response": "Manual mission approval is not configured.",
    }

    result = await generator.generate_response(state)

    assert result["final_response"] == "Manual mission approval is not configured."
    assert result["response_metadata"]["mission_id"] == "mission-1"

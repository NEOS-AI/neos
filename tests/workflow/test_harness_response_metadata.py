from datetime import datetime

from neos.workflow.processors.response_generator import ResponseGenerator


def test_response_metadata_includes_compact_harness_summary():
    state = {
        "search_results": [],
        "analysis_results": [],
        "generation_results": [],
        "quality_score": 0.9,
        "execution_time_ms": 120,
        "errors": [],
        "execution_steps": [],
        "execution_start": datetime.now(),
        "harness_mode": "gate",
        "harness_verdict": "pass",
        "harness_score": 0.87,
        "harness_failed_checks": [],
        "harness_repair_attempts": 1,
    }

    metadata = ResponseGenerator()._create_response_metadata(state)

    assert metadata["harness"] == {
        "enabled": True,
        "mode": "gate",
        "verdict": "pass",
        "score": 0.87,
        "failed_checks": [],
        "repair_attempts": 1,
    }


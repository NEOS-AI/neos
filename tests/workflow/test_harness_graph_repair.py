import os
import sys
import types

import pytest

os.environ["GOOGLE_API_KEY"] = "test-key"
os.environ["OPENAI_API_KEY"] = "test-key"

import neos.config.settings as settings_module

settings_module.settings.GOOGLE_API_KEY = "test-key"
settings_module.settings.OPENAI_API_KEY = "test-key"

youtube_module = types.ModuleType("youtube_transcript_api")
youtube_module.YouTubeTranscriptApi = object
youtube_errors_module = types.ModuleType("youtube_transcript_api._errors")
youtube_errors_module.TranscriptsDisabled = Exception
youtube_errors_module.NoTranscriptFound = Exception
youtube_errors_module.VideoUnavailable = Exception
sys.modules.setdefault("youtube_transcript_api", youtube_module)
sys.modules.setdefault("youtube_transcript_api._errors", youtube_errors_module)

googleapi_module = types.ModuleType("googleapiclient")
googleapi_discovery_module = types.ModuleType("googleapiclient.discovery")
googleapi_discovery_module.build = lambda *args, **kwargs: object()
googleapi_errors_module = types.ModuleType("googleapiclient.errors")
googleapi_errors_module.HttpError = Exception
sys.modules.setdefault("googleapiclient", googleapi_module)
sys.modules.setdefault("googleapiclient.discovery", googleapi_discovery_module)
sys.modules.setdefault("googleapiclient.errors", googleapi_errors_module)

isodate_module = types.ModuleType("isodate")
isodate_module.parse_duration = lambda value: value
sys.modules.setdefault("isodate", isodate_module)


from neos.workflow.graph import _should_route_to_harness_repair  # noqa: E402


def test_routes_needs_repair_to_repair_when_attempts_remain():
    state = {
        "harness_mode": "gate",
        "harness_verdict": "needs_repair",
        "harness_contract": {"max_repair_attempts": 2},
        "harness_repair_attempts": 1,
    }

    assert _should_route_to_harness_repair(state) == "repair"


def test_routes_needs_repair_to_end_when_attempts_exhausted():
    state = {
        "harness_mode": "gate",
        "harness_verdict": "needs_repair",
        "harness_contract": {"max_repair_attempts": 1},
        "harness_repair_attempts": 1,
    }

    assert _should_route_to_harness_repair(state) == "end"


def test_routes_non_repair_verdict_to_end():
    state = {
        "harness_mode": "gate",
        "harness_verdict": "fail",
        "harness_contract": {"max_repair_attempts": 2},
        "harness_repair_attempts": 0,
    }

    assert _should_route_to_harness_repair(state) == "end"


class _StubSearchOrchestrator:
    async def orchestrate(self, state):
        state = dict(state)
        state["search_results"] = [*state.get("search_results", []), object()]
        return state


class _StubResultProcessor:
    async def integrate_results(self, state):
        state = dict(state)
        state["integrated_results"] = {
            "total_sources": len(state.get("search_results", []))
        }
        return state


class _StubResponseGenerator:
    async def generate_response(self, state):
        assert state.get("final_response") is None
        state = dict(state)
        state["final_response"] = "repaired candidate"
        return state


@pytest.mark.asyncio
async def test_repair_node_clears_stale_final_response_before_regeneration():
    from neos.workflow.graph import MultiAgentWorkflow

    workflow = MultiAgentWorkflow()
    workflow.search_orchestrator = _StubSearchOrchestrator()
    workflow.result_processor = _StubResultProcessor()
    workflow.response_generator = _StubResponseGenerator()

    state = {
        "final_response": "failed candidate",
        "search_results": [],
        "analysis_results": [],
        "generation_results": [],
        "execution_steps": [],
        "harness_repair_attempts": 0,
        "harness_contract": {
            "mode": "gate",
            "risk_level": "medium",
            "min_score": 0.82,
            "max_repair_attempts": 1,
        },
        "harness_metadata": {
            "check_results": [
                {
                    "name": "source_count",
                    "passed": False,
                    "score": 0.0,
                    "severity": "critical",
                    "summary": "Need more sources",
                    "repairable": True,
                }
            ]
        },
        "thinking_trace": [{"event_type": "harness.run.completed"}],
        "original_query": "test research topic",
        "required_agents": [],
    }

    result = await workflow._research_harness_repair_node(state)

    assert result["final_response"] == "repaired candidate"
    assert result.get("thinking_trace") is not None

import os
import sys
import types

os.environ["GOOGLE_API_KEY"] = "test-key"

import pytest

from neos.workflow.enums import WorkflowNode, WorkflowPathway

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


class RecordingGraph:
    def __init__(self, state_type):
        self.state_type = state_type
        self.nodes = []
        self.edges = []
        self.conditional_edges = []

    def add_node(self, name, handler):
        self.nodes.append(name)

    def add_edge(self, source, target):
        self.edges.append((source, target))

    def add_conditional_edges(self, source, router, mapping):
        self.conditional_edges.append((source, mapping))

    def compile(self, **kwargs):
        return self


@pytest.mark.asyncio
async def test_standard_workflow_validates_generated_response_with_research_harness(monkeypatch):
    import neos.config.settings as settings_module

    settings_module.settings.GOOGLE_API_KEY = "test-key"

    import neos.workflow.graph as graph_module

    graph = RecordingGraph
    monkeypatch.setattr(graph_module, "StateGraph", graph)
    monkeypatch.setattr(
        graph_module.MultiAgentWorkflow,
        "_initialize_agents",
        lambda self: {},
    )

    workflow = graph_module.MultiAgentWorkflow()
    compiled = await workflow._create_workflow_graph(use_checkpointer=False)

    assert WorkflowNode.RESEARCH_HARNESS.value in compiled.nodes
    assert (
        WorkflowNode.RESP_GENERATOR.value,
        WorkflowNode.RESEARCH_HARNESS.value,
    ) in compiled.edges
    assert (
        WorkflowNode.SELF_REFLECTION.value,
        WorkflowNode.RESP_GENERATOR.value,
    ) in compiled.edges

    quality_edges = [
        mapping
        for source, mapping in compiled.conditional_edges
        if source == WorkflowNode.QUALITY_VALIDATOR.value
    ]
    assert quality_edges
    assert (
        quality_edges[0][WorkflowPathway.PROCEED.value]
        == WorkflowNode.SELF_REFLECTION.value
    )

    harness_edges = [
        mapping
        for source, mapping in compiled.conditional_edges
        if source == WorkflowNode.RESEARCH_HARNESS.value
    ]
    assert harness_edges
    assert harness_edges[0]["repair"] == WorkflowNode.RESEARCH_HARNESS_REPAIR.value
    assert harness_edges[0]["end"] == graph_module.END
    assert (
        WorkflowNode.RESEARCH_HARNESS_REPAIR.value,
        WorkflowNode.RESEARCH_HARNESS.value,
    ) in compiled.edges


@pytest.mark.asyncio
async def test_research_harness_node_preserves_generated_response_state():
    import neos.workflow.graph as graph_module

    class StubHarnessProcessor:
        async def process(self, state):
            return {"harness_mode": "gate", "harness_verdict": "pass"}

    workflow = graph_module.MultiAgentWorkflow.__new__(graph_module.MultiAgentWorkflow)
    workflow.research_harness_processor = StubHarnessProcessor()

    result = await workflow._research_harness_node(
        {
            "final_response": "candidate final response",
            "response_metadata": {"existing": True},
        }
    )

    assert result["final_response"] == "candidate final response"
    assert result["response_metadata"] == {"existing": True}
    assert result["harness_verdict"] == "pass"


@pytest.mark.asyncio
async def test_harness_repair_loop_completion_produces_successful_result():
    import neos.workflow.graph as graph_module

    class SequencedHarnessProcessor:
        def __init__(self):
            self.calls = 0

        async def process(self, state):
            self.calls += 1
            verdict = "needs_repair" if self.calls == 1 else "pass"
            runs = list(state.get("harness_runs") or [])
            runs.append({"run_id": f"run-{self.calls}", "checks": []})
            return {
                "harness_mode": "gate",
                "harness_contract": {"max_repair_attempts": 2},
                "harness_runs": runs,
                "harness_verdict": verdict,
                "harness_score": 0.9 if verdict == "pass" else 0.5,
                "harness_failed_checks": [] if verdict == "pass" else ["freshness"],
                "harness_repair_attempts": int(state.get("harness_repair_attempts") or 0),
                "harness_metadata": {
                    "check_results": [
                        {
                            "name": "freshness",
                            "passed": verdict == "pass",
                            "score": 1.0 if verdict == "pass" else 0.0,
                            "severity": "critical",
                            "summary": "freshness failed",
                            "repairable": verdict != "pass",
                            "failed_items": [],
                            "metadata": {},
                        }
                    ]
                },
            }

    class PassthroughSearch:
        async def orchestrate(self, state):
            return state

    class PassthroughResultProcessor:
        async def integrate_results(self, state):
            return state

    class StubResponseGenerator:
        async def generate_response(self, state):
            return {**state, "final_response": "repaired final response"}

    workflow = graph_module.MultiAgentWorkflow.__new__(graph_module.MultiAgentWorkflow)
    workflow.research_harness_processor = SequencedHarnessProcessor()
    from neos.workflow.processors.research_harness_repair_processor import (
        ResearchHarnessRepairProcessor,
    )

    workflow.research_harness_repair_processor = ResearchHarnessRepairProcessor()
    workflow.search_orchestrator = PassthroughSearch()
    workflow.result_processor = PassthroughResultProcessor()
    workflow.response_generator = StubResponseGenerator()

    state = {
        "original_query": "latest AI policy",
        "final_response": "candidate final response",
        "response_metadata": {},
        "execution_time_ms": 10,
        "quality_score": 0.9,
        "errors": [],
        "execution_steps": [],
        "harness_runs": [],
        "harness_repair_attempts": 0,
    }

    final_state = await workflow._research_harness_node(state)
    assert graph_module._should_route_to_harness_repair(final_state) == "repair"
    final_state = await workflow._research_harness_repair_node(final_state)
    final_state = await workflow._research_harness_node(final_state)
    final_result = workflow._create_workflow_result(final_state)

    assert final_result["success"] is True
    assert final_state["harness_repair_attempts"] == 1
    assert len(final_state["harness_runs"]) == 2
    assert final_state["harness_verdict"] == "pass"


@pytest.mark.asyncio
async def test_harness_repair_exhaustion_blocks_final_result():
    import neos.workflow.graph as graph_module

    class ExhaustingHarnessProcessor:
        async def process(self, state):
            runs = list(state.get("harness_runs") or [])
            runs.append({"run_id": f"run-{len(runs) + 1}", "checks": []})
            return {
                "harness_mode": "gate",
                "harness_contract": {"max_repair_attempts": 1},
                "harness_runs": runs,
                "harness_verdict": "needs_repair",
                "harness_score": 0.4,
                "harness_failed_checks": ["freshness"],
                "harness_repair_attempts": int(state.get("harness_repair_attempts") or 0),
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
            }

    class PassthroughSearch:
        async def orchestrate(self, state):
            return state

    class PassthroughResultProcessor:
        async def integrate_results(self, state):
            return state

    class StubResponseGenerator:
        async def generate_response(self, state):
            return {**state, "final_response": "still incomplete response"}

    workflow = graph_module.MultiAgentWorkflow.__new__(graph_module.MultiAgentWorkflow)
    workflow.research_harness_processor = ExhaustingHarnessProcessor()
    from neos.workflow.processors.research_harness_repair_processor import (
        ResearchHarnessRepairProcessor,
    )

    workflow.research_harness_repair_processor = ResearchHarnessRepairProcessor()
    workflow.search_orchestrator = PassthroughSearch()
    workflow.result_processor = PassthroughResultProcessor()
    workflow.response_generator = StubResponseGenerator()

    state = {
        "original_query": "latest AI policy",
        "final_response": "candidate final response",
        "response_metadata": {},
        "execution_time_ms": 10,
        "quality_score": 0.4,
        "errors": [],
        "execution_steps": [],
        "harness_runs": [],
        "harness_repair_attempts": 0,
    }

    final_state = await workflow._research_harness_node(state)
    assert graph_module._should_route_to_harness_repair(final_state) == "repair"
    final_state = await workflow._research_harness_repair_node(final_state)
    final_state = await workflow._research_harness_node(final_state)
    assert graph_module._should_route_to_harness_repair(final_state) == "end"
    final_result = workflow._create_workflow_result(final_state)

    assert final_result["success"] is False
    assert "research_harness_gate_failed" in final_result["errors"]
    assert final_result["blocked_response"]

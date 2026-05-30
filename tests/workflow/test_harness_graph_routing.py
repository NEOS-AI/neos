import os
import sys
import types
from contextlib import contextmanager

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


@contextmanager
def _noop_trace(*args, **kwargs):
    yield object()


telemetry_module = types.ModuleType("neos.workflow.telemetry")
telemetry_module.trace_workflow_node = _noop_trace
telemetry_module.add_span_event = lambda *args, **kwargs: None
telemetry_module.set_span_attributes = lambda *args, **kwargs: None
sys.modules.setdefault("neos.workflow.telemetry", telemetry_module)


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
        WorkflowNode.RESEARCH_HARNESS.value,
        graph_module.END,
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

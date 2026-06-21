import sys
import types

import pytest

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

from neos.workflow.builder.executors import NodeExecutor
from neos.workflow.builder.nodes import WorkflowNode
from neos.workflow.state import GenerationResult, SearchResult


@pytest.mark.asyncio
async def test_node_executor_runs_research_harness_processor():
    executor = NodeExecutor(workflow_id=1, workflow_name="wf")
    node = WorkflowNode(
        name="harness",
        node_type="processor",
        config={"processor_type": "research_harness"},
    )
    state = {
        "original_query": "research topic",
        "query_intent": "deep_research",
        "query_classification": {"complexity_score": 0.9},
        "search_results": [
            SearchResult(source="web", title="A", content="A", url="https://a.com", score=1.0),
            SearchResult(source="web", title="B", content="B", url="https://b.com", score=1.0),
            SearchResult(source="web", title="C", content="C", url="https://c.com", score=1.0),
        ],
        "generation_results": [
            GenerationResult(content_type="answer", content="A [1]. B [2]. C [3].")
        ],
        "execution_steps": [],
        "errors": [],
        "quality_score": 0.9,
        "response_metadata": {},
    }

    result = await executor.execute_processor(node, state)

    assert result["harness_mode"] == "gate"
    assert result["harness_verdict"] in {"pass", "needs_repair", "fail"}

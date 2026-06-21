import sys
import types

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

from neos.workflow.builder.workflow_executor import WorkflowExecutor


def test_custom_workflow_initial_state_contains_harness_fields():
    executor = WorkflowExecutor(workflow_id=1)
    state = executor._create_initial_state(
        {
            "user_id": "u1",
            "session_id": "s1",
            "query": "research topic",
        }
    )

    assert state["harness_contract"] == {}
    assert state["harness_runs"] == []
    assert state["harness_repair_attempts"] == 0

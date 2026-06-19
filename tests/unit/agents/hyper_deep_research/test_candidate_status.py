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

from neos.agents.search_agents.hyper_deep_research.agent import HyperDeepResearchAgent


class FakeRepository:
    def __init__(self):
        self.status_updates = []

    async def update_report_status(
        self,
        report_id,
        status,
        timestamp_field=None,
        quality_score=None,
    ):
        self.status_updates.append(
            {
                "report_id": report_id,
                "status": status,
                "timestamp_field": timestamp_field,
                "quality_score": quality_score,
            }
        )
        return True


@pytest.mark.asyncio
async def test_finalize_report_marks_candidate_ready_by_default():
    agent = HyperDeepResearchAgent.__new__(HyperDeepResearchAgent)
    agent.current_report_id = "report-1"
    agent.repository = FakeRepository()

    async def noop_metadata():
        return None

    agent._update_report_metadata = noop_metadata

    await agent._finalize_report()

    assert agent.repository.status_updates[0]["status"] == "candidate_ready"
    assert agent.repository.status_updates[0]["timestamp_field"] is None

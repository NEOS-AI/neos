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

from neos.api.handlers import deep_research_handlers


def test_build_deep_research_repair_service_uses_executor_when_enabled(monkeypatch):
    monkeypatch.setattr(
        deep_research_handlers.settings,
        "RESEARCH_HARNESS_DIRECT_REPAIR_ENABLED",
        True,
        raising=False,
    )

    service = deep_research_handlers.build_deep_research_repair_service()

    assert service.action_executor is not None


def test_build_deep_research_repair_service_preserves_skip_path_when_disabled(monkeypatch):
    monkeypatch.setattr(
        deep_research_handlers.settings,
        "RESEARCH_HARNESS_DIRECT_REPAIR_ENABLED",
        False,
        raising=False,
    )

    service = deep_research_handlers.build_deep_research_repair_service()

    assert service.action_executor is None


class FakeRepository:
    def __init__(self):
        self.report_ids = []

    async def refresh_report_totals(self, report_id):
        self.report_ids.append(report_id)
        return {"total_sections": 3, "total_sources": 8, "total_queries": 5}


@pytest.mark.asyncio
async def test_refresh_deep_research_totals_after_repair_returns_repository_values():
    repository = FakeRepository()

    totals = await deep_research_handlers.refresh_deep_research_totals_after_repair(
        "report-1",
        repository=repository,
    )

    assert totals == {"total_sections": 3, "total_sources": 8, "total_queries": 5}
    assert repository.report_ids == ["report-1"]

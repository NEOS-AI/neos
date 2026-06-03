import pytest
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

from neos.api.handlers.deep_research_handlers import is_deep_research_harness_blocked
from neos.api.services.deep_research_harness_service import DeepResearchHarnessService
from neos.workflow.harness.models import HarnessMode, HarnessRun, HarnessVerdict
from neos.workflow.harness.events import HarnessEventType
from datetime import datetime


@pytest.mark.asyncio
async def test_service_returns_harness_run_for_report(monkeypatch):
    service = DeepResearchHarnessService()

    async def fake_sections(report_id):
        return [
            {
                "section_order": 1,
                "section_title": "Report",
                "section_content": "Claim [1].",
                "sources": [{"title": "A", "url": "https://a.com"}],
            }
        ]

    async def fake_collection(report_id):
        return []

    monkeypatch.setattr(service, "_fetch_sections", fake_sections)
    monkeypatch.setattr(service, "_fetch_collection_rows", fake_collection)

    validation = await service.validate_report(
        report_id="report-1",
        research_topic="AI market",
        metadata={},
    )

    assert validation.run.mode.value == "gate"
    assert validation.run.verdict in {
        HarnessVerdict.PASS,
        HarnessVerdict.NEEDS_REPAIR,
        HarnessVerdict.FAIL,
    }
    assert validation.contract.mode.value == "gate"
    assert validation.report == "## Report\n\nClaim [1]."
    assert validation.sources[0]["url"] == "https://a.com"


@pytest.mark.asyncio
async def test_service_passes_harness_event_callback(monkeypatch):
    class FakeRunner:
        async def arun(self, **kwargs):
            await kwargs["event_callback"](
                HarnessEventType.CHECK_STARTED,
                {"check": "source_count", "mode": "gate"},
            )
            now = datetime.now()
            return HarnessRun(
                run_id="run-1",
                mode=HarnessMode.GATE,
                verdict=HarnessVerdict.PASS,
                score=1.0,
                checks=[],
                failed_checks=[],
                repair_attempts=0,
                started_at=now,
                completed_at=now,
            )

    service = DeepResearchHarnessService(runner=FakeRunner())

    async def fake_sections(report_id):
        return []

    async def fake_collection(report_id):
        return []

    events = []

    async def collect_event(event_type, payload):
        events.append((event_type, payload))

    monkeypatch.setattr(service, "_fetch_sections", fake_sections)
    monkeypatch.setattr(service, "_fetch_collection_rows", fake_collection)

    await service.validate_report(
        report_id="report-1",
        research_topic="AI market",
        metadata={},
        event_callback=collect_event,
    )

    assert events == [
        (
            HarnessEventType.CHECK_STARTED,
            {"check": "source_count", "mode": "gate"},
        )
    ]


class _ValueObject:
    def __init__(self, value):
        self.value = value


class _Run:
    def __init__(self, mode, verdict):
        self.mode = _ValueObject(mode)
        self.verdict = _ValueObject(verdict)


def test_deep_research_harness_blocks_failed_gate_runs():
    assert is_deep_research_harness_blocked(_Run("gate", "fail"))
    assert is_deep_research_harness_blocked(_Run("gate", "needs_repair"))


def test_deep_research_harness_allows_pass_and_advisory_runs():
    assert not is_deep_research_harness_blocked(_Run("gate", "pass"))
    assert not is_deep_research_harness_blocked(_Run("advisory", "fail"))

import sys
import types
from datetime import datetime
from pathlib import Path

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
from neos.workflow.harness.models import (
    HarnessContract,
    HarnessMode,
    HarnessRiskLevel,
    HarnessRun,
    HarnessVerdict,
)


def test_build_deep_research_repair_service_uses_executor_when_enabled(monkeypatch):
    monkeypatch.setattr(
        deep_research_handlers.settings,
        "RESEARCH_HARNESS_DIRECT_REPAIR_ENABLED",
        True,
        raising=False,
    )

    service = deep_research_handlers.build_deep_research_repair_service()

    assert service.action_executor is not None


def test_deep_research_handler_marks_validating_before_terminal_status():
    source = Path("neos/api/handlers/deep_research_handlers.py").read_text()

    validating_index = source.index('"validating"')
    failed_index = source.index('"failed"', validating_index)
    completed_index = source.index('"completed"', validating_index)

    assert validating_index < failed_index
    assert validating_index < completed_index


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


class FakeHarnessRepository:
    def __init__(self):
        self.saved = []

    async def save_run(self, **kwargs):
        self.saved.append(kwargs)


@pytest.mark.asyncio
async def test_persist_deep_research_harness_run_records_repair_provenance(
    monkeypatch,
):
    monkeypatch.setattr(
        deep_research_handlers.settings,
        "RESEARCH_HARNESS_PERSIST_RUNS",
        True,
        raising=False,
    )
    repository = FakeHarnessRepository()
    contract = HarnessContract(
        mode=HarnessMode.GATE,
        risk_level=HarnessRiskLevel.HIGH,
        min_score=0.82,
    )
    first_run = HarnessRun(
        run_id="run-1",
        mode=HarnessMode.GATE,
        verdict=HarnessVerdict.NEEDS_REPAIR,
        score=0.4,
        checks=[],
        failed_checks=["source_count"],
        repair_attempts=0,
        started_at=datetime.now(),
    )
    second_run = HarnessRun(
        run_id="run-2",
        mode=HarnessMode.GATE,
        verdict=HarnessVerdict.PASS,
        score=0.9,
        checks=[],
        failed_checks=[],
        repair_attempts=1,
        started_at=datetime.now(),
    )

    await deep_research_handlers.persist_deep_research_harness_run(
        run=first_run,
        contract=contract,
        report_id="report-1",
        user_id="user-1",
        session_id="session-1",
        repository=repository,
    )
    await deep_research_handlers.persist_deep_research_harness_run(
        run=second_run,
        contract=contract,
        report_id="report-1",
        user_id="user-1",
        session_id="session-1",
        repair_result={"executed_actions": [{"status": "executed"}]},
        repair_attempt=1,
        repository=repository,
    )

    assert len(repository.saved) == 2
    assert repository.saved[0]["report_id"] == "report-1"
    assert "repair_result" not in repository.saved[0]["run"].metadata
    assert repository.saved[1]["run"].metadata["repair_result"] == {
        "executed_actions": [{"status": "executed"}]
    }
    assert repository.saved[1]["run"].metadata["repair_attempt"] == 1

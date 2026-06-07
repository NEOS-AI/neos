import pytest

from neos.api.services.deep_research_repair_executor import (
    DirectDeepResearchRepairExecutor,
    _select_sections,
)
from neos.workflow.harness.models import HarnessRepairAction


class FakeRepository:
    def __init__(self):
        self.context = {
            "report_id": "report-1",
            "sections": [
                {
                    "section_id": "section-1",
                    "section_order": 1,
                    "section_type": "analysis",
                    "section_title": "Summary",
                    "section_content": "Weak uncited claim.",
                    "sources": [{"title": "Existing", "url": "https://existing.example"}],
                    "metadata": {},
                },
                {
                    "section_id": "section-2",
                    "section_order": 2,
                    "section_type": "appendix",
                    "section_title": "Appendix",
                    "section_content": "Appendix content.",
                    "sources": [],
                    "metadata": {},
                },
            ],
            "collection_rows": [],
            "report_metadata": {},
            "totals": {"total_sections": 2, "total_sources": 1, "total_queries": 0},
        }
        self.collection_records = []
        self.section_updates = []
        self.report_events = []

    async def fetch_repair_context(self, report_id):
        return self.context

    async def record_repair_collection(self, **kwargs):
        self.collection_records.append(kwargs)

    async def update_section_after_repair(self, **kwargs):
        self.section_updates.append(kwargs)

    async def append_report_repair_metadata(self, report_id, repair_event):
        self.report_events.append((report_id, repair_event))


class FakeRegenerator:
    def __init__(self):
        self.calls = []
        self.last_metadata = {"status": "executed"}

    async def regenerate(self, **kwargs):
        self.calls.append(kwargs)
        return "Repaired claim [1]."


async def fake_searcher(query, **kwargs):
    return [
        {
            "title": "Fresh source",
            "url": "https://fresh.example/story",
            "content": "Evidence for repair",
            "published_at": "2026-06-05",
        }
    ]


@pytest.mark.asyncio
async def test_request_more_sources_executes_search_and_records_collection():
    repository = FakeRepository()
    executor = DirectDeepResearchRepairExecutor(
        repository=repository,
        searcher=fake_searcher,
        regenerator=FakeRegenerator(),
    )

    result = await executor(
        report_id="report-1",
        action=HarnessRepairAction(
            action_type="request_more_sources",
            target_check="source_count",
            reason="too few sources",
            params={"query": "AI market"},
        ),
        context={"research_topic": "AI market", "attempt": 1},
    )

    assert result["status"] == "executed"
    assert result["added_sources"] == 1
    assert repository.collection_records[0]["query_text"] == "AI market"
    assert repository.collection_records[0]["action_type"] == "request_more_sources"
    assert repository.report_events[0][1]["action_type"] == "request_more_sources"


@pytest.mark.asyncio
async def test_search_independent_domains_filters_dominant_domains_after_search():
    async def searcher(query, **kwargs):
        return [
            {"title": "Dominant", "url": "https://existing.example/new"},
            {"title": "Independent", "url": "https://independent.example/new"},
        ]

    repository = FakeRepository()
    executor = DirectDeepResearchRepairExecutor(repository=repository, searcher=searcher)

    result = await executor(
        report_id="report-1",
        action=HarnessRepairAction(
            action_type="search_independent_domains",
            target_check="source_diversity",
            reason="dominant source",
            params={"query": "AI market", "avoid_domains": ["existing.example"]},
        ),
        context={"attempt": 1},
    )

    stored = repository.collection_records[0]["results"]
    assert result["status"] == "executed"
    assert [source["domain"] for source in stored] == ["independent.example"]


@pytest.mark.asyncio
async def test_regenerate_cited_sections_updates_only_selected_section():
    repository = FakeRepository()
    regenerator = FakeRegenerator()
    executor = DirectDeepResearchRepairExecutor(
        repository=repository,
        searcher=fake_searcher,
        regenerator=regenerator,
    )

    result = await executor(
        report_id="report-1",
        action=HarnessRepairAction(
            action_type="regenerate_cited_sections",
            target_check="citation_coverage",
            reason="weak citations",
            params={"failed_items": [{"section": "Summary"}]},
        ),
        context={"research_topic": "AI market", "attempt": 1},
    )

    assert result["status"] == "executed"
    assert result["updated_sections"] == ["section-1"]
    assert repository.section_updates[0]["section_id"] == "section-1"
    assert repository.section_updates[0]["content"] == "Repaired claim [1]."
    assert regenerator.calls[0]["section_title"] == "Summary"


@pytest.mark.asyncio
async def test_rebuild_citation_map_rewrites_invalid_numeric_markers_when_mapping_exists():
    repository = FakeRepository()
    repository.context["sections"][0]["section_content"] = "Claim with invalid source [9]."
    executor = DirectDeepResearchRepairExecutor(repository=repository, searcher=fake_searcher)

    result = await executor(
        report_id="report-1",
        action=HarnessRepairAction(
            action_type="rebuild_citation_map",
            target_check="citation_validity",
            reason="invalid citations",
            params={"failed_items": [{"marker": "9", "section": "Summary"}]},
        ),
        context={"attempt": 1},
    )

    assert result["status"] == "executed"
    assert repository.section_updates[0]["content"] == "Claim with invalid source [1]."


@pytest.mark.asyncio
async def test_executor_skips_mutation_when_action_has_no_evidence():
    async def empty_searcher(query, **kwargs):
        return []

    repository = FakeRepository()
    executor = DirectDeepResearchRepairExecutor(repository=repository, searcher=empty_searcher)

    result = await executor(
        report_id="report-1",
        action=HarnessRepairAction(
            action_type="date_constrained_freshness_search",
            target_check="freshness",
            reason="missing dates",
            params={"query": "AI market", "freshness_window_days": 30},
        ),
        context={"attempt": 1},
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "no_repair_sources_found"
    assert result["added_sources"] == 0
    assert result["search_metadata"]["provider"] == "empty_searcher"
    assert result["search_metadata"]["error_count"] == 0
    assert repository.collection_records == []
    assert repository.section_updates == []


@pytest.mark.asyncio
async def test_search_action_retries_once_and_returns_search_metadata(monkeypatch):
    attempts = 0

    async def flaky_searcher(query, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("temporary search timeout")
        return [
            {
                "title": "Recovered source",
                "url": "https://recovered.example/story",
                "content": "Evidence after retry",
            }
        ]

    monkeypatch.setattr(
        "neos.api.services.deep_research_repair_executor.settings."
        "RESEARCH_HARNESS_DIRECT_REPAIR_SEARCH_RETRIES",
        1,
    )
    monkeypatch.setattr(
        "neos.api.services.deep_research_repair_executor.settings."
        "RESEARCH_HARNESS_DIRECT_REPAIR_SEARCH_TIMEOUT_SECONDS",
        5,
    )

    repository = FakeRepository()
    executor = DirectDeepResearchRepairExecutor(
        repository=repository,
        searcher=flaky_searcher,
    )

    result = await executor(
        report_id="report-1",
        action=HarnessRepairAction(
            action_type="request_more_sources",
            target_check="source_count",
            reason="too few sources",
            params={"query": "AI market"},
        ),
        context={"attempt": 1},
    )

    assert result["status"] == "executed"
    assert result["added_sources"] == 1
    assert result["search_metadata"]["attempts"] == 2
    assert result["search_metadata"]["error_count"] == 1
    assert result["search_metadata"]["timeout_seconds"] == 5


@pytest.mark.asyncio
async def test_perspective_repair_uses_retry_metadata(monkeypatch):
    attempts = 0

    async def flaky_searcher(query, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("temporary perspective search timeout")
        return [
            {
                "title": "Counter perspective",
                "url": "https://counter.example/story",
                "content": "Evidence for a counter perspective",
            }
        ]

    monkeypatch.setattr(
        "neos.api.services.deep_research_repair_executor.settings."
        "RESEARCH_HARNESS_DIRECT_REPAIR_SEARCH_RETRIES",
        1,
    )
    monkeypatch.setattr(
        "neos.api.services.deep_research_repair_executor.settings."
        "RESEARCH_HARNESS_DIRECT_REPAIR_SEARCH_TIMEOUT_SECONDS",
        5,
    )

    repository = FakeRepository()
    executor = DirectDeepResearchRepairExecutor(
        repository=repository,
        searcher=flaky_searcher,
        regenerator=FakeRegenerator(),
    )

    result = await executor(
        report_id="report-1",
        action=HarnessRepairAction(
            action_type="add_perspective_balancing_sources",
            target_check="bias_perspective",
            reason="single perspective",
            params={"failed_items": [{"section": "Summary"}]},
        ),
        context={"research_topic": "AI market", "attempt": 1},
    )

    assert result["status"] == "executed"
    assert result["added_sources"] == 1
    assert result["search_metadata"]["attempts"] == 2
    assert result["search_metadata"]["error_count"] == 1
    assert repository.collection_records[0]["metadata"]["search_metadata"][
        "attempts"
    ] == 2


def test_select_sections_uses_failed_item_section_hints():
    repair_context = {
        "sections": [
            {
                "section_id": "section-1",
                "section_order": 1,
                "section_type": "analysis",
                "section_title": "Summary",
                "sources": [{"id": "source-a"}],
            },
            {
                "section_id": "section-2",
                "section_order": 2,
                "section_type": "analysis",
                "section_title": "Methods and data",
                "sources": [{"source_id": "source-b"}],
            },
            {
                "section_id": "section-3",
                "section_order": 3,
                "section_type": "analysis",
                "section_title": "Risks",
                "sources": [{"id": "source-c"}],
            },
            {
                "section_id": "appendix-1",
                "section_order": 4,
                "section_type": "appendix",
                "section_title": "Appendix",
                "sources": [],
            },
        ]
    }

    assert [
        section["section_id"]
        for section in _select_sections(repair_context, [{"section_id": "section-2"}])
    ] == ["section-2"]
    assert [
        section["section_id"]
        for section in _select_sections(repair_context, [{"title": "methods"}])
    ] == ["section-2"]
    assert [
        section["section_id"]
        for section in _select_sections(repair_context, [{"section_order": 3}])
    ] == ["section-3"]
    assert [
        section["section_id"]
        for section in _select_sections(repair_context, [{"citation_id": "source-b"}])
    ] == ["section-2"]
    assert [
        section["section_id"] for section in _select_sections(repair_context, [])
    ] == ["section-1", "section-2", "section-3"]

import pytest

from neos.api.services.deep_research_repair_executor import (
    DirectDeepResearchRepairExecutor,
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

    assert result == {
        "status": "skipped",
        "reason": "no_repair_sources_found",
        "added_sources": 0,
    }
    assert repository.collection_records == []
    assert repository.section_updates == []

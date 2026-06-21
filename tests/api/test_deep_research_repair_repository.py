import json
from datetime import datetime, timezone

import pytest

from neos.api.repositories.deep_research_repair_repository import (
    DeepResearchRepairRepository,
)


class FakeDB:
    def __init__(self):
        self.fetch_all_calls = []
        self.fetch_one_calls = []
        self.execute_calls = []
        self.fetch_all_results = []
        self.fetch_one_results = []

    async def fetch_all(self, query, *params):
        self.fetch_all_calls.append((query, params))
        return self.fetch_all_results.pop(0)

    async def fetch_one(self, query, *params):
        self.fetch_one_calls.append((query, params))
        return self.fetch_one_results.pop(0)

    async def execute(self, query, *params):
        self.execute_calls.append((query, params))


@pytest.mark.asyncio
async def test_fetch_repair_context_returns_ordered_sections_collection_and_report_metadata():
    db = FakeDB()
    db.fetch_all_results = [
        [
            (
                "section-1",
                1,
                "analysis",
                "Summary",
                "Claim [1].",
                [{"title": "A"}],
                {"existing": True},
            )
        ],
        [("collection-1", "query", [{"title": "A"}], {"phase": 1})],
    ]
    db.fetch_one_results = [({"harness": "old"}, 1, 1, 1)]

    context = await DeepResearchRepairRepository(db=db).fetch_repair_context("report-1")

    assert context["report_id"] == "report-1"
    assert context["sections"][0]["section_id"] == "section-1"
    assert context["collection_rows"][0]["collection_id"] == "collection-1"
    assert context["report_metadata"] == {"harness": "old"}
    assert context["totals"] == {"total_sections": 1, "total_sources": 1, "total_queries": 1}


@pytest.mark.asyncio
async def test_record_repair_collection_stores_json_safe_results():
    db = FakeDB()
    raw_results = [
        {
            "title": "Bad\x00Title",
            "url": "https://example.com",
            "retrieved_at": datetime(2026, 6, 5, tzinfo=timezone.utc),
        }
    ]

    await DeepResearchRepairRepository(db=db).record_repair_collection(
        report_id="report-1",
        query_text="AI market",
        action_type="request_more_sources",
        results=raw_results,
        section_id="section-1",
        metadata={"attempt": 1},
    )

    _, params = db.execute_calls[0]
    assert params[4] == "harness_repair"
    stored_results = json.loads(params[7])
    assert stored_results[0]["title"] == "BadTitle"
    assert stored_results[0]["retrieved_at"] == "2026-06-05T00:00:00+00:00"
    stored_metadata = json.loads(params[8])
    assert stored_metadata["repair_action"] == "request_more_sources"


@pytest.mark.asyncio
async def test_update_section_after_repair_preserves_existing_metadata_and_appends_event():
    db = FakeDB()
    db.fetch_one_results = [({"existing": True, "harness_repair_events": [{"attempt": 0}]},)]

    await DeepResearchRepairRepository(db=db).update_section_after_repair(
        section_id="section-1",
        content="Repaired [1].",
        sources=[{"title": "A"}, {"title": "B"}],
        metadata={"repair_event": {"attempt": 1, "action_type": "regenerate_cited_sections"}},
    )

    _, params = db.execute_calls[0]
    assert params[0] == "Repaired [1]."
    assert params[2] == 2
    merged_metadata = json.loads(params[3])
    assert merged_metadata["existing"] is True
    assert merged_metadata["harness_repair_events"] == [
        {"attempt": 0},
        {"attempt": 1, "action_type": "regenerate_cited_sections"},
    ]


@pytest.mark.asyncio
async def test_refresh_report_totals_recomputes_and_returns_handler_values():
    db = FakeDB()
    db.fetch_one_results = [(2, 4, 3)]

    totals = await DeepResearchRepairRepository(db=db).refresh_report_totals("report-1")

    assert totals == {"total_sections": 2, "total_sources": 4, "total_queries": 3}
    _, params = db.execute_calls[0]
    assert params == ("report-1", 2, 4, 3)


@pytest.mark.asyncio
async def test_refresh_report_totals_counts_repair_collection_sources():
    db = FakeDB()
    db.fetch_one_results = [(2, 4, 3, 2)]

    totals = await DeepResearchRepairRepository(db=db).refresh_report_totals("report-1")

    assert totals == {"total_sections": 2, "total_sources": 6, "total_queries": 3}
    _, params = db.execute_calls[0]
    assert params == ("report-1", 2, 6, 3)

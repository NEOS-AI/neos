from datetime import datetime, timezone

from neos.api.services.deep_research_repair_sources import (
    dedupe_sources,
    dominant_domains_from_sources,
    normalize_repair_source,
    sources_for_section,
)


def test_normalize_repair_source_extracts_domain_and_dates():
    raw = {
        "title": "Market update",
        "url": "https://news.example.com/report?id=1",
        "content": "Current market detail",
        "published_date": "2026-06-01",
        "score": 0.74,
    }

    source = normalize_repair_source(raw, index=2, action_type="request_more_sources")

    assert source["title"] == "Market update"
    assert source["url"] == "https://news.example.com/report?id=1"
    assert source["domain"] == "news.example.com"
    assert source["published_at"] == "2026-06-01"
    assert source["repair_action"] == "request_more_sources"
    assert source["metadata"]["provider_score"] == 0.74


def test_normalize_repair_source_reads_nested_date_and_tolerates_missing_url():
    retrieved_at = datetime(2026, 6, 5, tzinfo=timezone.utc)
    raw = {
        "title": "Undated source",
        "content": "No URL here",
        "metadata": {"published_at": "2026-05-31"},
    }

    source = normalize_repair_source(
        raw,
        index=1,
        action_type="date_constrained_freshness_search",
        retrieved_at=retrieved_at,
    )

    assert source["url"] == ""
    assert source["domain"] == ""
    assert source["published_at"] == "2026-05-31"
    assert source["retrieved_at"] == "2026-06-05T00:00:00+00:00"


def test_dedupe_sources_prefers_url_then_title_domain_fallback():
    existing = [
        {"title": "A", "url": "https://a.example/report", "domain": "a.example"},
        {"title": "No URL", "url": "", "domain": "b.example"},
    ]
    new = [
        {"title": "A duplicate", "url": "https://a.example/report", "domain": "a.example"},
        {"title": "No URL", "url": "", "domain": "b.example"},
        {"title": "Fresh", "url": "https://fresh.example/story", "domain": "fresh.example"},
    ]

    sources = dedupe_sources(existing, new)

    assert [source["title"] for source in sources] == ["A", "No URL", "Fresh"]


def test_sources_for_section_preserves_existing_sources_and_caps_size():
    existing = [{"title": f"Existing {idx}", "url": f"https://e{idx}.example"} for idx in range(2)]
    new = [{"title": f"New {idx}", "url": f"https://n{idx}.example"} for idx in range(4)]

    sources = sources_for_section(existing, new, limit=3)

    assert [source["title"] for source in sources] == ["Existing 0", "Existing 1", "New 0"]


def test_dominant_domains_from_sources_sorts_by_frequency():
    domains = dominant_domains_from_sources(
        [
            {"domain": "b.example"},
            {"url": "https://a.example/1"},
            {"url": "https://a.example/2"},
            {"domain": "c.example"},
            {"domain": "b.example"},
            {"domain": "b.example"},
        ]
    )

    assert domains == ["b.example", "a.example", "c.example"]

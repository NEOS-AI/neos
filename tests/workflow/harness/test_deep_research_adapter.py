from neos.workflow.harness.adapters.deep_research_report import (
    build_deep_research_contract_state,
    combine_deep_research_sections,
    extract_deep_research_sources,
)


def test_combines_final_report_sections_in_order():
    sections = [
        {"section_order": 2, "section_title": "B", "section_content": "Beta [2]"},
        {"section_order": 1, "section_title": "A", "section_content": "Alpha [1]"},
    ]

    report = combine_deep_research_sections(sections)

    assert report.startswith("## A")
    assert "## B" in report


def test_extracts_sources_from_sections_and_collection_rows():
    sections = [
        {
            "sources": [
                {"title": "A", "url": "https://a.com/x", "published_at": "2026-05-01"}
            ]
        }
    ]
    collection_rows = [
        {
            "results": [
                {"title": "B", "url": "https://b.com/y", "date": "2026-05-02"}
            ]
        }
    ]

    sources = extract_deep_research_sources(sections, collection_rows)

    assert [source["id"] for source in sources] == ["1", "2"]
    assert sources[0]["url"] == "https://a.com/x"
    assert sources[1]["url"] == "https://b.com/y"


def test_builds_gate_contract_state_for_deep_research():
    state = build_deep_research_contract_state(
        research_topic="latest AI browser market",
        metadata={"freshness_required": True},
    )

    assert state["query_intent"] == "deep_research"
    assert state["harness_mode"] == "gate"
    assert state["metadata"]["harness_profile"] == "direct_deep_research"
    assert state["metadata"]["freshness_required"] is True

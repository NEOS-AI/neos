from neos.workflow.harness.contract_builder import build_harness_contract
from neos.workflow.harness.adapters.workflow_state import extract_sources
from neos.workflow.harness.models import HarnessMode


def test_contract_uses_validation_contract_required_sources():
    state = {
        "query_intent": "deep_research",
        "query_classification": {"complexity_score": 0.7},
        "validation_contract": {
            "required_sources": ["sec.gov"],
            "min_quality_score": 0.88,
            "freshness_required": True,
            "allowed_repair_attempts": 2,
        },
    }

    contract = build_harness_contract(state)

    assert contract.mode == HarnessMode.GATE
    assert contract.min_score == 0.88
    assert "sec.gov" in contract.required_sources
    assert contract.freshness_required is True
    assert contract.max_repair_attempts == 2


def test_contract_defaults_for_advisory_general_chat():
    state = {
        "query_intent": "general_chat",
        "query_classification": {"complexity_score": 0.1},
    }

    contract = build_harness_contract(state)

    assert contract.mode == HarnessMode.ADVISORY
    assert contract.min_sources == 3
    assert contract.min_score == 0.70


def test_contract_builder_maps_mission_validation_contract_checks():
    contract = build_harness_contract(
        {
            "query_intent": "deep_research",
            "validation_contract": {
                "required_sources": 4,
                "citation_requirement": "required",
                "freshness_requirement": "30d",
                "factuality_checks": ["claim_accuracy"],
                "coverage_checks": ["scope"],
                "min_quality_score": 0.86,
            },
        }
    )

    assert contract.min_sources == 4
    assert contract.min_score == 0.86
    assert contract.freshness_required is True
    assert contract.freshness_window_days == 30
    assert "citation_validity" in contract.required_checks
    assert "citation_coverage" in contract.required_checks
    assert "factuality" in contract.required_checks
    assert "topic_coverage" in contract.required_checks


class SearchResultObject:
    source = "web"
    title = "Object Source"
    content = "Object content"
    url = "https://object.example/report"
    score = 0.9
    metadata = {"published_at": "2026-05-30T00:00:00+00:00"}


def test_extract_sources_normalizes_dict_and_object_envelopes():
    sources = extract_sources(
        {
            "search_results": [
                {
                    "source": "web",
                    "title": "Dict Source",
                    "content": "Dict content",
                    "url": "https://dict.example/report",
                    "metadata": {"date": "2026-05-29"},
                },
                SearchResultObject(),
            ]
        }
    )

    assert sources[0]["domain"] == "dict.example"
    assert sources[0]["source_type"] == "web"
    assert sources[0]["published_at"] == "2026-05-29"
    assert sources[1]["domain"] == "object.example"
    assert sources[1]["published_at"] == "2026-05-30T00:00:00+00:00"


def test_contract_builder_applies_harness_profile_presets():
    contract = build_harness_contract(
        {
            "query_intent": "general_chat",
            "metadata": {"harness_profile": "mission_strict"},
            "query_classification": {"complexity_score": 0.1},
        }
    )

    assert contract.mode == HarnessMode.GATE
    assert contract.min_score == 0.88
    assert "factuality" in contract.required_checks
    assert "bias_perspective" in contract.optional_checks
    assert "performance_budget" in contract.optional_checks

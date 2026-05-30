from neos.workflow.harness.contract_builder import build_harness_contract
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


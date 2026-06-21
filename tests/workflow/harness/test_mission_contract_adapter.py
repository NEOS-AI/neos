from neos.workflow.harness.adapters.mission import (
    mission_contract_to_harness_config,
)


def test_maps_citation_requirement_to_required_checks():
    config = mission_contract_to_harness_config(
        {
            "citation_requirement": "required",
            "required_sources": 4,
            "min_quality_score": 0.86,
        }
    )

    assert config["min_sources"] == 4
    assert config["min_score"] == 0.86
    assert "citation_validity" in config["required_checks"]
    assert "citation_coverage" in config["required_checks"]


def test_maps_freshness_requirement_days():
    config = mission_contract_to_harness_config({"freshness_requirement": "30d"})

    assert config["freshness_required"] is True
    assert config["freshness_window_days"] == 30


def test_maps_factuality_and_coverage_requirements_to_model_checks():
    config = mission_contract_to_harness_config(
        {
            "factuality_checks": ["claim_accuracy"],
            "coverage_checks": ["market_segments"],
        }
    )

    assert "factuality" in config["required_checks"]
    assert "topic_coverage" in config["required_checks"]

from neos.workflow.harness.contract_compiler import compile_harness_contract
from neos.workflow.harness.models import (
    HarnessContract,
    HarnessMode,
    HarnessRiskLevel,
)


def base_contract(**overrides):
    data = {
        "mode": HarnessMode.GATE,
        "risk_level": HarnessRiskLevel.MEDIUM,
        "min_score": 0.82,
        "required_checks": ["citation_validity"],
        "optional_checks": [],
        "metadata": {},
    }
    data.update(overrides)
    return HarnessContract(**data)


def test_citation_validity_requires_coverage_dependency():
    contract = compile_harness_contract(base_contract())

    assert contract.required_checks == ["citation_validity", "citation_coverage"]
    assert contract.metadata["compiled_contract"] is True


def test_strategy_requires_gate_adds_metadata():
    contract = compile_harness_contract(
        base_contract(
            mode=HarnessMode.ADVISORY,
            metadata={
                "thinking_strategy": {
                    "requires_gate": True,
                    "problem_type": "exploratory",
                    "effort_budget_tokens": 2000,
                }
            },
        )
    )

    assert contract.mode == HarnessMode.GATE
    assert contract.metadata["problem_type"] == "exploratory"
    assert contract.metadata["effort_budget_tokens"] == 2000


def test_blocked_domains_force_source_diversity_check():
    contract = compile_harness_contract(
        base_contract(
            required_checks=["source_count"],
            blocked_domains=["example.com"],
        )
    )

    assert "source_diversity" in contract.required_checks

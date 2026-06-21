from __future__ import annotations

from dataclasses import replace

from .models import HarnessContract, HarnessMode


_CHECK_DEPENDENCIES = {
    "citation_validity": ["citation_coverage"],
    "factuality": ["citation_validity", "citation_coverage"],
    "freshness": ["source_count"],
}


def compile_harness_contract(contract: HarnessContract) -> HarnessContract:
    required = _expand_checks(list(contract.required_checks or []))
    optional = [
        item
        for item in _expand_checks(list(contract.optional_checks or []))
        if item not in required
    ]
    metadata = dict(contract.metadata or {})
    strategy = metadata.get("thinking_strategy") or {}
    mode = contract.mode

    if strategy.get("requires_gate"):
        mode = HarnessMode.GATE
    if strategy:
        metadata["problem_type"] = strategy.get("problem_type")
        metadata["effort_budget_tokens"] = strategy.get("effort_budget_tokens")

    if contract.blocked_domains and "source_diversity" not in required:
        required.append("source_diversity")

    metadata["compiled_contract"] = True
    return replace(
        contract,
        mode=mode,
        required_checks=required,
        optional_checks=optional,
        metadata=metadata,
    )


def _expand_checks(checks: list[str]) -> list[str]:
    expanded: list[str] = []
    for check in checks:
        if check not in expanded:
            expanded.append(check)
        for dependency in _CHECK_DEPENDENCIES.get(check, []):
            if dependency not in expanded:
                expanded.append(dependency)
    return expanded

from __future__ import annotations

import re
from typing import Any


def mission_contract_to_harness_config(
    contract: dict[str, Any] | None,
) -> dict[str, Any]:
    contract = contract or {}
    required_checks: list[str] = []
    optional_checks: list[str] = []
    config: dict[str, Any] = {}

    if isinstance(contract.get("required_sources"), int):
        config["min_sources"] = int(contract["required_sources"])
    if contract.get("min_quality_score") is not None:
        config["min_score"] = float(contract["min_quality_score"])
    if contract.get("allowed_repair_attempts") is not None:
        config["max_repair_attempts"] = int(contract["allowed_repair_attempts"])
    if contract.get("failure_policy"):
        config["failure_policy"] = _failure_policy(contract["failure_policy"])

    freshness = contract.get("freshness_requirement")
    if freshness:
        config["freshness_required"] = True
        window = _freshness_days(str(freshness))
        if window is not None:
            config["freshness_window_days"] = window
        required_checks.append("freshness")

    citation = str(contract.get("citation_requirement") or "").lower()
    if citation and citation not in {"none", "optional"}:
        required_checks.extend(["citation_validity", "citation_coverage"])

    if contract.get("factuality_checks"):
        required_checks.append("factuality")
    if contract.get("coverage_checks"):
        required_checks.append("topic_coverage")
    if contract.get("safety_checks"):
        optional_checks.append("bias_perspective")

    config["required_checks"] = _unique(required_checks)
    config["optional_checks"] = _unique(optional_checks)
    return {key: value for key, value in config.items() if value not in (None, [], {})}


def _freshness_days(value: str) -> int | None:
    match = re.search(r"(\d+)\s*(d|day|days)", value, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    if "current" in value.lower() or "latest" in value.lower() or "recent" in value.lower():
        return 30
    return None


def _failure_policy(value: str) -> str:
    normalized = str(value).lower()
    if normalized in {"block", "warn", "partial"}:
        return normalized
    if normalized == "return_partial":
        return "partial"
    return "block"


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result

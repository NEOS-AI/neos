from __future__ import annotations

from datetime import datetime
from typing import Any

from .contract_compiler import compile_harness_contract
from .models import HarnessContract
from .policy import _as_bool, decide_harness_policy, get_harness_profile_config


def _complexity_from_state(state: dict[str, Any]) -> float:
    classification = state.get("query_classification") or {}
    return float(
        state.get("complexity_score")
        or classification.get("complexity_score")
        or classification.get("complexity")
        or 0.0
    )


def _intent_from_state(state: dict[str, Any]) -> str | None:
    return state.get("query_intent") or state.get("intent")


def _metadata_from_state(state: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in ("request_metadata", "harness_metadata", "metadata"):
        value = state.get(key)
        if isinstance(value, dict):
            metadata.update(value)

    for key in ("harness_mode", "risk_level", "freshness_required", "harness_profile"):
        if state.get(key) is not None:
            metadata[key] = state[key]

    contract = state.get("validation_contract") or {}
    if contract:
        if contract.get("freshness_required") is not None:
            metadata["freshness_required"] = contract.get("freshness_required")
        elif contract.get("freshness_requirement"):
            metadata["freshness_required"] = True
        if contract.get("risk_level"):
            metadata["risk_level"] = contract.get("risk_level")

    return metadata


def _required_sources(contract_data: dict[str, Any]) -> tuple[int | None, list[str]]:
    raw = contract_data.get("required_sources")
    if raw is None:
        return None, []
    if isinstance(raw, int):
        return raw, []
    if isinstance(raw, str):
        return None, [raw]
    if isinstance(raw, list):
        return None, [str(item) for item in raw]
    return None, []


def build_harness_contract(
    state: dict[str, Any],
    *,
    settings_overrides: dict[str, Any] | None = None,
) -> HarnessContract:
    metadata = _metadata_from_state(state)
    decision = decide_harness_policy(
        intent=_intent_from_state(state),
        complexity_score=_complexity_from_state(state),
        metadata=metadata,
        settings_overrides=settings_overrides,
    )

    validation_contract = state.get("validation_contract") or {}
    node_config = state.get("harness_config") or {}
    from .adapters.mission import mission_contract_to_harness_config

    mission_config = mission_contract_to_harness_config(validation_contract)
    profile_config = get_harness_profile_config(metadata.get("harness_profile"))
    node_config = {**profile_config, **mission_config, **node_config}
    min_sources, required_sources = _required_sources(validation_contract)
    config_min_sources, config_required_sources = _required_sources(node_config)

    required_sources.extend(config_required_sources)
    if config_min_sources is not None:
        min_sources = config_min_sources

    min_quality = (
        node_config.get("min_score")
        or validation_contract.get("min_quality_score")
        or decision.min_score
    )
    repair_attempts = (
        node_config.get("max_repair_attempts")
        or validation_contract.get("allowed_repair_attempts")
        or decision.max_repair_attempts
    )
    freshness_required = _as_bool(
        node_config.get("freshness_required", metadata.get("freshness_required")),
        False,
    )

    contract = HarnessContract(
        mode=decision.mode,
        risk_level=decision.risk_level,
        min_score=float(min_quality),
        min_sources=int(min_sources or node_config.get("min_sources") or 3),
        min_citation_coverage=float(
            node_config.get("min_citation_coverage", 0.75)
        ),
        min_source_diversity=float(node_config.get("min_source_diversity", 0.60)),
        freshness_required=freshness_required,
        freshness_window_days=node_config.get("freshness_window_days"),
        required_sources=required_sources,
        required_checks=list(node_config.get("required_checks") or []),
        optional_checks=list(node_config.get("optional_checks") or []),
        blocked_domains=list(node_config.get("blocked_domains") or []),
        preferred_domains=list(node_config.get("preferred_domains") or []),
        high_risk_categories=list(node_config.get("high_risk_categories") or []),
        max_repair_attempts=int(repair_attempts or 0),
        failure_policy=node_config.get("failure_policy", "block"),
        created_at=datetime.now(),
        metadata={
            "policy_reason": decision.reason,
            "intent": _intent_from_state(state),
            "complexity_score": _complexity_from_state(state),
            "thinking_strategy": state.get("thinking_strategy"),
        },
    )
    return compile_harness_contract(contract)

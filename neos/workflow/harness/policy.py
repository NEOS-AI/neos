from __future__ import annotations

from typing import Any

from neos.config.settings import settings

from .models import HarnessMode, HarnessPolicyDecision, HarnessRiskLevel


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _get_setting(
    settings_overrides: dict[str, Any] | None,
    key: str,
    default: Any,
) -> Any:
    if settings_overrides and key in settings_overrides:
        return settings_overrides[key]
    return getattr(settings, key, default)


def _coerce_mode(value: Any, default: HarnessMode) -> HarnessMode:
    if value is None:
        return default
    try:
        return HarnessMode(str(value).lower())
    except ValueError:
        return default


def _coerce_risk(value: Any) -> HarnessRiskLevel:
    try:
        return HarnessRiskLevel(str(value or "low").lower())
    except ValueError:
        return HarnessRiskLevel.LOW


def decide_harness_policy(
    *,
    intent: str | None,
    complexity_score: float | None,
    metadata: dict[str, Any] | None,
    settings_overrides: dict[str, Any] | None = None,
) -> HarnessPolicyDecision:
    metadata = metadata or {}
    enabled = _as_bool(
        _get_setting(settings_overrides, "RESEARCH_HARNESS_ENABLED", True),
        True,
    )
    allow_off = _as_bool(
        _get_setting(settings_overrides, "RESEARCH_HARNESS_ALLOW_OFF", False),
        False,
    )
    default_mode = _coerce_mode(
        _get_setting(settings_overrides, "RESEARCH_HARNESS_DEFAULT_MODE", "auto"),
        HarnessMode.AUTO,
    )
    gate_threshold = float(
        _get_setting(settings_overrides, "RESEARCH_HARNESS_GATE_THRESHOLD", 0.82)
    )
    advisory_threshold = float(
        _get_setting(settings_overrides, "RESEARCH_HARNESS_ADVISORY_THRESHOLD", 0.70)
    )
    high_risk_threshold = float(
        _get_setting(settings_overrides, "RESEARCH_HARNESS_HIGH_RISK_THRESHOLD", 0.90)
    )
    complexity_threshold = float(
        _get_setting(settings_overrides, "HYPER_DEEP_COMPLEXITY_THRESHOLD", 0.80)
    )
    max_attempts = int(
        _get_setting(settings_overrides, "RESEARCH_HARNESS_MAX_REPAIR_ATTEMPTS", 1)
    )

    if not enabled:
        return HarnessPolicyDecision(
            HarnessMode.OFF,
            HarnessRiskLevel.LOW,
            "disabled_by_settings",
            0.0,
            0,
        )

    explicit_mode = metadata.get("harness_mode")
    if explicit_mode:
        requested = _coerce_mode(explicit_mode, HarnessMode.AUTO)
        if requested == HarnessMode.OFF and not allow_off:
            return HarnessPolicyDecision(
                HarnessMode.ADVISORY,
                HarnessRiskLevel.LOW,
                "explicit_off_not_allowed",
                advisory_threshold,
                0,
            )
        if requested != HarnessMode.AUTO:
            threshold = gate_threshold if requested == HarnessMode.GATE else advisory_threshold
            attempts = max_attempts if requested != HarnessMode.OFF else 0
            return HarnessPolicyDecision(
                requested,
                _coerce_risk(metadata.get("risk_level", "medium")),
                "explicit_mode",
                threshold,
                attempts,
            )

    risk_level = _coerce_risk(metadata.get("risk_level"))
    freshness_required = _as_bool(metadata.get("freshness_required"), False)
    normalized_intent = (intent or "").lower()
    score = float(complexity_score or 0.0)

    if normalized_intent in {"hyper_deep_research", "deep_research"}:
        return HarnessPolicyDecision(
            HarnessMode.GATE,
            risk_level,
            "research_intent",
            gate_threshold,
            max_attempts,
        )
    if risk_level == HarnessRiskLevel.HIGH:
        return HarnessPolicyDecision(
            HarnessMode.GATE,
            risk_level,
            "high_risk",
            high_risk_threshold,
            max_attempts,
        )
    if freshness_required:
        return HarnessPolicyDecision(
            HarnessMode.GATE,
            risk_level,
            "freshness_required",
            gate_threshold,
            max_attempts,
        )
    if score >= complexity_threshold:
        return HarnessPolicyDecision(
            HarnessMode.GATE,
            risk_level,
            "complexity_threshold",
            gate_threshold,
            max_attempts,
        )

    if default_mode == HarnessMode.GATE:
        return HarnessPolicyDecision(
            HarnessMode.GATE,
            risk_level,
            "default_gate",
            gate_threshold,
            max_attempts,
        )
    if default_mode == HarnessMode.OFF and allow_off:
        return HarnessPolicyDecision(
            HarnessMode.OFF,
            risk_level,
            "default_off",
            0.0,
            0,
        )
    return HarnessPolicyDecision(
        HarnessMode.ADVISORY,
        risk_level,
        "default_advisory",
        advisory_threshold,
        0,
    )

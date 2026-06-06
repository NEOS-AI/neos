from neos.workflow.harness.models import HarnessMode, HarnessRiskLevel
from neos.workflow.harness.policy import (
    decide_harness_policy,
    get_harness_profile_config,
)


def test_hyper_deep_defaults_to_gate():
    decision = decide_harness_policy(
        intent="hyper_deep_research",
        complexity_score=0.4,
        metadata={},
        settings_overrides={
            "RESEARCH_HARNESS_ENABLED": True,
            "RESEARCH_HARNESS_DEFAULT_MODE": "auto",
        },
    )

    assert decision.mode == HarnessMode.GATE
    assert decision.reason == "research_intent"


def test_low_risk_general_chat_defaults_to_advisory():
    decision = decide_harness_policy(
        intent="general_chat",
        complexity_score=0.2,
        metadata={},
        settings_overrides={
            "RESEARCH_HARNESS_ENABLED": True,
            "RESEARCH_HARNESS_DEFAULT_MODE": "auto",
        },
    )

    assert decision.mode == HarnessMode.ADVISORY
    assert decision.min_score == 0.70


def test_freshness_request_upgrades_to_gate():
    decision = decide_harness_policy(
        intent="general_chat",
        complexity_score=0.2,
        metadata={"freshness_required": True},
        settings_overrides={
            "RESEARCH_HARNESS_ENABLED": True,
            "RESEARCH_HARNESS_DEFAULT_MODE": "auto",
        },
    )

    assert decision.mode == HarnessMode.GATE
    assert decision.reason == "freshness_required"


def test_high_risk_request_uses_high_risk_threshold():
    decision = decide_harness_policy(
        intent="general_chat",
        complexity_score=0.2,
        metadata={"risk_level": "high"},
        settings_overrides={
            "RESEARCH_HARNESS_ENABLED": True,
            "RESEARCH_HARNESS_HIGH_RISK_THRESHOLD": 0.91,
        },
    )

    assert decision.mode == HarnessMode.GATE
    assert decision.risk_level == HarnessRiskLevel.HIGH
    assert decision.min_score == 0.91


def test_explicit_off_is_respected_when_allowed():
    decision = decide_harness_policy(
        intent="deep_research",
        complexity_score=0.9,
        metadata={"harness_mode": "off"},
        settings_overrides={
            "RESEARCH_HARNESS_ENABLED": True,
            "RESEARCH_HARNESS_ALLOW_OFF": True,
        },
    )

    assert decision.mode == HarnessMode.OFF


def test_global_disable_overrides_explicit_gate_request():
    decision = decide_harness_policy(
        intent="deep_research",
        complexity_score=0.9,
        metadata={"harness_mode": "gate"},
        settings_overrides={
            "RESEARCH_HARNESS_ENABLED": False,
            "RESEARCH_HARNESS_DEFAULT_MODE": "auto",
        },
    )

    assert decision.mode == HarnessMode.OFF
    assert decision.reason == "disabled_by_settings"


def test_profile_can_select_gate_policy_defaults():
    decision = decide_harness_policy(
        intent="general_chat",
        complexity_score=0.1,
        metadata={"harness_profile": "mission_strict"},
        settings_overrides={
            "RESEARCH_HARNESS_ENABLED": True,
            "RESEARCH_HARNESS_DEFAULT_MODE": "auto",
        },
    )

    assert decision.mode == HarnessMode.GATE
    assert decision.min_score == 0.88
    assert decision.reason == "profile:mission_strict"


def test_explicit_mode_takes_precedence_over_profile():
    decision = decide_harness_policy(
        intent="general_chat",
        complexity_score=0.1,
        metadata={"harness_profile": "mission_strict", "harness_mode": "advisory"},
        settings_overrides={
            "RESEARCH_HARNESS_ENABLED": True,
            "RESEARCH_HARNESS_DEFAULT_MODE": "auto",
        },
    )

    assert decision.mode == HarnessMode.ADVISORY
    assert decision.reason == "explicit_mode"


def test_agent_oriented_harness_profiles_are_available():
    source_audit = get_harness_profile_config("agent_source_audit")
    factuality_audit = get_harness_profile_config("agent_factuality_audit")
    perspective_audit = get_harness_profile_config("agent_perspective_audit")

    assert source_audit["mode"] == "gate"
    assert source_audit["required_checks"] == [
        "source_count",
        "source_diversity",
        "citation_validity",
    ]
    assert source_audit["min_score"] == 0.82

    assert factuality_audit["mode"] == "gate"
    assert "factuality" in factuality_audit["required_checks"]
    assert factuality_audit["risk_level"] == "high"
    assert factuality_audit["min_score"] == 0.88

    assert perspective_audit["mode"] == "advisory"
    assert perspective_audit["required_checks"] == ["source_count"]
    assert "bias_perspective" in perspective_audit["optional_checks"]
    assert perspective_audit["min_score"] == 0.74

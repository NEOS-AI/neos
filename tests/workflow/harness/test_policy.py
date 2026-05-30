from neos.workflow.harness.models import HarnessMode, HarnessRiskLevel
from neos.workflow.harness.policy import decide_harness_policy


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


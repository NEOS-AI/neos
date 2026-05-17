import os
from unittest.mock import patch

os.environ["DEBUG"] = "false"
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from neos.workflow.autonomy.middleware import get_policy_from_state
from neos.workflow.autonomy.policy import AutonomyPolicy
from neos.workflow.enums import AutonomyLevel


def test_autonomous_requires_no_approvals():
    policy = AutonomyPolicy(AutonomyLevel.AUTONOMOUS)

    assert policy.get_approval_required_skills() == []
    assert policy.requires_approval("api_call") is False


def test_assisted_uses_configured_approval_skills():
    policy = AutonomyPolicy(AutonomyLevel.ASSISTED)

    with patch("neos.workflow.autonomy.policy.settings") as mock_settings:
        mock_settings.APPROVAL_REQUIRED_SKILLS = ["api_call", "file_processing"]
        result = policy.get_approval_required_skills()

    assert result == ["api_call", "file_processing"]


def test_manual_includes_search_skills_without_duplicates():
    policy = AutonomyPolicy(AutonomyLevel.MANUAL)

    with patch("neos.workflow.autonomy.policy.settings") as mock_settings:
        mock_settings.APPROVAL_REQUIRED_SKILLS = ["api_call", "knowledge_search"]
        result = policy.get_approval_required_skills()

    assert result.count("knowledge_search") == 1
    assert "api_call" in result
    assert "realtime_info_search" in result
    assert "data_analysis" in result
    assert "comparative_analysis" in result
    assert "image_generation" in result


def test_manual_disables_recursive_research_and_replanning():
    assert AutonomyPolicy(AutonomyLevel.MANUAL).allows_recursive_research() is False
    assert AutonomyPolicy(AutonomyLevel.MANUAL).allows_autonomous_replan() is False
    assert AutonomyPolicy(AutonomyLevel.ASSISTED).allows_recursive_research() is True
    assert AutonomyPolicy(AutonomyLevel.AUTONOMOUS).allows_autonomous_replan() is True


def test_policy_from_state_falls_back_to_settings_default():
    with patch("neos.workflow.autonomy.middleware.settings") as mock_settings:
        mock_settings.DEFAULT_AUTONOMY_LEVEL = AutonomyLevel.AUTONOMOUS.value
        policy = get_policy_from_state({})

    assert policy.level == AutonomyLevel.AUTONOMOUS


def test_policy_from_state_invalid_value_falls_back_to_assisted():
    policy = get_policy_from_state({"autonomy_level": "not-an-int"})

    assert policy.level == AutonomyLevel.ASSISTED

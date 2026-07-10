import pytest

from neos.config.settings import settings
from neos.workflow.enums import IntentType, WorkflowNode

pytestmark = pytest.mark.no_db


def test_deep_analysis_settings_defaults():
    assert settings.DEEP_ANALYSIS_ENABLED is False
    assert settings.DEEP_ANALYSIS_COMPLEXITY_THRESHOLD == 0.5


def test_deep_analysis_enum_values():
    assert WorkflowNode.DEEP_ANALYSIS_ORCHESTRATOR.value == "deep_analysis_orchestrator"
    assert IntentType.DEEP_ANALYSIS.value == "deep_analysis"

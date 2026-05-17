import os
from unittest.mock import patch

os.environ["DEBUG"] = "false"
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from neos.api.services.workflow_service import WorkflowService


def test_resolve_autonomy_level_uses_default_without_preferences():
    with patch("neos.api.services.workflow_service.settings") as mock_settings:
        mock_settings.DEFAULT_AUTONOMY_LEVEL = 1

        assert WorkflowService.resolve_autonomy_level(None) == 1


def test_resolve_autonomy_level_accepts_valid_request_value():
    assert WorkflowService.resolve_autonomy_level({"autonomy_level": 2}) == 2
    assert WorkflowService.resolve_autonomy_level({"autonomy_level": "0"}) == 0


def test_resolve_autonomy_level_falls_back_for_invalid_value():
    with patch("neos.api.services.workflow_service.settings") as mock_settings:
        mock_settings.DEFAULT_AUTONOMY_LEVEL = 1

        assert WorkflowService.resolve_autonomy_level({"autonomy_level": 4}) == 1
        assert WorkflowService.resolve_autonomy_level({"autonomy_level": "bad"}) == 1

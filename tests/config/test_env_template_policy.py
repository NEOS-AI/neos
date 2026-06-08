import re
from pathlib import Path

import pytest

from neos.config.loader import SECRET_ENV_KEYS


ASSIGNMENT_RE = re.compile(r"^([A-Z][A-Z0-9_]+)=", re.MULTILINE)
pytestmark = pytest.mark.no_db


def _template_text() -> str:
    return Path(".env.template").read_text(encoding="utf-8")


def _template_keys() -> set[str]:
    return set(ASSIGNMENT_RE.findall(_template_text()))


def test_env_template_keeps_required_secret_and_control_keys():
    keys = _template_keys()

    assert "JWT_SECRET_KEY" in keys
    assert "DATABASE_URL" in keys
    assert "OPENAI_API_KEY" in keys
    assert "NEOS_ENV" in keys
    assert "NEOS_CONFIG_PATH" in keys
    assert "NEOS_SECRETS_PATH" in keys


def test_env_template_does_not_include_yaml_or_removed_keys():
    keys = _template_keys()

    moved_or_removed_keys = {
        "RESEARCH_HARNESS_ENABLED",
        "LLM_MODEL",
        "DATABASE_POOL_SIZE",
        "TOOL_SEARCH_ALPHA",
        "TOOL_SEARCH_CACHE_TTL",
        "SEC_EDGAR_USER_AGENT",
        "RUSTFS_ENDPOINT_URL",
    }

    assert moved_or_removed_keys.isdisjoint(keys)


def test_env_template_assignment_keys_are_allowlisted():
    keys = _template_keys()
    allowed_controls = {"NEOS_ENV", "NEOS_CONFIG_PATH", "NEOS_SECRETS_PATH", "NEOS_MODEL_CONFIG_PATH"}
    unexpected = keys - SECRET_ENV_KEYS - allowed_controls

    assert unexpected == set()


def test_env_template_points_to_yaml_example():
    assert "config/neos.example.yaml" in _template_text()

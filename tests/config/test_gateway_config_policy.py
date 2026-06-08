from pathlib import Path

import pytest


pytestmark = pytest.mark.no_db


def _gateway_config_text() -> str:
    return Path("api_gateway/config.toml").read_text(encoding="utf-8")


def test_gateway_config_does_not_ship_secret_defaults():
    text = _gateway_config_text()

    assert 'secret_key = ""' in text
    assert 'password = ""' in text
    assert "neos_is_a_multiagent_ai_platform_for_research_and_knowledge_work" not in text
    assert 'password = "postgres"' not in text


def test_gateway_config_documents_required_production_secret_env():
    text = _gateway_config_text()

    assert "JWT_SECRET_KEY" in text
    assert "DATABASE_URL" in text
    assert "required in production" in text


def test_gateway_config_documents_transitional_env_overrides():
    text = _gateway_config_text()

    for env_key in (
        "DB_HOST",
        "DB_PORT",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
        "GATEWAY_PORT",
        "UPSTREAM_HOST",
        "UPSTREAM_PORT",
        "LOG_LEVEL",
    ):
        assert env_key in text

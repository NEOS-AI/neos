from pathlib import Path

import pytest

from neos.config import loader, settings as settings_module
from neos.config.schema import AppConfig
from neos.config.settings import Settings, reload_settings_for_tests, settings


@pytest.fixture(autouse=True)
def restore_settings_singleton():
    """Undo the global singleton rebinding done by reload_settings_for_tests.

    These tests intentionally reload the process-wide settings object. Without
    this teardown the replacement leaks into every later test in the session.
    """
    original = settings_module.settings
    yield
    settings_module.settings = original


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """Isolate the loader from the developer's `.env` and process environment.

    Process env has the highest precedence by design, so a test that asserts on
    values from an explicit config/secrets pair has to clear the keys it cares
    about. Third-party imports (litellm, crewai) call `dotenv.load_dotenv()` at
    import time, which copies the repo `.env` into `os.environ` — so in a
    full-suite run these keys are populated even though they are unset when
    this module runs alone.
    """
    monkeypatch.setattr(loader, "DEFAULT_DOTENV_PATH", tmp_path / "missing.env")
    for env_key in (*loader.LEGACY_ENV_KEYS, *loader.SECRET_ENV_KEYS):
        monkeypatch.delenv(env_key, raising=False)


def write_yaml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def write_dotenv(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_reload_settings_for_tests_rebuilds_legacy_singleton(
    tmp_path, isolated_env
):
    config_path = write_yaml(
        tmp_path / "settings.yaml",
        """
research_harness:
  direct_repair:
    enabled: true
api:
  cors:
    allowed_origins:
      - http://localhost:3000
      - https://app.example.com
agent:
  timeouts:
    web_lookup: 19
coding_model:
  enabled: false
""",
    )
    # development 프로파일은 실제 코딩 루프를 켜고, 켜진 루프는 크리덴셜을
    # 요구한다. isolated_env 가 크리덴셜을 지우므로 이 재적재 테스트는 루프를 끈다.
    secrets_path = write_dotenv(
        tmp_path / "secrets.env",
        "DATABASE_URL=postgresql+asyncpg://user:pass@example.com:5432/neos\n",
    )

    reloaded = reload_settings_for_tests(
        env="development",
        config_path=str(config_path),
        secrets_path=str(secrets_path),
    )

    assert reloaded.DATABASE_URL == "postgresql+asyncpg://user:pass@example.com:5432/neos"
    assert reloaded.RESEARCH_HARNESS_DIRECT_REPAIR_ENABLED is True
    assert reloaded.CORS_ALLOWED_ORIGINS == ["http://localhost:3000", "https://app.example.com"]
    assert reloaded.AGENT_TIMEOUTS["web_lookup"] == 19


def test_settings_reload_for_tests_method_delegates(tmp_path, isolated_env):
    config_path = write_yaml(
        tmp_path / "settings.yaml",
        "llm:\n  model: method-model\ncoding_model:\n  enabled: false\n",
    )

    reloaded = settings.reload_for_tests(env="development", config_path=str(config_path))

    assert reloaded.LLM_MODEL == "method-model"


def test_settings_class_remains_instantiable():
    local_settings = Settings(config=AppConfig.model_validate({"llm": {"model": "direct-model"}}))

    assert local_settings.LLM_MODEL == "direct-model"


def test_settings_object_allows_monkeypatching(monkeypatch):
    local_settings = Settings(config=AppConfig())

    monkeypatch.setattr(local_settings, "LLM_MODEL", "patched-model")

    assert local_settings.LLM_MODEL == "patched-model"


def test_nested_anthropic_feature_settings_have_legacy_aliases():
    local_settings = Settings(config=AppConfig())

    assert local_settings.LLM_PROMPT_CACHING_ENABLED is True
    assert local_settings.LLM_PROMPT_CACHING_TTL == "5m"
    assert local_settings.LLM_ADVISOR_ENABLED is False
    assert local_settings.LLM_ADVISOR_MODEL == "claude-opus-4-8"
    assert local_settings.LLM_ADVISOR_MAX_USES == 2
    assert local_settings.LLM_ADVISOR_MAX_TOKENS == 2048
    assert local_settings.LLM_ADVISOR_MAX_PAUSE_TURNS == 3
    assert local_settings.LLM_ADVISOR_PROMPT_CACHING_ENABLED is False

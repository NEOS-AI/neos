from pathlib import Path

import pytest

from neos.config import loader


@pytest.fixture(autouse=True)
def isolate_repo_dotenv(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "DEFAULT_DOTENV_PATH", tmp_path / "missing.env")
    for env_key in loader.LEGACY_ENV_KEYS:
        monkeypatch.delenv(env_key, raising=False)


def write_yaml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def write_dotenv(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_yaml_precedence(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    write_yaml(config_dir / "neos.default.yaml", "llm:\n  model: default-model\n")
    write_yaml(config_dir / "neos.staging.yaml", "llm:\n  model: env-model\n")
    custom_config = write_yaml(tmp_path / "custom.yaml", "llm:\n  model: custom-model\n")
    monkeypatch.setattr(loader, "DEFAULT_CONFIG_DIR", config_dir)

    config = loader.load_app_config(env="staging", config_path=str(custom_config))

    assert config.llm.model == "custom-model"


def test_process_env_secret_wins_over_secrets_dotenv(tmp_path, monkeypatch):
    secrets_path = write_dotenv(tmp_path / "secrets.env", "OPENAI_API_KEY=dotenv-key\n")
    monkeypatch.setenv("OPENAI_API_KEY", "process-key")

    config = loader.load_app_config(secrets_path=str(secrets_path))

    assert config.secrets.openai_api_key == "process-key"


def test_legacy_non_secret_env_overrides_yaml_with_warning(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    write_yaml(config_dir / "neos.default.yaml", "llm:\n  model: yaml-model\n")
    monkeypatch.setattr(loader, "DEFAULT_CONFIG_DIR", config_dir)
    monkeypatch.setenv("LLM_MODEL", "legacy-env-model")

    with pytest.warns(UserWarning, match="LLM_MODEL"):
        config = loader.load_app_config(env="development")

    assert config.llm.model == "legacy-env-model"


def test_bootstrap_controls_prefer_process_env():
    controls = loader.resolve_bootstrap_controls(
        dotenv_env={
            "NEOS_ENV": "staging",
            "NEOS_CONFIG_PATH": "dotenv.yaml",
            "NEOS_SECRETS_PATH": "dotenv.env",
        },
        process_env={
            "NEOS_ENV": "production",
            "NEOS_CONFIG_PATH": "process.yaml",
        },
    )

    assert controls.env == "production"
    assert controls.config_path == Path("process.yaml")
    assert controls.secrets_path == Path("dotenv.env")


def test_validate_env_allowlist_reports_neos_like_unknown_keys():
    warnings = loader.validate_env_allowlist(
        {
            "NEOS_UNEXPECTED_FLAG": "1",
            "DATABASE_URL": "postgresql+asyncpg://example",
            "PATH": "/usr/bin",
        },
        app_env="development",
    )

    assert "NEOS_UNEXPECTED_FLAG" in warnings
    assert "PATH" not in warnings

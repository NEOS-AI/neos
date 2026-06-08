from pathlib import Path
from typing import Any

import pytest
import yaml


pytestmark = pytest.mark.no_db


DEV_PYTHON_SERVICES = ("celery-worker", "celery-beat", "flower")
ENTERPRISE_BACKEND_SERVICES = ("neos-backend-1", "neos-backend-2", "neos-backend-3")
NON_SECRET_APP_ENV_KEYS = {
    "ENVIRONMENT",
    "LOG_LEVEL",
    "METRICS_ENABLED",
    "STORAGE_PROVIDER",
    "RUSTFS_BUCKET_NAME",
    "RUSTFS_ENDPOINT_URL",
    "S3_BUCKET_NAME",
    "S3_ENDPOINT_URL",
    "AWS_REGION",
    "LOCAL_STORAGE_PATH",
}


def _compose(path: str) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _env_map(service: dict[str, Any]) -> dict[str, str]:
    env = service.get("environment", {})
    if isinstance(env, dict):
        return {str(key): str(value) for key, value in env.items()}
    result = {}
    for item in env:
        key, _, value = str(item).partition("=")
        result[key] = value
    return result


def _volumes(service: dict[str, Any]) -> list[str]:
    return [str(item) for item in service.get("volumes", [])]


def test_dev_python_services_mount_yaml_config_and_use_profile_controls():
    compose = _compose("docker-compose.dev.yml")

    for service_name in DEV_PYTHON_SERVICES:
        service = compose["services"][service_name]
        env = _env_map(service)

        assert "./config:/app/config:ro" in _volumes(service)
        assert env["NEOS_ENV"] == "development"
        assert env["NEOS_CONFIG_PATH"] == "/app/config/neos.development.yaml"
        assert NON_SECRET_APP_ENV_KEYS.isdisjoint(env)


def test_enterprise_backends_mount_yaml_config_and_avoid_non_secret_env():
    compose = _compose("docker-compose.enterprise.yml")

    for service_name in ENTERPRISE_BACKEND_SERVICES:
        service = compose["services"][service_name]
        env = _env_map(service)

        assert "./config:/app/config:ro" in _volumes(service)
        assert "neos_storage:/app/storage" in _volumes(service)
        assert env["NEOS_ENV"] == "production"
        assert env["NEOS_CONFIG_PATH"] == "/app/config/neos.production.yaml"
        assert NON_SECRET_APP_ENV_KEYS.isdisjoint(env)
        assert "minioadmin" not in "\n".join(service.get("environment", []))
        assert "ChangeThisPasswordInProduction" not in "\n".join(service.get("environment", []))


def test_enterprise_compose_defines_backend_config_anchors():
    text = Path("docker-compose.enterprise.yml").read_text(encoding="utf-8")

    assert "x-neos-config-env:" in text
    assert "x-neos-secret-env:" in text
    assert "x-neos-backend-volumes:" in text

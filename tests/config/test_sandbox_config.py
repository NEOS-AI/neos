import pytest
from pydantic import ValidationError

from neos.config.schema import AppConfig


DIGEST_IMAGE = "neos-sandbox@sha256:" + "a" * 64


def test_development_defaults_to_memory_provider() -> None:
    config = AppConfig.model_validate({"environment": "development"})

    assert config.sandbox.provider == "memory"
    assert config.sandbox.resources.memory_bytes == 512 * 1024 * 1024
    assert config.sandbox.execution.max_stdin_bytes == 1024 * 1024


@pytest.mark.parametrize(
    "docker",
    [
        {"image": "neos-sandbox:latest"},
        {"image": DIGEST_IMAGE, "network_mode": "bridge"},
        {"image": DIGEST_IMAGE, "user": "0:0"},
    ],
)
def test_production_rejects_unsafe_docker_configuration(docker) -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate(
            {
                "environment": "production",
                "sandbox": {"provider": "docker", "docker": docker},
            }
        )


def test_production_accepts_pinned_isolated_non_root_docker() -> None:
    config = AppConfig.model_validate(
        {
            "environment": "production",
            "sandbox": {
                "enabled": True,
                "provider": "docker",
                "docker": {"image": DIGEST_IMAGE},
            },
        }
    )

    assert config.sandbox.docker.image == DIGEST_IMAGE
    assert config.sandbox.docker.network_mode == "none"


def test_lifecycle_timeout_relationships_are_validated() -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate(
            {
                "sandbox": {
                    "lifecycle": {
                        "idle_timeout_sec": 120,
                        "max_lifetime_sec": 60,
                    }
                }
            }
        )

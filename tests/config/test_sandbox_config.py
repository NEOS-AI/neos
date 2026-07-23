import pytest
from pydantic import ValidationError

from neos.config.schema import AppConfig


DIGEST_IMAGE = "neos-sandbox@sha256:" + "a" * 64


def test_development_defaults_to_memory_provider() -> None:
    config = AppConfig.model_validate({"environment": "development"})

    assert config.sandbox.provider == "memory"
    assert config.sandbox.resources.memory_bytes == 512 * 1024 * 1024
    assert config.sandbox.execution.max_stdin_bytes == 1024 * 1024
    assert config.sandbox.workspace.tree_max_entries == 5_000
    assert config.sandbox.workspace.file_max_bytes == 1024 * 1024
    assert config.sandbox.workspace.diff_max_bytes == 2 * 1024 * 1024
    assert config.sandbox.workspace.edit_batch_size == 20
    assert config.sandbox.workspace.ticket_ttl_seconds == 30
    assert config.sandbox.workspace.pty_idle_ttl_seconds == 1_800
    assert config.sandbox.workspace.pty_max_sessions == 3


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tree_max_entries", 20_001),
        ("file_max_bytes", 0),
        ("diff_max_bytes", 0),
        ("edit_batch_size", 101),
        ("ticket_ttl_seconds", 301),
        ("pty_idle_ttl_seconds", 0),
        ("pty_max_sessions", 11),
    ],
)
def test_workspace_gateway_limits_are_bounded(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate(
            {"sandbox": {"workspace": {field: value}}}
        )


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

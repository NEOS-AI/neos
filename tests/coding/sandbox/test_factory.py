import pytest

from neos.coding.sandbox.base import SandboxUnavailable
from neos.coding.sandbox.docker import DockerSandboxProvider
from neos.coding.sandbox.factory import create_sandbox_provider
from neos.coding.sandbox.memory import MemorySandboxProvider
from neos.config.schema import SandboxConfig

pytestmark = pytest.mark.no_db

DIGEST_IMAGE = "neos-sandbox@sha256:" + "a" * 64


def test_sandbox_defaults_do_not_auto_allow_when_sandboxed() -> None:
    config = SandboxConfig()

    assert config.enabled is False
    assert config.provider == "memory"
    assert not hasattr(config, "auto_allow_bash_if_sandboxed")
    assert not hasattr(config, "fail_if_unavailable")


def test_factory_selects_memory_provider(tmp_path) -> None:
    config = SandboxConfig.model_validate(
        {"provider": "memory", "memory": {"root": str(tmp_path)}}
    )

    provider = create_sandbox_provider(config)

    assert isinstance(provider, MemorySandboxProvider)


def test_factory_selects_docker_provider() -> None:
    config = SandboxConfig.model_validate(
        {
            "provider": "docker",
            "docker": {
                "image": DIGEST_IMAGE,
            },
        }
    )

    provider = create_sandbox_provider(config)

    assert isinstance(provider, DockerSandboxProvider)


def test_factory_refuses_enabled_docker_without_cli(monkeypatch) -> None:
    monkeypatch.setattr(
        "neos.coding.sandbox.factory._docker_cli_available", lambda: False
    )
    config = SandboxConfig.model_validate(
        {
            "enabled": True,
            "provider": "docker",
            "docker": {"image": DIGEST_IMAGE},
        }
    )

    with pytest.raises(SandboxUnavailable, match="sandbox_required_unavailable"):
        create_sandbox_provider(config)


def test_factory_keeps_disabled_docker_lazy_without_cli(monkeypatch) -> None:
    monkeypatch.setattr(
        "neos.coding.sandbox.factory._docker_cli_available", lambda: False
    )
    config = SandboxConfig.model_validate(
        {"provider": "docker", "docker": {"image": DIGEST_IMAGE}}
    )

    provider = create_sandbox_provider(config)

    assert isinstance(provider, DockerSandboxProvider)


def test_factory_enabled_memory_does_not_require_docker(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        "neos.coding.sandbox.factory._docker_cli_available", lambda: False
    )
    config = SandboxConfig.model_validate(
        {"enabled": True, "provider": "memory", "memory": {"root": str(tmp_path)}}
    )

    provider = create_sandbox_provider(config)

    assert isinstance(provider, MemorySandboxProvider)

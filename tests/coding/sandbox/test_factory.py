from neos.coding.sandbox.docker import DockerSandboxProvider
from neos.coding.sandbox.factory import create_sandbox_provider
from neos.coding.sandbox.memory import MemorySandboxProvider
from neos.config.schema import SandboxConfig


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
                "image": "neos-sandbox@sha256:" + "a" * 64,
            },
        }
    )

    provider = create_sandbox_provider(config)

    assert isinstance(provider, DockerSandboxProvider)

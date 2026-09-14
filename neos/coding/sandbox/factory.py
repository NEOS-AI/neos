import shutil
from pathlib import Path

from neos.coding.sandbox.base import SandboxUnavailable
from neos.coding.sandbox.command import DockerCommandRunner
from neos.coding.sandbox.docker import DockerSandboxConfig, DockerSandboxProvider
from neos.coding.sandbox.memory import MemorySandboxProvider
from neos.config.schema import SandboxConfig


def _docker_cli_available() -> bool:
    return shutil.which("docker") is not None


def create_sandbox_provider(config: SandboxConfig):
    """Construct the configured provider without starting sandbox resources.

    When ``sandbox.enabled`` is true the named provider is required. Missing
    Docker is refused; there is no silent memory/host fallback.
    """
    streams = config.streams
    if config.provider == "memory":
        return MemorySandboxProvider(
            root=Path(config.memory.root),
            allowed_env_names=frozenset(config.execution.allowed_env_names),
            max_pty_sessions=streams.pty_max_sessions,
            pty_replay_events=streams.replay_events,
            pty_replay_bytes=streams.replay_bytes,
            watcher_debounce_sec=streams.watcher_debounce_sec,
            watcher_replay_events=streams.replay_events,
        )

    if (
        config.provider == "docker"
        and config.enabled
        and not _docker_cli_available()
    ):
        raise SandboxUnavailable("sandbox_required_unavailable")
    docker = config.docker
    resources = config.resources
    return DockerSandboxProvider(
        runner=DockerCommandRunner(),
        config=DockerSandboxConfig(
            image=docker.image,
            create_timeout_sec=config.lifecycle.create_timeout_sec,
            operation_timeout_sec=config.execution.command_timeout_sec,
            network_mode=docker.network_mode,
            allow_unpinned_image=docker.allow_unpinned_image,
            tmpfs_bytes=resources.tmpfs_bytes,
            allowed_env_names=frozenset(
                config.execution.allowed_env_names
            ),
            max_pty_sessions=streams.pty_max_sessions,
            pty_replay_events=streams.replay_events,
            pty_replay_bytes=streams.replay_bytes,
            watcher_debounce_sec=streams.watcher_debounce_sec,
            watcher_replay_events=streams.replay_events,
        ),
    )

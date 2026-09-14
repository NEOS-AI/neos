"""ManagedSandboxProvider: the coding `SandboxProvider` on the managed adapter plane."""

from __future__ import annotations

import base64
from dataclasses import replace
from datetime import timedelta

import pytest

from neos.coding.managed.adapters.base import (
    CreateSucceededThenTimedOut,
    DestroyResult,
    ManagedAdapterTimeoutError,
)
from neos.coding.managed.adapters.fake import FakeManagedSandboxAdapter
from neos.coding.managed.transports import (
    E2BExecTransport,
    create_e2b_transport_factory,
    create_modal_transport_factory,
)
from neos.coding.sandbox.base import (
    CommandRequest,
    SandboxLimits,
    SandboxNotFound,
    SandboxPolicyViolation,
    SandboxState,
    SandboxStateConflict,
    SandboxTimeout,
    SandboxUnavailable,
)
from neos.coding.sandbox.factory import create_sandbox_provider
from neos.coding.sandbox.managed import (
    AdapterDirectAllocator,
    ManagedBackend,
    ManagedSandboxProvider,
    TransportSessionOpener,
    owner_from_idempotency_key,
)
from neos.coding.sandbox.remote import ExecResult
from neos.config.schema import AppConfig, SandboxConfig

pytestmark = pytest.mark.no_db

IMAGE = "registry.example/neos-sandbox@sha256:" + "0" * 64


class ScriptedTransport:
    """Records every exec; replays scripted results, else an empty JSON object."""

    name = "scripted"

    def __init__(self, responses: list[ExecResult] | None = None) -> None:
        self.calls: list[dict] = []
        self._responses = list(responses or [])

    async def exec(self, argv, *, workdir, env, stdin, timeout_sec):
        self.calls.append(
            {
                "argv": tuple(argv),
                "workdir": workdir,
                "env": dict(env),
                "stdin": stdin,
                "timeout_sec": timeout_sec,
            }
        )
        if self._responses:
            return self._responses.pop(0)
        return ExecResult(exit_code=0, stdout=b"{}", stderr=b"")


def _sessions(transport: ScriptedTransport) -> TransportSessionOpener:
    return TransportSessionOpener(
        transport_for=lambda _sandbox_id: transport,
        allowed_env_names=frozenset({"LANG", "PATH"}),
        operation_timeout_sec=5.0,
    )


def _provider(
    adapter: FakeManagedSandboxAdapter | None = None,
    *,
    transport: ScriptedTransport | None = None,
    kill_switch: bool = False,
) -> tuple[ManagedSandboxProvider, FakeManagedSandboxAdapter, ScriptedTransport]:
    adapter = adapter or FakeManagedSandboxAdapter()
    transport = transport or ScriptedTransport()
    provider = ManagedSandboxProvider(
        adapter=adapter,
        allocator=AdapterDirectAllocator(
            adapter=adapter,
            region="local",
            image_identity=IMAGE,
            max_lifetime=timedelta(hours=1),
            kill_switch=lambda: kill_switch,
        ),
        sessions=_sessions(transport),
        image_identity=IMAGE,
        default_limits=SandboxLimits.safe_defaults(),
        poll_interval_sec=0.0,
    )
    return provider, adapter, transport


async def _create(provider: ManagedSandboxProvider, owner: str = "ct_1"):
    return await provider.create(owner_id=owner, limits=SandboxLimits.safe_defaults())


async def test_create_allocates_once_and_names_the_managed_provider() -> None:
    provider, adapter, _ = _provider()

    sandbox = await _create(provider)

    assert sandbox.state is SandboxState.RUNNING
    assert sandbox.provider == "managed:fake"
    assert sandbox.owner_id == "ct_1"
    assert sandbox.image_digest == IMAGE
    assert adapter.allocate_calls == 1


async def test_restarted_provider_recovers_owner_from_provider_metadata() -> None:
    provider, adapter, transport = _provider()
    sandbox = await _create(provider, owner="ct:with:colons")

    restarted, _, _ = _provider(adapter, transport=transport)
    recovered = await restarted.get(sandbox.sandbox_id)

    assert recovered.owner_id == "ct:with:colons"
    assert recovered.state is SandboxState.RUNNING


async def test_kill_switch_refuses_new_allocation_without_calling_provider() -> None:
    provider, adapter, _ = _provider(kill_switch=True)

    with pytest.raises(SandboxUnavailable, match="managed_kill_switch"):
        await _create(provider)
    assert adapter.allocate_calls == 0


async def test_ambiguous_create_is_rediscovered_not_created_again() -> None:
    adapter = FakeManagedSandboxAdapter(allocate_fault=CreateSucceededThenTimedOut())
    provider, _, _ = _provider(adapter)

    sandbox = await _create(provider)

    assert sandbox.state is SandboxState.RUNNING
    assert adapter.allocate_calls == 1
    assert adapter.rediscovery_calls == 1


async def test_timeout_without_a_rediscoverable_sandbox_is_refused() -> None:
    adapter = FakeManagedSandboxAdapter(
        allocate_fault=ManagedAdapterTimeoutError("allocate_timed_out")
    )
    provider, _, _ = _provider(adapter)

    with pytest.raises(SandboxUnavailable, match="managed_allocation_ambiguous"):
        await _create(provider)
    assert adapter.allocate_calls == 1


async def test_suspend_on_provider_without_pause_is_refused_not_ignored() -> None:
    base = FakeManagedSandboxAdapter()
    adapter = FakeManagedSandboxAdapter(
        capabilities=replace(base.capabilities, pause_resume=False)
    )
    provider, _, _ = _provider(adapter)
    sandbox = await _create(provider)

    with pytest.raises(SandboxStateConflict, match="managed_pause_unsupported"):
        await provider.suspend(sandbox.sandbox_id)


async def test_suspend_blocks_session_until_resume() -> None:
    transport = ScriptedTransport()
    provider, _, _ = _provider(transport=transport)
    sandbox = await _create(provider)
    session = await provider.open_session(sandbox.sandbox_id)

    suspended = await provider.suspend(sandbox.sandbox_id)
    assert suspended.state is SandboxState.SUSPENDED
    with pytest.raises(SandboxStateConflict):
        await session.read_file("notes.txt")

    await provider.resume(sandbox.sandbox_id)
    transport._responses.append(ExecResult(exit_code=0, stdout=b"hello", stderr=b""))
    assert await session.read_file("notes.txt") == b"hello"


async def test_destroy_is_idempotent() -> None:
    provider, adapter, _ = _provider()
    sandbox = await _create(provider)

    await provider.destroy(sandbox.sandbox_id)
    await provider.destroy(sandbox.sandbox_id)

    assert adapter.destroy_calls == 1
    with pytest.raises(SandboxNotFound):
        await provider.get(sandbox.sandbox_id)


async def test_unconfirmed_destroy_is_not_reported_as_success() -> None:
    adapter = FakeManagedSandboxAdapter(destroy_result=DestroyResult(confirmed=False))
    provider, _, _ = _provider(adapter)
    sandbox = await _create(provider)

    with pytest.raises(SandboxUnavailable, match="managed_destroy_unconfirmed"):
        await provider.destroy(sandbox.sandbox_id)


async def test_restore_is_refused() -> None:
    provider, _, _ = _provider()

    with pytest.raises(SandboxUnavailable, match="managed_restore_unsupported"):
        await provider.restore("fake_snapshot_0001", owner_id="ct_1")


async def test_snapshot_returns_the_provider_snapshot_ref() -> None:
    provider, _, _ = _provider()
    sandbox = await _create(provider)

    snapshot = await provider.snapshot(sandbox.sandbox_id)

    assert snapshot.snapshot_id.startswith("fake_snapshot_")
    assert snapshot.source_sandbox_id == sandbox.sandbox_id


async def test_remote_read_maps_helper_exit_code_to_policy_error() -> None:
    transport = ScriptedTransport([ExecResult(exit_code=3, stdout=b"", stderr=b"")])
    provider, _, _ = _provider(transport=transport)
    sandbox = await _create(provider)
    session = await provider.open_session(sandbox.sandbox_id)

    with pytest.raises(SandboxPolicyViolation, match="file_read_limit_exceeded"):
        await session.read_file("big.bin")
    call = transport.calls[-1]
    assert call["argv"][:2] == ("python", "-c")
    assert call["workdir"] == "/workspace"


async def test_remote_execute_sets_workdir_and_drops_reserved_guest_env() -> None:
    transport = ScriptedTransport(
        [
            ExecResult(exit_code=0, stdout=b"{}", stderr=b""),
            ExecResult(exit_code=1, stdout=b"out", stderr=b"err"),
            ExecResult(exit_code=0, stdout=b"{}", stderr=b""),
        ]
    )
    provider, _, _ = _provider(transport=transport)
    sandbox = await _create(provider)
    session = await provider.open_session(sandbox.sandbox_id)

    result = await session.execute(
        CommandRequest(argv=("pytest", "-q"), cwd="pkg", env={"LANG": "C", "PATH": "/x"})
    )

    assert result.exit_code == 1
    assert result.stdout == b"out"
    command = transport.calls[1]
    assert command["argv"] == ("pytest", "-q")
    assert command["workdir"] == "/workspace/pkg"
    assert command["env"] == {"LANG": "C"}


async def test_remote_execute_refuses_env_outside_the_allowlist() -> None:
    provider, _, _ = _provider()
    sandbox = await _create(provider)
    session = await provider.open_session(sandbox.sandbox_id)

    with pytest.raises(SandboxPolicyViolation, match="environment_not_allowed"):
        await session.execute(CommandRequest(argv=("env",), env={"AWS_SECRET": "x"}))


async def test_remote_timeout_is_raised_not_returned_as_a_result() -> None:
    transport = ScriptedTransport(
        [ExecResult(exit_code=None, stdout=b"", stderr=b"", timed_out=True)]
    )
    provider, _, _ = _provider(transport=transport)
    sandbox = await _create(provider)
    session = await provider.open_session(sandbox.sandbox_id)

    with pytest.raises(SandboxTimeout, match="scripted_command_timeout"):
        await session.read_file("slow.txt")


async def test_remote_pty_is_refused() -> None:
    provider, _, _ = _provider()
    sandbox = await _create(provider)
    session = await provider.open_session(sandbox.sandbox_id)

    with pytest.raises(SandboxUnavailable, match="pty_unsupported"):
        await session.create_pty(argv=("bash",))


def test_owner_is_recovered_only_from_our_idempotency_keys() -> None:
    assert owner_from_idempotency_key("coding-task:ct:1:nonce") == "ct:1"
    assert owner_from_idempotency_key("other:ct_1:nonce") is None
    assert owner_from_idempotency_key("coding-task:ct_1") is None


def test_factory_refuses_managed_provider_when_plane_is_disabled() -> None:
    with pytest.raises(SandboxUnavailable, match="managed_sandbox_disabled"):
        create_sandbox_provider(SandboxConfig(provider="managed"))


def test_factory_refuses_remote_managed_provider_without_a_bound_client() -> None:
    config = SandboxConfig(provider="managed", managed={"enabled": True, "provider": "e2b"})

    with pytest.raises(SandboxUnavailable, match="managed_e2b_client_not_bound"):
        create_sandbox_provider(config)


async def test_factory_uses_an_injected_managed_backend() -> None:
    config = SandboxConfig(provider="managed", managed={"enabled": True, "provider": "e2b"})
    adapter = FakeManagedSandboxAdapter()
    backend = ManagedBackend(
        adapter=adapter,
        sessions=_sessions(ScriptedTransport()),
        image_identity=IMAGE,
    )

    provider = create_sandbox_provider(config, managed_backends={"e2b": backend})
    sandbox = await _create(provider)

    assert isinstance(provider, ManagedSandboxProvider)
    assert sandbox.provider == "managed:fake"
    assert adapter.allocate_calls == 1


def test_factory_managed_docker_runs_on_the_local_docker_provider() -> None:
    from neos.coding.sandbox.docker import DockerSandboxProvider

    config = SandboxConfig(
        provider="managed", managed={"enabled": True, "provider": "docker"}
    )

    provider = create_sandbox_provider(config)

    assert isinstance(provider, ManagedSandboxProvider)
    assert isinstance(provider.local_provider, DockerSandboxProvider)
    assert provider.provider_name == "managed:docker"


def test_managed_provider_requires_the_managed_plane() -> None:
    with pytest.raises(ValueError, match="requires sandbox.managed.enabled"):
        AppConfig.model_validate({"sandbox": {"provider": "managed"}})


def test_staging_real_loop_accepts_a_managed_sandbox() -> None:
    config = AppConfig.model_validate(
        {
            "environment": "staging",
            "coding_model": {
                "enabled": True,
                "input_cost_micros_per_million": 3_000_000,
                "output_cost_micros_per_million": 15_000_000,
            },
            "sandbox": {
                "enabled": True,
                "provider": "managed",
                "managed": {"enabled": True, "provider": "docker"},
            },
            "secrets": {
                "anthropic_api_key": "sk-ant-test-placeholder",
                "managed_provider_reference_key": base64.b64encode(b"k" * 32).decode(),
            },
        }
    )

    assert config.sandbox.provider == "managed"


def test_transport_factories_refuse_without_a_bound_client() -> None:
    with pytest.raises(RuntimeError, match="e2b_exec_client_not_bound"):
        create_e2b_transport_factory(enabled=True, api_key="key")
    with pytest.raises(RuntimeError, match="modal_exec_client_not_bound"):
        create_modal_transport_factory(enabled=True, token_id="id", token_secret="secret")


async def test_e2b_transport_turns_vendor_errors_into_sandbox_unavailable() -> None:
    class ExplodingClient:
        async def run_command(self, sandbox_id, argv, **kwargs):
            raise RuntimeError("vendor exploded")

    transport = E2BExecTransport(client=ExplodingClient(), sandbox_id="sbx_1")

    with pytest.raises(SandboxUnavailable, match="e2b_transport_error"):
        await transport.exec(
            ("true",), workdir="/workspace", env={}, stdin=b"", timeout_sec=1.0
        )

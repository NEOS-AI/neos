"""Track Q6c: the managed (E2B / Modal) secret channel -- flag-off, per-provider opt-in.

docs/Q6C_MANAGED_SECRET_CHANNEL_DESIGN_261002.md. The fake vendor SDKs run the
real guest (`LocalSandboxd`) behind them; a recording proxy keeps **every call
that reached the vendor SDK** and every byte that crossed the stdio relay it
opened, so "what reaches the vendor" is asserted on the calls themselves.

No real vendor SDK is bound in this repository, so nothing here proves the vendor
side -- these tests pin what NEOS sends and when it refuses. Each docstring names
the mutation the test bites.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from neos.coding.sandbox.base import CommandRequest, SandboxPolicyViolation, SandboxUnavailable
from neos.coding.sandbox.factory import create_sandbox_provider
from neos.coding.sandbox.managed import ManagedBackend
from neos.coding.sandbox.managed.clients.base import (
    SANDBOXD_CONNECT_ARGV,
    StdioRelayEvidence,
    declared_relay_evidence,
    secret_relay_proven,
)
from neos.coding.sandbox.managed.clients.e2b import E2BProviderClient
from neos.coding.sandbox.managed.clients.modal import ModalProviderClient
from neos.coding.sandbox.managed.ledger import InMemoryCodingRuntimeLedger
from neos.coding.sandboxd import guest
from neos.coding.secrets import InMemorySecretStore
from neos.coding.tools.executor import SandboxToolExecutor
from neos.coding.tools.registry import CodingToolRegistry
from neos.config.schema import AppConfig, ManagedSandboxConfig, SandboxConfig
from tests.coding.sandbox.managed_fakes import (
    IMAGE,
    OWNERSHIP_KEY,
    FakeE2BSdk,
    FakeModalSdk,
    FakeVendor,
    allocation_cipher,
    create,
    managed_stack,
)

pytestmark = pytest.mark.no_db

TOKEN = "q6c-tok-8d1e4b7a2c9f0e35"
_DIGEST = hashlib.sha256(TOKEN.encode()).hexdigest()
_SHOW = (
    "import hashlib, os; "
    "print(hashlib.sha256(os.environ.get('GH_TOKEN', '').encode()).hexdigest())"
)


def _evidence(kind: str, **changes) -> StdioRelayEvidence:
    values = {
        "vendor": kind,
        "tls_verified": True,
        "stdin_retention_source": "https://vendor.invalid/exec-stdin-retention (test, 2026-10-02)",
        "smoke_record": "test-only",
    }
    values.update(changes)
    return StdioRelayEvidence(**values)


def _forms(value: str) -> tuple[bytes, ...]:
    raw = value.encode()
    return (raw, base64.b64encode(raw), raw.hex().encode())


def _frames(data: bytes) -> list[dict]:
    frames, offset = [], 0
    while offset < len(data):
        size = guest.frame_length(data[offset : offset + 4])
        frames.append(guest.decode_payload(data[offset + 4 : offset + 4 + size]))
        offset += 4 + size
    return frames


class RecordingChannel:
    def __init__(self, inner) -> None:
        self._inner = inner
        self.sent = bytearray()
        self.received = bytearray()

    async def read_exactly(self, size: int) -> bytes:
        data = await self._inner.read_exactly(size)
        self.received.extend(data)
        return data

    async def write(self, data: bytes) -> None:
        self.sent.extend(data)
        await self._inner.write(data)

    async def close(self) -> None:
        await self._inner.close()


class RecordingSdk:
    """A vendor SDK proxy: records every call's arguments and the relay's bytes.

    `evidence` is what a real binding would declare; `None` models today's state.
    """

    def __init__(self, inner, evidence: object | None) -> None:
        self._inner = inner
        if evidence is not None:
            self.stdio_relay_evidence = evidence
        self.calls: list[tuple[str, tuple, dict]] = []
        self.channels: list[RecordingChannel] = []

    def __getattr__(self, name: str):
        attribute = getattr(self._inner, name)
        if not callable(attribute):
            return attribute

        async def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            result = await attribute(*args, **kwargs)
            if name == "open_stdio":
                result = RecordingChannel(result)
                self.channels.append(result)
            return result

        return call

    def sent(self) -> bytes:
        return b"".join(bytes(channel.sent) for channel in self.channels)

    def received(self) -> bytes:
        return b"".join(bytes(channel.received) for channel in self.channels)

    def exec_frames(self) -> list[dict]:
        return [
            frame
            for channel in self.channels
            for frame in _frames(bytes(channel.sent))
            if frame.get("op") == "exec"
        ]


async def _no_sleep(_seconds: float) -> None:
    return None


def _client_factory(kind: str, evidence: object | None, holder: dict):
    def build(vendor: FakeVendor):
        if kind == "e2b":
            sdk = RecordingSdk(FakeE2BSdk(vendor), evidence)
            client = E2BProviderClient(sdk=sdk, sleep=_no_sleep)
        else:
            sdk = RecordingSdk(FakeModalSdk(vendor), evidence)
            client = ModalProviderClient(sdk=sdk)
        holder["sdk"] = sdk
        return client

    return build


def _ledger_text(stack) -> str:
    ledger = stack.ledger
    return repr((ledger.runtimes, ledger.physical, ledger.snapshots, stack.table.rows))


KINDS = pytest.mark.parametrize("kind", ["e2b", "modal"])


# ---- flag off: byte-identical refusal ------------------------------------------------


@KINDS
async def test_flag_off_refuses_even_with_evidence_and_sends_nothing(tmp_path, kind) -> None:
    """Mutation: let evidence alone (no operator opt-in) open the channel (MS3)."""
    holder: dict = {}
    async with managed_stack(
        tmp_path, kind, client_factory=_client_factory(kind, _evidence(kind), holder)
    ) as stack:
        assert secret_relay_proven(stack.client)
        sandbox = await create(stack)
        session = await stack.provider.open_session(sandbox.sandbox_id)
        await session.execute(CommandRequest(argv=("true",)))
        before = len(holder["sdk"].exec_frames())

        with pytest.raises(SandboxPolicyViolation, match="^secret_env_unsupported$"):
            await session.execute(
                CommandRequest(argv=("touch", "ran"), secret_env={"GH_TOKEN": TOKEN})
            )

        assert len(holder["sdk"].exec_frames()) == before
        assert not (stack.vendor.live()[0].daemon.workspace / "ran").exists()
        for form in _forms(TOKEN):
            assert form not in holder["sdk"].sent()


@KINDS
async def test_flag_off_frames_are_unchanged(tmp_path, kind) -> None:
    """Mutation: send `secret_env` (even `{}`) on managed frames without secrets (S9)."""
    holder: dict = {}
    async with managed_stack(
        tmp_path, kind, client_factory=_client_factory(kind, None, holder)
    ) as stack:
        sandbox = await create(stack)
        session = await stack.provider.open_session(sandbox.sandbox_id)
        await session.execute(CommandRequest(argv=("true",)))
        (frame,) = holder["sdk"].exec_frames()
        assert set(frame["args"]) == {
            "argv", "cwd", "env", "stdin", "timeout_sec", "max_output_bytes", "max_stdin_bytes"
        }


# ---- opt-in without evidence: refuse to start -----------------------------------------


@KINDS
async def test_opt_in_without_evidence_refuses_to_start(tmp_path, kind) -> None:
    """Mutation: drop the constructor's evidence check -- config alone would open it."""
    holder: dict = {}
    async with managed_stack(
        tmp_path, kind, client_factory=_client_factory(kind, None, holder)
    ) as stack:
        with pytest.raises(SandboxUnavailable, match=f"managed_secret_channel_unproven:{kind}"):
            stack.build_provider(secret_channel=True)


@pytest.mark.parametrize(
    "evidence",
    [
        pytest.param(lambda kind: _evidence(kind, tls_verified=False), id="tls_unverified"),
        pytest.param(
            lambda kind: _evidence(kind, stdin_retention_source="http://vendor.invalid"),
            id="source_not_https",
        ),
        pytest.param(lambda kind: _evidence(kind, stdin_retention_source=""), id="no_source"),
        pytest.param(lambda kind: _evidence(kind, smoke_record="  "), id="no_smoke"),
        pytest.param(
            lambda kind: _evidence("modal" if kind == "e2b" else "e2b"), id="other_vendor"
        ),
        pytest.param(
            lambda kind: {
                "vendor": kind,
                "tls_verified": True,
                "stdin_retention_source": "https://x",
                "smoke_record": "x",
            },
            id="not_the_evidence_type",
        ),
        pytest.param(lambda kind: True, id="bare_true"),
    ],
)
@KINDS
def test_incomplete_evidence_is_no_evidence(tmp_path, kind, evidence) -> None:
    """Mutation: any one field of `StdioRelayEvidence.proves` dropped, or duck-typing it."""
    holder: dict = {}
    client = _client_factory(kind, evidence(kind), holder)(FakeVendor(root=tmp_path))
    assert client.secret_relay_evidence is None
    assert declared_relay_evidence(holder["sdk"], kind) is None
    assert not secret_relay_proven(client)


def test_a_client_that_declares_nothing_is_not_proven() -> None:
    """Mutation: default `secret_relay_proven` to true for clients without the property."""

    class Bare:
        name = "e2b"

    assert not secret_relay_proven(Bare())
    assert not secret_relay_proven(object())


# ---- opt-in with evidence: what reaches the vendor ------------------------------------


@KINDS
async def test_opted_in_the_secret_travels_only_in_the_relay_frame_field(
    tmp_path, kind, caplog
) -> None:
    """Mutation: merge `secret_env` into `env`, or route it through any vendor SDK argument.

    The vendor sees the fixed relay argv and nothing else from NEOS outside the
    relay's stdin bytes; inside those bytes the value is only in `secret_env`.
    """
    caplog.set_level(logging.DEBUG)
    holder: dict = {}
    async with managed_stack(
        tmp_path, kind, client_factory=_client_factory(kind, _evidence(kind), holder)
    ) as stack:
        stack.provider = stack.build_provider(secret_channel=True)
        sandbox = await create(stack)
        session = await stack.provider.open_session(sandbox.sandbox_id)

        result = await session.execute(
            CommandRequest(argv=(sys.executable, "-c", _SHOW), secret_env={"GH_TOKEN": TOKEN})
        )

        assert result.exit_code == 0, result.stderr
        assert result.stdout.decode().strip() == _DIGEST
        sdk = holder["sdk"]
        (frame,) = sdk.exec_frames()
        assert frame["args"]["secret_env"] == {"GH_TOKEN": TOKEN}
        assert frame["args"]["env"] == {}
        assert TOKEN not in repr(frame["args"]["argv"])
        # Every vendor SDK call: the relay is opened with the fixed argv, and no
        # argument of any call (create, metadata, list, open_stdio...) holds the value.
        relays = [(args, kwargs) for name, args, kwargs in sdk.calls if name == "open_stdio"]
        assert relays
        assert all(
            tuple(args[1]) == SANDBOXD_CONNECT_ARGV and len(args) == 2 and not kwargs
            for args, kwargs in relays
        )
        assert TOKEN not in repr(sdk.calls)
        assert TOKEN not in repr([obj.metadata for obj in stack.vendor.objects.values()])
        for form in _forms(TOKEN):
            assert form not in sdk.received()
        assert TOKEN not in _ledger_text(stack)
        assert TOKEN not in caplog.text


@KINDS
async def test_lease_views_keep_the_opt_in(tmp_path, kind) -> None:
    """Mutation: `for_lease` forgets `secret_channel` -- the run's own view would refuse."""
    holder: dict = {}
    async with managed_stack(
        tmp_path, kind, client_factory=_client_factory(kind, _evidence(kind), holder)
    ) as stack:
        stack.provider = stack.build_provider(secret_channel=True)
        sandbox = await create(stack)
        view = stack.provider.for_lease(stack.lease())
        try:
            session = await view.open_session(sandbox.sandbox_id)
            result = await session.execute(
                CommandRequest(
                    argv=(sys.executable, "-c", _SHOW), secret_env={"GH_TOKEN": TOKEN}
                )
            )
        finally:
            await view.close()
        assert result.stdout.decode().strip() == _DIGEST


@KINDS
async def test_evidence_withdrawn_after_start_closes_the_channel(tmp_path, kind) -> None:
    """Mutation: `_Attachment.confidential_channel` trusts the constructor's check alone."""
    holder: dict = {}
    async with managed_stack(
        tmp_path, kind, client_factory=_client_factory(kind, _evidence(kind), holder)
    ) as stack:
        stack.provider = stack.build_provider(secret_channel=True)
        sandbox = await create(stack)
        session = await stack.provider.open_session(sandbox.sandbox_id)
        del holder["sdk"].stdio_relay_evidence
        with pytest.raises(SandboxPolicyViolation, match="^secret_env_unsupported$"):
            await session.execute(
                CommandRequest(argv=("touch", "ran"), secret_env={"GH_TOKEN": TOKEN})
            )
        assert holder["sdk"].exec_frames() == []


# ---- the executor over a managed sandbox: S6 scrubbing still holds ----------------------


async def _lookup():
    store = InMemorySecretStore()
    await store.put("test_q6c_owner", "github", env_name="GH_TOKEN", value=TOKEN)

    async def lookup(names):
        return await store.resolve("test_q6c_owner", names)

    return lookup


_ECHO = (
    "import os, sys\n"
    "print(os.environ['GH_TOKEN'])\n"
    "print(os.environ['GH_TOKEN'], file=sys.stderr)\n"
)


def _tail_script(cut: int) -> str:
    return f"import os, sys\nsys.stdout.write('A' * {cut - 10} + os.environ['GH_TOKEN'])\n"


def _execute_call(script: str, *, max_output_bytes: int | None = None):
    registry = CodingToolRegistry.default(
        # The registry refuses executable paths and inline `-c`; the guest PATH is /usr/bin:/bin.
        command_allowlist=frozenset({"python3"}),
        allowed_env_names=frozenset({"LANG"}),
        secret_env_refs=True,
    )
    payload: dict = {
        "argv": ["python3", script],
        "env": {"GH_TOKEN": "secret://github"},
    }
    if max_output_bytes is not None:
        payload["max_output_bytes"] = max_output_bytes
    return registry.validate("execute.v1", payload)


async def _opted_in_session(stack, script: str):
    stack.provider = stack.build_provider(secret_channel=True)
    sandbox = await create(stack)
    session = await stack.provider.open_session(sandbox.sandbox_id)
    await session.write_file("q6c.py", script.encode())
    return session


@KINDS
async def test_the_executor_scrubs_managed_output_and_keeps_only_the_reference(
    tmp_path, kind
) -> None:
    """Mutation: skip `scrub_bytes` on the managed path, or resolve into `env`."""
    holder: dict = {}
    async with managed_stack(
        tmp_path, kind, client_factory=_client_factory(kind, _evidence(kind), holder)
    ) as stack:
        session = await _opted_in_session(stack, _ECHO)
        call = _execute_call("q6c.py")

        result = await SandboxToolExecutor(4096, 10).execute(
            session, call, secrets=await _lookup()
        )

        assert result.status == "ok", result.to_mapping()
        assert TOKEN not in repr(result.to_mapping())
        assert "<redacted:secret://github>" in result.stdout["preview"]
        assert "<redacted:secret://github>" in result.stderr["preview"]
        assert call.input["env"] == {"GH_TOKEN": "secret://github"}
        (frame,) = holder["sdk"].exec_frames()
        assert frame["args"]["env"] == {}
        assert frame["args"]["secret_env"] == {"GH_TOKEN": TOKEN}


@KINDS
async def test_a_truncated_tail_of_the_value_is_scrubbed_on_managed_output(
    tmp_path, kind
) -> None:
    """Mutation: drop the truncated-tail branch of S6 for relay output."""
    holder: dict = {}
    async with managed_stack(
        tmp_path, kind, client_factory=_client_factory(kind, _evidence(kind), holder)
    ) as stack:
        cut = 2048
        session = await _opted_in_session(stack, _tail_script(cut))
        call = _execute_call("q6c.py", max_output_bytes=cut)

        result = await SandboxToolExecutor(8192, 10).execute(
            session, call, secrets=await _lookup()
        )

        assert result.status == "ok", result.to_mapping()
        assert result.stdout["truncated"] is True
        assert result.stdout["preview"].endswith("<redacted:secret://github>")
        assert TOKEN[:10] not in repr(result.to_mapping())


@KINDS
async def test_without_the_opt_in_the_executor_reports_the_named_denial(tmp_path, kind) -> None:
    """MS3: flag off, a managed sandbox is still `denied/secret_env_unsupported` (S9)."""
    holder: dict = {}
    async with managed_stack(
        tmp_path, kind, client_factory=_client_factory(kind, _evidence(kind), holder)
    ) as stack:
        sandbox = await create(stack)
        session = await stack.provider.open_session(sandbox.sandbox_id)
        result = await SandboxToolExecutor(4096, 10).execute(
            session, _execute_call("q6c.py"), secrets=await _lookup()
        )
        assert (result.status, result.reason_code) == ("denied", "secret_env_unsupported")
        assert holder["sdk"].exec_frames() == []


# ---- config and factory ---------------------------------------------------------------


def test_the_default_opts_no_provider_in() -> None:
    assert ManagedSandboxConfig().secret_env_providers == ()
    assert AppConfig().sandbox.managed.secret_env_providers == ()


@pytest.mark.parametrize(
    "value",
    [["e2b", "e2b"], ["daytona"], ["docker"], ["fake"], "e2b"],
    ids=["duplicate", "unknown", "docker", "fake", "bare_string"],
)
def test_the_opt_in_list_is_validated(value) -> None:
    """Mutation: drop the duplicate check, or widen the literal past e2b/modal."""
    with pytest.raises(ValidationError):
        ManagedSandboxConfig.model_validate({"secret_env_providers": value})


def test_the_opt_in_needs_the_broker() -> None:
    """Mutation: drop `validate_managed_secret_channel` -- an inert opt-in would stay on."""
    with pytest.raises(ValidationError, match="requires coding_model.secret_broker"):
        AppConfig.model_validate({"sandbox": {"managed": {"secret_env_providers": ["e2b"]}}})
    config = AppConfig.model_validate(
        {
            "sandbox": {"managed": {"secret_env_providers": ["e2b", "modal"]}},
            "coding_model": {"secret_broker": True},
            "secrets": {"secret_broker_key": "k" * 40},
        }
    )
    assert config.sandbox.managed.secret_env_providers == ("e2b", "modal")


def _config(provider: str, opted: list[str]) -> SandboxConfig:
    return SandboxConfig.model_validate(
        {
            "provider": "managed",
            "managed": {"enabled": True, "provider": provider, "secret_env_providers": opted},
        }
    )


def _backend(tmp_path: Path, kind: str, evidence: object | None) -> ManagedBackend:
    return ManagedBackend(
        client=_client_factory(kind, evidence, {})(FakeVendor(root=tmp_path)),
        ledger=InMemoryCodingRuntimeLedger(),
        image_digest=IMAGE,
        ownership_key=OWNERSHIP_KEY,
        allocation_cipher=allocation_cipher,
    )


@KINDS
def test_the_factory_refuses_an_unproven_opt_in(tmp_path, kind) -> None:
    """Mutation: the factory passes the flag but nothing checks the evidence."""
    with pytest.raises(SandboxUnavailable, match=f"managed_secret_channel_unproven:{kind}"):
        create_sandbox_provider(
            _config(kind, [kind]), managed_backends={kind: _backend(tmp_path, kind, None)}
        )


@KINDS
def test_the_factory_opens_only_the_named_provider(tmp_path, kind) -> None:
    """Mutation: treat a non-empty list as 'every provider' (MS3 is per provider)."""
    other = "modal" if kind == "e2b" else "e2b"
    proven = _backend(tmp_path, kind, _evidence(kind))
    named = create_sandbox_provider(_config(kind, [kind]), managed_backends={kind: proven})
    unnamed = create_sandbox_provider(_config(kind, [other]), managed_backends={kind: proven})
    default = create_sandbox_provider(_config(kind, []), managed_backends={kind: proven})
    assert named._secret_channel is True
    assert unnamed._secret_channel is False
    assert default._secret_channel is False

"""Track Q6b: `CommandRequest.secret_env` over the sandboxd RPC.

The guest runs unmodified as a local subprocess (`LocalSandboxd`); a recording
channel keeps every byte the host wrote and read, so "the value is not in the
trace" is asserted on the wire itself, not on a log formatter. Each docstring
names the mutation the test bites (docs/Q6B_SANDBOX_SECRET_CHANNEL_DESIGN_261002.md).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import sys
from pathlib import Path

import pytest

from neos.coding.sandbox.base import (
    CommandRequest,
    SandboxLimits,
    SandboxPolicyViolation,
)
from neos.coding.sandboxd import guest
from neos.coding.sandboxd.client import (
    OPTIONAL_CAPABILITIES,
    SandboxdClient,
    SandboxdExpectation,
)
from neos.coding.sandboxd.local import LocalSandboxd
from neos.coding.sandboxd.session import SandboxdLease, SandboxdSession
from tests.coding.sandbox.managed_fakes import create, managed_stack

pytestmark = pytest.mark.no_db

TOKEN = "q6b-tok-3f9c1a7e5d2b8c40"
_DIGEST = hashlib.sha256(TOKEN.encode()).hexdigest()
_SHOW = (
    "import hashlib, os\n"
    "print(hashlib.sha256(os.environ.get('GH_TOKEN', '').encode()).hexdigest())\n"
    "print(os.environ['PATH'], os.environ['HOME'], os.environ['TMPDIR'], sep='|')\n"
)


def _forms(value: str) -> tuple[bytes, ...]:
    """Every encoding the value could travel in on this wire."""
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
    """Wraps the real unix-socket channel; keeps what crossed it."""

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


class RecordingAttachment:
    sandbox_id = "sbx_q6b"
    allowed_env_names = frozenset({"LANG"})
    operation_timeout_sec = 15.0
    max_pty_sessions = 2

    def __init__(
        self,
        daemon: LocalSandboxd,
        *,
        expectation: SandboxdExpectation | None = None,
        confidential: bool | None = True,
    ) -> None:
        self.daemon = daemon
        self.expectation = expectation or SandboxdExpectation.bundled()
        self.channel: RecordingChannel | None = None
        self.client: SandboxdClient | None = None
        self.lock = asyncio.Lock()
        if confidential is not None:
            # `None` models an attachment written before Q6b: no attribute at all.
            self.confidential_channel = confidential and daemon.confidential_channel

    async def attach(self) -> SandboxdLease:
        if self.client is None or self.client.closed:
            self.channel = RecordingChannel(await self.daemon.open_channel())
            self.client = SandboxdClient(self.channel)
            await self.client.handshake(self.expectation)
        return SandboxdLease(
            client=self.client, limits=SandboxLimits.safe_defaults(), generation=1
        )

    def mutation_lock(self):
        return self.lock

    async def commit_revision(self, revision: int, *, generation: int) -> None:
        return None

    async def current_generation(self) -> int:
        return 1

    async def commit_stream_cursor(self, stream: str, cursor: int, *, generation: int) -> None:
        return None


@pytest.fixture
async def daemon(tmp_path: Path):
    local = LocalSandboxd(tmp_path / "sbx", stderr_path=tmp_path / "guest.stderr")
    await local.start()
    try:
        yield local
    finally:
        await local.stop()


def _show(daemon: LocalSandboxd) -> None:
    (daemon.workspace / "show.py").write_text(_SHOW)


def _exec_frames(channel: RecordingChannel) -> list[dict]:
    return [frame for frame in _frames(bytes(channel.sent)) if frame.get("op") == "exec"]


# ---- round trip ------------------------------------------------------------------


async def test_the_secret_reaches_the_child_and_only_the_secret_field_carries_it(
    daemon, tmp_path, caplog
) -> None:
    """Mutation: merge `secret_env` into `env` before transport (or drop it)."""
    caplog.set_level(logging.DEBUG)
    _show(daemon)
    attachment = RecordingAttachment(daemon)
    session = SandboxdSession(attachment)

    result = await session.execute(
        CommandRequest(argv=(sys.executable, "show.py"), secret_env={"GH_TOKEN": TOKEN})
    )

    assert result.exit_code == 0, result.stderr
    assert result.stdout.decode().splitlines()[0] == _DIGEST
    (frame,) = _exec_frames(attachment.channel)
    assert frame["args"]["secret_env"] == {"GH_TOKEN": TOKEN}
    assert frame["args"]["env"] == {}
    assert TOKEN not in str(frame["args"]["argv"])
    # Nothing the guest sent back carries the value; neither do logs or its stderr.
    for form in _forms(TOKEN):
        assert form not in bytes(attachment.channel.received)
        assert form not in (tmp_path / "guest.stderr").read_bytes()
    assert TOKEN not in caplog.text


async def test_frames_without_secrets_are_byte_for_byte_what_they_were(daemon) -> None:
    """Mutation: always send `secret_env` (even `{}`) -- S9 says flag-off is unchanged."""
    attachment = RecordingAttachment(daemon)
    await SandboxdSession(attachment).execute(CommandRequest(argv=("true",)))

    (frame,) = _exec_frames(attachment.channel)
    assert set(frame["args"]) == {
        "argv", "cwd", "env", "stdin", "timeout_sec", "max_output_bytes", "max_stdin_bytes"
    }


async def test_reserved_names_are_not_overridable_by_secrets(daemon) -> None:
    """Mutation: drop the guest's reserved-name filter for `secret_env`.

    The raw client skips the host filter, so only the guest stands between a
    secret named PATH and the child's PATH.
    """
    _show(daemon)
    client = SandboxdClient(await daemon.open_channel())
    await client.handshake(SandboxdExpectation.bundled())
    try:
        result = await client.call(
            "exec",
            {
                "argv": [sys.executable, "show.py"],
                "secret_env": {
                    "GH_TOKEN": TOKEN,
                    "PATH": "/evil",
                    "HOME": "/evil",
                    "TMPDIR": "/evil",
                },
                "timeout_sec": 10,
                "max_output_bytes": 4096,
                "max_stdin_bytes": 0,
            },
        )
    finally:
        await client.close()
    digest, paths = base64.b64decode(result["stdout"]).decode().splitlines()
    assert digest == _DIGEST
    path, home, tmp = paths.split("|")
    assert path == guest.GUEST_PATH
    assert "/evil" not in (home, tmp)


async def test_the_host_also_filters_reserved_names(daemon) -> None:
    """Mutation: send `request.secret_env` unfiltered from the session."""
    attachment = RecordingAttachment(daemon)
    await SandboxdSession(attachment).execute(
        CommandRequest(argv=("true",), secret_env={"GH_TOKEN": TOKEN, "PATH": "/evil"})
    )
    (frame,) = _exec_frames(attachment.channel)
    assert frame["args"]["secret_env"] == {"GH_TOKEN": TOKEN}


# ---- error paths -----------------------------------------------------------------


async def test_exec_failures_carry_a_code_not_the_environment(daemon, tmp_path) -> None:
    """Mutation: a guest error that formats its arguments into the code."""
    attachment = RecordingAttachment(daemon)
    session = SandboxdSession(attachment)
    with pytest.raises(SandboxPolicyViolation, match="command_not_found") as missing:
        await session.execute(
            CommandRequest(argv=("/nonexistent/q6b",), secret_env={"GH_TOKEN": TOKEN})
        )
    client = SandboxdClient(await daemon.open_channel())
    await client.handshake(SandboxdExpectation.bundled())
    try:
        with pytest.raises(SandboxPolicyViolation, match="command_environment_invalid") as bad:
            await client.call(
                "exec",
                {
                    "argv": ["true"],
                    "secret_env": {"1BAD": TOKEN, "OK": TOKEN + "\0"},
                    "timeout_sec": 5,
                    "max_output_bytes": 100,
                    "max_stdin_bytes": 0,
                },
            )
        with pytest.raises(SandboxPolicyViolation, match="request_invalid") as shaped:
            await client.call(
                "exec",
                {
                    "argv": ["true"],
                    "secret_env": [TOKEN],
                    "timeout_sec": 5,
                    "max_output_bytes": 100,
                    "max_stdin_bytes": 0,
                },
            )
    finally:
        await client.close()
    for error in (missing.value, bad.value, shaped.value):
        assert TOKEN not in str(error) and TOKEN not in repr(error)
    for form in _forms(TOKEN):
        assert form not in bytes(attachment.channel.received)
        assert form not in (tmp_path / "guest.stderr").read_bytes()


async def test_a_command_request_never_shows_the_secret_in_its_repr() -> None:
    """Mutation: `secret_env` without `repr=False` (Q6 field; Q6b relies on it)."""
    request = CommandRequest(argv=("true",), secret_env={"GH_TOKEN": TOKEN})
    assert TOKEN not in repr(request)


# ---- negotiation and transport ----------------------------------------------------


def test_the_secret_capability_is_advertised_but_not_required_at_handshake() -> None:
    """Mutation: require the capability at handshake -- every older pinned guest stops serving."""
    assert guest.SECRET_ENV_CAPABILITY in guest.CAPABILITIES
    assert guest.SECRET_ENV_CAPABILITY in OPTIONAL_CAPABILITIES
    assert guest.SECRET_ENV_CAPABILITY not in SandboxdExpectation.bundled().required_capabilities
    assert SandboxdExpectation.bundled().required_capabilities == (
        frozenset(guest.CAPABILITIES) - {guest.SECRET_ENV_CAPABILITY}
    )


def _older_guest(tmp_path: Path) -> Path:
    """The current guest minus the advertisement -- nothing it does not have.

    A real pre-Q6b guest ignores `secret_env` (`args.get` never reads it), so it
    would run the command *without* the secret. The host must never send it.
    """
    source = Path(guest.__file__).read_text()
    marker = "    SECRET_ENV_CAPABILITY,\n"
    assert source.count(marker) == 1
    path = tmp_path / "older_guest.py"
    path.write_text(source.replace(marker, ""))
    return path


async def test_an_older_guest_is_refused_secrets_and_nothing_is_sent(tmp_path) -> None:
    """Mutation: skip the per-lease capability check (C3)."""
    older = _older_guest(tmp_path)
    daemon = LocalSandboxd(tmp_path / "old", guest_path=older)
    await daemon.start()
    try:
        attachment = RecordingAttachment(
            daemon, expectation=SandboxdExpectation(bundle_digest=guest.bundle_digest(str(older)))
        )
        session = SandboxdSession(attachment)
        # It still serves everything else.
        assert (await session.execute(CommandRequest(argv=("true",)))).exit_code == 0
        assert not attachment.client.supports(guest.SECRET_ENV_CAPABILITY)
        before = len(_exec_frames(attachment.channel))

        with pytest.raises(SandboxPolicyViolation, match="secret_env_unsupported"):
            await session.execute(
                CommandRequest(argv=("touch", "ran"), secret_env={"GH_TOKEN": TOKEN})
            )

        assert len(_exec_frames(attachment.channel)) == before
        assert not (daemon.workspace / "ran").exists()
        for form in _forms(TOKEN):
            assert form not in bytes(attachment.channel.sent)
    finally:
        await daemon.stop()


@pytest.mark.parametrize("confidential", [False, None], ids=["declared_false", "undeclared"])
async def test_an_attachment_that_cannot_show_a_private_channel_refuses(
    daemon, confidential
) -> None:
    """Mutation: default `confidential_channel` to True, or drop the C1 check."""
    attachment = RecordingAttachment(daemon, confidential=confidential)
    with pytest.raises(SandboxPolicyViolation, match="secret_env_unsupported"):
        await SandboxdSession(attachment).execute(
            CommandRequest(argv=("touch", "ran"), secret_env={"GH_TOKEN": TOKEN})
        )
    assert attachment.client is None  # refused before connecting
    assert not (daemon.workspace / "ran").exists()


@pytest.mark.parametrize("kind", ["e2b", "modal"])
async def test_managed_sandboxes_still_refuse_secrets(tmp_path: Path, kind: str) -> None:
    """Mutation: let the managed attachment claim a confidential channel.

    The guest behind the fake vendor *does* advertise the capability -- the
    refusal is the transport decision (C1), not the negotiation.
    """
    async with managed_stack(tmp_path, kind) as stack:
        sandbox = await create(stack)
        session = await stack.provider.open_session(sandbox.sandbox_id)
        await session.execute(CommandRequest(argv=("true",)))
        (_epoch, client), = stack.provider._clients.values()
        assert client.supports(guest.SECRET_ENV_CAPABILITY)

        with pytest.raises(SandboxPolicyViolation, match="secret_env_unsupported"):
            await session.execute(
                CommandRequest(argv=("touch", "ran"), secret_env={"GH_TOKEN": TOKEN})
            )

        workspace = stack.vendor.live()[0].daemon.workspace
        assert not (workspace / "ran").exists()

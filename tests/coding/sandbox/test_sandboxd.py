"""neos-sandboxd: framed RPC, handshake pinning, CAS, and guest-side policy.

The guest runs unmodified as a local subprocess (`LocalSandboxd`). Provider
level suites (conformance, security, recovery) drive the same daemon through
`ManagedSandboxProvider`; this file pins the protocol and the guest itself.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from neos.coding.domain.approvals import is_denied_secret_path
from neos.coding.sandbox import ignore as host_ignore
from neos.coding.sandbox.base import (
    CommandRequest,
    ReplayGap,
    SandboxLimits,
    SandboxPolicyViolation,
    SandboxStateConflict,
    SandboxUnavailable,
)
from neos.coding.sandboxd import guest
from neos.coding.sandboxd.client import (
    SandboxdClient,
    SandboxdExpectation,
)
from neos.coding.sandboxd.local import LocalSandboxd
from neos.coding.sandboxd.session import SandboxdLease, SandboxdSession

pytestmark = pytest.mark.no_db


class LocalAttachment:
    """Minimal attachment: one sandbox, one generation, no ledger."""

    sandbox_id = "sbx_local"
    allowed_env_names = frozenset({"LANG", "NEOS_VISIBLE"})
    operation_timeout_sec = 15.0
    max_pty_sessions = 4

    def __init__(self, daemon: LocalSandboxd, limits: SandboxLimits) -> None:
        self.daemon = daemon
        self.limits = limits
        self.client: SandboxdClient | None = None
        self.lock = asyncio.Lock()

    async def attach(self) -> SandboxdLease:
        if self.client is None or self.client.closed:
            self.client = SandboxdClient(await self.daemon.open_channel())
            await self.client.handshake(SandboxdExpectation.bundled())
        return SandboxdLease(client=self.client, limits=self.limits, generation=1)

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
    local = LocalSandboxd(tmp_path / "sbx")
    await local.start()
    try:
        yield local
    finally:
        await local.stop()


@pytest.fixture
def session(daemon: LocalSandboxd) -> SandboxdSession:
    return SandboxdSession(LocalAttachment(daemon, SandboxLimits.safe_defaults()))


# ---- protocol ------------------------------------------------------------------


def test_frames_round_trip_and_refuse_oversized_payloads() -> None:
    frame = guest.encode_frame({"v": 1, "id": 7, "op": "revision"})
    assert guest.decode_payload(frame[4:]) == {"v": 1, "id": 7, "op": "revision"}
    with pytest.raises(guest.FrameError, match="frame_too_large"):
        guest.frame_length((guest.MAX_FRAME_BYTES + 1).to_bytes(4, "big"))
    with pytest.raises(guest.FrameError, match="frame_invalid"):
        guest.decode_payload(b"[1, 2]")


def test_digest_mode_prints_the_pinned_bundle_digest() -> None:
    output = subprocess.run(
        [sys.executable, guest.__file__, "digest"],
        check=True,
        capture_output=True,
        env={"PATH": guest.GUEST_PATH},
    ).stdout.decode()
    assert output.strip() == guest.bundle_digest()
    assert output.startswith("sha256:")


async def test_handshake_refuses_a_different_bundle_digest(daemon) -> None:
    client = SandboxdClient(await daemon.open_channel())
    with pytest.raises(SandboxUnavailable, match="sandboxd_digest_mismatch"):
        await client.handshake(SandboxdExpectation(bundle_digest="sha256:" + "0" * 64))
    assert client.closed
    with pytest.raises(SandboxUnavailable):
        await client.call("revision")


async def test_handshake_refuses_a_different_protocol_version(daemon) -> None:
    client = SandboxdClient(await daemon.open_channel())
    expectation = SandboxdExpectation(
        bundle_digest=guest.bundle_digest(), protocol_version=guest.PROTOCOL_VERSION + 1
    )
    with pytest.raises(SandboxUnavailable, match="sandboxd_protocol_mismatch"):
        await client.handshake(expectation)


async def test_handshake_refuses_missing_capabilities(daemon) -> None:
    client = SandboxdClient(await daemon.open_channel())
    expectation = SandboxdExpectation(
        bundle_digest=guest.bundle_digest(),
        required_capabilities=frozenset({*guest.CAPABILITIES, "pty.resize.v9"}),
    )
    with pytest.raises(SandboxUnavailable, match="sandboxd_capability_missing:pty.resize.v9"):
        await client.handshake(expectation)


async def test_guest_refuses_requests_before_the_handshake(daemon) -> None:
    channel = await daemon.open_channel()
    await channel.write(guest.encode_frame({"v": 1, "id": 1, "op": "revision", "args": {}}))
    header = await channel.read_exactly(4)
    response = guest.decode_payload(await channel.read_exactly(guest.frame_length(header)))
    assert response["ok"] is False
    assert response["error"] == {"kind": "protocol", "code": "handshake_required"}
    await channel.close()


async def test_client_refuses_calls_without_a_handshake(daemon) -> None:
    client = SandboxdClient(await daemon.open_channel())
    with pytest.raises(SandboxUnavailable, match="sandboxd_handshake_required"):
        await client.call("revision")
    await client.close()


async def test_handshake_base_revision_never_moves_the_revision_backwards(daemon) -> None:
    first = SandboxdClient(await daemon.open_channel())
    hello = await first.handshake(SandboxdExpectation.bundled(), base_revision=5)
    assert hello.revision == 5
    second = SandboxdClient(await daemon.open_channel())
    assert (await second.handshake(SandboxdExpectation.bundled(), base_revision=2)).revision == 5
    await first.close()
    await second.close()


# ---- revision and CAS ----------------------------------------------------------


async def test_write_if_revision_is_an_atomic_compare_and_replace(session) -> None:
    assert await session.write_file_if_revision("a.txt", b"one", expected_revision=0) == 1
    with pytest.raises(SandboxStateConflict, match="workspace_revision_conflict"):
        await session.write_file_if_revision("a.txt", b"two", expected_revision=0)
    assert await session.read_file("a.txt") == b"one"
    assert await session.workspace_revision() == 1


async def test_concurrent_conditional_writes_have_exactly_one_winner(daemon) -> None:
    limits = SandboxLimits.safe_defaults()
    # Separate attachments: no host lock serializes them, only the guest.
    sessions = [SandboxdSession(LocalAttachment(daemon, limits)) for _ in range(8)]
    outcomes = await asyncio.gather(
        *(
            item.write_file_if_revision("race.txt", f"writer-{index}".encode(), expected_revision=0)
            for index, item in enumerate(sessions)
        ),
        return_exceptions=True,
    )
    winners = [outcome for outcome in outcomes if outcome == 1]
    losers = [outcome for outcome in outcomes if isinstance(outcome, SandboxStateConflict)]
    assert len(winners) == 1
    assert len(losers) == 7


async def test_revision_survives_a_daemon_restart(tmp_path) -> None:
    root = tmp_path / "persist"
    first = LocalSandboxd(root)
    await first.start()
    try:
        session = SandboxdSession(LocalAttachment(first, SandboxLimits.safe_defaults()))
        await session.write_file("x.txt", b"x")
        await session.mkdir("d")
    finally:
        await first.stop()
    second = LocalSandboxd(root)
    await second.start()
    try:
        session = SandboxdSession(LocalAttachment(second, SandboxLimits.safe_defaults()))
        assert await session.workspace_revision() == 2
    finally:
        await second.stop()


async def test_watcher_cursor_outside_the_journal_is_a_replay_gap(session) -> None:
    for index in range(guest.JOURNAL_EVENTS + 5):
        await session.mkdir(f"d{index}")
    with pytest.raises(ReplayGap):
        await session.watch_files(after_cursor=0)
    watcher = await session.watch_files(after_cursor=guest.JOURNAL_EVENTS)
    replay = await watcher.replay(after_cursor=guest.JOURNAL_EVENTS)
    assert replay[-1].value.workspace_revision == guest.JOURNAL_EVENTS + 5


# ---- guest path policy ---------------------------------------------------------


async def test_traversal_and_absolute_paths_are_refused_by_the_guest(daemon) -> None:
    client = SandboxdClient(await daemon.open_channel())
    await client.handshake(SandboxdExpectation.bundled())
    # Bypass the host-side normalization: the guest must refuse on its own.
    with pytest.raises(SandboxPolicyViolation, match="workspace_path_escape"):
        await client.call("read_file", {"path": "../../etc/passwd", "max_bytes": 100})
    with pytest.raises(SandboxPolicyViolation, match="workspace_path_is_absolute"):
        await client.call("stat", {"path": "/etc/passwd"})
    with pytest.raises(SandboxPolicyViolation, match="protected_git_path"):
        await client.call(
            "write_file", {"path": ".git/config", "data": "", "max_bytes": 10}
        )
    await client.close()


async def test_symlink_parent_and_leaf_do_not_escape_the_workspace(
    daemon, session, tmp_path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"host secret")
    os.symlink(outside, daemon.workspace / "linkdir")
    os.symlink(outside / "secret.txt", daemon.workspace / "leak.txt")

    with pytest.raises(SandboxPolicyViolation, match="workspace_symlink_parent"):
        await session.write_file("linkdir/planted.txt", b"x")
    with pytest.raises(SandboxPolicyViolation, match="workspace_symlink_parent"):
        await session.read_file("linkdir/secret.txt")
    with pytest.raises(SandboxPolicyViolation, match="workspace_symlink_leaf"):
        await session.read_file("leak.txt")
    with pytest.raises(SandboxPolicyViolation, match="workspace_symlink_leaf"):
        await session.write_file("leak.txt", b"overwrite")
    assert not (outside / "planted.txt").exists()
    assert (outside / "secret.txt").read_bytes() == b"host secret"


async def test_hardlinked_files_are_neither_read_nor_chmodded(daemon, session, tmp_path) -> None:
    outside = tmp_path / "host.txt"
    outside.write_bytes(b"host bytes")
    os.link(outside, daemon.workspace / "hard.txt")

    with pytest.raises(SandboxPolicyViolation, match="workspace_hardlink"):
        await session.read_file("hard.txt")
    with pytest.raises(SandboxPolicyViolation, match="workspace_hardlink"):
        await session.chmod("hard.txt", 0o777)
    # A write replaces the directory entry; the other link keeps its bytes.
    await session.write_file("hard.txt", b"replaced")
    assert outside.read_bytes() == b"host bytes"


async def test_fifos_and_devices_are_refused_without_blocking(daemon, session) -> None:
    os.mkfifo(daemon.workspace / "pipe")
    async with asyncio.timeout(5):
        with pytest.raises(SandboxPolicyViolation, match="workspace_path_is_not_file"):
            await session.read_file("pipe")


async def test_setuid_bits_are_refused(session) -> None:
    await session.write_file("tool", b"#!/bin/sh\n")
    with pytest.raises(SandboxPolicyViolation, match="workspace_mode_not_allowed"):
        await session.chmod("tool", 0o4755)


async def test_secret_paths_are_refused_and_hidden(daemon, session) -> None:
    (daemon.workspace / ".env").write_bytes(b"TOKEN=1")
    client = SandboxdClient(await daemon.open_channel())
    await client.handshake(SandboxdExpectation.bundled())
    with pytest.raises(SandboxPolicyViolation, match="workspace_secret_path"):
        await client.call("read_file", {"path": ".env", "max_bytes": 100})
    await client.close()
    assert all(entry.path != ".env" for entry in await session.list_tree("."))


async def test_read_byte_cap_is_enforced_in_the_guest(session) -> None:
    await session.write_file("big.txt", b"x" * 64)
    with pytest.raises(SandboxPolicyViolation, match="file_read_limit_exceeded"):
        await session.read_file("big.txt", max_bytes=16)


# ---- commands ------------------------------------------------------------------


async def test_argv_is_never_reparsed_by_a_shell(daemon, session) -> None:
    payload = "$(touch pwned); `touch pwned2` && touch pwned3"
    result = await session.execute(CommandRequest(argv=("printf", "%s", payload)))
    assert result.stdout == payload.encode()
    assert not any((daemon.workspace / name).exists() for name in ("pwned", "pwned2", "pwned3"))
    with pytest.raises(SandboxPolicyViolation, match="shell_command_not_allowed"):
        client = SandboxdClient(await daemon.open_channel())
        await client.handshake(SandboxdExpectation.bundled())
        try:
            await client.call(
                "exec",
                {
                    "argv": ["/bin/sh", "-c", "touch pwned"],
                    "timeout_sec": 5,
                    "max_output_bytes": 100,
                    "max_stdin_bytes": 100,
                },
            )
        finally:
            await client.close()


async def test_guest_environment_is_built_not_inherited(session, monkeypatch) -> None:
    monkeypatch.setenv("NEOS_HOST_SECRET", "must-not-leak")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-leak")
    result = await session.execute(
        CommandRequest(argv=("env",), env={"NEOS_VISIBLE": "yes", "LANG": "C.UTF-8"})
    )
    lines = set(result.stdout.decode().splitlines())
    assert b"must-not-leak" not in result.stdout
    assert f"PATH={guest.GUEST_PATH}" in lines
    assert "NEOS_VISIBLE=yes" in lines
    assert not any(line.startswith("HOME=" + str(Path.home())) and str(Path.home()) != "/" for line in lines)
    with pytest.raises(SandboxPolicyViolation, match="environment_not_allowed"):
        await session.execute(CommandRequest(argv=("env",), env={"AWS_SECRET_ACCESS_KEY": "x"}))


async def test_stdout_and_stderr_have_separate_caps_and_truncation_bits(session) -> None:
    script = (
        "import sys; sys.stdout.write('o' * 200000); sys.stdout.flush(); "
        "sys.stderr.write('e' * 10)"
    )
    started = time.monotonic()
    result = await session.execute(
        CommandRequest(argv=(sys.executable, "-c", script), max_output_bytes=1024, timeout_sec=20)
    )
    assert time.monotonic() - started < 15
    assert result.stdout_truncated is True
    assert len(result.stdout) == 1024
    assert result.stderr_truncated is False


async def test_output_bomb_is_stopped_not_buffered(session) -> None:
    script = "import sys\nwhile True: sys.stdout.write('x' * 65536)"
    async with asyncio.timeout(15):
        result = await session.execute(
            CommandRequest(argv=(sys.executable, "-c", script), max_output_bytes=4096, timeout_sec=10)
        )
    assert result.stdout_truncated is True
    assert len(result.stdout) == 4096


async def test_stdin_bomb_is_refused_before_it_runs(daemon, session) -> None:
    limits = SandboxLimits.safe_defaults()
    with pytest.raises(SandboxPolicyViolation, match="command_stdin_limit_exceeded"):
        await session.execute(
            CommandRequest(argv=("cat",), stdin=b"x" * (limits.max_stdin_bytes + 1))
        )
    client = SandboxdClient(await daemon.open_channel())
    await client.handshake(SandboxdExpectation.bundled())
    try:
        with pytest.raises(SandboxPolicyViolation, match="command_stdin_limit_exceeded"):
            await client.call(
                "exec",
                {
                    "argv": ["cat"],
                    "stdin": "eHh4eA==",
                    "timeout_sec": 5,
                    "max_output_bytes": 100,
                    "max_stdin_bytes": 2,
                },
            )
    finally:
        await client.close()


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A zombie still answers kill(0); ask ps for its state.
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True).stdout
    return bool(state.strip()) and not state.strip().startswith(b"Z")


async def test_timeout_kills_the_whole_process_group(daemon, session) -> None:
    script = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "open('child.pid', 'w').write(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    limits = SandboxLimits.safe_defaults()
    result = await session.execute(
        CommandRequest(argv=(sys.executable, "-c", script), timeout_sec=2)
    )
    assert result.timed_out is True
    assert result.exit_code is None
    pid = int((daemon.workspace / "child.pid").read_text())
    deadline = time.monotonic() + 5
    while _alive(pid) and time.monotonic() < deadline:
        await asyncio.sleep(0.1)
    assert not _alive(pid)
    assert limits.command_timeout_sec >= 2


async def test_background_descendants_do_not_outlive_a_finished_command(daemon, session) -> None:
    script = (
        "import subprocess, sys\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "open('bg.pid', 'w').write(str(child.pid))\n"
    )
    result = await session.execute(CommandRequest(argv=(sys.executable, "-c", script), timeout_sec=10))
    assert result.exit_code == 0
    pid = int((daemon.workspace / "bg.pid").read_text())
    deadline = time.monotonic() + 5
    while _alive(pid) and time.monotonic() < deadline:
        await asyncio.sleep(0.1)
    assert not _alive(pid)


async def test_command_changes_bump_the_guest_revision(session) -> None:
    result = await session.execute(CommandRequest(argv=("touch", "made-by-command.txt")))
    assert result.exit_code == 0
    assert await session.workspace_revision() == 1
    unchanged = await session.execute(CommandRequest(argv=("true",)))
    assert unchanged.exit_code == 0
    assert await session.workspace_revision() == 1


# ---- PTY -----------------------------------------------------------------------


async def test_pty_journal_replays_after_the_connection_drops(daemon, session) -> None:
    terminal = await session.create_pty(argv=("/bin/sh",))
    await session.write_pty(terminal.pty_id, b"printf journal-replay\n")
    seen = None
    async with asyncio.timeout(10):
        async for event in terminal.subscribe(after_cursor=0):
            if b"journal-replay" in getattr(event.value, "data", b""):
                seen = event
                break
    assert seen is not None
    await daemon.drop_connections()
    replay = await terminal.replay(after_cursor=0)
    assert any(event.cursor == seen.cursor for event in replay)
    await session.resize_pty(terminal.pty_id, rows=40, cols=120)
    await session.kill_pty(terminal.pty_id)


async def test_pty_session_limit_is_enforced(session) -> None:
    terminals = [await session.create_pty(argv=("/bin/sh",)) for _ in range(4)]
    with pytest.raises(SandboxPolicyViolation, match="pty_session_limit_exceeded"):
        await session.create_pty(argv=("/bin/sh",))
    for terminal in terminals:
        await session.kill_pty(terminal.pty_id)


# ---- semantic parity with the host modules --------------------------------------


_PATH_CORPUS = (
    ".env",
    ".env.local",
    "src/.ENV",
    "a/.git/config",
    ".ssh/id_rsa",
    "home/.aws/credentials",
    ".neos/secrets/token",
    "pkg/.npmrc",
    "x/.netrc",
    "readme.md",
    "src/main.py",
    "node_modules/x/index.js",
    "build/out.o",
    "docs/.envrc",
    "ｅｎｖ/.ＥＮＶ",
)


def test_guest_secret_rule_matches_the_host_rule() -> None:
    for path in _PATH_CORPUS:
        assert guest.is_secret(path) is is_denied_secret_path(path), path


def test_guest_ignore_rules_match_the_host_rules(tmp_path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / ".gitignore").write_text("*.log\n/build/\n!keep.log\nsub/generated/\n")
    (tmp_path / "sub" / ".ignore").write_text("tmp*\n")
    assert guest.DEFAULT_SKIP_DIRS == host_ignore.DEFAULT_SKIP_DIRS
    host_rules = host_ignore.load_ignore_rules(tmp_path)
    guest_rules = guest.load_ignore_rules(str(tmp_path))
    assert [tuple(rule) for rule in host_rules] == guest_rules
    candidates = (
        ("app.log", False),
        ("keep.log", False),
        ("build", True),
        ("src/build", True),
        ("sub/tmpfile", False),
        ("tmpfile", False),
        ("sub/generated", True),
        ("sub/generated", False),
        ("node_modules/a.js", False),
        ("src/.git/HEAD", False),
        *((path, False) for path in _PATH_CORPUS),
    )
    for rel_path, is_dir in candidates:
        assert guest.should_skip_walk(rel_path, guest_rules, is_dir=is_dir) is (
            host_ignore.should_skip_walk(rel_path, rules=host_rules, is_dir=is_dir)
        ), rel_path

"""Security suite for managed coding sandboxes (B2 gate item 2, on fakes).

Every test goes through `ManagedSandboxProvider` -> fake vendor SDK -> a real
local `neos-sandboxd`. Real-account runs of this suite remain open.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import sys
import time
from pathlib import Path

import pytest

from neos.coding.sandbox.base import (
    CommandRequest,
    SandboxLimits,
    SandboxPolicyViolation,
    SandboxStateConflict,
    SandboxUnavailable,
)
from neos.coding.sandbox.managed.clients.e2b import E2BProviderClient
from neos.coding.sandbox.managed.clients.modal import ModalProviderClient
from neos.coding.sandbox.managed.ledger import LedgerConflict, LedgerState
from neos.coding.sandbox.managed.profiles import (
    STRICT_PIDS_V1,
    STRICT_WORKSPACE_QUOTA_V1,
)
from neos.coding.sandboxd.client import SandboxdExpectation
from tests.coding.sandbox.managed_fakes import (
    LEAKED_TOKEN,
    FakeE2BSdk,
    FakeModalSdk,
    VendorHTTPError,
    create,
    managed_stack,
)

pytestmark = pytest.mark.no_db

KINDS = ("e2b", "modal")


def _visible_chain(error: BaseException) -> list[BaseException]:
    chain = []
    current: BaseException | None = error
    while current is not None:
        chain.append(current)
        if current.__cause__ is not None:
            current = current.__cause__
        elif not current.__suppress_context__:
            current = current.__context__
        else:
            current = None
    return chain


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    import subprocess

    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True).stdout
    return bool(state.strip()) and not state.strip().startswith(b"Z")


# ---- workspace escapes -----------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
async def test_traversal_symlink_hardlink_and_device_are_refused(tmp_path: Path, kind: str) -> None:
    async with managed_stack(tmp_path, kind) as stack:
        sandbox = await create(stack.provider)
        session = await stack.provider.open_session(sandbox.sandbox_id)
        workspace = stack.vendor.live()[0].daemon.workspace
        outside = tmp_path / "host"
        outside.mkdir()
        (outside / "secret.txt").write_bytes(b"host-only")
        os.symlink(outside, workspace / "escape")
        os.link(outside / "secret.txt", workspace / "linked.txt")
        os.mkfifo(workspace / "fifo")

        with pytest.raises(SandboxPolicyViolation, match="workspace_path_escape"):
            await session.read_file("../../etc/passwd")
        with pytest.raises(SandboxPolicyViolation, match="workspace_symlink_parent"):
            await session.write_file("escape/planted.txt", b"x")
        with pytest.raises(SandboxPolicyViolation, match="workspace_hardlink"):
            await session.read_file("linked.txt")
        async with asyncio.timeout(5):
            with pytest.raises(SandboxPolicyViolation, match="workspace_path_is_not_file"):
                await session.read_file("fifo")
        assert not (outside / "planted.txt").exists()


# ---- ownership and generation ---------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
async def test_provider_object_without_our_digest_is_neither_used_nor_destroyed(
    tmp_path: Path, kind: str
) -> None:
    async with managed_stack(tmp_path, kind) as stack:
        sandbox = await create(stack.provider)
        stack.vendor.tamper_digest = True
        restarted = stack.restart()
        try:
            session = await restarted.open_session(sandbox.sandbox_id)
            with pytest.raises(SandboxUnavailable, match="managed_ownership_mismatch"):
                await session.read_file("x.txt")
            with pytest.raises(SandboxUnavailable, match="managed_ownership_mismatch"):
                await restarted.destroy(sandbox.sandbox_id)
        finally:
            await restarted.close()
        assert stack.vendor.count("kill") + stack.vendor.count("terminate") == 0
        assert len(stack.vendor.live()) == 1


async def test_ledger_row_edited_without_the_key_is_refused(tmp_path: Path) -> None:
    async with managed_stack(tmp_path, "e2b") as stack:
        sandbox = await create(stack.provider, owner="ct_victim")
        row = await stack.ledger.get(sandbox.sandbox_id)
        stack.ledger._rows[sandbox.sandbox_id] = dataclasses.replace(row, owner_id="ct_attacker")
        session = await stack.provider.open_session(sandbox.sandbox_id)
        with pytest.raises(SandboxUnavailable, match="managed_ownership_mismatch"):
            await session.list_tree(".")


async def test_ledger_writes_are_fenced_by_owner_and_generation(tmp_path: Path) -> None:
    async with managed_stack(tmp_path, "e2b") as stack:
        sandbox = await create(stack.provider)
        row = await stack.ledger.get(sandbox.sandbox_id)
        with pytest.raises(LedgerConflict, match="ledger_owner_mismatch"):
            await stack.ledger.update(
                row.sandbox_id, owner_id="someone_else", generation=row.generation,
                expected_version=None, changes={"workspace_revision": 99}, now=stack.clock(),
            )
        with pytest.raises(LedgerConflict, match="ledger_generation_mismatch"):
            await stack.ledger.update(
                row.sandbox_id, owner_id=row.owner_id, generation=row.generation + 1,
                expected_version=None, changes={"workspace_revision": 99}, now=stack.clock(),
            )
        assert (await stack.ledger.get(sandbox.sandbox_id)).workspace_revision == 0


async def test_streams_from_an_old_generation_are_closed(tmp_path: Path) -> None:
    async with managed_stack(tmp_path, "modal") as stack:
        sandbox = await create(stack.provider)
        session = await stack.provider.open_session(sandbox.sandbox_id)
        watcher = await session.watch_files(after_cursor=0)
        terminal = await session.create_pty(argv=("/bin/sh",))

        await stack.provider.suspend(sandbox.sandbox_id)
        await stack.provider.resume(sandbox.sandbox_id)
        assert (await stack.ledger.get(sandbox.sandbox_id)).generation == 2

        with pytest.raises(SandboxStateConflict, match="stream_generation_changed"):
            await terminal.replay(after_cursor=0)
        with pytest.raises(SandboxStateConflict, match="stream_generation_changed"):
            async with asyncio.timeout(5):
                await anext(watcher)
        # File operations re-resolve the new generation and keep working.
        assert await session.write_file("after.txt", b"x") == 1


async def test_warm_resume_keeps_streams_on_the_same_generation(tmp_path: Path) -> None:
    async with managed_stack(tmp_path, "e2b") as stack:
        sandbox = await create(stack.provider)
        session = await stack.provider.open_session(sandbox.sandbox_id)
        terminal = await session.create_pty(argv=("/bin/sh",))
        await session.write_pty(terminal.pty_id, b"printf before-pause\n")
        await asyncio.sleep(0.3)
        await stack.provider.suspend(sandbox.sandbox_id)
        await stack.provider.resume(sandbox.sandbox_id)
        replay = await terminal.replay(after_cursor=0)
        assert any(b"before-pause" in getattr(event.value, "data", b"") for event in replay)
        await session.kill_pty(terminal.pty_id)


# ---- commands --------------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
async def test_shell_strings_are_never_interpreted(tmp_path: Path, kind: str) -> None:
    async with managed_stack(tmp_path, kind) as stack:
        sandbox = await create(stack.provider)
        session = await stack.provider.open_session(sandbox.sandbox_id)
        payload = "$(touch owned); `touch owned2`"
        result = await session.execute(CommandRequest(argv=("printf", "%s", payload)))
        assert result.stdout == payload.encode()
        workspace = stack.vendor.live()[0].daemon.workspace
        assert not (workspace / "owned").exists()
        with pytest.raises(SandboxPolicyViolation, match="shell_command_not_allowed"):
            CommandRequest(argv=("bash", "-c", "touch owned"))


@pytest.mark.parametrize("kind", KINDS)
async def test_host_environment_and_vendor_errors_do_not_leak(
    tmp_path: Path, kind: str, monkeypatch
) -> None:
    monkeypatch.setenv("NEOS_HOST_ONLY_SECRET", "host-secret-value")
    async with managed_stack(tmp_path, kind) as stack:
        sandbox = await create(stack.provider)
        session = await stack.provider.open_session(sandbox.sandbox_id)
        result = await session.execute(CommandRequest(argv=("env",)))
        assert b"host-secret-value" not in result.stdout
        assert f"HOME={Path.home()}".encode() not in result.stdout
        with pytest.raises(SandboxPolicyViolation, match="environment_not_allowed"):
            await session.execute(CommandRequest(argv=("env",), env={"AWS_SECRET_ACCESS_KEY": "x"}))

        restarted = stack.restart()
        try:
            stack.vendor.fault("get_info" if kind == "e2b" else "from_id", VendorHTTPError(500))
            restarted_session = await restarted.open_session(sandbox.sandbox_id)
            with pytest.raises(SandboxUnavailable, match="managed_provider_server_error") as info:
                await restarted_session.read_file("x.txt")
        finally:
            await restarted.close()
        for error in _visible_chain(info.value):
            assert LEAKED_TOKEN not in str(error)


@pytest.mark.parametrize("kind", KINDS)
async def test_output_and_stdin_bombs_are_bounded(tmp_path: Path, kind: str) -> None:
    async with managed_stack(tmp_path, kind) as stack:
        sandbox = await create(stack.provider)
        session = await stack.provider.open_session(sandbox.sandbox_id)
        script = "import sys\nwhile True: sys.stdout.write('x' * 65536)"
        async with asyncio.timeout(20):
            result = await session.execute(
                CommandRequest(argv=(sys.executable, "-c", script), max_output_bytes=2048, timeout_sec=10)
            )
        assert result.stdout_truncated is True
        assert len(result.stdout) == 2048
        limit = SandboxLimits.safe_defaults().max_stdin_bytes
        with pytest.raises(SandboxPolicyViolation, match="command_stdin_limit_exceeded"):
            await session.execute(CommandRequest(argv=("cat",), stdin=b"x" * (limit + 1)))


@pytest.mark.parametrize("kind", KINDS)
async def test_no_descendant_survives_a_command_timeout(tmp_path: Path, kind: str) -> None:
    async with managed_stack(tmp_path, kind) as stack:
        sandbox = await create(stack.provider)
        session = await stack.provider.open_session(sandbox.sandbox_id)
        script = (
            "import subprocess, sys, time\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            "open('child.pid', 'w').write(str(child.pid))\n"
            "time.sleep(60)\n"
        )
        result = await session.execute(CommandRequest(argv=(sys.executable, "-c", script), timeout_sec=2))
        assert result.timed_out is True
        workspace = stack.vendor.live()[0].daemon.workspace
        pid = int((workspace / "child.pid").read_text())
        deadline = time.monotonic() + 5
        while _alive(pid) and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        assert not _alive(pid)


# ---- network profile -------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
async def test_network_deny_is_requested_read_back_and_recorded(tmp_path: Path, kind: str) -> None:
    async with managed_stack(tmp_path, kind) as stack:
        sandbox = await create(stack.provider)
        row = await stack.ledger.get(sandbox.sandbox_id)
        assert row.profile == "offline-v1"
        assert dict(row.network_policy) == {"outbound": "deny", "inbound": "deny", "allow": []}
        # E2B got allow_internet_access=False; Modal got block_network=True.
        assert stack.vendor.live()[0].network_open is False


@pytest.mark.parametrize("kind", KINDS)
async def test_provider_that_ignores_network_deny_is_abandoned(tmp_path: Path, kind: str) -> None:
    async with managed_stack(tmp_path, kind) as stack:
        stack.vendor.open_network = True
        with pytest.raises(
            SandboxUnavailable, match="profile_unsupported:offline-v1:network_readback_mismatch"
        ):
            await create(stack.provider)
        assert stack.vendor.live() == []
        rows = await stack.ledger.list_by_state(frozenset({LedgerState.DESTROYED}))
        assert len(rows) == 1


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("profile", (STRICT_PIDS_V1, STRICT_WORKSPACE_QUOTA_V1))
async def test_hard_quota_profiles_fail_closed_before_create(
    tmp_path: Path, kind: str, profile
) -> None:
    async with managed_stack(tmp_path, kind, profile=profile) as stack:
        with pytest.raises(SandboxUnavailable, match=f"profile_unsupported:{profile.name}:hard_"):
            await create(stack.provider)
        assert stack.vendor.count("create") == 0
        assert await stack.ledger.max_ordinal(owner_id="ct_1", task_id="ct_1") == 0


@pytest.mark.parametrize("kind", KINDS)
async def test_unverifiable_network_policy_is_refused_before_create(tmp_path: Path, kind: str) -> None:
    def blind_client(vendor):
        if kind == "e2b":
            sdk = FakeE2BSdk(vendor)
            sdk.reports_network_policy = False
            return E2BProviderClient(sdk=sdk)
        sdk = FakeModalSdk(vendor)
        sdk.reports_network_policy = False
        return ModalProviderClient(sdk=sdk)

    async with managed_stack(tmp_path, kind, client_factory=blind_client) as stack:
        with pytest.raises(
            SandboxUnavailable, match="profile_unsupported:offline-v1:network_policy_unverifiable"
        ):
            await create(stack.provider)
        assert stack.vendor.count("create") == 0


async def test_region_mismatch_is_abandoned(tmp_path: Path) -> None:
    async with managed_stack(tmp_path, "modal") as stack:
        stack.vendor.report_region = "us-east"
        with pytest.raises(SandboxUnavailable, match="managed_region_mismatch"):
            await create(stack.provider)
        assert stack.vendor.live() == []


async def test_guest_with_a_different_bundle_digest_never_serves(tmp_path: Path) -> None:
    pinned = SandboxdExpectation(bundle_digest="sha256:" + "1" * 64)
    async with managed_stack(tmp_path, "e2b", expectation=pinned) as stack:
        with pytest.raises(SandboxUnavailable, match="sandboxd_digest_mismatch"):
            await create(stack.provider)
        assert stack.vendor.live() == []

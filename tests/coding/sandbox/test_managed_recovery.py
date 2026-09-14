"""Recovery suite for managed coding sandboxes (B2 gate item 3, on fakes).

Review §6: the ledger row comes first, retries rediscover by idempotency key
(0 -> create, 1 -> adopt, >=2 -> quarantine), and a destroy nobody confirmed
stays `destroy_pending`. Region outage and real-account runs remain open.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from neos.coding.sandbox.base import SandboxNotFound, SandboxState, SandboxUnavailable
from neos.coding.sandbox.managed.ledger import LedgerState
from tests.coding.sandbox.managed_fakes import (
    DUPLICATE,
    KILLED_THEN_TIMEOUT,
    THEN_LOST,
    THEN_TIMEOUT,
    ServiceBusy,
    VendorHTTPError,
    create,
    managed_stack,
)

pytestmark = pytest.mark.no_db

KINDS = ("e2b", "modal")
OWNER = "ct_1"


async def _rows(stack, *states: LedgerState):
    return await stack.ledger.find_by_state(owner_id=OWNER, task_id=OWNER, states=frozenset(states))


# ---- create ----------------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("fault", (THEN_TIMEOUT, THEN_LOST))
async def test_create_that_landed_without_a_response_is_adopted(
    tmp_path: Path, kind: str, fault: str
) -> None:
    async with managed_stack(tmp_path, kind) as stack:
        stack.vendor.fault("create", fault)
        sandbox = await create(stack.provider)
        assert sandbox.state is SandboxState.RUNNING
        assert stack.vendor.count("create") == 1
        assert len(stack.vendor.live()) == 1
        session = await stack.provider.open_session(sandbox.sandbox_id)
        assert await session.write_file("a.txt", b"a") == 1


@pytest.mark.parametrize("kind", KINDS)
async def test_duplicate_provider_objects_quarantine_and_block_new_work(
    tmp_path: Path, kind: str
) -> None:
    async with managed_stack(tmp_path, kind) as stack:
        if kind == "modal":
            # Modal refuses a second running object with the same name, so a
            # duplicate can only come from outside NEOS. Plant one.
            stack.vendor.fault("create", THEN_TIMEOUT)
            original_spawn = stack.vendor.spawn

            async def spawn_twice(**kwargs):
                first = await original_spawn(**kwargs)
                await original_spawn(**{**kwargs, "name": kwargs["name"] + "-copy"})
                return first

            stack.vendor.spawn = spawn_twice  # type: ignore[method-assign]
        else:
            # One call creates two objects, then its response is lost.
            stack.vendor.fault("create", DUPLICATE)
            original = stack.vendor.create_with_faults

            async def duplicate_then_timeout(operation, spawn):
                await original(operation, spawn)
                raise TimeoutError("lost")

            stack.vendor.create_with_faults = duplicate_then_timeout  # type: ignore[method-assign]
        with pytest.raises(SandboxUnavailable, match="managed_sandbox_quarantined"):
            await create(stack.provider)
        assert len(await _rows(stack, LedgerState.QUARANTINED)) == 1
        with pytest.raises(SandboxUnavailable, match="managed_owner_quarantined"):
            await create(stack.provider)
        assert stack.vendor.count("create") == 1
        # Nothing was destroyed on NEOS's own initiative.
        assert len(stack.vendor.live()) == 2


@pytest.mark.parametrize("kind", KINDS)
async def test_process_restart_after_an_ambiguous_create_adopts_instead_of_recreating(
    tmp_path: Path, kind: str
) -> None:
    async with managed_stack(tmp_path, kind) as stack:
        stack.vendor.fault("create", THEN_TIMEOUT)
        stack.vendor.fault("list", VendorHTTPError(502))
        with pytest.raises(SandboxUnavailable, match="managed_allocation_ambiguous"):
            await create(stack.provider)
        pending = await _rows(stack, LedgerState.CREATING)
        assert len(pending) == 1

        restarted = stack.restart()
        try:
            sandbox = await create(restarted)
        finally:
            await restarted.close()
        assert sandbox.sandbox_id == pending[0].sandbox_id
        assert stack.vendor.count("create") == 1
        assert len(stack.vendor.live()) == 1


@pytest.mark.parametrize("kind", KINDS)
async def test_server_error_before_accept_is_ambiguous_then_retried_by_rediscovery(
    tmp_path: Path, kind: str
) -> None:
    async with managed_stack(tmp_path, kind) as stack:
        stack.vendor.fault("create", VendorHTTPError(500))
        with pytest.raises(SandboxUnavailable, match="managed_allocation_ambiguous"):
            await create(stack.provider)
        assert stack.vendor.count("create") == 1
        assert stack.vendor.live() == []

        sandbox = await create(stack.provider)
        assert stack.vendor.count("create") == 2
        assert sandbox.sandbox_id == (await _rows(stack, LedgerState.RUNNING))[0].sandbox_id
        assert await stack.ledger.max_ordinal(owner_id=OWNER, task_id=OWNER) == 1


async def test_conflict_without_a_discoverable_object_is_not_retried_blindly(tmp_path: Path) -> None:
    async with managed_stack(tmp_path, "e2b") as stack:
        stack.vendor.fault("create", VendorHTTPError(409))
        with pytest.raises(SandboxUnavailable, match="managed_allocation_ambiguous"):
            await create(stack.provider)
        assert stack.vendor.count("create") == 1


@pytest.mark.parametrize("kind", KINDS)
async def test_rate_limited_create_fails_the_row_and_a_later_create_starts_fresh(
    tmp_path: Path, kind: str
) -> None:
    async with managed_stack(tmp_path, kind) as stack:
        stack.vendor.fault("create", VendorHTTPError(429))
        with pytest.raises(SandboxUnavailable, match="managed_provider_rate_limited"):
            await create(stack.provider)
        failed = await _rows(stack, LedgerState.FAILED)
        assert len(failed) == 1
        assert failed[0].error_code == "provider_rate_limited"
        sandbox = await create(stack.provider)
        assert sandbox.sandbox_id != failed[0].sandbox_id
        assert await stack.ledger.max_ordinal(owner_id=OWNER, task_id=OWNER) == 2


async def test_kill_switch_refuses_before_the_ledger_or_provider(tmp_path: Path) -> None:
    async with managed_stack(tmp_path, "e2b", kill_switch=True) as stack:
        with pytest.raises(SandboxUnavailable, match="managed_kill_switch"):
            await create(stack.provider)
        assert stack.vendor.calls == []
        assert await stack.ledger.max_ordinal(owner_id=OWNER, task_id=OWNER) == 0


# ---- lifecycle -------------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
async def test_provider_object_gone_is_reported_and_destroy_confirms(tmp_path: Path, kind: str) -> None:
    async with managed_stack(tmp_path, kind) as stack:
        sandbox = await create(stack.provider)
        obj = stack.vendor.live()[0]
        await obj.daemon.stop()
        obj.state = "terminated"

        restarted = stack.restart()
        try:
            session = await restarted.open_session(sandbox.sandbox_id)
            with pytest.raises(SandboxUnavailable, match="managed_provider_object_missing"):
                await session.read_file("a.txt")
            await restarted.destroy(sandbox.sandbox_id)
        finally:
            await restarted.close()
        row = await stack.ledger.get(sandbox.sandbox_id)
        assert row.state is LedgerState.DESTROYED
        assert row.destroy_confirmed_at is not None
        with pytest.raises(SandboxNotFound):
            await stack.provider.get(sandbox.sandbox_id)


async def test_e2b_pause_busy_is_retried_boundedly_and_stays_running_on_refusal(tmp_path: Path) -> None:
    async with managed_stack(tmp_path, "e2b") as stack:
        sandbox = await create(stack.provider)
        stack.vendor.fault("pause", ServiceBusy(), ServiceBusy())
        assert (await stack.provider.suspend(sandbox.sandbox_id)).state is SandboxState.SUSPENDED
        assert stack.vendor.count("pause") == 3
        await stack.provider.resume(sandbox.sandbox_id)

        stack.vendor.fault("pause", *(ServiceBusy() for _ in range(4)))
        with pytest.raises(SandboxUnavailable, match="managed_provider_busy"):
            await stack.provider.suspend(sandbox.sandbox_id)
        assert (await stack.ledger.get(sandbox.sandbox_id)).state is LedgerState.RUNNING
        session = await stack.provider.open_session(sandbox.sandbox_id)
        assert await session.write_file("still-running.txt", b"x") == 1


async def test_e2b_snapshot_drops_connections_and_journals_replay(tmp_path: Path) -> None:
    async with managed_stack(tmp_path, "e2b") as stack:
        sandbox = await create(stack.provider)
        session = await stack.provider.open_session(sandbox.sandbox_id)
        terminal = await session.create_pty(argv=("/bin/sh",))
        await session.write_pty(terminal.pty_id, b"printf survives-snapshot\n")
        await asyncio.sleep(0.3)

        snapshot = await stack.provider.snapshot(sandbox.sandbox_id)

        assert snapshot.content_checksum.startswith("sha256:")
        replay = await terminal.replay(after_cursor=0)
        assert any(b"survives-snapshot" in getattr(event.value, "data", b"") for event in replay)
        assert await session.write_file("after.txt", b"x") == 1
        await session.kill_pty(terminal.pty_id)


async def test_modal_cold_suspend_keeps_revision_and_content(tmp_path: Path) -> None:
    async with managed_stack(tmp_path, "modal") as stack:
        sandbox = await create(stack.provider)
        session = await stack.provider.open_session(sandbox.sandbox_id)
        for index in range(3):
            await session.write_file(f"f{index}.txt", str(index).encode())
        await stack.provider.suspend(sandbox.sandbox_id)
        assert stack.vendor.live() == []
        resumed = await stack.provider.resume(sandbox.sandbox_id)
        assert resumed.workspace_revision == 3
        assert await session.read_file("f2.txt") == b"2"
        assert await session.write_file("f3.txt", b"3") == 4


async def test_modal_terminate_unconfirmed_keeps_the_row_running(tmp_path: Path) -> None:
    async with managed_stack(tmp_path, "modal") as stack:
        sandbox = await create(stack.provider)
        stack.vendor.fault("terminate", TimeoutError())
        with pytest.raises(SandboxUnavailable, match="managed_suspend_terminate_unconfirmed"):
            await stack.provider.suspend(sandbox.sandbox_id)
        row = await stack.ledger.get(sandbox.sandbox_id)
        assert row.state is LedgerState.RUNNING
        assert row.provider_ref is not None


# ---- snapshots -------------------------------------------------------------------


async def test_expired_snapshot_is_refused_before_the_provider_is_asked(tmp_path: Path) -> None:
    async with managed_stack(tmp_path, "modal") as stack:
        sandbox = await create(stack.provider)
        snapshot = await stack.provider.snapshot(sandbox.sandbox_id)
        stack.clock.advance(days=31)
        with pytest.raises(SandboxUnavailable, match="managed_snapshot_expired"):
            await stack.provider.restore(snapshot.snapshot_id, owner_id=OWNER)
        assert stack.vendor.count("create") == 1


async def test_snapshot_missing_at_the_provider_is_refused(tmp_path: Path) -> None:
    async with managed_stack(tmp_path, "modal") as stack:
        sandbox = await create(stack.provider)
        snapshot = await stack.provider.snapshot(sandbox.sandbox_id)
        stack.vendor.snapshots.clear()
        with pytest.raises(SandboxUnavailable, match="managed_snapshot_not_found"):
            await stack.provider.restore(snapshot.snapshot_id, owner_id=OWNER)


async def test_cold_resume_after_snapshot_ttl_stays_suspended(tmp_path: Path) -> None:
    async with managed_stack(tmp_path, "modal") as stack:
        sandbox = await create(stack.provider)
        await stack.provider.suspend(sandbox.sandbox_id)
        stack.clock.advance(days=31)
        with pytest.raises(SandboxUnavailable, match="managed_snapshot_expired"):
            await stack.provider.resume(sandbox.sandbox_id)
        assert (await stack.ledger.get(sandbox.sandbox_id)).state is LedgerState.SUSPENDED


@pytest.mark.parametrize("kind", KINDS)
async def test_restore_verifies_the_checksum_and_owner(tmp_path: Path, kind: str) -> None:
    async with managed_stack(tmp_path, kind) as stack:
        sandbox = await create(stack.provider)
        session = await stack.provider.open_session(sandbox.sandbox_id)
        await session.write_file("state.txt", b"v1")
        snapshot = await stack.provider.snapshot(sandbox.sandbox_id)

        with pytest.raises(SandboxNotFound):
            await stack.provider.restore(snapshot.snapshot_id, owner_id="ct_other")

        for directory, _expires in stack.vendor.snapshots.values():
            (directory / "workspace" / "state.txt").write_bytes(b"tampered")
        with pytest.raises(SandboxUnavailable, match="managed_snapshot_checksum_mismatch"):
            await stack.provider.restore(snapshot.snapshot_id, owner_id=OWNER)
        assert len(stack.vendor.live()) == 1


# ---- destroy ---------------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
async def test_ambiguous_destroy_stays_pending_until_the_reaper_confirms(
    tmp_path: Path, kind: str
) -> None:
    operation = "kill" if kind == "e2b" else "terminate"
    async with managed_stack(tmp_path, kind) as stack:
        alive = await create(stack.provider, owner="ct_alive")
        killed = await create(stack.provider, owner="ct_killed")

        stack.vendor.fault(operation, TimeoutError())
        with pytest.raises(SandboxUnavailable, match="managed_destroy_pending"):
            await stack.provider.destroy(alive.sandbox_id)
        stack.vendor.fault(operation, KILLED_THEN_TIMEOUT)
        with pytest.raises(SandboxUnavailable, match="managed_destroy_pending"):
            await stack.provider.destroy(killed.sandbox_id)

        for sandbox_id in (alive.sandbox_id, killed.sandbox_id):
            row = await stack.ledger.get(sandbox_id)
            assert row.state is LedgerState.DESTROY_PENDING
            assert row.destroy_confirmed_at is None
        assert len(stack.vendor.live()) == 1

        assert await stack.provider.reconcile_destroy_pending() == 2
        for sandbox_id in (alive.sandbox_id, killed.sandbox_id):
            assert (await stack.ledger.get(sandbox_id)).state is LedgerState.DESTROYED
        assert stack.vendor.live() == []

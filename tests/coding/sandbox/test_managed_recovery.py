"""Recovery suite for managed coding sandboxes (B2 gate item 3, on fakes).

Review §6 on top of the managed allocation plane: the coding intent and the
physical row come before the vendor create; an ambiguous create is resolved by
`advance()` rediscovering, never by a second create; duplicates quarantine; a
Modal cold resume that crashes before its commit is adopted on restart; cleanup
removes every incarnation and a destroy nobody confirmed is retried. Region
outage and real-account runs remain open.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from neos.coding.managed.adapters.base import ManagedAdapterOwnershipError
from neos.coding.managed.domain import ManagedSandboxState, ProviderErrorCode
from neos.coding.sandbox.base import SandboxNotFound, SandboxState, SandboxUnavailable
from neos.coding.sandbox.managed.ledger import PhysicalState, RuntimeState
from tests.coding.sandbox.managed_fakes import (
    DUPLICATE,
    KILLED_THEN_TIMEOUT,
    LIMITS,
    THEN_LOST,
    THEN_TIMEOUT,
    ServiceBusy,
    VendorHTTPError,
    allocation_cipher,
    create,
    managed_stack,
)

pytestmark = pytest.mark.no_db

KINDS = ("e2b", "modal")
OWNER = "ct_1"


async def _runtime_for(stack, allocation_id: str):
    return await stack.ledger.get_by_allocation(allocation_id)


# ---- allocation through the plane ----------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("fault", (THEN_TIMEOUT, THEN_LOST))
async def test_a_create_that_landed_without_a_response_is_rediscovered_not_recreated(
    tmp_path: Path, kind: str, fault: str
) -> None:
    async with managed_stack(tmp_path, kind) as stack:
        stack.vendor.fault("create", fault)
        allocation = await stack.admit(OWNER)
        first = await stack.advance(allocation.allocation_id)
        assert first.state is ManagedSandboxState.RECOVERY_PENDING
        runtime = await _runtime_for(stack, allocation.allocation_id)
        assert (await stack.ledger.get_physical(runtime.sandbox_id, 1)).state is PhysicalState.CREATING

        second = await stack.advance(allocation.allocation_id)
        assert second.state is ManagedSandboxState.ACTIVE
        assert stack.vendor.count("create") == 1
        assert len(stack.vendor.live()) == 1

        sandbox = await stack.provider.create(owner_id=OWNER, limits=LIMITS)
        assert sandbox.state is SandboxState.RUNNING
        session = await stack.provider.open_session(sandbox.sandbox_id)
        assert await session.write_file("a.txt", b"a") == 1


@pytest.mark.parametrize("kind", KINDS)
async def test_duplicate_provider_objects_quarantine_and_are_never_adopted(
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
            stack.vendor.fault("create", DUPLICATE)
            original = stack.vendor.create_with_faults

            async def duplicate_then_timeout(operation, spawn):
                await original(operation, spawn)
                raise TimeoutError("lost")

            stack.vendor.create_with_faults = duplicate_then_timeout  # type: ignore[method-assign]
        allocation = await stack.admit(OWNER)
        assert (await stack.advance(allocation.allocation_id)).state is ManagedSandboxState.RECOVERY_PENDING
        with pytest.raises(ManagedAdapterOwnershipError, match="coding_duplicate_provider_objects"):
            await stack.advance(allocation.allocation_id)
        runtime = await _runtime_for(stack, allocation.allocation_id)
        assert runtime.state is RuntimeState.QUARANTINED
        assert stack.vendor.count("create") == 1
        # Nothing was destroyed on NEOS's own initiative.
        assert len(stack.vendor.live()) == 2
        with pytest.raises(SandboxUnavailable, match="managed_sandbox_quarantined"):
            await stack.provider.create(owner_id=OWNER, limits=LIMITS)


@pytest.mark.parametrize("kind", KINDS)
async def test_an_ambiguous_create_with_nothing_to_find_stops_for_an_operator(
    tmp_path: Path, kind: str
) -> None:
    async with managed_stack(tmp_path, kind) as stack:
        stack.vendor.fault("create", VendorHTTPError(500))
        allocation = await stack.admit(OWNER)
        assert (await stack.advance(allocation.allocation_id)).state is ManagedSandboxState.RECOVERY_PENDING
        stopped = await stack.advance(allocation.allocation_id)
        assert stopped.state is ManagedSandboxState.MANUAL_RECOVERY_REQUIRED
        assert stack.vendor.count("create") == 1
        assert stack.vendor.live() == []


@pytest.mark.parametrize("kind", KINDS)
async def test_a_refused_create_fails_the_allocation_and_nothing_attaches(
    tmp_path: Path, kind: str
) -> None:
    async with managed_stack(tmp_path, kind) as stack:
        stack.vendor.fault("create", VendorHTTPError(429))
        allocation = await stack.provision(OWNER)
        assert allocation.state is ManagedSandboxState.FAILED
        assert allocation.error_code is ProviderErrorCode.OTHER
        with pytest.raises(SandboxUnavailable, match="managed_allocation_required"):
            await stack.provider.create(owner_id=OWNER, limits=LIMITS)


async def test_an_allocation_without_a_coding_intent_never_reaches_the_vendor(tmp_path: Path) -> None:
    async with managed_stack(tmp_path, "e2b") as stack:
        allocation = await stack.provision(OWNER, intent=False)
        assert allocation.state is ManagedSandboxState.FAILED
        assert allocation.error_code is ProviderErrorCode.POLICY_DENIED
        assert stack.vendor.calls == []
        with pytest.raises(SandboxUnavailable, match="managed_allocation_required"):
            await stack.provider.create(owner_id=OWNER, limits=LIMITS)


async def test_the_provider_never_allocates_on_its_own(tmp_path: Path) -> None:
    async with managed_stack(tmp_path, "e2b") as stack:
        with pytest.raises(SandboxUnavailable, match="managed_allocation_required"):
            await stack.provider.create(owner_id=OWNER, limits=LIMITS)
        assert stack.vendor.count("create") == 0
        await create(stack)
        await stack.provider.create(owner_id=OWNER, limits=LIMITS)  # attach again
        assert stack.vendor.count("create") == 1


async def test_kill_switch_refuses_attach_before_the_provider_is_asked(tmp_path: Path) -> None:
    async with managed_stack(tmp_path, "e2b", kill_switch=True) as stack:
        await stack.provision(OWNER)
        before = list(stack.vendor.calls)
        with pytest.raises(SandboxUnavailable, match="managed_kill_switch"):
            await stack.provider.create(owner_id=OWNER, limits=LIMITS)
        assert stack.vendor.calls == before


# ---- lifecycle -------------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
async def test_a_vanished_object_is_reported_and_cleanup_confirms_it(tmp_path: Path, kind: str) -> None:
    async with managed_stack(tmp_path, kind) as stack:
        sandbox = await create(stack)
        allocation = await stack.allocation_of(sandbox.sandbox_id)
        obj = stack.vendor.live()[0]
        await obj.daemon.stop()
        obj.state = "terminated"

        restarted = stack.restart()
        try:
            session = await restarted.open_session(sandbox.sandbox_id)
            with pytest.raises(SandboxUnavailable, match="managed_provider_object_missing"):
                await session.read_file("a.txt")
        finally:
            await restarted.close()
        outcome = await stack.cleanup(allocation.allocation_id)
        assert outcome.state is ManagedSandboxState.CLEANED
        assert (await stack.ledger.get_physical(sandbox.sandbox_id, 1)).state is PhysicalState.DESTROYED
        with pytest.raises(SandboxNotFound):
            await stack.provider.get(sandbox.sandbox_id)


async def test_e2b_pause_busy_is_retried_boundedly_and_stays_running_on_refusal(tmp_path: Path) -> None:
    async with managed_stack(tmp_path, "e2b") as stack:
        sandbox = await create(stack)
        stack.vendor.fault("pause", ServiceBusy(), ServiceBusy())
        assert (await stack.provider.suspend(sandbox.sandbox_id)).state is SandboxState.SUSPENDED
        assert stack.vendor.count("pause") == 3
        await stack.provider.resume(sandbox.sandbox_id)

        stack.vendor.fault("pause", *(ServiceBusy() for _ in range(4)))
        with pytest.raises(SandboxUnavailable, match="managed_provider_busy"):
            await stack.provider.suspend(sandbox.sandbox_id)
        assert (await stack.ledger.get(sandbox.sandbox_id)).state is RuntimeState.RUNNING
        session = await stack.provider.open_session(sandbox.sandbox_id)
        assert await session.write_file("still-running.txt", b"x") == 1


async def test_e2b_snapshot_drops_connections_and_journals_replay(tmp_path: Path) -> None:
    async with managed_stack(tmp_path, "e2b") as stack:
        sandbox = await create(stack)
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


async def test_modal_cold_resume_replaces_the_object_and_the_allocation_ref_together(
    tmp_path: Path,
) -> None:
    async with managed_stack(tmp_path, "modal") as stack:
        sandbox = await create(stack)
        session = await stack.provider.open_session(sandbox.sandbox_id)
        for index in range(3):
            await session.write_file(f"f{index}.txt", str(index).encode())
        await stack.provider.suspend(sandbox.sandbox_id)
        assert stack.vendor.live() == []
        assert (await stack.ledger.get_physical(sandbox.sandbox_id, 1)).state is PhysicalState.DESTROYED

        resumed = await stack.provider.resume(sandbox.sandbox_id)
        assert resumed.workspace_revision == 3
        assert await session.read_file("f2.txt") == b"2"
        assert await session.write_file("f3.txt", b"3") == 4

        runtime = await stack.ledger.get(sandbox.sandbox_id)
        assert (runtime.incarnation, runtime.stream_epoch) == (2, 2)
        replacement = await stack.ledger.get_physical(sandbox.sandbox_id, 2)
        allocation = await stack.allocation_of(sandbox.sandbox_id)
        assert allocation.generation == 1
        assert allocation_cipher(allocation).decrypt(allocation.provider_ref) == replacement.provider_ref
        assert [obj.object_id for obj in stack.vendor.live()] == [replacement.provider_ref]


async def test_modal_cold_resume_that_crashed_before_its_commit_is_adopted(tmp_path: Path) -> None:
    async with managed_stack(tmp_path, "modal") as stack:
        sandbox = await create(stack)
        session = await stack.provider.open_session(sandbox.sandbox_id)
        await session.write_file("kept.txt", b"kept")
        await stack.provider.suspend(sandbox.sandbox_id)

        real_commit = stack.ledger.commit_incarnation

        async def crash(*args, **kwargs):
            raise RuntimeError("process died between create and commit")

        stack.ledger.commit_incarnation = crash  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="process died"):
            await stack.provider.resume(sandbox.sandbox_id)
        stack.ledger.commit_incarnation = real_commit  # type: ignore[method-assign]
        assert stack.vendor.count("create") == 2
        assert (await stack.ledger.get_physical(sandbox.sandbox_id, 2)).state is PhysicalState.CREATING

        restarted = stack.restart()
        try:
            resumed = await restarted.resume(sandbox.sandbox_id)
            restarted_session = await restarted.open_session(resumed.sandbox_id)
            assert await restarted_session.read_file("kept.txt") == b"kept"
        finally:
            await restarted.close()
        assert stack.vendor.count("create") == 2
        assert len(stack.vendor.live()) == 1


async def test_modal_terminate_unconfirmed_keeps_the_runtime_running(tmp_path: Path) -> None:
    async with managed_stack(tmp_path, "modal") as stack:
        sandbox = await create(stack)
        stack.vendor.fault("terminate", TimeoutError())
        with pytest.raises(SandboxUnavailable, match="managed_suspend_terminate_unconfirmed"):
            await stack.provider.suspend(sandbox.sandbox_id)
        runtime = await stack.ledger.get(sandbox.sandbox_id)
        assert runtime.state is RuntimeState.RUNNING
        assert (await stack.ledger.get_physical(sandbox.sandbox_id, 1)).state is PhysicalState.ACTIVE


# ---- snapshots and restore ------------------------------------------------------------


async def test_expired_snapshot_is_refused_before_the_provider_is_asked(tmp_path: Path) -> None:
    async with managed_stack(tmp_path, "modal") as stack:
        sandbox = await create(stack)
        snapshot = await stack.provider.snapshot(sandbox.sandbox_id)
        stack.clock.advance(days=31)
        with pytest.raises(SandboxUnavailable, match="managed_snapshot_expired"):
            await stack.provider.restore(snapshot.snapshot_id, owner_id=OWNER)
        assert stack.vendor.count("create") == 1


async def test_snapshot_missing_at_the_provider_is_refused(tmp_path: Path) -> None:
    async with managed_stack(tmp_path, "modal") as stack:
        sandbox = await create(stack)
        snapshot = await stack.provider.snapshot(sandbox.sandbox_id)
        stack.vendor.snapshots.clear()
        with pytest.raises(SandboxUnavailable, match="managed_snapshot_not_found"):
            await stack.provider.restore(snapshot.snapshot_id, owner_id=OWNER)


async def test_cold_resume_after_snapshot_ttl_stays_suspended(tmp_path: Path) -> None:
    async with managed_stack(tmp_path, "modal") as stack:
        sandbox = await create(stack)
        await stack.provider.suspend(sandbox.sandbox_id)
        stack.clock.advance(days=31)
        with pytest.raises(SandboxUnavailable, match="managed_snapshot_expired"):
            await stack.provider.resume(sandbox.sandbox_id)
        assert (await stack.ledger.get(sandbox.sandbox_id)).state is RuntimeState.SUSPENDED


@pytest.mark.parametrize("kind", KINDS)
async def test_restore_needs_a_prepared_target_and_verifies_owner_and_checksum(
    tmp_path: Path, kind: str
) -> None:
    async with managed_stack(tmp_path, kind) as stack:
        sandbox = await create(stack)
        session = await stack.provider.open_session(sandbox.sandbox_id)
        await session.write_file("state.txt", b"v1")
        snapshot = await stack.provider.snapshot(sandbox.sandbox_id)

        with pytest.raises(SandboxNotFound):
            await stack.provider.restore(snapshot.snapshot_id, owner_id="ct_other")
        with pytest.raises(SandboxUnavailable, match="managed_restore_target_required"):
            await stack.provider.restore(snapshot.snapshot_id, owner_id=OWNER)

        source = await stack.allocation_of(sandbox.sandbox_id)
        await stack.provider.destroy(sandbox.sandbox_id)
        assert (await stack.cleanup(source.allocation_id)).state is ManagedSandboxState.CLEANED
        for directory, _expires in stack.vendor.snapshots.values():
            (directory / "workspace" / "state.txt").write_bytes(b"tampered")
        target = await stack.admit(OWNER, source_snapshot_id=snapshot.snapshot_id)
        assert (await stack.advance(target.allocation_id)).state is ManagedSandboxState.ACTIVE

        with pytest.raises(SandboxUnavailable, match="managed_snapshot_checksum_mismatch"):
            await stack.provider.restore(snapshot.snapshot_id, owner_id=OWNER)
        runtime = await _runtime_for(stack, target.allocation_id)
        assert runtime.state is RuntimeState.FAILED
        with pytest.raises(SandboxUnavailable, match="managed_sandbox_released"):
            await stack.provider.restore(snapshot.snapshot_id, owner_id=OWNER)


# ---- cleanup through the allocation plane ------------------------------------------------


async def test_cleanup_removes_every_incarnation_of_a_cold_resumed_sandbox(tmp_path: Path) -> None:
    async with managed_stack(tmp_path, "modal") as stack:
        sandbox = await create(stack)
        await stack.provider.suspend(sandbox.sandbox_id)
        await stack.provider.resume(sandbox.sandbox_id)
        allocation = await stack.allocation_of(sandbox.sandbox_id)

        outcome = await stack.cleanup(allocation.allocation_id)

        assert outcome.state is ManagedSandboxState.CLEANED
        assert stack.vendor.live() == []
        states = [row.state for row in await stack.ledger.list_physical(sandbox.sandbox_id)]
        assert states == [PhysicalState.DESTROYED, PhysicalState.DESTROYED]
        assert (await stack.ledger.get(sandbox.sandbox_id)).state is RuntimeState.DETACHED


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("fault", (TimeoutError(), KILLED_THEN_TIMEOUT))
async def test_an_unconfirmed_cleanup_stays_pending_and_the_retry_confirms_it(
    tmp_path: Path, kind: str, fault
) -> None:
    operation = "kill" if kind == "e2b" else "terminate"
    async with managed_stack(tmp_path, kind) as stack:
        sandbox = await create(stack)
        allocation = await stack.allocation_of(sandbox.sandbox_id)
        stack.vendor.fault(operation, fault)

        first = await stack.cleanup(allocation.allocation_id)
        assert first.state is ManagedSandboxState.CLEANUP_RETRY
        physical = await stack.ledger.get_physical(sandbox.sandbox_id, 1)
        assert physical.state is PhysicalState.DESTROY_PENDING
        assert physical.destroy_confirmed_at is None

        second = await stack.cleanup(allocation.allocation_id)
        assert second.state is ManagedSandboxState.CLEANED
        assert stack.vendor.live() == []

"""`PostgresCodingRuntimeLedger` against a real PostgreSQL (migration 057).

What a recording fake session cannot prove: that the run-lease fence reads the
real `coding_run_leases` row, that an incarnation handoff moves the runtime,
the physical row, and the 045 allocation's sealed `provider_ref` in **one**
transaction (and rolls all three back together), and that the partial unique
index allows one active vendor object per logical sandbox.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from neos.coding.managed.domain import ManagedSandboxState
from neos.coding.managed.repository import PostgresManagedSandboxRepository
from neos.coding.sandbox.base import SandboxLimits
from neos.coding.sandbox.managed.ledger import (
    LedgerConflict,
    PhysicalRecord,
    PhysicalState,
    RuntimeFence,
    RuntimeRecord,
    RuntimeState,
)
from neos.coding.sandbox.managed.ledger_sql import PostgresCodingRuntimeLedger
from tests.coding.managed.integration.test_postgres_allocation import (
    NOW,
    _seed_admitted_allocation,
)

KEY = b"r" * 32


async def _active_allocation(session_factory, allocation_id: str):
    await _seed_admitted_allocation(session_factory, allocation_id)
    async with await session_factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    "UPDATE coding_managed_sandboxes SET state = 'active', "
                    "provider_ref = :ref, ownership_digest = :digest "
                    "WHERE allocation_id = :allocation_id"
                ),
                {"ref": b"sealed-v1", "digest": "sha256:" + "a" * 64, "allocation_id": allocation_id},
            )
    return await PostgresManagedSandboxRepository(session_factory).read_allocation(allocation_id)


def _runtime(allocation, **changes) -> RuntimeRecord:
    values = dict(
        sandbox_id=f"sbx_{uuid4().hex[:24]}",
        allocation_id=allocation.allocation_id,
        allocation_generation=allocation.generation,
        tenant_id=allocation.tenant_id,
        task_id=allocation.task_id,
        owner_id="u_owner",
        provider="modal",
        image_digest="img@sha256:" + "0" * 64,
        sandboxd_digest="sha256:" + "1" * 64,
        profile="offline-v1",
        network_policy={"outbound": "deny", "inbound": "deny", "allow": []},
        region="local",
        limits=SandboxLimits.safe_defaults(),
        expires_at=allocation.absolute_expires_at,
        state=RuntimeState.INTENT,
        incarnation=1,
        stream_epoch=1,
        workspace_revision=0,
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    values.update(changes)
    return RuntimeRecord(**values)


def _physical(sandbox_id: str, incarnation: int, **changes) -> PhysicalRecord:
    values = dict(
        sandbox_id=sandbox_id,
        incarnation=incarnation,
        idempotency_key=f"key_{sandbox_id}_{incarnation}",
        ownership_digest="hmac-sha256:" + "b" * 64,
        state=PhysicalState.CREATING,
        created_at=NOW,
        updated_at=NOW,
    )
    values.update(changes)
    return PhysicalRecord(**values)


async def _running(ledger: PostgresCodingRuntimeLedger, allocation) -> RuntimeRecord:
    runtime = await ledger.put_intent(_runtime(allocation))
    await ledger.put_physical(_physical(runtime.sandbox_id, 1))
    await ledger.update_physical(
        runtime.sandbox_id, 1, now=NOW,
        changes={"provider_ref": "obj-1", "ref_index": f"ref_{runtime.sandbox_id}_1",
                 "state": PhysicalState.ACTIVE},
    )
    return await ledger.update(
        runtime.sandbox_id, incarnation=1, expected_version=1, now=NOW,
        changes={"state": RuntimeState.RUNNING},
    )


@pytest.mark.integration
async def test_the_revision_fence_reads_the_live_run_lease(managed_postgres_session_factory) -> None:
    factory = managed_postgres_session_factory
    ledger = PostgresCodingRuntimeLedger(factory, reference_key=KEY, key_version=1)
    allocation = await _active_allocation(factory, f"msa_{uuid4().hex[:12]}")
    runtime = await _running(ledger, allocation)
    async with await factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO coding_run_leases (task_id, run_id, worker_id, fencing_token, "
                    "acquired_at, heartbeat_at, expires_at) "
                    "VALUES (:task_id, :run_id, 'worker', 5, :now, :now, :expires)"
                ),
                {
                    "task_id": allocation.task_id,
                    "run_id": allocation.run_id,
                    "now": datetime.now(UTC),
                    "expires": datetime.now(UTC) + timedelta(minutes=5),
                },
            )
    live = RuntimeFence(allocation.task_id, allocation.run_id, "worker", 5)
    stale = RuntimeFence(allocation.task_id, allocation.run_id, "worker", 4)
    now = datetime.now(UTC)

    committed = await ledger.commit_revision(
        runtime.sandbox_id, stream_epoch=1, revision=3, fence=live, now=now
    )
    assert committed.workspace_revision == 3
    with pytest.raises(LedgerConflict, match="sandbox_fence_stale"):
        await ledger.commit_revision(runtime.sandbox_id, stream_epoch=1, revision=9, fence=stale, now=now)
    with pytest.raises(LedgerConflict, match="sandbox_fence_stale"):
        await ledger.validate_fence(live, now=now + timedelta(minutes=10))
    with pytest.raises(LedgerConflict, match="stream_generation_changed"):
        await ledger.commit_cursor(
            runtime.sandbox_id, stream_epoch=2, stream="watch", cursor=1, fence=live, now=now
        )
    assert (await ledger.get(runtime.sandbox_id)).workspace_revision == 3


@pytest.mark.integration
async def test_an_incarnation_handoff_moves_runtime_object_and_allocation_ref_atomically(
    managed_postgres_session_factory,
) -> None:
    factory = managed_postgres_session_factory
    ledger = PostgresCodingRuntimeLedger(factory, reference_key=KEY, key_version=1)
    allocation = await _active_allocation(factory, f"msa_{uuid4().hex[:12]}")
    runtime = await _running(ledger, allocation)
    runtime = await ledger.update(
        runtime.sandbox_id, incarnation=1, expected_version=runtime.version, now=NOW,
        changes={"state": RuntimeState.SUSPENDED, "resume_snapshot_ref": "im-1"},
    )
    await ledger.update_physical(
        runtime.sandbox_id, 1, now=NOW,
        changes={"state": PhysicalState.DESTROYED, "destroy_requested_at": NOW,
                 "destroy_confirmed_at": NOW},
    )
    await ledger.put_physical(_physical(runtime.sandbox_id, 2))
    replacement = _physical(
        runtime.sandbox_id, 2, provider_ref="obj-2",
        ref_index=f"ref_{runtime.sandbox_id}_2", state=PhysicalState.ACTIVE,
    )

    committed = await ledger.commit_incarnation(
        runtime.sandbox_id,
        expected_version=runtime.version,
        replacement=replacement,
        allocation_ref_ciphertext=b"sealed-v2",
        workspace_revision=4,
        now=NOW,
    )

    assert (committed.incarnation, committed.stream_epoch, committed.state) == (2, 2, RuntimeState.RUNNING)
    assert committed.resume_snapshot_ref is None
    assert (await ledger.get_physical(runtime.sandbox_id, 2)).provider_ref == "obj-2"
    moved = await ledger.allocation(allocation.allocation_id)
    assert bytes(moved.provider_ref) == b"sealed-v2"
    assert moved.generation == 1

    # A handoff racing cleanup commits nothing -- runtime, physical row, and the
    # allocation ref all stay where they were.
    await ledger.update(
        runtime.sandbox_id, incarnation=2, expected_version=committed.version, now=NOW,
        changes={"state": RuntimeState.SUSPENDED, "resume_snapshot_ref": "im-2"},
    )
    await ledger.update_physical(
        runtime.sandbox_id, 2, now=NOW,
        changes={"state": PhysicalState.DESTROYED, "destroy_requested_at": NOW,
                 "destroy_confirmed_at": NOW},
    )
    await ledger.put_physical(_physical(runtime.sandbox_id, 3))
    async with await factory() as session:
        async with session.begin():
            await session.execute(
                text("UPDATE coding_managed_sandboxes SET state = :state WHERE allocation_id = :id"),
                {"state": ManagedSandboxState.CLEANUP_PENDING.value, "id": allocation.allocation_id},
            )
    before = await ledger.get(runtime.sandbox_id)
    with pytest.raises(LedgerConflict, match="ledger_allocation_not_attachable"):
        await ledger.commit_incarnation(
            runtime.sandbox_id,
            expected_version=before.version,
            replacement=_physical(
                runtime.sandbox_id, 3, provider_ref="obj-3",
                ref_index=f"ref_{runtime.sandbox_id}_3", state=PhysicalState.ACTIVE,
            ),
            allocation_ref_ciphertext=b"sealed-v3",
            workspace_revision=5,
            now=NOW,
        )
    assert (await ledger.get(runtime.sandbox_id)).incarnation == 2
    assert (await ledger.get_physical(runtime.sandbox_id, 3)).state is PhysicalState.CREATING
    assert bytes((await ledger.allocation(allocation.allocation_id)).provider_ref) == b"sealed-v2"


@pytest.mark.integration
async def test_one_active_vendor_object_per_logical_sandbox(managed_postgres_session_factory) -> None:
    factory = managed_postgres_session_factory
    ledger = PostgresCodingRuntimeLedger(factory, reference_key=KEY, key_version=1)
    allocation = await _active_allocation(factory, f"msa_{uuid4().hex[:12]}")
    runtime = await _running(ledger, allocation)
    await ledger.put_physical(_physical(runtime.sandbox_id, 2))
    with pytest.raises(IntegrityError):
        await ledger.update_physical(
            runtime.sandbox_id, 2, now=NOW,
            changes={"provider_ref": "obj-2", "ref_index": f"ref_{runtime.sandbox_id}_2",
                     "state": PhysicalState.ACTIVE},
        )
    assert await ledger.allocation_for_task(allocation.task_id) is not None
    with pytest.raises(LedgerConflict, match="ledger_intent_conflict"):
        await ledger.put_intent(_runtime(allocation, profile="strict-pids-v1"))

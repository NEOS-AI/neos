"""Coding runtime ledger: the shared fences, the in-memory ledger, the SQL repository.

No Postgres runs here (see `integration/test_postgres_coding_runtime.py` for
that). The SQL repository is exercised against a recording fake session:
statement shape, lock order, sealed references, and the fences both
implementations share.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from neos.coding.managed.domain import ManagedSandboxAllocation, ManagedSandboxState
from neos.coding.sandbox.base import SandboxLimits, SandboxUnavailable
from neos.coding.sandbox.managed.ledger import (
    InMemoryAllocationTable,
    InMemoryCodingRuntimeLedger,
    LedgerConflict,
    PhysicalRecord,
    PhysicalState,
    RuntimeFence,
    RuntimeRecord,
    RuntimeState,
    SnapshotRecord,
)
from neos.coding.sandbox.managed.ledger_sql import PostgresCodingRuntimeLedger

pytestmark = pytest.mark.no_db

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
KEY = b"r" * 32
FENCE = RuntimeFence(task_id="ct_1", run_id="cr_1", worker_id="w", fencing_token=3)


def _allocation(**changes) -> ManagedSandboxAllocation:
    values = dict(
        allocation_id="msa_1",
        tenant_id="tenant_1",
        task_id="ct_1",
        run_id="cr_1",
        provider="modal",
        region="local",
        provider_ref=b"sealed-v1",
        ownership_digest="sha256:" + "a" * 64,
        state=ManagedSandboxState.ACTIVE,
        generation=1,
        fencing_token=2,
        lease_expires_at=None,
        absolute_expires_at=NOW + timedelta(hours=1),
        version=3,
        error_code=None,
        snapshot_ref=None,
        archive_ref=None,
        image_identity="img@sha256:" + "0" * 64,
    )
    values.update(changes)
    return ManagedSandboxAllocation(**values)


def _runtime(**changes) -> RuntimeRecord:
    values = dict(
        sandbox_id="sbx_1",
        allocation_id="msa_1",
        allocation_generation=1,
        tenant_id="tenant_1",
        task_id="ct_1",
        owner_id="u_1",
        provider="modal",
        image_digest="img@sha256:" + "0" * 64,
        sandboxd_digest="sha256:" + "1" * 64,
        profile="offline-v1",
        network_policy={"outbound": "deny", "inbound": "deny", "allow": []},
        region="local",
        limits=SandboxLimits.safe_defaults(),
        expires_at=NOW + timedelta(hours=1),
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


def _physical(**changes) -> PhysicalRecord:
    values = dict(
        sandbox_id="sbx_1",
        incarnation=1,
        idempotency_key="idem_msa_1",
        ownership_digest="hmac-sha256:" + "b" * 64,
        state=PhysicalState.CREATING,
        created_at=NOW,
        updated_at=NOW,
    )
    values.update(changes)
    return PhysicalRecord(**values)


# ---- record invariants --------------------------------------------------------------


def test_record_invariants_are_enforced() -> None:
    with pytest.raises(ValueError, match="positive"):
        _runtime(incarnation=0)
    with pytest.raises(ValueError, match="timezone-aware"):
        _runtime(expires_at=datetime(2026, 9, 15, 13, 0))
    with pytest.raises(ValueError, match="go together"):
        _physical(provider_ref="obj-1")
    with pytest.raises(ValueError, match="destroy confirmation"):
        _physical(state=PhysicalState.DESTROYED)
    with pytest.raises(ValueError, match="needs its provider ref"):
        _physical(state=PhysicalState.ACTIVE)
    with pytest.raises(ValueError, match="destroy_requested_at"):
        _physical(state=PhysicalState.DESTROY_PENDING)


def test_allocation_table_keeps_one_live_allocation_per_task() -> None:
    table = InMemoryAllocationTable()
    table.put(_allocation())
    with pytest.raises(LedgerConflict, match="allocation_live_for_task"):
        table.put(_allocation(allocation_id="msa_2"))
    table.put(_allocation(allocation_id="msa_2", state=ManagedSandboxState.FAILED))
    assert table.live_for_task("ct_1").allocation_id == "msa_1"


# ---- in-memory fences -----------------------------------------------------------------


async def test_put_intent_is_idempotent_and_refuses_a_different_intent() -> None:
    ledger = InMemoryCodingRuntimeLedger()
    stored = await ledger.put_intent(_runtime())
    assert await ledger.put_intent(_runtime()) is stored
    with pytest.raises(LedgerConflict, match="ledger_intent_conflict"):
        await ledger.put_intent(_runtime(profile="strict-pids-v1"))
    with pytest.raises(ValueError, match="intent state"):
        await ledger.put_intent(_runtime(sandbox_id="sbx_2", state=RuntimeState.RUNNING))


async def test_update_fence_checks_incarnation_version_and_field() -> None:
    ledger = InMemoryCodingRuntimeLedger()
    await ledger.put_intent(_runtime())
    common = dict(now=NOW, changes={"state": RuntimeState.RUNNING})
    with pytest.raises(LedgerConflict, match="ledger_incarnation_mismatch"):
        await ledger.update("sbx_1", incarnation=2, expected_version=1, **common)
    with pytest.raises(LedgerConflict, match="ledger_version_conflict"):
        await ledger.update("sbx_1", incarnation=1, expected_version=7, **common)
    with pytest.raises(ValueError, match="immutable"):
        await ledger.update(
            "sbx_1", incarnation=1, expected_version=1, now=NOW, changes={"incarnation": 2}
        )
    updated = await ledger.update("sbx_1", incarnation=1, expected_version=1, **common)
    assert updated.version == 2 and updated.state is RuntimeState.RUNNING
    await ledger.update(
        "sbx_1", incarnation=1, expected_version=None, now=NOW,
        changes={"state": RuntimeState.DETACHED},
    )
    with pytest.raises(LedgerConflict, match="ledger_sandbox_detached"):
        await ledger.update(
            "sbx_1", incarnation=1, expected_version=None, now=NOW,
            changes={"workspace_revision": 4},
        )


async def test_revision_and_cursor_commits_are_fenced_by_epoch_state_and_lease() -> None:
    dead: set[RuntimeFence] = set()
    ledger = InMemoryCodingRuntimeLedger(lease_is_live=lambda fence, _now: fence not in dead)
    await ledger.put_intent(_runtime())
    with pytest.raises(LedgerConflict, match="ledger_sandbox_not_running"):
        await ledger.commit_revision("sbx_1", stream_epoch=1, revision=1, fence=None, now=NOW)
    await ledger.update(
        "sbx_1", incarnation=1, expected_version=None, now=NOW,
        changes={"state": RuntimeState.RUNNING},
    )
    assert (
        await ledger.commit_revision("sbx_1", stream_epoch=1, revision=2, fence=FENCE, now=NOW)
    ).workspace_revision == 2
    # Monotonic: an older report never lowers the revision.
    assert (
        await ledger.commit_revision("sbx_1", stream_epoch=1, revision=1, fence=FENCE, now=NOW)
    ).workspace_revision == 2
    with pytest.raises(LedgerConflict, match="stream_generation_changed"):
        await ledger.commit_cursor(
            "sbx_1", stream_epoch=2, stream="watch", cursor=5, fence=FENCE, now=NOW
        )
    with pytest.raises(LedgerConflict, match="sandbox_fence_stale"):
        await ledger.commit_revision(
            "sbx_1", stream_epoch=1, revision=3,
            fence=dataclasses.replace(FENCE, task_id="ct_other"), now=NOW,
        )
    dead.add(FENCE)
    with pytest.raises(LedgerConflict, match="sandbox_fence_stale"):
        await ledger.commit_revision("sbx_1", stream_epoch=1, revision=3, fence=FENCE, now=NOW)
    with pytest.raises(LedgerConflict, match="sandbox_fence_stale"):
        await ledger.validate_fence(FENCE, now=NOW)
    assert (await ledger.get("sbx_1")).workspace_revision == 2


async def _running_modal_ledger() -> tuple[InMemoryCodingRuntimeLedger, InMemoryAllocationTable]:
    table = InMemoryAllocationTable()
    table.put(_allocation())
    ledger = InMemoryCodingRuntimeLedger(table)
    await ledger.put_intent(_runtime())
    await ledger.put_physical(_physical())
    await ledger.update_physical(
        "sbx_1", 1, now=NOW,
        changes={"provider_ref": "obj-1", "ref_index": "ref_1", "state": PhysicalState.ACTIVE},
    )
    await ledger.update(
        "sbx_1", incarnation=1, expected_version=None, now=NOW,
        changes={"state": RuntimeState.SUSPENDED, "resume_snapshot_ref": "im-1"},
    )
    await ledger.update_physical(
        "sbx_1", 1, now=NOW,
        changes={
            "state": PhysicalState.DESTROYED,
            "destroy_requested_at": NOW,
            "destroy_confirmed_at": NOW,
        },
    )
    await ledger.put_physical(
        _physical(incarnation=2, idempotency_key="neos-coding-sbx:v1:sbx_1:2")
    )
    return ledger, table


async def test_commit_incarnation_moves_runtime_physical_and_allocation_ref_together() -> None:
    ledger, table = await _running_modal_ledger()
    runtime = await ledger.get("sbx_1")
    replacement = _physical(
        incarnation=2,
        idempotency_key="neos-coding-sbx:v1:sbx_1:2",
        provider_ref="obj-2",
        ref_index="ref_2",
        state=PhysicalState.ACTIVE,
    )
    committed = await ledger.commit_incarnation(
        "sbx_1",
        expected_version=runtime.version,
        replacement=replacement,
        allocation_ref_ciphertext=b"sealed-v2",
        workspace_revision=4,
        now=NOW,
    )
    assert (committed.incarnation, committed.stream_epoch) == (2, 2)
    assert committed.state is RuntimeState.RUNNING
    assert committed.resume_snapshot_ref is None
    assert committed.workspace_revision == 4
    assert (await ledger.get_physical("sbx_1", 2)).state is PhysicalState.ACTIVE
    allocation = table.rows["msa_1"]
    assert allocation.provider_ref == b"sealed-v2"
    assert allocation.generation == 1  # admission generation does not move

    with pytest.raises(LedgerConflict, match="ledger_version_conflict"):
        await ledger.commit_incarnation(
            "sbx_1", expected_version=runtime.version, replacement=replacement,
            allocation_ref_ciphertext=b"x", workspace_revision=4, now=NOW,
        )


async def test_commit_incarnation_refuses_when_the_allocation_is_being_cleaned() -> None:
    ledger, table = await _running_modal_ledger()
    table.rows["msa_1"] = _allocation(state=ManagedSandboxState.CLEANUP_PENDING)
    runtime = await ledger.get("sbx_1")
    with pytest.raises(LedgerConflict, match="ledger_allocation_not_attachable"):
        await ledger.commit_incarnation(
            "sbx_1",
            expected_version=runtime.version,
            replacement=_physical(
                incarnation=2, idempotency_key="neos-coding-sbx:v1:sbx_1:2",
                provider_ref="obj-2", ref_index="ref_2", state=PhysicalState.ACTIVE,
            ),
            allocation_ref_ciphertext=b"sealed-v2",
            workspace_revision=4,
            now=NOW,
        )
    assert (await ledger.get("sbx_1")).incarnation == 1
    assert table.rows["msa_1"].provider_ref == b"sealed-v1"


async def test_physical_rows_are_unique_by_incarnation_and_key() -> None:
    ledger = InMemoryCodingRuntimeLedger()
    assert await ledger.put_physical(_physical()) is not None
    assert await ledger.put_physical(_physical()) is None
    assert await ledger.put_physical(_physical(incarnation=2)) is None  # same key
    await ledger.update_physical(
        "sbx_1", 1, now=NOW,
        changes={"state": PhysicalState.DESTROYED, "destroy_confirmed_at": NOW},
    )
    with pytest.raises(LedgerConflict, match="ledger_physical_destroyed"):
        await ledger.update_physical("sbx_1", 1, now=NOW, changes={"state": PhysicalState.ACTIVE})


# ---- SQL repository ------------------------------------------------------------


class FakeResult:
    def __init__(self, row=None, rows=()) -> None:
        self._row = row
        self._rows = list(rows)

    def first(self):
        return self._row

    def all(self):
        return self._rows


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


class FakeSession:
    def __init__(self, results: list[FakeResult]) -> None:
        self.results = results
        self.statements: list[tuple[str, dict]] = []

    def begin(self):
        return FakeTransaction()

    async def execute(self, statement, params=None):
        self.statements.append((str(statement), dict(params or {})))
        return self.results.pop(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


def _repository(session: FakeSession) -> PostgresCodingRuntimeLedger:
    async def factory():
        return session

    return PostgresCodingRuntimeLedger(factory, reference_key=KEY, key_version=1)


def _row(params: dict) -> SimpleNamespace:
    return SimpleNamespace(**params)


def _allocation_row(allocation: ManagedSandboxAllocation) -> SimpleNamespace:
    values = dataclasses.asdict(allocation)
    values["state"] = allocation.state.value
    return SimpleNamespace(**values)


async def test_sql_put_intent_inserts_once_and_returns_the_stored_intent() -> None:
    record = _runtime()
    stored = _row(_repository(FakeSession([]))._runtime_params(record))
    session = FakeSession([FakeResult(row=None), FakeResult(row=stored)])
    assert await _repository(session).put_intent(record) == record
    insert, params = session.statements[0]
    assert "INSERT INTO coding_managed_runtime" in insert
    assert "ON CONFLICT DO NOTHING" in insert
    assert json.loads(params["network_policy"])["outbound"] == "deny"

    different = FakeSession([FakeResult(row=None), FakeResult(row=stored)])
    with pytest.raises(LedgerConflict, match="ledger_intent_conflict"):
        await _repository(different).put_intent(_runtime(image_digest="img@sha256:" + "9" * 64))


async def test_sql_runtime_round_trip_seals_the_resume_ref_to_its_incarnation() -> None:
    record = _runtime(state=RuntimeState.SUSPENDED, resume_snapshot_ref="im-plaintext",
                      stream_cursors={"watch": 3})
    params = _repository(FakeSession([]))._runtime_params(record)
    assert b"im-plaintext" not in params["resume_snapshot_ref"]
    loaded = await _repository(FakeSession([FakeResult(row=_row(params))])).get("sbx_1")
    assert loaded.resume_snapshot_ref == "im-plaintext"
    assert dict(loaded.stream_cursors) == {"watch": 3}
    assert loaded.limits == record.limits

    moved = _row({**params, "incarnation": 2})
    with pytest.raises(SandboxUnavailable, match="managed_ledger_reference_unverifiable"):
        await _repository(FakeSession([FakeResult(row=moved)])).get("sbx_1")


async def test_sql_physical_ref_is_sealed_and_bound_to_its_incarnation() -> None:
    record = _physical(provider_ref="obj-plaintext", ref_index="ref_1", state=PhysicalState.ACTIVE)
    writer = FakeSession([FakeResult(row=("sbx_1",))])
    assert await _repository(writer).put_physical(record) == record
    params = writer.statements[0][1]
    assert b"obj-plaintext" not in params["provider_ref"]
    loaded = await _repository(FakeSession([FakeResult(row=_row(params))])).get_physical("sbx_1", 1)
    assert loaded.provider_ref == "obj-plaintext"
    moved = _row({**params, "incarnation": 2})
    with pytest.raises(SandboxUnavailable, match="managed_ledger_reference_unverifiable"):
        await _repository(FakeSession([FakeResult(row=moved)])).get_physical("sbx_1", 2)


async def test_sql_revision_commit_checks_the_lease_under_a_share_lock() -> None:
    running = _row(_repository(FakeSession([]))._runtime_params(_runtime(state=RuntimeState.RUNNING)))
    stale = FakeSession([FakeResult(row=running), FakeResult(row=None)])
    with pytest.raises(LedgerConflict, match="sandbox_fence_stale"):
        await _repository(stale).commit_revision(
            "sbx_1", stream_epoch=1, revision=1, fence=FENCE, now=NOW
        )
    assert "FOR UPDATE" in stale.statements[0][0]
    lease_sql, lease_params = stale.statements[1]
    assert "FROM coding_run_leases" in lease_sql and "FOR SHARE" in lease_sql
    assert lease_params["fencing_token"] == 3
    assert len(stale.statements) == 2  # nothing written

    live = FakeSession(
        [FakeResult(row=running), FakeResult(row=(1,)), FakeResult(row=("sbx_1",))]
    )
    updated = await _repository(live).commit_revision(
        "sbx_1", stream_epoch=1, revision=5, fence=FENCE, now=NOW
    )
    assert updated.workspace_revision == 5
    update_sql, update_params = live.statements[2]
    assert "AND version = :previous_version" in update_sql
    assert update_params["previous_version"] == 1

    other_epoch = FakeSession([FakeResult(row=running)])
    with pytest.raises(LedgerConflict, match="stream_generation_changed"):
        await _repository(other_epoch).commit_revision(
            "sbx_1", stream_epoch=2, revision=5, fence=None, now=NOW
        )


async def test_sql_commit_incarnation_locks_allocation_before_runtime_and_moves_the_ref() -> None:
    repository = _repository(FakeSession([]))
    suspended = _runtime(state=RuntimeState.SUSPENDED, version=4)
    runtime_row = _row(repository._runtime_params(suspended))
    committed_row = _row(
        repository._runtime_params(
            dataclasses.replace(suspended, incarnation=2, stream_epoch=2,
                                state=RuntimeState.RUNNING, version=5)
        )
    )
    session = FakeSession(
        [
            FakeResult(row=SimpleNamespace(allocation_id="msa_1")),
            FakeResult(row=_allocation_row(_allocation())),
            FakeResult(row=runtime_row),
            FakeResult(row=("sbx_1",)),
            FakeResult(row=committed_row),
            FakeResult(row=("msa_1",)),
        ]
    )
    committed = await _repository(session).commit_incarnation(
        "sbx_1",
        expected_version=4,
        replacement=_physical(
            incarnation=2, idempotency_key="neos-coding-sbx:v1:sbx_1:2",
            provider_ref="obj-2", ref_index="ref_2", state=PhysicalState.ACTIVE,
        ),
        allocation_ref_ciphertext=b"sealed-v2",
        workspace_revision=3,
        now=NOW,
    )
    assert committed.incarnation == 2
    statements = [sql for sql, _ in session.statements]
    assert "FROM coding_managed_sandboxes" in statements[1] and "FOR UPDATE" in statements[1]
    assert "FROM coding_managed_runtime" in statements[2] and "FOR UPDATE" in statements[2]
    assert "UPDATE coding_managed_physical_objects" in statements[3]
    assert "stream_epoch = stream_epoch + 1" in statements[4]
    allocation_sql, allocation_params = session.statements[5]
    assert "UPDATE coding_managed_sandboxes SET provider_ref" in allocation_sql
    assert allocation_params["provider_ref"] == b"sealed-v2"
    assert allocation_params["generation"] == 1


async def test_sql_commit_incarnation_refuses_a_cleaning_allocation_before_writing() -> None:
    repository = _repository(FakeSession([]))
    runtime_row = _row(repository._runtime_params(_runtime(state=RuntimeState.SUSPENDED, version=4)))
    session = FakeSession(
        [
            FakeResult(row=SimpleNamespace(allocation_id="msa_1")),
            FakeResult(row=_allocation_row(_allocation(state=ManagedSandboxState.CLEANUP_PENDING))),
            FakeResult(row=runtime_row),
        ]
    )
    with pytest.raises(LedgerConflict, match="ledger_allocation_not_attachable"):
        await _repository(session).commit_incarnation(
            "sbx_1",
            expected_version=4,
            replacement=_physical(
                incarnation=2, idempotency_key="k2", provider_ref="obj-2",
                ref_index="ref_2", state=PhysicalState.ACTIVE,
            ),
            allocation_ref_ciphertext=b"sealed-v2",
            workspace_revision=3,
            now=NOW,
        )
    assert len(session.statements) == 3


async def test_sql_snapshot_ref_is_sealed_and_round_trips() -> None:
    snapshot = SnapshotRecord(
        snapshot_id="snp_1",
        sandbox_id="sbx_1",
        allocation_id="msa_1",
        task_id="ct_1",
        incarnation=1,
        provider="modal",
        provider_snapshot_ref="im-plaintext",
        workspace_revision=4,
        content_checksum="sha256:" + "c" * 64,
        image_digest="img@sha256:" + "0" * 64,
        profile="offline-v1",
        region="local",
        limits=SandboxLimits.safe_defaults(),
        created_at=NOW,
        expires_at=NOW + timedelta(days=30),
    )
    writer = FakeSession([FakeResult(row=("snp_1",))])
    await _repository(writer).put_snapshot(snapshot)
    params = writer.statements[0][1]
    assert b"im-plaintext" not in params["provider_snapshot_ref"]
    reader = FakeSession([FakeResult(row=_row(params))])
    assert await _repository(reader).get_snapshot("snp_1") == snapshot

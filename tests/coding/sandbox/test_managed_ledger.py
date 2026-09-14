"""Coding sandbox ledger: the shared fence, the in-memory ledger, the SQL repository.

No Postgres runs here. The SQL repository is exercised against a recording
fake session: statement shape, sealed references, and the owner / generation /
version fence that both implementations share.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from neos.coding.sandbox.base import SandboxLimits, SandboxUnavailable
from neos.coding.sandbox.managed.ledger import (
    InMemorySandboxLedger,
    LedgerConflict,
    LedgerState,
    SandboxLedgerRecord,
    SnapshotLedgerRecord,
)
from neos.coding.sandbox.managed.ledger_sql import PostgresSandboxLedger

pytestmark = pytest.mark.no_db

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
KEY = b"r" * 32


def _record(**changes) -> SandboxLedgerRecord:
    values = dict(
        sandbox_id="sbx_1",
        owner_id="ct_1",
        task_id="ct_1",
        ordinal=1,
        generation=1,
        allocation_id="alc_1",
        idempotency_key="neos-coding-sbx:v1:alc_1",
        ownership_digest="hmac-sha256:" + "a" * 64,
        provider="e2b",
        provider_ref=None,
        image_digest="img@sha256:" + "0" * 64,
        sandboxd_digest="sha256:" + "1" * 64,
        profile="offline-v1",
        network_policy={"outbound": "deny", "inbound": "deny", "allow": []},
        region="local",
        limits=SandboxLimits.safe_defaults(),
        state=LedgerState.CREATING,
        workspace_revision=0,
        expires_at=NOW + timedelta(hours=1),
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    values.update(changes)
    return SandboxLedgerRecord(**values)


# ---- record invariants and in-memory fence ------------------------------------------


def test_record_invariants_are_enforced() -> None:
    with pytest.raises(ValueError, match="destroy confirmation"):
        _record(state=LedgerState.DESTROYED)
    with pytest.raises(ValueError, match="provider reference"):
        _record(state=LedgerState.DESTROYED, destroy_confirmed_at=NOW, provider_ref="obj-1")
    with pytest.raises(ValueError, match="destroy_requested_at"):
        _record(state=LedgerState.DESTROY_PENDING)
    with pytest.raises(ValueError, match="timezone-aware"):
        _record(expires_at=datetime(2026, 9, 14, 13, 0))


async def test_reserve_refuses_a_second_row_for_the_same_slot_or_key() -> None:
    ledger = InMemorySandboxLedger()
    assert await ledger.reserve(_record()) is not None
    assert await ledger.reserve(_record(sandbox_id="sbx_2", allocation_id="alc_2")) is None
    assert await ledger.reserve(
        _record(sandbox_id="sbx_3", ordinal=2, allocation_id="alc_3")
    ) is None  # same idempotency key
    assert await ledger.max_ordinal(owner_id="ct_1", task_id="ct_1") == 1


async def test_update_fence_checks_owner_generation_version_and_field() -> None:
    ledger = InMemorySandboxLedger()
    await ledger.reserve(_record())
    common = dict(now=NOW, changes={"state": LedgerState.RUNNING})
    with pytest.raises(LedgerConflict, match="ledger_owner_mismatch"):
        await ledger.update("sbx_1", owner_id="ct_2", generation=1, expected_version=1, **common)
    with pytest.raises(LedgerConflict, match="ledger_generation_mismatch"):
        await ledger.update("sbx_1", owner_id="ct_1", generation=2, expected_version=1, **common)
    with pytest.raises(LedgerConflict, match="ledger_version_conflict"):
        await ledger.update("sbx_1", owner_id="ct_1", generation=1, expected_version=7, **common)
    with pytest.raises(ValueError, match="immutable"):
        await ledger.update(
            "sbx_1", owner_id="ct_1", generation=1, expected_version=1,
            now=NOW, changes={"owner_id": "ct_2"},
        )
    updated = await ledger.update("sbx_1", owner_id="ct_1", generation=1, expected_version=1, **common)
    assert updated.version == 2
    assert updated.state is LedgerState.RUNNING


async def test_destroyed_rows_accept_no_further_writes() -> None:
    ledger = InMemorySandboxLedger()
    await ledger.reserve(_record())
    await ledger.update(
        "sbx_1", owner_id="ct_1", generation=1, expected_version=None, now=NOW,
        changes={"state": LedgerState.DESTROYED, "destroy_confirmed_at": NOW},
    )
    with pytest.raises(LedgerConflict, match="ledger_sandbox_destroyed"):
        await ledger.update(
            "sbx_1", owner_id="ct_1", generation=1, expected_version=None, now=NOW,
            changes={"workspace_revision": 4},
        )


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


def _repository(session: FakeSession) -> PostgresSandboxLedger:
    async def factory():
        return session

    return PostgresSandboxLedger(factory, reference_key=KEY, key_version=1)


def _row_from(params: dict) -> SimpleNamespace:
    return SimpleNamespace(**params)


async def test_sql_reserve_seals_the_provider_ref_and_never_overwrites() -> None:
    session = FakeSession([FakeResult(row=("sbx_1",)), FakeResult(row=None)])
    repository = _repository(session)
    record = _record(provider_ref="obj-plaintext-ref")

    assert await repository.reserve(record) == record
    assert await repository.reserve(record) is None

    statement, params = session.statements[0]
    assert "INSERT INTO coding_sandbox_ledger" in statement
    assert "ON CONFLICT DO NOTHING" in statement
    assert isinstance(params["provider_ref"], bytes)
    assert b"obj-plaintext-ref" not in params["provider_ref"]
    assert json.loads(params["network_policy"])["outbound"] == "deny"


async def test_sql_get_round_trips_through_the_sealed_columns() -> None:
    writer = FakeSession([FakeResult(row=("sbx_1",))])
    record = _record(provider_ref="obj-9", stream_cursors={"watch": 3})
    await _repository(writer).reserve(record)
    row = _row_from(writer.statements[0][1])

    reader = FakeSession([FakeResult(row=row)])
    loaded = await _repository(reader).get("sbx_1")

    assert loaded.provider_ref == "obj-9"
    assert dict(loaded.stream_cursors) == {"watch": 3}
    assert loaded.limits == record.limits
    assert loaded.state is LedgerState.CREATING


async def test_sql_sealed_ref_is_bound_to_its_generation() -> None:
    writer = FakeSession([FakeResult(row=("sbx_1",))])
    await _repository(writer).reserve(_record(provider_ref="obj-9"))
    params = writer.statements[0][1]
    moved = _row_from({**params, "generation": 2})

    reader = FakeSession([FakeResult(row=moved)])
    with pytest.raises(SandboxUnavailable, match="managed_ledger_reference_unverifiable"):
        await _repository(reader).get("sbx_1")


async def test_sql_update_locks_fences_and_checks_the_version() -> None:
    writer = FakeSession([FakeResult(row=("sbx_1",))])
    await _repository(writer).reserve(_record())
    row = _row_from(writer.statements[0][1])

    session = FakeSession([FakeResult(row=row), FakeResult(row=("sbx_1",))])
    updated = await _repository(session).update(
        "sbx_1", owner_id="ct_1", generation=1, expected_version=1, now=NOW,
        changes={"state": LedgerState.RUNNING, "provider_ref": "obj-1", "workspace_revision": 2},
    )
    assert updated.version == 2
    select, _ = session.statements[0]
    update, params = session.statements[1]
    assert "FOR UPDATE" in select
    assert "AND version = :previous_version" in update
    assert params["previous_version"] == 1
    assert isinstance(params["provider_ref"], bytes)

    lost = FakeSession([FakeResult(row=row), FakeResult(row=None)])
    with pytest.raises(LedgerConflict, match="ledger_version_conflict"):
        await _repository(lost).update(
            "sbx_1", owner_id="ct_1", generation=1, expected_version=None, now=NOW,
            changes={"workspace_revision": 3},
        )

    stale = FakeSession([FakeResult(row=row)])
    with pytest.raises(LedgerConflict, match="ledger_generation_mismatch"):
        await _repository(stale).update(
            "sbx_1", owner_id="ct_1", generation=5, expected_version=None, now=NOW,
            changes={"workspace_revision": 3},
        )
    assert len(stale.statements) == 1  # nothing written


async def test_sql_snapshot_ref_is_sealed_and_round_trips() -> None:
    snapshot = SnapshotLedgerRecord(
        snapshot_id="snp_1",
        sandbox_id="sbx_1",
        owner_id="ct_1",
        generation=1,
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

    reader = FakeSession([FakeResult(row=_row_from(params))])
    assert await _repository(reader).get_snapshot("snp_1") == snapshot


def test_record_replace_preserves_read_only_mappings() -> None:
    record = _record(stream_cursors={"watch": 1})
    changed = dataclasses.replace(record, workspace_revision=1)
    with pytest.raises(TypeError):
        changed.stream_cursors["watch"] = 2  # type: ignore[index]

"""Durable NEOS ledger for managed coding sandboxes.

vendor object는 SoT가 아니다. 이 원장이 SoT다
(docs/MANAGED_SANDBOX_PROVIDER_REVIEW_260914.md §6, §8.1):

1. 행은 provider create **전에** 기록한다 (`CREATING`).
2. 식별자는 (owner, task, ordinal, generation)에서 결정적으로 나온다
   (`identity.py`). 재시도는 idempotency key로 provider를 재발견한다.
3. 모든 변경은 owner_id + generation + version을 대조한다. 오래된 호출자는
   새 generation에 쓰지 못한다.
4. destroy는 요청 전에 `DESTROY_PENDING`을 기록하고, 확인된 뒤에만
   `DESTROYED`가 된다.

`InMemorySandboxLedger`는 테스트용이다. 프로세스가 죽으면 원장도 사라지므로
production에서 쓸 수 없다 -- factory는 원장을 주입받지 못하면 거절한다.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol

from neos.coding.sandbox.base import SandboxLimits, SandboxStateConflict


class LedgerState(StrEnum):
    CREATING = "creating"
    RUNNING = "running"
    SUSPENDED = "suspended"
    QUARANTINED = "quarantined"
    FAILED = "failed"
    DESTROY_PENDING = "destroy_pending"
    DESTROYED = "destroyed"


# 새 작업을 막는 상태. 격리된 행이 하나라도 있으면 같은 owner/task의 create를
# 거절한다 -- provider 쪽에 우리 것이 둘 이상 떠 있다는 뜻이고, 사람이 보기
# 전에 셋째를 만들면 안 된다.
BLOCKING_STATES = frozenset({LedgerState.QUARANTINED})
TERMINAL_STATES = frozenset({LedgerState.FAILED, LedgerState.DESTROYED})


class LedgerConflict(SandboxStateConflict):
    """owner / generation / version 대조 실패. 쓰기는 일어나지 않았다."""


# `update()`가 바꿀 수 있는 필드. 식별자(sandbox/owner/task/ordinal)는 절대
# 바뀌지 않는다; generation 은 provider object 교체 때만 올라간다.
MUTABLE_FIELDS = frozenset(
    {
        "generation",
        "allocation_id",
        "idempotency_key",
        "ownership_digest",
        "provider_ref",
        "state",
        "resume_snapshot_ref",
        "resume_snapshot_expires_at",
        "workspace_revision",
        "stream_cursors",
        "error_code",
        "destroy_requested_at",
        "destroy_confirmed_at",
    }
)


def limits_to_record(limits: SandboxLimits) -> dict[str, float | int]:
    return {
        "cpu_count": limits.cpu_count,
        "memory_bytes": limits.memory_bytes,
        "pids": limits.pids,
        "workspace_bytes": limits.workspace_bytes,
        "command_timeout_sec": limits.command_timeout_sec,
        "max_output_bytes": limits.max_output_bytes,
        "max_stdin_bytes": limits.max_stdin_bytes,
    }


def limits_from_record(value: Mapping[str, Any]) -> SandboxLimits:
    return SandboxLimits(
        cpu_count=float(value["cpu_count"]),
        memory_bytes=int(value["memory_bytes"]),
        pids=int(value["pids"]),
        workspace_bytes=int(value["workspace_bytes"]),
        command_timeout_sec=float(value["command_timeout_sec"]),
        max_output_bytes=int(value["max_output_bytes"]),
        max_stdin_bytes=int(value["max_stdin_bytes"]),
    )


@dataclass(frozen=True, slots=True)
class SandboxLedgerRecord:
    sandbox_id: str
    owner_id: str
    task_id: str
    ordinal: int
    generation: int
    allocation_id: str
    idempotency_key: str
    ownership_digest: str
    provider: str
    provider_ref: str | None
    image_digest: str
    sandboxd_digest: str
    profile: str
    network_policy: Mapping[str, Any]
    region: str
    limits: SandboxLimits
    state: LedgerState
    workspace_revision: int
    expires_at: datetime
    version: int
    created_at: datetime
    updated_at: datetime
    source_snapshot_id: str | None = None
    resume_snapshot_ref: str | None = None
    resume_snapshot_expires_at: datetime | None = None
    stream_cursors: Mapping[str, int] = field(default_factory=dict)
    error_code: str | None = None
    destroy_requested_at: datetime | None = None
    destroy_confirmed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.ordinal < 1 or self.generation < 1 or self.version < 1:
            raise ValueError("ledger ordinal, generation, and version must be positive")
        if self.workspace_revision < 0:
            raise ValueError("workspace revision must not be negative")
        for name in ("expires_at", "created_at", "updated_at"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if (self.state is LedgerState.DESTROYED) != (self.destroy_confirmed_at is not None):
            raise ValueError("destroyed state and destroy confirmation go together")
        if self.state is LedgerState.DESTROYED and self.provider_ref is not None:
            raise ValueError("destroyed sandbox cannot retain a provider reference")
        if self.state is LedgerState.DESTROY_PENDING and self.destroy_requested_at is None:
            raise ValueError("destroy_pending requires destroy_requested_at")
        object.__setattr__(self, "network_policy", MappingProxyType(dict(self.network_policy)))
        object.__setattr__(self, "stream_cursors", MappingProxyType(dict(self.stream_cursors)))


@dataclass(frozen=True, slots=True)
class SnapshotLedgerRecord:
    snapshot_id: str
    sandbox_id: str
    owner_id: str
    generation: int
    provider: str
    provider_snapshot_ref: str
    workspace_revision: int
    content_checksum: str
    image_digest: str
    profile: str
    region: str
    limits: SandboxLimits
    created_at: datetime
    expires_at: datetime | None = None


class SandboxLedger(Protocol):
    async def max_ordinal(self, *, owner_id: str, task_id: str) -> int: ...

    async def reserve(self, record: SandboxLedgerRecord) -> SandboxLedgerRecord | None:
        """Insert a new row. None when (owner, task, ordinal) is already taken."""
        ...

    async def get(self, sandbox_id: str) -> SandboxLedgerRecord | None: ...

    async def find_by_state(
        self, *, owner_id: str, task_id: str, states: frozenset[LedgerState]
    ) -> tuple[SandboxLedgerRecord, ...]: ...

    async def list_by_state(
        self, states: frozenset[LedgerState], *, limit: int = 100
    ) -> tuple[SandboxLedgerRecord, ...]: ...

    async def update(
        self,
        sandbox_id: str,
        *,
        owner_id: str,
        generation: int,
        expected_version: int | None,
        changes: Mapping[str, Any],
        now: datetime,
    ) -> SandboxLedgerRecord: ...

    async def put_snapshot(self, record: SnapshotLedgerRecord) -> None: ...

    async def get_snapshot(self, snapshot_id: str) -> SnapshotLedgerRecord | None: ...


def check_changes(changes: Mapping[str, Any]) -> None:
    unknown = set(changes) - MUTABLE_FIELDS
    if unknown:
        raise ValueError(f"ledger field is immutable: {sorted(unknown)[0]}")


def apply_update(
    record: SandboxLedgerRecord,
    *,
    owner_id: str,
    generation: int,
    expected_version: int | None,
    changes: Mapping[str, Any],
    now: datetime,
) -> SandboxLedgerRecord:
    """The shared owner/generation/version fence. Raises before any write."""
    check_changes(changes)
    if record.owner_id != owner_id:
        raise LedgerConflict("ledger_owner_mismatch")
    if record.generation != generation:
        raise LedgerConflict("ledger_generation_mismatch")
    if expected_version is not None and record.version != expected_version:
        raise LedgerConflict("ledger_version_conflict")
    if record.state is LedgerState.DESTROYED:
        raise LedgerConflict("ledger_sandbox_destroyed")
    return replace(record, **dict(changes), version=record.version + 1, updated_at=now)


class InMemorySandboxLedger:
    """Test ledger with the same fencing rules as the SQL repository."""

    def __init__(self) -> None:
        self._rows: dict[str, SandboxLedgerRecord] = {}
        self._snapshots: dict[str, SnapshotLedgerRecord] = {}
        self._lock = asyncio.Lock()
        self.update_calls = 0

    async def max_ordinal(self, *, owner_id: str, task_id: str) -> int:
        async with self._lock:
            return max(
                (
                    row.ordinal
                    for row in self._rows.values()
                    if row.owner_id == owner_id and row.task_id == task_id
                ),
                default=0,
            )

    async def reserve(self, record: SandboxLedgerRecord) -> SandboxLedgerRecord | None:
        async with self._lock:
            for row in self._rows.values():
                if (row.owner_id, row.task_id, row.ordinal) == (
                    record.owner_id,
                    record.task_id,
                    record.ordinal,
                ):
                    return None
                if row.idempotency_key == record.idempotency_key:
                    return None
            if record.sandbox_id in self._rows:
                return None
            self._rows[record.sandbox_id] = record
            return record

    async def get(self, sandbox_id: str) -> SandboxLedgerRecord | None:
        async with self._lock:
            return self._rows.get(sandbox_id)

    async def find_by_state(
        self, *, owner_id: str, task_id: str, states: frozenset[LedgerState]
    ) -> tuple[SandboxLedgerRecord, ...]:
        async with self._lock:
            return tuple(
                sorted(
                    (
                        row
                        for row in self._rows.values()
                        if row.owner_id == owner_id
                        and row.task_id == task_id
                        and row.state in states
                    ),
                    key=lambda row: row.ordinal,
                )
            )

    async def list_by_state(
        self, states: frozenset[LedgerState], *, limit: int = 100
    ) -> tuple[SandboxLedgerRecord, ...]:
        async with self._lock:
            rows = sorted(
                (row for row in self._rows.values() if row.state in states),
                key=lambda row: row.updated_at,
            )
            return tuple(rows[:limit])

    async def update(
        self,
        sandbox_id: str,
        *,
        owner_id: str,
        generation: int,
        expected_version: int | None,
        changes: Mapping[str, Any],
        now: datetime,
    ) -> SandboxLedgerRecord:
        async with self._lock:
            self.update_calls += 1
            record = self._rows.get(sandbox_id)
            if record is None:
                raise LedgerConflict("ledger_sandbox_missing")
            updated = apply_update(
                record,
                owner_id=owner_id,
                generation=generation,
                expected_version=expected_version,
                changes=changes,
                now=now,
            )
            self._rows[sandbox_id] = updated
            return updated

    async def put_snapshot(self, record: SnapshotLedgerRecord) -> None:
        async with self._lock:
            existing = self._snapshots.get(record.snapshot_id)
            if existing is not None and existing != record:
                raise LedgerConflict("ledger_snapshot_conflict")
            self._snapshots[record.snapshot_id] = record

    async def get_snapshot(self, snapshot_id: str) -> SnapshotLedgerRecord | None:
        async with self._lock:
            return self._snapshots.get(snapshot_id)

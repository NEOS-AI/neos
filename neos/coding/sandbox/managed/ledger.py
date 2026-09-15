"""Durable coding runtime ledger for managed sandboxes.

vendor object 는 SoT 가 아니다. 이 원장과 할당 원장(045)이 SoT 다
(docs/MANAGED_SANDBOX_PROVIDER_REVIEW_260914.md §6, §8.1).

세 층을 적는다.

* **runtime** -- 논리 샌드박스 하나. allocation 에 1:1 로 붙는다(FK). 코딩 intent
  (profile / image / guest digest / limits / region / expiry)는 **할당 전에**
  `INTENT` 상태로 기록되고, 할당 어댑터가 그것을 읽어 vendor object 를 만든다.
* **physical** -- vendor object 하나 (`incarnation`). 행은 create **전에**
  `CREATING` 으로 기록한다. destroy 는 확인된 뒤에만 `DESTROYED` 다.
* **snapshot** -- provider snapshot id 와 NEOS checksum. portable archive 가 아니다.

세 가지 fence 를 구별한다.

* `incarnation` / `stream_epoch` -- 옛 object 의 결과·스트림이 새 object 에 쓰지
  못하게 한다. 할당 `generation` 과 **다른 값**이다: 할당 generation 은 admission
  세대이고, Modal cold resume 은 generation 을 바꾸지 않고 incarnation 만 올린다.
* `RuntimeFence` -- 실행 lease (`coding_run_leases` 의 run/worker/fencing token).
  lease 를 잃은 옛 worker 는 revision 을 커밋하지 못한다.
* `version` -- lifecycle 쓰기의 CAS.

`InMemory*` 는 테스트용이다. 프로세스가 죽으면 사라지므로 production 에서 쓸 수
없다 -- factory 는 원장을 주입받지 못하면 거절한다.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol

from neos.coding.domain.durability import ExecutionLease
from neos.coding.managed.domain import ManagedSandboxAllocation, ManagedSandboxState
from neos.coding.sandbox.base import SandboxLimits, SandboxStateConflict


class RuntimeState(StrEnum):
    INTENT = "intent"
    RUNNING = "running"
    SUSPENDED = "suspended"
    QUARANTINED = "quarantined"
    FAILED = "failed"
    # 코딩 쪽이 놓았다. vendor object 정리는 할당 평면의 cleanup 이 한다.
    DETACHED = "detached"


class PhysicalState(StrEnum):
    CREATING = "creating"
    ACTIVE = "active"
    DESTROY_PENDING = "destroy_pending"
    DESTROYED = "destroyed"


class LedgerConflict(SandboxStateConflict):
    """fence / version / incarnation 대조 실패. 쓰기는 일어나지 않았다."""


RUNTIME_MUTABLE_FIELDS = frozenset(
    {
        "state",
        "workspace_revision",
        "stream_cursors",
        "resume_snapshot_ref",
        "resume_snapshot_expires_at",
        "error_code",
    }
)
PHYSICAL_MUTABLE_FIELDS = frozenset(
    {
        "provider_ref",
        "ref_index",
        "state",
        "destroy_requested_at",
        "destroy_confirmed_at",
    }
)
# 할당 원장에서 코딩 세션이 붙어도 되는 상태. cleanup 에 들어간 할당에는
# 붙지 않는다 -- 정리 중인 object 위에서 일하게 된다.
ATTACHABLE_ALLOCATION_STATES = frozenset({ManagedSandboxState.ACTIVE})


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


def _require_aware(name: str, value: datetime | None) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class RuntimeFence:
    """실행 lease 증명. `coding_run_leases` 행과 네 값이 모두 같아야 산다."""

    task_id: str
    run_id: str
    worker_id: str
    fencing_token: int

    @classmethod
    def from_lease(cls, lease: ExecutionLease) -> RuntimeFence:
        return cls(
            task_id=lease.task_id,
            run_id=lease.run_id,
            worker_id=lease.worker_id,
            fencing_token=lease.fencing_token,
        )


@dataclass(frozen=True, slots=True)
class RuntimeRecord:
    sandbox_id: str
    allocation_id: str
    allocation_generation: int
    tenant_id: str
    task_id: str
    owner_id: str
    provider: str
    image_digest: str
    sandboxd_digest: str
    profile: str
    network_policy: Mapping[str, Any]
    region: str
    limits: SandboxLimits
    expires_at: datetime
    state: RuntimeState
    incarnation: int
    stream_epoch: int
    workspace_revision: int
    version: int
    created_at: datetime
    updated_at: datetime
    source_snapshot_id: str | None = None
    resume_snapshot_ref: str | None = None
    resume_snapshot_expires_at: datetime | None = None
    stream_cursors: Mapping[str, int] = field(default_factory=dict)
    error_code: str | None = None

    def __post_init__(self) -> None:
        for name in ("allocation_generation", "incarnation", "stream_epoch", "version"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive")
        if self.workspace_revision < 0:
            raise ValueError("workspace revision must not be negative")
        for name in ("expires_at", "created_at", "updated_at", "resume_snapshot_expires_at"):
            _require_aware(name, getattr(self, name))
        if (self.resume_snapshot_ref is None) != (self.resume_snapshot_expires_at is None) and (
            self.resume_snapshot_ref is None
        ):
            raise ValueError("resume snapshot expiry needs a resume snapshot ref")
        object.__setattr__(self, "network_policy", MappingProxyType(dict(self.network_policy)))
        object.__setattr__(self, "stream_cursors", MappingProxyType(dict(self.stream_cursors)))


@dataclass(frozen=True, slots=True)
class PhysicalRecord:
    sandbox_id: str
    incarnation: int
    idempotency_key: str
    ownership_digest: str
    state: PhysicalState
    created_at: datetime
    updated_at: datetime
    provider_ref: str | None = None
    ref_index: str | None = None
    destroy_requested_at: datetime | None = None
    destroy_confirmed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.incarnation < 1:
            raise ValueError("incarnation must be positive")
        for name in ("created_at", "updated_at", "destroy_requested_at", "destroy_confirmed_at"):
            _require_aware(name, getattr(self, name))
        if (self.provider_ref is None) != (self.ref_index is None):
            raise ValueError("provider ref and its index go together")
        if (self.state is PhysicalState.DESTROYED) != (self.destroy_confirmed_at is not None):
            raise ValueError("destroyed state and destroy confirmation go together")
        if self.state is PhysicalState.DESTROY_PENDING and self.destroy_requested_at is None:
            raise ValueError("destroy_pending requires destroy_requested_at")
        if self.state is PhysicalState.ACTIVE and self.provider_ref is None:
            raise ValueError("an active physical object needs its provider ref")


@dataclass(frozen=True, slots=True)
class SnapshotRecord:
    snapshot_id: str
    sandbox_id: str
    allocation_id: str
    task_id: str
    incarnation: int
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


class CodingRuntimeLedger(Protocol):
    # ---- allocation plane (read-only here) --------------------------------
    async def allocation(self, allocation_id: str) -> ManagedSandboxAllocation | None: ...

    async def allocation_for_task(self, task_id: str) -> ManagedSandboxAllocation | None:
        """The one live (not cleaned/failed) allocation of a task, if any."""
        ...

    # ---- fence --------------------------------------------------------------
    async def validate_fence(self, fence: RuntimeFence, *, now: datetime) -> None: ...

    # ---- runtime --------------------------------------------------------------
    async def put_intent(self, record: RuntimeRecord) -> RuntimeRecord:
        """Insert an `INTENT` row. The same intent again returns the stored row;
        a different intent for the same allocation is a conflict."""
        ...

    async def get(self, sandbox_id: str) -> RuntimeRecord | None: ...

    async def get_by_allocation(self, allocation_id: str) -> RuntimeRecord | None: ...

    async def update(
        self,
        sandbox_id: str,
        *,
        incarnation: int,
        expected_version: int | None,
        changes: Mapping[str, Any],
        now: datetime,
    ) -> RuntimeRecord: ...

    async def commit_revision(
        self,
        sandbox_id: str,
        *,
        stream_epoch: int,
        revision: int,
        fence: RuntimeFence | None,
        now: datetime,
    ) -> RuntimeRecord: ...

    async def commit_cursor(
        self,
        sandbox_id: str,
        *,
        stream_epoch: int,
        stream: str,
        cursor: int,
        fence: RuntimeFence | None,
        now: datetime,
    ) -> RuntimeRecord: ...

    async def commit_incarnation(
        self,
        sandbox_id: str,
        *,
        expected_version: int,
        replacement: PhysicalRecord,
        allocation_ref_ciphertext: bytes,
        workspace_revision: int,
        now: datetime,
    ) -> RuntimeRecord:
        """Atomically: runtime moves to `replacement.incarnation` (stream epoch + 1,
        RUNNING); the replacement physical row becomes ACTIVE; the allocation's
        sealed `provider_ref` points at the replacement. Allocation `generation`
        does not change."""
        ...

    # ---- physical -------------------------------------------------------------
    async def put_physical(self, record: PhysicalRecord) -> PhysicalRecord | None:
        """Insert. None when (sandbox, incarnation) or the idempotency key exists."""
        ...

    async def get_physical(self, sandbox_id: str, incarnation: int) -> PhysicalRecord | None: ...

    async def list_physical(self, sandbox_id: str) -> tuple[PhysicalRecord, ...]: ...

    async def find_physical_by_ref_index(self, ref_index: str) -> PhysicalRecord | None: ...

    async def find_physical_by_idempotency_key(self, key: str) -> PhysicalRecord | None: ...

    async def update_physical(
        self,
        sandbox_id: str,
        incarnation: int,
        *,
        changes: Mapping[str, Any],
        now: datetime,
    ) -> PhysicalRecord: ...

    # ---- snapshots ------------------------------------------------------------
    async def put_snapshot(self, record: SnapshotRecord) -> None: ...

    async def get_snapshot(self, snapshot_id: str) -> SnapshotRecord | None: ...


def check_fields(changes: Mapping[str, Any], allowed: frozenset[str]) -> None:
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError(f"ledger field is immutable: {sorted(unknown)[0]}")


def apply_runtime_update(
    record: RuntimeRecord,
    *,
    incarnation: int,
    expected_version: int | None,
    changes: Mapping[str, Any],
    now: datetime,
) -> RuntimeRecord:
    """The shared incarnation/version fence. Raises before any write."""
    check_fields(changes, RUNTIME_MUTABLE_FIELDS)
    if record.incarnation != incarnation:
        raise LedgerConflict("ledger_incarnation_mismatch")
    if expected_version is not None and record.version != expected_version:
        raise LedgerConflict("ledger_version_conflict")
    if record.state is RuntimeState.DETACHED:
        raise LedgerConflict("ledger_sandbox_detached")
    return replace(record, **dict(changes), version=record.version + 1, updated_at=now)


def apply_physical_update(
    record: PhysicalRecord, *, changes: Mapping[str, Any], now: datetime
) -> PhysicalRecord:
    check_fields(changes, PHYSICAL_MUTABLE_FIELDS)
    if record.state is PhysicalState.DESTROYED:
        raise LedgerConflict("ledger_physical_destroyed")
    return replace(record, **dict(changes), updated_at=now)


def same_intent(stored: RuntimeRecord, candidate: RuntimeRecord) -> bool:
    keys = (
        "sandbox_id", "allocation_id", "allocation_generation", "tenant_id", "task_id",
        "owner_id", "provider", "image_digest", "sandboxd_digest", "profile", "region",
        "limits", "expires_at", "source_snapshot_id",
    )
    return all(getattr(stored, key) == getattr(candidate, key) for key in keys) and dict(
        stored.network_policy
    ) == dict(candidate.network_policy)


class InMemoryAllocationTable:
    """The allocation-plane rows the coding ledger reads, in memory.

    045 의 부분 유니크 인덱스를 그대로 흉내 낸다: 태스크당 살아 있는 할당은
    하나다. fake 가 이 제약을 풀면 테스트가 production 에서 불가능한 상태 위에서
    통과한다.
    """

    _DEAD = frozenset({ManagedSandboxState.CLEANED, ManagedSandboxState.FAILED})

    def __init__(self) -> None:
        self.rows: dict[str, ManagedSandboxAllocation] = {}

    def put(self, allocation: ManagedSandboxAllocation) -> None:
        if allocation.state not in self._DEAD:
            for row in self.rows.values():
                if (
                    row.task_id == allocation.task_id
                    and row.allocation_id != allocation.allocation_id
                    and row.state not in self._DEAD
                ):
                    raise LedgerConflict("allocation_live_for_task")
        self.rows[allocation.allocation_id] = allocation

    def live_for_task(self, task_id: str) -> ManagedSandboxAllocation | None:
        live = [
            row for row in self.rows.values()
            if row.task_id == task_id and row.state not in self._DEAD
        ]
        return live[0] if live else None


class InMemoryCodingRuntimeLedger:
    """Test ledger with the same fences as the SQL repository."""

    def __init__(
        self,
        allocations: InMemoryAllocationTable | None = None,
        *,
        lease_is_live: Callable[[RuntimeFence, datetime], bool] | None = None,
    ) -> None:
        self.allocations = allocations or InMemoryAllocationTable()
        # None: every fence is live. Tests that exercise lease loss pass a check.
        self._lease_is_live = lease_is_live or (lambda _fence, _now: True)
        self.runtimes: dict[str, RuntimeRecord] = {}
        self.physical: dict[tuple[str, int], PhysicalRecord] = {}
        self.snapshots: dict[str, SnapshotRecord] = {}
        self._lock = asyncio.Lock()

    # ---- allocation plane -------------------------------------------------------

    async def allocation(self, allocation_id: str) -> ManagedSandboxAllocation | None:
        return self.allocations.rows.get(allocation_id)

    async def allocation_for_task(self, task_id: str) -> ManagedSandboxAllocation | None:
        return self.allocations.live_for_task(task_id)

    # ---- fence -------------------------------------------------------------------

    async def validate_fence(self, fence: RuntimeFence, *, now: datetime) -> None:
        if not self._lease_is_live(fence, now):
            raise LedgerConflict("sandbox_fence_stale")

    # ---- runtime -----------------------------------------------------------------

    async def put_intent(self, record: RuntimeRecord) -> RuntimeRecord:
        if record.state is not RuntimeState.INTENT:
            raise ValueError("intent rows start in the intent state")
        async with self._lock:
            existing = self.runtimes.get(record.sandbox_id) or next(
                (row for row in self.runtimes.values() if row.allocation_id == record.allocation_id),
                None,
            )
            if existing is not None:
                if not same_intent(existing, record):
                    raise LedgerConflict("ledger_intent_conflict")
                return existing
            self.runtimes[record.sandbox_id] = record
            return record

    async def get(self, sandbox_id: str) -> RuntimeRecord | None:
        return self.runtimes.get(sandbox_id)

    async def get_by_allocation(self, allocation_id: str) -> RuntimeRecord | None:
        return next(
            (row for row in self.runtimes.values() if row.allocation_id == allocation_id), None
        )

    async def update(
        self,
        sandbox_id: str,
        *,
        incarnation: int,
        expected_version: int | None,
        changes: Mapping[str, Any],
        now: datetime,
    ) -> RuntimeRecord:
        async with self._lock:
            record = self._require(sandbox_id)
            updated = apply_runtime_update(
                record,
                incarnation=incarnation,
                expected_version=expected_version,
                changes=changes,
                now=now,
            )
            self.runtimes[sandbox_id] = updated
            return updated

    async def commit_revision(
        self,
        sandbox_id: str,
        *,
        stream_epoch: int,
        revision: int,
        fence: RuntimeFence | None,
        now: datetime,
    ) -> RuntimeRecord:
        async with self._lock:
            record = self._require_live_epoch(sandbox_id, stream_epoch, fence, now)
            if revision <= record.workspace_revision:
                return record
            updated = replace(
                record, workspace_revision=revision, version=record.version + 1, updated_at=now
            )
            self.runtimes[sandbox_id] = updated
            return updated

    async def commit_cursor(
        self,
        sandbox_id: str,
        *,
        stream_epoch: int,
        stream: str,
        cursor: int,
        fence: RuntimeFence | None,
        now: datetime,
    ) -> RuntimeRecord:
        async with self._lock:
            record = self._require_live_epoch(sandbox_id, stream_epoch, fence, now)
            if record.stream_cursors.get(stream, 0) >= cursor:
                return record
            cursors = dict(record.stream_cursors)
            cursors[stream] = cursor
            updated = replace(
                record, stream_cursors=cursors, version=record.version + 1, updated_at=now
            )
            self.runtimes[sandbox_id] = updated
            return updated

    async def commit_incarnation(
        self,
        sandbox_id: str,
        *,
        expected_version: int,
        replacement: PhysicalRecord,
        allocation_ref_ciphertext: bytes,
        workspace_revision: int,
        now: datetime,
    ) -> RuntimeRecord:
        async with self._lock:
            record = self._require(sandbox_id)
            if record.version != expected_version:
                raise LedgerConflict("ledger_version_conflict")
            if replacement.sandbox_id != sandbox_id or replacement.incarnation != record.incarnation + 1:
                raise LedgerConflict("ledger_incarnation_mismatch")
            if replacement.state is not PhysicalState.ACTIVE:
                raise ValueError("the replacement must be active")
            stored = self.physical.get((sandbox_id, replacement.incarnation))
            if stored is None or stored.idempotency_key != replacement.idempotency_key:
                raise LedgerConflict("ledger_physical_unrecorded")
            allocation = self.allocations.rows.get(record.allocation_id)
            if (
                allocation is None
                or allocation.state not in ATTACHABLE_ALLOCATION_STATES
                or allocation.generation != record.allocation_generation
            ):
                raise LedgerConflict("ledger_allocation_not_attachable")
            self.allocations.rows[allocation.allocation_id] = replace(
                allocation, provider_ref=allocation_ref_ciphertext, version=allocation.version + 1
            )
            self.physical[(sandbox_id, replacement.incarnation)] = replace(
                replacement, created_at=stored.created_at, updated_at=now
            )
            updated = replace(
                record,
                incarnation=replacement.incarnation,
                stream_epoch=record.stream_epoch + 1,
                state=RuntimeState.RUNNING,
                workspace_revision=max(record.workspace_revision, workspace_revision),
                resume_snapshot_ref=None,
                resume_snapshot_expires_at=None,
                error_code=None,
                version=record.version + 1,
                updated_at=now,
            )
            self.runtimes[sandbox_id] = updated
            return updated

    # ---- physical ----------------------------------------------------------------

    async def put_physical(self, record: PhysicalRecord) -> PhysicalRecord | None:
        async with self._lock:
            key = (record.sandbox_id, record.incarnation)
            if key in self.physical or any(
                row.idempotency_key == record.idempotency_key for row in self.physical.values()
            ):
                return None
            self.physical[key] = record
            return record

    async def get_physical(self, sandbox_id: str, incarnation: int) -> PhysicalRecord | None:
        return self.physical.get((sandbox_id, incarnation))

    async def list_physical(self, sandbox_id: str) -> tuple[PhysicalRecord, ...]:
        return tuple(
            sorted(
                (row for (owner, _), row in self.physical.items() if owner == sandbox_id),
                key=lambda row: row.incarnation,
            )
        )

    async def find_physical_by_ref_index(self, ref_index: str) -> PhysicalRecord | None:
        return next((row for row in self.physical.values() if row.ref_index == ref_index), None)

    async def find_physical_by_idempotency_key(self, key: str) -> PhysicalRecord | None:
        return next((row for row in self.physical.values() if row.idempotency_key == key), None)

    async def update_physical(
        self,
        sandbox_id: str,
        incarnation: int,
        *,
        changes: Mapping[str, Any],
        now: datetime,
    ) -> PhysicalRecord:
        async with self._lock:
            record = self.physical.get((sandbox_id, incarnation))
            if record is None:
                raise LedgerConflict("ledger_physical_missing")
            updated = apply_physical_update(record, changes=changes, now=now)
            if updated.ref_index is not None and any(
                row.ref_index == updated.ref_index and key != (sandbox_id, incarnation)
                for key, row in self.physical.items()
            ):
                raise LedgerConflict("ledger_ref_index_conflict")
            self.physical[(sandbox_id, incarnation)] = updated
            return updated

    # ---- snapshots ---------------------------------------------------------------

    async def put_snapshot(self, record: SnapshotRecord) -> None:
        async with self._lock:
            existing = self.snapshots.get(record.snapshot_id)
            if existing is not None and existing != record:
                raise LedgerConflict("ledger_snapshot_conflict")
            self.snapshots[record.snapshot_id] = record

    async def get_snapshot(self, snapshot_id: str) -> SnapshotRecord | None:
        return self.snapshots.get(snapshot_id)

    # ---- helpers -------------------------------------------------------------------

    def _require(self, sandbox_id: str) -> RuntimeRecord:
        record = self.runtimes.get(sandbox_id)
        if record is None:
            raise LedgerConflict("ledger_sandbox_missing")
        return record

    def _require_live_epoch(
        self,
        sandbox_id: str,
        stream_epoch: int,
        fence: RuntimeFence | None,
        now: datetime,
    ) -> RuntimeRecord:
        record = self._require(sandbox_id)
        if record.stream_epoch != stream_epoch:
            raise LedgerConflict("stream_generation_changed")
        if record.state is not RuntimeState.RUNNING:
            raise LedgerConflict("ledger_sandbox_not_running")
        if fence is not None:
            if fence.task_id != record.task_id or not self._lease_is_live(fence, now):
                raise LedgerConflict("sandbox_fence_stale")
        return record

"""PostgreSQL implementation of the coding runtime ledger (migration 057).

provider 참조와 snapshot 참조는 AES-GCM 으로 봉인한 BYTEA 로만 저장한다
(`neos.coding.managed.crypto`). AAD 에 sandbox_id 와 incarnation 을 묶으므로 한
object 의 봉인을 다른 incarnation 이나 다른 샌드박스 행에 옮겨 붙이면 복호화가
실패한다. ref 로 행을 찾는 곳은 키 있는 `ref_index` 를 쓴다.

모든 쓰기는 `SELECT ... FOR UPDATE` 로 행을 잠근 뒤 in-memory 원장과 **같은**
fence 함수(`apply_runtime_update` / `apply_physical_update`)를 적용한다. 두 구현이
대조 규칙을 각자 들고 있으면 언젠가 갈라진다.

실행 lease fence 는 `coding_run_leases` 행을 `FOR SHARE` 로 읽는다 -- 커밋이 끝날
때까지 다른 worker 가 lease 를 가져가지 못한다.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import text

from neos.coding.managed.crypto import (
    AesGcmProviderReferenceCipher,
    ProviderReferenceCipherError,
)
from neos.coding.managed.domain import ManagedSandboxAllocation, ManagedSandboxState
from neos.coding.managed.repository import _allocation_from_row
from neos.coding.persistence.postgres import SessionFactory
from neos.coding.sandbox.base import SandboxUnavailable
from neos.coding.sandbox.managed.ledger import (
    ATTACHABLE_ALLOCATION_STATES,
    LedgerConflict,
    PhysicalRecord,
    PhysicalState,
    RuntimeFence,
    RuntimeRecord,
    RuntimeState,
    SnapshotRecord,
    apply_physical_update,
    apply_runtime_update,
    limits_from_record,
    limits_to_record,
    same_intent,
)

_RUNTIME_COLUMNS = (
    "sandbox_id, allocation_id, allocation_generation, tenant_id, task_id, owner_id, "
    "provider, image_digest, sandboxd_digest, profile, network_policy, region, limits, "
    "expires_at, state, incarnation, stream_epoch, workspace_revision, stream_cursors, "
    "source_snapshot_id, resume_snapshot_ref, resume_snapshot_expires_at, error_code, "
    "version, created_at, updated_at"
)
_PHYSICAL_COLUMNS = (
    "sandbox_id, incarnation, idempotency_key, ownership_digest, provider_ref, ref_index, "
    "state, created_at, updated_at, destroy_requested_at, destroy_confirmed_at"
)
_SNAPSHOT_COLUMNS = (
    "snapshot_id, sandbox_id, allocation_id, task_id, incarnation, provider, "
    "provider_snapshot_ref, workspace_revision, content_checksum, image_digest, profile, "
    "region, limits, created_at, expires_at"
)
_ALLOCATION_COLUMNS = (
    "allocation_id, tenant_id, task_id, run_id, provider, region, provider_ref, "
    "ownership_digest, state, generation, fencing_token, lease_expires_at, "
    "absolute_expires_at, version, error_code, snapshot_ref, archive_ref, image_identity"
)
_JSON_COLUMNS = frozenset({"network_policy", "limits", "stream_cursors"})
_DEAD_ALLOCATION_STATES = (ManagedSandboxState.CLEANED.value, ManagedSandboxState.FAILED.value)


def _json(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, (str, bytes, bytearray)):
        return json.loads(value)
    raise SandboxUnavailable("managed_ledger_row_invalid")


def _names(columns: str) -> list[str]:
    return [name.strip() for name in columns.split(",")]


def _values(columns: str) -> str:
    return ", ".join(
        f"CAST(:{name} AS JSONB)" if name in _JSON_COLUMNS else f":{name}"
        for name in _names(columns)
    )


class PostgresCodingRuntimeLedger:
    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        reference_key: bytes,
        key_version: int,
    ) -> None:
        self._session_factory = session_factory
        self._reference_key = reference_key
        self._key_version = key_version

    # ---- sealing ---------------------------------------------------------

    def _cipher(self, associated_data: str) -> AesGcmProviderReferenceCipher:
        return AesGcmProviderReferenceCipher(
            key=self._reference_key,
            key_version=self._key_version,
            associated_data=associated_data,
        )

    @staticmethod
    def _physical_aad(sandbox_id: str, incarnation: int) -> str:
        return f"coding-physical:{sandbox_id}:{incarnation}"

    @staticmethod
    def _resume_aad(sandbox_id: str, incarnation: int) -> str:
        return f"coding-runtime-resume:{sandbox_id}:{incarnation}"

    @staticmethod
    def _snapshot_aad(snapshot_id: str) -> str:
        return f"coding-runtime-snapshot:{snapshot_id}"

    def _seal(self, value: str | None, aad: str) -> bytes | None:
        return None if value is None else self._cipher(aad).encrypt(value)

    def _open(self, value: bytes | memoryview | None, aad: str) -> str | None:
        if value is None:
            return None
        try:
            return self._cipher(aad).decrypt(bytes(value))
        except ProviderReferenceCipherError as error:
            # The seal does not belong to this row / incarnation. Do not guess.
            raise SandboxUnavailable("managed_ledger_reference_unverifiable") from error

    # ---- row mapping -----------------------------------------------------

    def _runtime_params(self, record: RuntimeRecord) -> dict[str, Any]:
        return {
            "sandbox_id": record.sandbox_id,
            "allocation_id": record.allocation_id,
            "allocation_generation": record.allocation_generation,
            "tenant_id": record.tenant_id,
            "task_id": record.task_id,
            "owner_id": record.owner_id,
            "provider": record.provider,
            "image_digest": record.image_digest,
            "sandboxd_digest": record.sandboxd_digest,
            "profile": record.profile,
            "network_policy": json.dumps(dict(record.network_policy), sort_keys=True),
            "region": record.region,
            "limits": json.dumps(limits_to_record(record.limits), sort_keys=True),
            "expires_at": record.expires_at,
            "state": record.state.value,
            "incarnation": record.incarnation,
            "stream_epoch": record.stream_epoch,
            "workspace_revision": record.workspace_revision,
            "stream_cursors": json.dumps(dict(record.stream_cursors), sort_keys=True),
            "source_snapshot_id": record.source_snapshot_id,
            "resume_snapshot_ref": self._seal(
                record.resume_snapshot_ref,
                self._resume_aad(record.sandbox_id, record.incarnation),
            ),
            "resume_snapshot_expires_at": record.resume_snapshot_expires_at,
            "error_code": record.error_code,
            "version": record.version,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    def _runtime(self, row: Any) -> RuntimeRecord:
        try:
            return RuntimeRecord(
                sandbox_id=row.sandbox_id,
                allocation_id=row.allocation_id,
                allocation_generation=row.allocation_generation,
                tenant_id=row.tenant_id,
                task_id=row.task_id,
                owner_id=row.owner_id,
                provider=row.provider,
                image_digest=row.image_digest,
                sandboxd_digest=row.sandboxd_digest,
                profile=row.profile,
                network_policy=_json(row.network_policy),
                region=row.region,
                limits=limits_from_record(_json(row.limits)),
                expires_at=row.expires_at,
                state=RuntimeState(row.state),
                incarnation=row.incarnation,
                stream_epoch=row.stream_epoch,
                workspace_revision=row.workspace_revision,
                stream_cursors=_json(row.stream_cursors),
                source_snapshot_id=row.source_snapshot_id,
                resume_snapshot_ref=self._open(
                    row.resume_snapshot_ref, self._resume_aad(row.sandbox_id, row.incarnation)
                ),
                resume_snapshot_expires_at=row.resume_snapshot_expires_at,
                error_code=row.error_code,
                version=row.version,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise SandboxUnavailable("managed_ledger_row_invalid") from error

    def _physical_params(self, record: PhysicalRecord) -> dict[str, Any]:
        return {
            "sandbox_id": record.sandbox_id,
            "incarnation": record.incarnation,
            "idempotency_key": record.idempotency_key,
            "ownership_digest": record.ownership_digest,
            "provider_ref": self._seal(
                record.provider_ref, self._physical_aad(record.sandbox_id, record.incarnation)
            ),
            "ref_index": record.ref_index,
            "state": record.state.value,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "destroy_requested_at": record.destroy_requested_at,
            "destroy_confirmed_at": record.destroy_confirmed_at,
        }

    def _physical(self, row: Any) -> PhysicalRecord:
        try:
            return PhysicalRecord(
                sandbox_id=row.sandbox_id,
                incarnation=row.incarnation,
                idempotency_key=row.idempotency_key,
                ownership_digest=row.ownership_digest,
                provider_ref=self._open(
                    row.provider_ref, self._physical_aad(row.sandbox_id, row.incarnation)
                ),
                ref_index=row.ref_index,
                state=PhysicalState(row.state),
                created_at=row.created_at,
                updated_at=row.updated_at,
                destroy_requested_at=row.destroy_requested_at,
                destroy_confirmed_at=row.destroy_confirmed_at,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise SandboxUnavailable("managed_ledger_row_invalid") from error

    async def _fetch_one(self, sql: str, params: Mapping[str, Any]) -> Any:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(text(sql), dict(params))
                return result.first()

    async def _fetch_all(self, sql: str, params: Mapping[str, Any]) -> list[Any]:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(text(sql), dict(params))
                return list(result.all())

    # ---- allocation plane (read-only) ----------------------------------------

    async def allocation(self, allocation_id: str) -> ManagedSandboxAllocation | None:
        row = await self._fetch_one(
            f"SELECT {_ALLOCATION_COLUMNS} FROM coding_managed_sandboxes "
            "WHERE allocation_id = :allocation_id",
            {"allocation_id": allocation_id},
        )
        return None if row is None else _allocation_from_row(row)

    async def allocation_for_task(self, task_id: str) -> ManagedSandboxAllocation | None:
        row = await self._fetch_one(
            f"SELECT {_ALLOCATION_COLUMNS} FROM coding_managed_sandboxes "
            "WHERE task_id = :task_id AND cleaned_at IS NULL "
            "AND state <> ALL(CAST(:dead_states AS VARCHAR[])) "
            "ORDER BY generation DESC LIMIT 1",
            {"task_id": task_id, "dead_states": list(_DEAD_ALLOCATION_STATES)},
        )
        return None if row is None else _allocation_from_row(row)

    # ---- fence -------------------------------------------------------------------

    @staticmethod
    async def _lease_is_live(session, fence: RuntimeFence, now: datetime) -> bool:
        result = await session.execute(
            text(
                "SELECT 1 AS live FROM coding_run_leases "
                "WHERE task_id = :task_id AND run_id = :run_id "
                "AND worker_id = :worker_id AND fencing_token = :fencing_token "
                "AND expires_at > :now FOR SHARE"
            ),
            {
                "task_id": fence.task_id,
                "run_id": fence.run_id,
                "worker_id": fence.worker_id,
                "fencing_token": fence.fencing_token,
                "now": now,
            },
        )
        return result.first() is not None

    async def validate_fence(self, fence: RuntimeFence, *, now: datetime) -> None:
        async with await self._session_factory() as session:
            async with session.begin():
                if not await self._lease_is_live(session, fence, now):
                    raise LedgerConflict("sandbox_fence_stale")

    # ---- runtime -----------------------------------------------------------------

    async def put_intent(self, record: RuntimeRecord) -> RuntimeRecord:
        if record.state is not RuntimeState.INTENT:
            raise ValueError("intent rows start in the intent state")
        row = await self._fetch_one(
            f"INSERT INTO coding_managed_runtime ({_RUNTIME_COLUMNS}) "
            f"VALUES ({_values(_RUNTIME_COLUMNS)}) ON CONFLICT DO NOTHING "
            "RETURNING sandbox_id",
            self._runtime_params(record),
        )
        if row is not None:
            return record
        existing = await self.get_by_allocation(record.allocation_id) or await self.get(
            record.sandbox_id
        )
        if existing is None or not same_intent(existing, record):
            raise LedgerConflict("ledger_intent_conflict")
        return existing

    async def get(self, sandbox_id: str) -> RuntimeRecord | None:
        row = await self._fetch_one(
            f"SELECT {_RUNTIME_COLUMNS} FROM coding_managed_runtime WHERE sandbox_id = :sandbox_id",
            {"sandbox_id": sandbox_id},
        )
        return None if row is None else self._runtime(row)

    async def get_by_allocation(self, allocation_id: str) -> RuntimeRecord | None:
        row = await self._fetch_one(
            f"SELECT {_RUNTIME_COLUMNS} FROM coding_managed_runtime "
            "WHERE allocation_id = :allocation_id",
            {"allocation_id": allocation_id},
        )
        return None if row is None else self._runtime(row)

    async def _lock_runtime(self, session, sandbox_id: str) -> RuntimeRecord:
        result = await session.execute(
            text(
                f"SELECT {_RUNTIME_COLUMNS} FROM coding_managed_runtime "
                "WHERE sandbox_id = :sandbox_id FOR UPDATE"
            ),
            {"sandbox_id": sandbox_id},
        )
        row = result.first()
        if row is None:
            raise LedgerConflict("ledger_sandbox_missing")
        return self._runtime(row)

    async def _write_runtime(self, session, updated: RuntimeRecord, previous_version: int) -> None:
        params = self._runtime_params(updated)
        params["previous_version"] = previous_version
        written = await session.execute(
            text(
                "UPDATE coding_managed_runtime SET "
                "state = :state, workspace_revision = :workspace_revision, "
                "stream_cursors = CAST(:stream_cursors AS JSONB), "
                "resume_snapshot_ref = :resume_snapshot_ref, "
                "resume_snapshot_expires_at = :resume_snapshot_expires_at, "
                "error_code = :error_code, version = :version, updated_at = :updated_at "
                "WHERE sandbox_id = :sandbox_id AND version = :previous_version "
                "RETURNING sandbox_id"
            ),
            params,
        )
        if written.first() is None:
            raise LedgerConflict("ledger_version_conflict")

    async def update(
        self,
        sandbox_id: str,
        *,
        incarnation: int,
        expected_version: int | None,
        changes: Mapping[str, Any],
        now: datetime,
    ) -> RuntimeRecord:
        async with await self._session_factory() as session:
            async with session.begin():
                current = await self._lock_runtime(session, sandbox_id)
                updated = apply_runtime_update(
                    current,
                    incarnation=incarnation,
                    expected_version=expected_version,
                    changes=changes,
                    now=now,
                )
                await self._write_runtime(session, updated, current.version)
        return updated

    async def _live_epoch(
        self,
        session,
        sandbox_id: str,
        stream_epoch: int,
        fence: RuntimeFence | None,
        now: datetime,
    ) -> RuntimeRecord:
        current = await self._lock_runtime(session, sandbox_id)
        if current.stream_epoch != stream_epoch:
            raise LedgerConflict("stream_generation_changed")
        if current.state is not RuntimeState.RUNNING:
            raise LedgerConflict("ledger_sandbox_not_running")
        if fence is not None and (
            fence.task_id != current.task_id or not await self._lease_is_live(session, fence, now)
        ):
            raise LedgerConflict("sandbox_fence_stale")
        return current

    async def commit_revision(
        self,
        sandbox_id: str,
        *,
        stream_epoch: int,
        revision: int,
        fence: RuntimeFence | None,
        now: datetime,
    ) -> RuntimeRecord:
        async with await self._session_factory() as session:
            async with session.begin():
                current = await self._live_epoch(session, sandbox_id, stream_epoch, fence, now)
                if revision <= current.workspace_revision:
                    return current
                updated = RuntimeRecord(
                    **{
                        **_record_fields(current),
                        "workspace_revision": revision,
                        "version": current.version + 1,
                        "updated_at": now,
                    }
                )
                await self._write_runtime(session, updated, current.version)
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
        async with await self._session_factory() as session:
            async with session.begin():
                current = await self._live_epoch(session, sandbox_id, stream_epoch, fence, now)
                if current.stream_cursors.get(stream, 0) >= cursor:
                    return current
                cursors = dict(current.stream_cursors)
                cursors[stream] = cursor
                updated = RuntimeRecord(
                    **{
                        **_record_fields(current),
                        "stream_cursors": cursors,
                        "version": current.version + 1,
                        "updated_at": now,
                    }
                )
                await self._write_runtime(session, updated, current.version)
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
        if replacement.state is not PhysicalState.ACTIVE or replacement.provider_ref is None:
            raise ValueError("the replacement must be active with its provider ref")
        async with await self._session_factory() as session:
            async with session.begin():
                located = (
                    await session.execute(
                        text(
                            "SELECT allocation_id FROM coding_managed_runtime "
                            "WHERE sandbox_id = :sandbox_id"
                        ),
                        {"sandbox_id": sandbox_id},
                    )
                ).first()
                if located is None:
                    raise LedgerConflict("ledger_sandbox_missing")
                # Lock order is allocation -> runtime -> physical everywhere.
                allocation_row = (
                    await session.execute(
                        text(
                            f"SELECT {_ALLOCATION_COLUMNS} FROM coding_managed_sandboxes "
                            "WHERE allocation_id = :allocation_id FOR UPDATE"
                        ),
                        {"allocation_id": located.allocation_id},
                    )
                ).first()
                current = await self._lock_runtime(session, sandbox_id)
                if current.version != expected_version:
                    raise LedgerConflict("ledger_version_conflict")
                if (
                    replacement.sandbox_id != sandbox_id
                    or replacement.incarnation != current.incarnation + 1
                ):
                    raise LedgerConflict("ledger_incarnation_mismatch")
                allocation = None if allocation_row is None else _allocation_from_row(allocation_row)
                if (
                    allocation is None
                    or allocation.allocation_id != current.allocation_id
                    or allocation.state not in ATTACHABLE_ALLOCATION_STATES
                    or allocation.generation != current.allocation_generation
                ):
                    raise LedgerConflict("ledger_allocation_not_attachable")
                physical = await session.execute(
                    text(
                        "UPDATE coding_managed_physical_objects SET "
                        "provider_ref = :provider_ref, ref_index = :ref_index, "
                        "state = 'active', updated_at = :now "
                        "WHERE sandbox_id = :sandbox_id AND incarnation = :incarnation "
                        "AND idempotency_key = :idempotency_key AND state = 'creating' "
                        "RETURNING sandbox_id"
                    ),
                    {
                        "provider_ref": self._seal(
                            replacement.provider_ref,
                            self._physical_aad(sandbox_id, replacement.incarnation),
                        ),
                        "ref_index": replacement.ref_index,
                        "now": now,
                        "sandbox_id": sandbox_id,
                        "incarnation": replacement.incarnation,
                        "idempotency_key": replacement.idempotency_key,
                    },
                )
                if physical.first() is None:
                    raise LedgerConflict("ledger_physical_unrecorded")
                runtime_row = (
                    await session.execute(
                        text(
                            "UPDATE coding_managed_runtime SET "
                            "incarnation = :incarnation, stream_epoch = stream_epoch + 1, "
                            "state = 'running', "
                            "workspace_revision = GREATEST(workspace_revision, :workspace_revision), "
                            "resume_snapshot_ref = NULL, resume_snapshot_expires_at = NULL, "
                            "error_code = NULL, version = version + 1, updated_at = :now "
                            "WHERE sandbox_id = :sandbox_id AND version = :expected_version "
                            f"RETURNING {_RUNTIME_COLUMNS}"
                        ),
                        {
                            "incarnation": replacement.incarnation,
                            "workspace_revision": workspace_revision,
                            "now": now,
                            "sandbox_id": sandbox_id,
                            "expected_version": expected_version,
                        },
                    )
                ).first()
                if runtime_row is None:
                    raise LedgerConflict("ledger_version_conflict")
                moved = await session.execute(
                    text(
                        "UPDATE coding_managed_sandboxes SET provider_ref = :provider_ref, "
                        "version = version + 1, updated_at = :now "
                        "WHERE allocation_id = :allocation_id AND generation = :generation "
                        "AND state = :active RETURNING allocation_id"
                    ),
                    {
                        "provider_ref": allocation_ref_ciphertext,
                        "now": now,
                        "allocation_id": current.allocation_id,
                        "generation": current.allocation_generation,
                        "active": ManagedSandboxState.ACTIVE.value,
                    },
                )
                if moved.first() is None:
                    raise LedgerConflict("ledger_allocation_not_attachable")
        return self._runtime(runtime_row)

    # ---- physical ----------------------------------------------------------------

    async def put_physical(self, record: PhysicalRecord) -> PhysicalRecord | None:
        row = await self._fetch_one(
            f"INSERT INTO coding_managed_physical_objects ({_PHYSICAL_COLUMNS}) "
            f"VALUES ({_values(_PHYSICAL_COLUMNS)}) ON CONFLICT DO NOTHING "
            "RETURNING sandbox_id",
            self._physical_params(record),
        )
        return record if row is not None else None

    async def get_physical(self, sandbox_id: str, incarnation: int) -> PhysicalRecord | None:
        row = await self._fetch_one(
            f"SELECT {_PHYSICAL_COLUMNS} FROM coding_managed_physical_objects "
            "WHERE sandbox_id = :sandbox_id AND incarnation = :incarnation",
            {"sandbox_id": sandbox_id, "incarnation": incarnation},
        )
        return None if row is None else self._physical(row)

    async def list_physical(self, sandbox_id: str) -> tuple[PhysicalRecord, ...]:
        rows = await self._fetch_all(
            f"SELECT {_PHYSICAL_COLUMNS} FROM coding_managed_physical_objects "
            "WHERE sandbox_id = :sandbox_id ORDER BY incarnation",
            {"sandbox_id": sandbox_id},
        )
        return tuple(self._physical(row) for row in rows)

    async def find_physical_by_ref_index(self, ref_index: str) -> PhysicalRecord | None:
        row = await self._fetch_one(
            f"SELECT {_PHYSICAL_COLUMNS} FROM coding_managed_physical_objects "
            "WHERE ref_index = :ref_index",
            {"ref_index": ref_index},
        )
        return None if row is None else self._physical(row)

    async def find_physical_by_idempotency_key(self, key: str) -> PhysicalRecord | None:
        row = await self._fetch_one(
            f"SELECT {_PHYSICAL_COLUMNS} FROM coding_managed_physical_objects "
            "WHERE idempotency_key = :idempotency_key",
            {"idempotency_key": key},
        )
        return None if row is None else self._physical(row)

    async def update_physical(
        self,
        sandbox_id: str,
        incarnation: int,
        *,
        changes: Mapping[str, Any],
        now: datetime,
    ) -> PhysicalRecord:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        f"SELECT {_PHYSICAL_COLUMNS} FROM coding_managed_physical_objects "
                        "WHERE sandbox_id = :sandbox_id AND incarnation = :incarnation "
                        "FOR UPDATE"
                    ),
                    {"sandbox_id": sandbox_id, "incarnation": incarnation},
                )
                row = result.first()
                if row is None:
                    raise LedgerConflict("ledger_physical_missing")
                updated = apply_physical_update(self._physical(row), changes=changes, now=now)
                await session.execute(
                    text(
                        "UPDATE coding_managed_physical_objects SET "
                        "provider_ref = :provider_ref, ref_index = :ref_index, "
                        "state = :state, updated_at = :updated_at, "
                        "destroy_requested_at = :destroy_requested_at, "
                        "destroy_confirmed_at = :destroy_confirmed_at "
                        "WHERE sandbox_id = :sandbox_id AND incarnation = :incarnation"
                    ),
                    self._physical_params(updated),
                )
        return updated

    # ---- snapshots ---------------------------------------------------------------

    async def put_snapshot(self, record: SnapshotRecord) -> None:
        row = await self._fetch_one(
            f"INSERT INTO coding_managed_runtime_snapshots ({_SNAPSHOT_COLUMNS}) "
            f"VALUES ({_values(_SNAPSHOT_COLUMNS)}) "
            "ON CONFLICT (snapshot_id) DO NOTHING RETURNING snapshot_id",
            {
                "snapshot_id": record.snapshot_id,
                "sandbox_id": record.sandbox_id,
                "allocation_id": record.allocation_id,
                "task_id": record.task_id,
                "incarnation": record.incarnation,
                "provider": record.provider,
                "provider_snapshot_ref": self._cipher(
                    self._snapshot_aad(record.snapshot_id)
                ).encrypt(record.provider_snapshot_ref),
                "workspace_revision": record.workspace_revision,
                "content_checksum": record.content_checksum,
                "image_digest": record.image_digest,
                "profile": record.profile,
                "region": record.region,
                "limits": json.dumps(limits_to_record(record.limits), sort_keys=True),
                "created_at": record.created_at,
                "expires_at": record.expires_at,
            },
        )
        if row is None:
            existing = await self.get_snapshot(record.snapshot_id)
            if existing != record:
                raise LedgerConflict("ledger_snapshot_conflict")

    async def get_snapshot(self, snapshot_id: str) -> SnapshotRecord | None:
        row = await self._fetch_one(
            f"SELECT {_SNAPSHOT_COLUMNS} FROM coding_managed_runtime_snapshots "
            "WHERE snapshot_id = :snapshot_id",
            {"snapshot_id": snapshot_id},
        )
        if row is None:
            return None
        try:
            return SnapshotRecord(
                snapshot_id=row.snapshot_id,
                sandbox_id=row.sandbox_id,
                allocation_id=row.allocation_id,
                task_id=row.task_id,
                incarnation=row.incarnation,
                provider=row.provider,
                provider_snapshot_ref=self._open(
                    row.provider_snapshot_ref, self._snapshot_aad(row.snapshot_id)
                )
                or "",
                workspace_revision=row.workspace_revision,
                content_checksum=row.content_checksum,
                image_digest=row.image_digest,
                profile=row.profile,
                region=row.region,
                limits=limits_from_record(_json(row.limits)),
                created_at=row.created_at,
                expires_at=row.expires_at,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise SandboxUnavailable("managed_ledger_row_invalid") from error


def _record_fields(record: RuntimeRecord) -> dict[str, Any]:
    return {name: getattr(record, name) for name in RuntimeRecord.__dataclass_fields__}

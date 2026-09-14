"""PostgreSQL implementation of the coding sandbox ledger (migration 057).

provider 참조와 resume/snapshot 참조는 AES-GCM으로 봉인한 BYTEA로만 저장한다
(`neos.coding.managed.crypto`). AAD에 sandbox_id와 generation을 묶으므로 한
generation의 봉인을 다른 generation이나 다른 샌드박스 행에 옮겨 붙이면 복호화가
실패한다.

`update()`는 `SELECT ... FOR UPDATE`로 행을 잠근 뒤 in-memory 원장과 **같은**
`apply_update` fence(owner / generation / version)를 적용하고, 그 결과만 쓴다.
두 구현이 대조 규칙을 각자 들고 있으면 언젠가 갈라진다.
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
from neos.coding.persistence.postgres import SessionFactory
from neos.coding.sandbox.base import SandboxUnavailable
from neos.coding.sandbox.managed.ledger import (
    LedgerConflict,
    LedgerState,
    SandboxLedgerRecord,
    SnapshotLedgerRecord,
    apply_update,
    check_changes,
    limits_from_record,
    limits_to_record,
)

_COLUMNS = (
    "sandbox_id, owner_id, task_id, ordinal, generation, allocation_id, "
    "idempotency_key, ownership_digest, provider, provider_ref, image_digest, "
    "sandboxd_digest, profile, network_policy, region, limits, state, "
    "source_snapshot_id, resume_snapshot_ref, resume_snapshot_expires_at, "
    "workspace_revision, stream_cursors, error_code, expires_at, version, "
    "created_at, updated_at, destroy_requested_at, destroy_confirmed_at"
)
_SNAPSHOT_COLUMNS = (
    "snapshot_id, sandbox_id, owner_id, generation, provider, "
    "provider_snapshot_ref, workspace_revision, content_checksum, image_digest, "
    "profile, region, limits, created_at, expires_at"
)


def _json(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, (str, bytes, bytearray)):
        return json.loads(value)
    raise SandboxUnavailable("managed_ledger_row_invalid")


class PostgresSandboxLedger:
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
    def _ref_aad(sandbox_id: str, generation: int, kind: str) -> str:
        return f"coding-sandbox-ledger:{kind}:{sandbox_id}:{generation}"

    def _seal(self, value: str | None, aad: str) -> bytes | None:
        return None if value is None else self._cipher(aad).encrypt(value)

    def _open(self, value: bytes | memoryview | None, aad: str) -> str | None:
        if value is None:
            return None
        try:
            return self._cipher(aad).decrypt(bytes(value))
        except ProviderReferenceCipherError as error:
            # 봉인이 이 행/세대의 것이 아니다. 조용히 넘기지 않는다.
            raise SandboxUnavailable("managed_ledger_reference_unverifiable") from error

    # ---- row mapping -----------------------------------------------------

    def _params(self, record: SandboxLedgerRecord) -> dict[str, Any]:
        return {
            "sandbox_id": record.sandbox_id,
            "owner_id": record.owner_id,
            "task_id": record.task_id,
            "ordinal": record.ordinal,
            "generation": record.generation,
            "allocation_id": record.allocation_id,
            "idempotency_key": record.idempotency_key,
            "ownership_digest": record.ownership_digest,
            "provider": record.provider,
            "provider_ref": self._seal(
                record.provider_ref,
                self._ref_aad(record.sandbox_id, record.generation, "provider"),
            ),
            "image_digest": record.image_digest,
            "sandboxd_digest": record.sandboxd_digest,
            "profile": record.profile,
            "network_policy": json.dumps(dict(record.network_policy), sort_keys=True),
            "region": record.region,
            "limits": json.dumps(limits_to_record(record.limits), sort_keys=True),
            "state": record.state.value,
            "source_snapshot_id": record.source_snapshot_id,
            "resume_snapshot_ref": self._seal(
                record.resume_snapshot_ref,
                self._ref_aad(record.sandbox_id, record.generation, "resume"),
            ),
            "resume_snapshot_expires_at": record.resume_snapshot_expires_at,
            "workspace_revision": record.workspace_revision,
            "stream_cursors": json.dumps(dict(record.stream_cursors), sort_keys=True),
            "error_code": record.error_code,
            "expires_at": record.expires_at,
            "version": record.version,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "destroy_requested_at": record.destroy_requested_at,
            "destroy_confirmed_at": record.destroy_confirmed_at,
        }

    def _record(self, row: Any) -> SandboxLedgerRecord:
        try:
            return SandboxLedgerRecord(
                sandbox_id=row.sandbox_id,
                owner_id=row.owner_id,
                task_id=row.task_id,
                ordinal=row.ordinal,
                generation=row.generation,
                allocation_id=row.allocation_id,
                idempotency_key=row.idempotency_key,
                ownership_digest=row.ownership_digest,
                provider=row.provider,
                provider_ref=self._open(
                    row.provider_ref,
                    self._ref_aad(row.sandbox_id, row.generation, "provider"),
                ),
                image_digest=row.image_digest,
                sandboxd_digest=row.sandboxd_digest,
                profile=row.profile,
                network_policy=_json(row.network_policy),
                region=row.region,
                limits=limits_from_record(_json(row.limits)),
                state=LedgerState(row.state),
                source_snapshot_id=row.source_snapshot_id,
                resume_snapshot_ref=self._open(
                    row.resume_snapshot_ref,
                    self._ref_aad(row.sandbox_id, row.generation, "resume"),
                ),
                resume_snapshot_expires_at=row.resume_snapshot_expires_at,
                workspace_revision=row.workspace_revision,
                stream_cursors=_json(row.stream_cursors),
                error_code=row.error_code,
                expires_at=row.expires_at,
                version=row.version,
                created_at=row.created_at,
                updated_at=row.updated_at,
                destroy_requested_at=row.destroy_requested_at,
                destroy_confirmed_at=row.destroy_confirmed_at,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise SandboxUnavailable("managed_ledger_row_invalid") from error

    # ---- ledger ----------------------------------------------------------

    async def max_ordinal(self, *, owner_id: str, task_id: str) -> int:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        "SELECT COALESCE(MAX(ordinal), 0) AS ordinal "
                        "FROM coding_sandbox_ledger "
                        "WHERE owner_id = :owner_id AND task_id = :task_id"
                    ),
                    {"owner_id": owner_id, "task_id": task_id},
                )
                row = result.first()
        return 0 if row is None else int(row.ordinal)

    async def reserve(self, record: SandboxLedgerRecord) -> SandboxLedgerRecord | None:
        names = [name.strip() for name in _COLUMNS.split(",")]
        values = ", ".join(
            f"CAST(:{name} AS JSONB)"
            if name in {"network_policy", "limits", "stream_cursors"}
            else f":{name}"
            for name in names
        )
        async with await self._session_factory() as session:
            async with session.begin():
                # 어떤 unique 위반이든 (sandbox_id / allocation / idempotency key /
                # owner+task+ordinal) "이미 누가 예약했다"로 본다. 호출자는 원장을
                # 다시 읽어 판단한다 -- 덮어쓰지 않는다.
                result = await session.execute(
                    text(
                        f"INSERT INTO coding_sandbox_ledger ({_COLUMNS}) "
                        f"VALUES ({values}) ON CONFLICT DO NOTHING "
                        "RETURNING sandbox_id"
                    ),
                    self._params(record),
                )
                inserted = result.first()
        return record if inserted is not None else None

    async def get(self, sandbox_id: str) -> SandboxLedgerRecord | None:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        f"SELECT {_COLUMNS} FROM coding_sandbox_ledger "
                        "WHERE sandbox_id = :sandbox_id"
                    ),
                    {"sandbox_id": sandbox_id},
                )
                row = result.first()
        return None if row is None else self._record(row)

    async def find_by_state(
        self, *, owner_id: str, task_id: str, states: frozenset[LedgerState]
    ) -> tuple[SandboxLedgerRecord, ...]:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        f"SELECT {_COLUMNS} FROM coding_sandbox_ledger "
                        "WHERE owner_id = :owner_id AND task_id = :task_id "
                        "AND state = ANY(:states) ORDER BY ordinal"
                    ),
                    {
                        "owner_id": owner_id,
                        "task_id": task_id,
                        "states": sorted(state.value for state in states),
                    },
                )
                rows = result.all()
        return tuple(self._record(row) for row in rows)

    async def list_by_state(
        self, states: frozenset[LedgerState], *, limit: int = 100
    ) -> tuple[SandboxLedgerRecord, ...]:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        f"SELECT {_COLUMNS} FROM coding_sandbox_ledger "
                        "WHERE state = ANY(:states) ORDER BY updated_at LIMIT :limit"
                    ),
                    {"states": sorted(state.value for state in states), "limit": limit},
                )
                rows = result.all()
        return tuple(self._record(row) for row in rows)

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
        check_changes(changes)
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        f"SELECT {_COLUMNS} FROM coding_sandbox_ledger "
                        "WHERE sandbox_id = :sandbox_id FOR UPDATE"
                    ),
                    {"sandbox_id": sandbox_id},
                )
                row = result.first()
                if row is None:
                    raise LedgerConflict("ledger_sandbox_missing")
                current = self._record(row)
                updated = apply_update(
                    current,
                    owner_id=owner_id,
                    generation=generation,
                    expected_version=expected_version,
                    changes=changes,
                    now=now,
                )
                params = self._params(updated)
                params["previous_version"] = current.version
                written = await session.execute(
                    text(
                        "UPDATE coding_sandbox_ledger SET "
                        "generation = :generation, allocation_id = :allocation_id, "
                        "idempotency_key = :idempotency_key, "
                        "ownership_digest = :ownership_digest, "
                        "provider_ref = :provider_ref, state = :state, "
                        "resume_snapshot_ref = :resume_snapshot_ref, "
                        "resume_snapshot_expires_at = :resume_snapshot_expires_at, "
                        "workspace_revision = :workspace_revision, "
                        "stream_cursors = CAST(:stream_cursors AS JSONB), "
                        "error_code = :error_code, version = :version, "
                        "updated_at = :updated_at, "
                        "destroy_requested_at = :destroy_requested_at, "
                        "destroy_confirmed_at = :destroy_confirmed_at "
                        "WHERE sandbox_id = :sandbox_id "
                        "AND version = :previous_version "
                        "RETURNING sandbox_id"
                    ),
                    params,
                )
                if written.first() is None:
                    raise LedgerConflict("ledger_version_conflict")
        return updated

    async def put_snapshot(self, record: SnapshotLedgerRecord) -> None:
        aad = f"coding-sandbox-snapshot:{record.snapshot_id}"
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        f"INSERT INTO coding_sandbox_ledger_snapshots ({_SNAPSHOT_COLUMNS}) "
                        "VALUES (:snapshot_id, :sandbox_id, :owner_id, :generation, "
                        ":provider, :provider_snapshot_ref, :workspace_revision, "
                        ":content_checksum, :image_digest, :profile, :region, "
                        "CAST(:limits AS JSONB), :created_at, :expires_at) "
                        "ON CONFLICT (snapshot_id) DO NOTHING RETURNING snapshot_id"
                    ),
                    {
                        "snapshot_id": record.snapshot_id,
                        "sandbox_id": record.sandbox_id,
                        "owner_id": record.owner_id,
                        "generation": record.generation,
                        "provider": record.provider,
                        "provider_snapshot_ref": self._cipher(aad).encrypt(
                            record.provider_snapshot_ref
                        ),
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
                inserted = result.first()
        if inserted is None:
            existing = await self.get_snapshot(record.snapshot_id)
            if existing != record:
                raise LedgerConflict("ledger_snapshot_conflict")

    async def get_snapshot(self, snapshot_id: str) -> SnapshotLedgerRecord | None:
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        f"SELECT {_SNAPSHOT_COLUMNS} FROM coding_sandbox_ledger_snapshots "
                        "WHERE snapshot_id = :snapshot_id"
                    ),
                    {"snapshot_id": snapshot_id},
                )
                row = result.first()
        if row is None:
            return None
        try:
            return SnapshotLedgerRecord(
                snapshot_id=row.snapshot_id,
                sandbox_id=row.sandbox_id,
                owner_id=row.owner_id,
                generation=row.generation,
                provider=row.provider,
                provider_snapshot_ref=self._open(
                    row.provider_snapshot_ref, f"coding-sandbox-snapshot:{row.snapshot_id}"
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

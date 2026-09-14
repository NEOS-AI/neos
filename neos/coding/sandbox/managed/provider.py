"""`SandboxProvider` for managed coding sandboxes (E2B, Modal).

Structure (docs/MANAGED_SANDBOX_PROVIDER_REVIEW_260914.md §8.1)::

    coding loop -> ManagedSandboxProvider -> durable ledger (SoT)
                                          -> narrow provider client
                                          -> immutable guest neos-sandboxd

Rules this module keeps:

* **Ledger first.** A row (`CREATING`) is written before any provider create.
  Identifiers are deterministic, so a retry after a crash or a lost response
  recomputes the same idempotency key and rediscovers: 0 found -> create,
  1 -> adopt, >=2 -> quarantine and block new work for that owner.
* **Ownership before action.** Provider metadata must carry the HMAC digest the
  ledger expects before NEOS attaches to, suspends, or destroys an object. A
  mismatch is never deleted.
* **Owner + generation fence every write.** A provider object replacement
  (Modal cold resume) bumps the generation; streams bound to the old one close.
* **Named profile, exact match, before create.** Network default-deny is
  applied explicitly and read back.
* **Destroy is confirmed, not requested.** An ambiguous destroy stays
  `destroy_pending` for `reconcile_destroy_pending()`.

Nothing here is production-enabled: the factory refuses without an injected
provider client and ledger, and `sandbox.managed.enabled` defaults off.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from neos.coding.sandbox.base import (
    Sandbox,
    SandboxError,
    SandboxLimits,
    SandboxNotFound,
    SandboxState,
    SandboxStateConflict,
    SandboxUnavailable,
    Snapshot,
)
from neos.coding.sandbox.managed.clients.base import (
    ProviderClientError,
    ProviderCreateSpec,
    ProviderErrorKind,
    ProviderSandboxInfo,
    ProviderSandboxStatus,
    SandboxProviderClient,
)
from neos.coding.sandbox.managed.identity import (
    METADATA_ALLOCATION_ID,
    METADATA_GENERATION,
    METADATA_IDEMPOTENCY_KEY,
    METADATA_OWNERSHIP_DIGEST,
    METADATA_SANDBOX_ID,
    SandboxIdentity,
)
from neos.coding.sandbox.managed.ledger import (
    BLOCKING_STATES,
    LedgerConflict,
    LedgerState,
    SandboxLedger,
    SandboxLedgerRecord,
    SnapshotLedgerRecord,
)
from neos.coding.sandbox.managed.profiles import (
    SandboxProfile,
    get_profile,
    negotiate_profile,
    verify_applied_network,
)
from neos.coding.sandboxd.client import SandboxdClient, SandboxdExpectation
from neos.coding.sandboxd.session import SandboxdLease, SandboxdSession

_PINNED_IMAGE = re.compile(r"[^\s]+@sha256:[0-9a-f]{64}")
_RESERVE_ATTEMPTS = 5

_STATE_VIEW: Mapping[LedgerState, tuple[SandboxState, bool]] = {
    LedgerState.CREATING: (SandboxState.CREATING, True),
    LedgerState.RUNNING: (SandboxState.RUNNING, True),
    LedgerState.SUSPENDED: (SandboxState.SUSPENDED, True),
    LedgerState.QUARANTINED: (SandboxState.CREATING, False),
    LedgerState.FAILED: (SandboxState.DESTROYED, False),
    LedgerState.DESTROY_PENDING: (SandboxState.DESTROYED, False),
    LedgerState.DESTROYED: (SandboxState.DESTROYED, True),
}


class _OwnershipMismatch(SandboxUnavailable):
    """Provider object does not prove it is ours. Never destroy it."""


class _Quarantined(SandboxUnavailable):
    """>=2 provider objects carry one idempotency key. Must not be masked."""


def _provider_failure(error: ProviderClientError) -> SandboxUnavailable:
    return SandboxUnavailable(f"managed_provider_{error.kind.value}")


class _Attachment:
    """Per-session view of one ledger row; see `neos.coding.sandboxd.session`."""

    def __init__(self, provider: ManagedSandboxProvider, sandbox_id: str) -> None:
        self._provider = provider
        self._sandbox_id = sandbox_id

    @property
    def sandbox_id(self) -> str:
        return self._sandbox_id

    @property
    def allowed_env_names(self) -> frozenset[str]:
        return self._provider._allowed_env_names

    @property
    def operation_timeout_sec(self) -> float:
        return self._provider._operation_timeout_sec

    @property
    def max_pty_sessions(self) -> int:
        return self._provider._max_pty_sessions

    async def attach(self) -> SandboxdLease:
        record = await self._provider._running_record(self._sandbox_id)
        client = await self._provider._client_for(record)
        return SandboxdLease(client=client, limits=record.limits, generation=record.generation)

    def mutation_lock(self) -> asyncio.Lock:
        return self._provider._lock_for(self._sandbox_id)

    async def commit_revision(self, revision: int, *, generation: int) -> None:
        await self._provider._commit_revision(self._sandbox_id, revision, generation=generation)

    async def current_generation(self) -> int | None:
        record = await self._provider._ledger.get(self._sandbox_id)
        if record is None or record.state is LedgerState.DESTROYED:
            return None
        return record.generation

    async def commit_stream_cursor(self, stream: str, cursor: int, *, generation: int) -> None:
        await self._provider._commit_stream_cursor(
            self._sandbox_id, stream, cursor, generation=generation
        )


class ManagedSandboxProvider:
    def __init__(
        self,
        *,
        client: SandboxProviderClient,
        ledger: SandboxLedger,
        identity: SandboxIdentity,
        profile: SandboxProfile,
        image_digest: str,
        region: str,
        expectation: SandboxdExpectation,
        max_lifetime_sec: float,
        allowed_env_names: frozenset[str],
        operation_timeout_sec: float = 60.0,
        max_pty_sessions: int = 4,
        kill_switch: Callable[[], bool] = lambda: False,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if _PINNED_IMAGE.fullmatch(image_digest) is None:
            raise SandboxUnavailable("managed_image_unpinned")
        self._client = client
        self._ledger = ledger
        self._identity = identity
        self._profile = profile
        self._image_digest = image_digest
        self._region = region
        self._expectation = expectation
        self._max_lifetime = timedelta(seconds=max_lifetime_sec)
        self._allowed_env_names = allowed_env_names
        self._operation_timeout_sec = operation_timeout_sec
        self._max_pty_sessions = max_pty_sessions
        self._kill_switch = kill_switch
        self._clock = clock or (lambda: datetime.now(UTC))
        self._clients: dict[str, tuple[int, SandboxdClient]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._connect_locks: dict[str, asyncio.Lock] = {}
        self._negotiated = False

    # ---- identity ---------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return f"managed:{self._client.name}"

    @property
    def image_identity(self) -> str:
        return self._image_digest

    @property
    def local_provider(self) -> None:
        """Managed coding sandboxes have no local Docker provider behind them."""
        return None

    @property
    def profile(self) -> SandboxProfile:
        return self._profile

    # ---- create / restore -------------------------------------------------

    async def create(self, *, owner_id: str, limits: SandboxLimits) -> Sandbox:
        await self._admit()
        task_id = owner_id
        await self._refuse_blocked(owner_id, task_id)
        pending = [
            row
            for row in await self._ledger.find_by_state(
                owner_id=owner_id, task_id=task_id, states=frozenset({LedgerState.CREATING})
            )
            if row.source_snapshot_id is None
        ]
        if pending:
            # A previous attempt wrote the row and never finished. Its provider
            # object may exist: rediscover by its key before creating anything.
            return await self._materialize(pending[0], rediscover_first=True)
        record = await self._reserve(owner_id=owner_id, task_id=task_id, limits=limits)
        return await self._materialize(record, rediscover_first=False)

    async def restore(self, snapshot_id: str, *, owner_id: str) -> Sandbox:
        await self._admit()
        snapshot = await self._ledger.get_snapshot(snapshot_id)
        if snapshot is None or snapshot.owner_id != owner_id:
            # Another owner's snapshot is indistinguishable from a missing one.
            raise SandboxNotFound(snapshot_id)
        if snapshot.provider != self._client.name:
            raise SandboxUnavailable("managed_snapshot_provider_mismatch")
        await self._require_snapshot_available(snapshot.provider_snapshot_ref, snapshot.expires_at)
        await self._refuse_blocked(owner_id, owner_id)
        pending = [
            row
            for row in await self._ledger.find_by_state(
                owner_id=owner_id, task_id=owner_id, states=frozenset({LedgerState.CREATING})
            )
            if row.source_snapshot_id == snapshot_id
        ]
        if pending:
            record, rediscover = pending[0], True
        else:
            record = await self._reserve(
                owner_id=owner_id,
                task_id=owner_id,
                limits=snapshot.limits,
                source_snapshot_id=snapshot_id,
                revision=snapshot.workspace_revision,
            )
            rediscover = False
        return await self._materialize(
            record,
            rediscover_first=rediscover,
            source_snapshot_ref=snapshot.provider_snapshot_ref,
            expected_checksum=snapshot.content_checksum,
        )

    async def _admit(self) -> None:
        if self._kill_switch():
            raise SandboxUnavailable("managed_kill_switch")
        if not self._negotiated:
            try:
                capabilities = await self._client.probe()
            except ProviderClientError as error:
                raise _provider_failure(error) from None
            negotiate_profile(self._profile, capabilities)
            self._negotiated = True

    async def _refuse_blocked(self, owner_id: str, task_id: str) -> None:
        blocked = await self._ledger.find_by_state(
            owner_id=owner_id, task_id=task_id, states=BLOCKING_STATES
        )
        if blocked:
            raise SandboxUnavailable("managed_owner_quarantined")

    async def _require_snapshot_available(
        self, provider_snapshot_ref: str, expires_at: datetime | None
    ) -> None:
        if expires_at is not None and self._clock() >= expires_at:
            raise SandboxUnavailable("managed_snapshot_expired")
        try:
            exists = await self._client.snapshot_exists(provider_snapshot_ref)
        except ProviderClientError as error:
            raise _provider_failure(error) from None
        if not exists:
            raise SandboxUnavailable("managed_snapshot_not_found")

    async def _reserve(
        self,
        *,
        owner_id: str,
        task_id: str,
        limits: SandboxLimits,
        source_snapshot_id: str | None = None,
        revision: int = 0,
    ) -> SandboxLedgerRecord:
        for _attempt in range(_RESERVE_ATTEMPTS):
            ordinal = await self._ledger.max_ordinal(owner_id=owner_id, task_id=task_id) + 1
            sandbox_id = self._identity.sandbox_id(
                owner_id=owner_id, task_id=task_id, ordinal=ordinal
            )
            allocation_id = self._identity.allocation_id(sandbox_id=sandbox_id, generation=1)
            now = self._clock()
            record = SandboxLedgerRecord(
                sandbox_id=sandbox_id,
                owner_id=owner_id,
                task_id=task_id,
                ordinal=ordinal,
                generation=1,
                allocation_id=allocation_id,
                idempotency_key=self._identity.idempotency_key(allocation_id),
                ownership_digest=self._identity.ownership_digest(
                    allocation_id=allocation_id, owner_id=owner_id, generation=1
                ),
                provider=self._client.name,
                provider_ref=None,
                image_digest=self._image_digest,
                sandboxd_digest=self._expectation.bundle_digest,
                profile=self._profile.name,
                network_policy=self._profile.network.as_record(),
                region=self._region,
                limits=limits,
                state=LedgerState.CREATING,
                workspace_revision=revision,
                expires_at=now + self._max_lifetime,
                version=1,
                created_at=now,
                updated_at=now,
                source_snapshot_id=source_snapshot_id,
            )
            reserved = await self._ledger.reserve(record)
            if reserved is not None:
                return reserved
        raise SandboxUnavailable("managed_ledger_reservation_contended")

    def _spec(
        self, record: SandboxLedgerRecord, *, source_snapshot_ref: str | None = None
    ) -> ProviderCreateSpec:
        remaining = int((record.expires_at - self._clock()).total_seconds())
        if remaining <= 0:
            raise SandboxUnavailable("managed_sandbox_expired")
        return ProviderCreateSpec(
            allocation_id=record.allocation_id,
            idempotency_key=record.idempotency_key,
            provider_name=self._identity.provider_name(record.allocation_id),
            metadata={
                METADATA_SANDBOX_ID: record.sandbox_id,
                METADATA_ALLOCATION_ID: record.allocation_id,
                METADATA_IDEMPOTENCY_KEY: record.idempotency_key,
                METADATA_OWNERSHIP_DIGEST: record.ownership_digest,
                METADATA_GENERATION: str(record.generation),
            },
            image=record.image_digest,
            region=record.region,
            network=self._profile.network,
            limits=record.limits,
            lifetime_sec=remaining,
            source_snapshot_ref=source_snapshot_ref,
        )

    async def _materialize(
        self,
        record: SandboxLedgerRecord,
        *,
        rediscover_first: bool,
        source_snapshot_ref: str | None = None,
        expected_checksum: str | None = None,
        cold_resume_from: str | None = None,
    ) -> Sandbox:
        async with self._lock_for(record.sandbox_id):
            spec = self._spec(record, source_snapshot_ref=source_snapshot_ref or cold_resume_from)
            info = await self._rediscover(record) if rediscover_first else None
            if info is None:
                info = await self._provider_create(record, spec, cold_resume=cold_resume_from)
            try:
                self._verify_owned(record, info)
            except _OwnershipMismatch:
                await self._quarantine(record, "provider_ownership_mismatch")
                raise
            record = await self._write(record, provider_ref=info.provider_ref)
            try:
                self._verify_placement(info)
                client = await self._connect(record, info.provider_ref)
                if expected_checksum is not None:
                    result = await client.call("checksum", timeout_sec=self._operation_timeout_sec)
                    if result.get("checksum") != expected_checksum:
                        raise SandboxUnavailable("managed_snapshot_checksum_mismatch")
            except SandboxError:
                await self._abandon(record)
                raise
            hello_revision = client.hello.revision if client.hello else record.workspace_revision
            record = await self._write(
                record,
                state=LedgerState.RUNNING,
                workspace_revision=max(record.workspace_revision, hello_revision),
                resume_snapshot_ref=None,
                resume_snapshot_expires_at=None,
                error_code=None,
            )
            return self._sandbox(record)

    async def _provider_create(
        self,
        record: SandboxLedgerRecord,
        spec: ProviderCreateSpec,
        *,
        cold_resume: str | None,
    ) -> ProviderSandboxInfo:
        try:
            if cold_resume is not None:
                return await self._client.resume(cold_resume, spec=spec)
            return await self._client.create(spec)
        except ProviderClientError as error:
            if error.ambiguous or error.kind is ProviderErrorKind.CONFLICT:
                # The object may exist (lost response, timeout after accept, a
                # deterministic-name collision). Resolve by rediscovery only;
                # a second create here is how orphans leak money.
                try:
                    found = await self._rediscover(record)
                except _Quarantined:
                    raise
                except SandboxUnavailable:
                    raise SandboxUnavailable("managed_allocation_ambiguous") from None
                if found is None:
                    raise SandboxUnavailable("managed_allocation_ambiguous") from None
                return found
            if cold_resume is None:
                await self._write(record, state=LedgerState.FAILED, error_code=f"provider_{error.kind.value}")
            raise _provider_failure(error) from None

    async def _rediscover(self, record: SandboxLedgerRecord) -> ProviderSandboxInfo | None:
        try:
            found = await self._client.find(record.idempotency_key)
        except ProviderClientError as error:
            raise SandboxUnavailable(f"managed_rediscovery_{error.kind.value}") from None
        if len(found) >= 2:
            await self._quarantine(record, "duplicate_provider_objects")
            raise _Quarantined("managed_sandbox_quarantined")
        return found[0] if found else None

    def _verify_owned(self, record: SandboxLedgerRecord, info: ProviderSandboxInfo) -> None:
        metadata = info.metadata
        if (
            metadata.get(METADATA_SANDBOX_ID) != record.sandbox_id
            or metadata.get(METADATA_ALLOCATION_ID) != record.allocation_id
            or metadata.get(METADATA_IDEMPOTENCY_KEY) != record.idempotency_key
            or metadata.get(METADATA_OWNERSHIP_DIGEST) != record.ownership_digest
            or not self._identity.verify_ownership(
                metadata.get(METADATA_OWNERSHIP_DIGEST),
                allocation_id=record.allocation_id,
                owner_id=record.owner_id,
                generation=record.generation,
            )
        ):
            raise _OwnershipMismatch("managed_ownership_mismatch")

    def _verify_placement(self, info: ProviderSandboxInfo) -> None:
        verify_applied_network(self._profile, info.network)
        if info.region is None:
            raise SandboxUnavailable("managed_region_unverifiable")
        if info.region != self._region:
            raise SandboxUnavailable("managed_region_mismatch")
        if info.status is not ProviderSandboxStatus.RUNNING:
            raise SandboxUnavailable(f"managed_provider_not_running:{info.status.value}")

    async def _quarantine(self, record: SandboxLedgerRecord, code: str) -> None:
        try:
            await self._write(record, state=LedgerState.QUARANTINED, error_code=code)
        except LedgerConflict:
            pass

    async def _abandon(self, record: SandboxLedgerRecord) -> None:
        """Destroy an owned object we will not serve; the caller's error wins."""
        await self._drop_client(record.sandbox_id)
        try:
            await self._destroy_record(record)
        except SandboxError:
            pass

    # ---- ledger writes ----------------------------------------------------

    async def _write(self, record: SandboxLedgerRecord, **changes: Any) -> SandboxLedgerRecord:
        return await self._ledger.update(
            record.sandbox_id,
            owner_id=record.owner_id,
            generation=record.generation,
            expected_version=record.version,
            changes=changes,
            now=self._clock(),
        )

    async def _commit_revision(self, sandbox_id: str, revision: int, *, generation: int) -> None:
        record = await self._ledger.get(sandbox_id)
        if record is None:
            raise SandboxNotFound(sandbox_id)
        if revision <= record.workspace_revision and record.generation == generation:
            return
        try:
            await self._ledger.update(
                sandbox_id,
                owner_id=record.owner_id,
                generation=generation,
                expected_version=None,
                changes={"workspace_revision": max(revision, record.workspace_revision)},
                now=self._clock(),
            )
        except LedgerConflict as error:
            # The guest applied the mutation but the host could not commit it
            # against this generation. The outcome is ambiguous; re-read.
            raise SandboxUnavailable("managed_revision_commit_ambiguous") from error

    async def _commit_stream_cursor(
        self, sandbox_id: str, stream: str, cursor: int, *, generation: int
    ) -> None:
        record = await self._ledger.get(sandbox_id)
        if record is None:
            raise SandboxNotFound(sandbox_id)
        if record.stream_cursors.get(stream, 0) >= cursor and record.generation == generation:
            return
        cursors = dict(record.stream_cursors)
        cursors[stream] = max(cursor, cursors.get(stream, 0))
        try:
            await self._ledger.update(
                sandbox_id,
                owner_id=record.owner_id,
                generation=generation,
                expected_version=None,
                changes={"stream_cursors": cursors},
                now=self._clock(),
            )
        except LedgerConflict as error:
            raise SandboxStateConflict("stream_generation_changed") from error

    # ---- read ---------------------------------------------------------------

    async def get(self, sandbox_id: str) -> Sandbox:
        record = await self._ledger.get(sandbox_id)
        if record is None or record.state is LedgerState.DESTROYED:
            raise SandboxNotFound(sandbox_id)
        return self._sandbox(record)

    def _sandbox(self, record: SandboxLedgerRecord) -> Sandbox:
        state, healthy = _STATE_VIEW[record.state]
        return Sandbox(
            sandbox_id=record.sandbox_id,
            owner_id=record.owner_id,
            state=state,
            limits=record.limits,
            created_at=record.created_at,
            updated_at=record.updated_at,
            workspace_revision=record.workspace_revision,
            provider=self.provider_name,
            image_digest=record.image_digest,
            expires_at=record.expires_at,
            healthy=healthy,
            last_error_code=record.error_code,
        )

    async def _running_record(self, sandbox_id: str) -> SandboxLedgerRecord:
        record = await self._ledger.get(sandbox_id)
        if record is None or record.state is LedgerState.DESTROYED:
            raise SandboxNotFound(sandbox_id)
        if not self._identity.verify_ownership(
            record.ownership_digest,
            allocation_id=record.allocation_id,
            owner_id=record.owner_id,
            generation=record.generation,
        ):
            # The ledger row itself was edited without the key.
            raise SandboxUnavailable("managed_ownership_mismatch")
        if record.state is not LedgerState.RUNNING:
            raise SandboxStateConflict(f"{_STATE_VIEW[record.state][0].value}->running")
        if self._clock() >= record.expires_at:
            raise SandboxStateConflict("sandbox_expired")
        return record

    # ---- sessions ----------------------------------------------------------

    def _lock_for(self, sandbox_id: str) -> asyncio.Lock:
        return self._locks.setdefault(sandbox_id, asyncio.Lock())

    async def _client_for(self, record: SandboxLedgerRecord) -> SandboxdClient:
        async with self._connect_locks.setdefault(record.sandbox_id, asyncio.Lock()):
            cached = self._clients.get(record.sandbox_id)
            if cached is not None:
                generation, client = cached
                if generation == record.generation and not client.closed:
                    return client
                await client.close()
                self._clients.pop(record.sandbox_id, None)
            if record.provider_ref is None:
                raise SandboxUnavailable("managed_provider_ref_missing")
            info = await self._describe(record.provider_ref)
            self._verify_owned(record, info)
            if info.status is not ProviderSandboxStatus.RUNNING:
                raise SandboxStateConflict(f"provider_{info.status.value}->running")
            return await self._open_client(record, record.provider_ref)

    async def _connect(self, record: SandboxLedgerRecord, provider_ref: str) -> SandboxdClient:
        async with self._connect_locks.setdefault(record.sandbox_id, asyncio.Lock()):
            await self._drop_client_unlocked(record.sandbox_id)
            return await self._open_client(record, provider_ref)

    async def _open_client(self, record: SandboxLedgerRecord, provider_ref: str) -> SandboxdClient:
        try:
            channel = await self._client.open_channel(provider_ref)
        except ProviderClientError as error:
            raise _provider_failure(error) from None
        client = SandboxdClient(channel, request_timeout_sec=self._operation_timeout_sec)
        await client.handshake(self._expectation, base_revision=record.workspace_revision)
        self._clients[record.sandbox_id] = (record.generation, client)
        return client

    async def _drop_client(self, sandbox_id: str) -> None:
        async with self._connect_locks.setdefault(sandbox_id, asyncio.Lock()):
            await self._drop_client_unlocked(sandbox_id)

    async def _drop_client_unlocked(self, sandbox_id: str) -> None:
        cached = self._clients.pop(sandbox_id, None)
        if cached is not None:
            await cached[1].close()

    async def _describe(self, provider_ref: str) -> ProviderSandboxInfo:
        try:
            return await self._client.describe(provider_ref)
        except ProviderClientError as error:
            if error.kind is ProviderErrorKind.NOT_FOUND:
                raise SandboxUnavailable("managed_provider_object_missing") from None
            raise _provider_failure(error) from None

    async def open_session(self, sandbox_id: str) -> SandboxdSession:
        record = await self._ledger.get(sandbox_id)
        if record is None or record.state is LedgerState.DESTROYED:
            raise SandboxNotFound(sandbox_id)
        return SandboxdSession(_Attachment(self, sandbox_id))

    # ---- suspend / resume ---------------------------------------------------

    async def suspend(self, sandbox_id: str) -> Sandbox:
        async with self._lock_for(sandbox_id):
            record = await self._running_record(sandbox_id)
            ref = record.provider_ref
            if ref is None:
                raise SandboxUnavailable("managed_provider_ref_missing")
            self._verify_owned(record, await self._describe(ref))
            try:
                checksum = await self._checksum(record)
                outcome = await self._client.suspend(ref)
            except ProviderClientError as error:
                # E2B pause refused as busy: the sandbox is still running and
                # the ledger still says so. Nothing to roll back.
                raise _provider_failure(error) from None
            await self._drop_client(sandbox_id)
            if not outcome.terminated:
                record = await self._write(record, state=LedgerState.SUSPENDED)
                return self._sandbox(record)
            snapshot = outcome.snapshot
            if snapshot is None:
                raise SandboxUnavailable("managed_suspend_snapshot_missing")
            if not outcome.terminate_confirmed:
                # The snapshot exists but the old object may still run (and
                # bill). Keep the row RUNNING with its ref so the next suspend
                # or destroy retries against an object we can still prove.
                raise SandboxUnavailable("managed_suspend_terminate_unconfirmed")
            await self._ledger.put_snapshot(
                self._snapshot_record(record, snapshot.snapshot_ref, snapshot.expires_at, checksum)
            )
            # Cold suspend replaces the provider object. Reserve the *next*
            # generation now, so a crashed or retried resume reuses one key.
            next_generation = record.generation + 1
            allocation_id = self._identity.allocation_id(
                sandbox_id=sandbox_id, generation=next_generation
            )
            record = await self._write(
                record,
                state=LedgerState.SUSPENDED,
                provider_ref=None,
                resume_snapshot_ref=snapshot.snapshot_ref,
                resume_snapshot_expires_at=snapshot.expires_at,
                generation=next_generation,
                allocation_id=allocation_id,
                idempotency_key=self._identity.idempotency_key(allocation_id),
                ownership_digest=self._identity.ownership_digest(
                    allocation_id=allocation_id,
                    owner_id=record.owner_id,
                    generation=next_generation,
                ),
                workspace_revision=checksum[1],
            )
            return self._sandbox(record)

    async def resume(self, sandbox_id: str) -> Sandbox:
        record = await self._ledger.get(sandbox_id)
        if record is None or record.state is LedgerState.DESTROYED:
            raise SandboxNotFound(sandbox_id)
        if record.state is not LedgerState.SUSPENDED:
            raise SandboxStateConflict(f"{_STATE_VIEW[record.state][0].value}->running")
        if record.resume_snapshot_ref is None:
            return await self._warm_resume(record)
        return await self._cold_resume(record)

    async def _warm_resume(self, record: SandboxLedgerRecord) -> Sandbox:
        async with self._lock_for(record.sandbox_id):
            ref = record.provider_ref
            if ref is None:
                raise SandboxUnavailable("managed_provider_ref_missing")
            self._verify_owned(record, await self._describe(ref))
            try:
                info = await self._client.resume(ref, spec=self._spec(record))
            except ProviderClientError as error:
                raise _provider_failure(error) from None
            self._verify_owned(record, info)
            self._verify_placement(info)
            client = await self._connect(record, ref)
            revision = client.hello.revision if client.hello else record.workspace_revision
            record = await self._write(
                record,
                state=LedgerState.RUNNING,
                workspace_revision=max(revision, record.workspace_revision),
            )
            return self._sandbox(record)

    async def _cold_resume(self, record: SandboxLedgerRecord) -> Sandbox:
        if self._kill_switch():
            raise SandboxUnavailable("managed_kill_switch")
        snapshot_ref = record.resume_snapshot_ref
        assert snapshot_ref is not None
        await self._require_snapshot_available(snapshot_ref, record.resume_snapshot_expires_at)
        snapshot = await self._ledger.get_snapshot(
            self._identity.snapshot_id(
                sandbox_id=record.sandbox_id,
                generation=record.generation - 1,
                provider_snapshot_ref=snapshot_ref,
            )
        )
        if snapshot is None:
            raise SandboxUnavailable("managed_snapshot_unrecorded")
        return await self._materialize(
            record,
            rediscover_first=True,
            cold_resume_from=snapshot_ref,
            expected_checksum=snapshot.content_checksum,
        )

    # ---- snapshot -----------------------------------------------------------

    async def _checksum(self, record: SandboxLedgerRecord) -> tuple[str, int]:
        client = await self._client_for(record)
        result = await client.call("checksum", timeout_sec=self._operation_timeout_sec)
        checksum = result.get("checksum")
        revision = result.get("revision")
        if not isinstance(checksum, str) or not isinstance(revision, int):
            raise SandboxUnavailable("sandboxd_response_invalid")
        return checksum, revision

    def _snapshot_record(
        self,
        record: SandboxLedgerRecord,
        provider_snapshot_ref: str,
        expires_at: datetime | None,
        checksum: tuple[str, int],
    ) -> SnapshotLedgerRecord:
        return SnapshotLedgerRecord(
            snapshot_id=self._identity.snapshot_id(
                sandbox_id=record.sandbox_id,
                generation=record.generation,
                provider_snapshot_ref=provider_snapshot_ref,
            ),
            sandbox_id=record.sandbox_id,
            owner_id=record.owner_id,
            generation=record.generation,
            provider=record.provider,
            provider_snapshot_ref=provider_snapshot_ref,
            workspace_revision=checksum[1],
            content_checksum=checksum[0],
            image_digest=record.image_digest,
            profile=record.profile,
            region=record.region,
            limits=record.limits,
            created_at=self._clock(),
            expires_at=expires_at,
        )

    async def snapshot(self, sandbox_id: str) -> Snapshot:
        async with self._lock_for(sandbox_id):
            record = await self._running_record(sandbox_id)
            ref = record.provider_ref
            if ref is None:
                raise SandboxUnavailable("managed_provider_ref_missing")
            self._verify_owned(record, await self._describe(ref))
            checksum = await self._checksum(record)
            try:
                provider_snapshot = await self._client.snapshot(ref)
            except ProviderClientError as error:
                raise _provider_failure(error) from None
            if provider_snapshot.connections_dropped:
                # E2B: the sandbox is RUNNING again but every live connection
                # dropped. Reconnect lazily; journals replay from cursors.
                await self._drop_client(sandbox_id)
            snapshot = self._snapshot_record(
                record, provider_snapshot.snapshot_ref, provider_snapshot.expires_at, checksum
            )
            await self._ledger.put_snapshot(snapshot)
            await self._commit_revision(sandbox_id, checksum[1], generation=record.generation)
            return Snapshot(
                snapshot_id=snapshot.snapshot_id,
                source_sandbox_id=sandbox_id,
                workspace_revision=snapshot.workspace_revision,
                created_at=snapshot.created_at,
                content_checksum=snapshot.content_checksum,
                image_digest=snapshot.image_digest,
            )

    # ---- destroy ------------------------------------------------------------

    async def destroy(self, sandbox_id: str) -> None:
        record = await self._ledger.get(sandbox_id)
        if record is None or record.state is LedgerState.DESTROYED:
            return
        async with self._lock_for(sandbox_id):
            await self._drop_client(sandbox_id)
            record = await self._ledger.get(sandbox_id)
            if record is None or record.state is LedgerState.DESTROYED:
                return
            await self._destroy_record(record)

    async def _destroy_record(self, record: SandboxLedgerRecord) -> None:
        ref = record.provider_ref
        if ref is None and record.state in {LedgerState.CREATING, LedgerState.QUARANTINED}:
            # The create may have landed without us recording the ref.
            found = await self._client_find_for_destroy(record)
            if len(found) >= 2:
                await self._quarantine(record, "duplicate_provider_objects")
                raise SandboxUnavailable("managed_sandbox_quarantined")
            if found:
                self._verify_owned(record, found[0])
                ref = found[0].provider_ref
        if ref is None:
            await self._confirm_destroyed(record)
            return
        try:
            info = await self._client.describe(ref)
        except ProviderClientError as error:
            if error.kind is ProviderErrorKind.NOT_FOUND:
                await self._confirm_destroyed(record)
                return
            raise _provider_failure(error) from None
        # Never delete an object that does not prove it is ours.
        self._verify_owned(record, info)
        if record.state is not LedgerState.DESTROY_PENDING:
            record = await self._write(
                record,
                state=LedgerState.DESTROY_PENDING,
                provider_ref=ref,
                destroy_requested_at=self._clock(),
            )
        try:
            outcome = await self._client.destroy(ref)
        except ProviderClientError as error:
            if error.kind is ProviderErrorKind.NOT_FOUND:
                await self._confirm_destroyed(record)
                return
            raise SandboxUnavailable("managed_destroy_pending") from None
        if outcome.not_found or outcome.confirmed:
            await self._confirm_destroyed(record)
            return
        # The request went out; nothing confirmed it. `destroy_pending` stays
        # for the reaper -- a sent request is not a deletion.
        raise SandboxUnavailable("managed_destroy_pending")

    async def _client_find_for_destroy(
        self, record: SandboxLedgerRecord
    ) -> tuple[ProviderSandboxInfo, ...]:
        try:
            return await self._client.find(record.idempotency_key)
        except ProviderClientError as error:
            raise _provider_failure(error) from None

    async def _confirm_destroyed(self, record: SandboxLedgerRecord) -> None:
        now = self._clock()
        await self._write(
            record,
            state=LedgerState.DESTROYED,
            provider_ref=None,
            resume_snapshot_ref=None,
            resume_snapshot_expires_at=None,
            destroy_requested_at=record.destroy_requested_at or now,
            destroy_confirmed_at=now,
        )

    async def reconcile_destroy_pending(self, *, limit: int = 100) -> int:
        """Re-check ambiguous destroys. Returns how many are now confirmed."""
        confirmed = 0
        for record in await self._ledger.list_by_state(
            frozenset({LedgerState.DESTROY_PENDING}), limit=limit
        ):
            try:
                await self.destroy(record.sandbox_id)
            except SandboxError:
                continue
            confirmed += 1
        return confirmed

    async def close(self) -> None:
        for sandbox_id in list(self._clients):
            await self._drop_client(sandbox_id)


@dataclass(frozen=True, slots=True)
class ManagedBackend:
    """Everything a managed provider needs that config alone cannot supply."""

    client: SandboxProviderClient
    ledger: SandboxLedger
    image_digest: str
    ownership_key: bytes
    sandboxd_digest: str | None = None

    def __repr__(self) -> str:  # never print the key
        return f"ManagedBackend(client={self.client.name!r}, image_digest={self.image_digest!r})"


SERVABLE_PROVIDERS = frozenset({"e2b", "modal"})


def create_managed_sandbox_provider(
    config,
    *,
    backends: Mapping[str, ManagedBackend] | None = None,
) -> ManagedSandboxProvider:
    """Build the provider named by `sandbox.managed.provider`. Fail closed.

    `e2b` and `modal` need an injected `ManagedBackend` (provider client with a
    real SDK binding, durable ledger, pinned image, ownership key). Any other
    name -- including `docker` and `fake` -- has no guest daemon to serve.
    """
    managed = config.managed
    if not managed.enabled:
        raise SandboxUnavailable("managed_sandbox_disabled")
    name = managed.provider
    if name not in SERVABLE_PROVIDERS:
        raise SandboxUnavailable(f"managed_provider_not_servable:{name}")
    backend = (backends or {}).get(name)
    if backend is None:
        raise SandboxUnavailable(f"managed_{name}_client_not_bound")
    if backend.client.name != name:
        raise SandboxUnavailable("managed_backend_provider_mismatch")
    profile = get_profile(managed.coding_profile)
    digest = managed.sandboxd_digest or backend.sandboxd_digest
    expectation = (
        SandboxdExpectation(bundle_digest=digest) if digest else SandboxdExpectation.bundled()
    )
    return ManagedSandboxProvider(
        client=backend.client,
        ledger=backend.ledger,
        identity=SandboxIdentity(backend.ownership_key),
        profile=profile,
        image_digest=backend.image_digest,
        region=managed.region,
        expectation=expectation,
        max_lifetime_sec=config.lifecycle.max_lifetime_sec,
        allowed_env_names=frozenset(config.execution.allowed_env_names),
        operation_timeout_sec=config.execution.command_timeout_sec,
        max_pty_sessions=config.streams.pty_max_sessions,
        kill_switch=lambda: managed.global_kill_switch,
    )


__all__ = [
    "ManagedBackend",
    "ManagedSandboxProvider",
    "SERVABLE_PROVIDERS",
    "create_managed_sandbox_provider",
]

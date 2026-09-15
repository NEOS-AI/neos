"""Managed coding `SandboxProvider`, attached to the managed allocation plane.

구조 (docs/MANAGED_SANDBOX_PROVIDER_REVIEW_260914.md §8.1, docs/PLAN_260913.md §B2):

```text
admission -> coding intent -> ManagedSandboxAllocationService.advance()
                                  `-- ManagedCodingAllocationAdapter  (adapter.py)
                                        `-- provider client -> vendor object + neos-sandboxd
coding loop -> SandboxBindingService -> ManagedSandboxProvider (this module)
                                           |-- runtime ledger (ledger.py, 057)
                                           `-- SandboxdSession -> neos-sandboxd
```

* **이 provider 는 vendor object 를 할당하지 않는다.** `create(owner_id=task_id)` 는
  그 태스크의 살아 있는 allocation 과 코딩 intent 를 찾아 **붙는다**. 할당 평면이
  admission / quota / kill switch / cleanup SLO 를 소유한다. allocation 이 없으면
  `managed_allocation_required` 다 -- 여기서 몰래 만들지 않는다.
* 붙기 전에 두 digest(레거시 sha256 + 키 있는 HMAC), network read-back, region,
  guest handshake 를 모두 검증한다 (`ownership.py`).
* `for_lease(lease)` 는 실행 lease 에 묶인 view 다. 그 view 의 revision / cursor
  커밋과 mutation 은 `coding_run_leases` 가 살아 있어야 통과하고, 그 view 의
  `destroy` 는 **자기 handle 만** 놓는다 -- binding CAS 에서 진 쪽이 이긴 쪽의
  allocation 을 무너뜨리지 못한다.
* lease 없는 `destroy` 는 runtime 을 `detached` 로 적는다. vendor object 는 할당
  평면의 cleanup 이 (태스크 종료 / 절대 만료 때) 지운다.
* Modal cold resume 은 새 vendor object(incarnation + 1)를 만들고, 원장 한
  트랜잭션에서 allocation 의 봉인된 `provider_ref` 를 교체한다. allocation
  generation 은 바뀌지 않는다.
* `restore` 는 준비된 target allocation(같은 태스크, intent 의 `source_snapshot_id`)
  에만 붙는다. 045 는 태스크당 살아 있는 allocation 을 하나로 강제하므로, source 가
  살아 있는 동안 같은 태스크에 독립 restore 를 만들 수 없다.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from neos.coding.domain.durability import ExecutionLease
from neos.coding.managed.allocation import ManagedSandboxCipher
from neos.coding.managed.crypto import ProviderReferenceCipherError
from neos.coding.managed.domain import ManagedSandboxAllocation
from neos.coding.sandbox.base import (
    Sandbox,
    SandboxError,
    SandboxLimits,
    SandboxNotFound,
    SandboxPolicyViolation,
    SandboxState,
    SandboxStateConflict,
    SandboxUnavailable,
    Snapshot,
)
from neos.coding.sandbox.managed.adapter import (
    ManagedCodingAllocationAdapter,
    build_create_spec,
)
from neos.coding.sandbox.managed.clients.base import (
    ProviderClientError,
    ProviderErrorKind,
    ProviderSandboxInfo,
    ProviderSandboxStatus,
    SandboxProviderClient,
)
from neos.coding.sandbox.managed.identity import ManagedCodingIdentity
from neos.coding.sandbox.managed.ledger import (
    ATTACHABLE_ALLOCATION_STATES,
    CodingRuntimeLedger,
    LedgerConflict,
    PhysicalRecord,
    PhysicalState,
    RuntimeFence,
    RuntimeRecord,
    RuntimeState,
    SnapshotRecord,
)
from neos.coding.sandbox.managed.ownership import (
    OwnershipMismatch,
    physical_identity,
    verify_owned,
    verify_placement,
)
from neos.coding.sandbox.managed.profiles import (
    SandboxProfile,
    get_profile,
    negotiate_profile,
)
from neos.coding.sandboxd.client import SandboxdClient, SandboxdExpectation
from neos.coding.sandboxd.session import SandboxdLease, SandboxdSession

AllocationCipherFactory = Callable[[ManagedSandboxAllocation], ManagedSandboxCipher]

_PINNED_IMAGE = re.compile(r"[^\s]+@sha256:[0-9a-f]{64}")

_STATE_VIEW: Mapping[RuntimeState, tuple[SandboxState, bool]] = {
    RuntimeState.INTENT: (SandboxState.CREATING, True),
    RuntimeState.RUNNING: (SandboxState.RUNNING, True),
    RuntimeState.SUSPENDED: (SandboxState.SUSPENDED, True),
    RuntimeState.QUARANTINED: (SandboxState.CREATING, False),
    RuntimeState.FAILED: (SandboxState.DESTROYED, False),
    RuntimeState.DETACHED: (SandboxState.DESTROYED, True),
}


def _provider_failure(error: ProviderClientError) -> SandboxUnavailable:
    return SandboxUnavailable(f"managed_provider_{error.kind.value}")


def _fence_failure(error: LedgerConflict) -> SandboxError:
    code = str(error)
    if code in {"stream_generation_changed", "sandbox_fence_stale"}:
        return SandboxStateConflict(code)
    return SandboxUnavailable("managed_revision_commit_ambiguous")


@dataclass
class _SharedLocks:
    """Lifecycle locks shared by a provider and every lease view of it."""

    lifecycle: dict[str, asyncio.Lock] = field(default_factory=dict)
    connect: dict[str, asyncio.Lock] = field(default_factory=dict)
    negotiated: set[str] = field(default_factory=set)

    def lifecycle_lock(self, sandbox_id: str) -> asyncio.Lock:
        return self.lifecycle.setdefault(sandbox_id, asyncio.Lock())

    def connect_lock(self, sandbox_id: str) -> asyncio.Lock:
        return self.connect.setdefault(sandbox_id, asyncio.Lock())


class _Attachment:
    """`SandboxdAttachment` for one sandbox. Generation here is the stream epoch."""

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
        runtime = await self._provider._running_record(self._sandbox_id)
        client = await self._provider._client_for(runtime)
        return SandboxdLease(client=client, limits=runtime.limits, generation=runtime.stream_epoch)

    @asynccontextmanager
    async def mutation_lock(self) -> AsyncIterator[None]:
        async with self._provider._locks.lifecycle_lock(self._sandbox_id):
            # A worker that lost its lease must not reach the guest at all --
            # a commit check after the guest applied the write is too late.
            await self._provider._check_fence()
            yield

    async def commit_revision(self, revision: int, *, generation: int) -> None:
        await self._provider._commit_revision(self._sandbox_id, revision, stream_epoch=generation)

    async def current_generation(self) -> int | None:
        runtime = await self._provider._ledger.get(self._sandbox_id)
        return None if runtime is None else runtime.stream_epoch

    async def commit_stream_cursor(self, stream: str, cursor: int, *, generation: int) -> None:
        await self._provider._commit_cursor(
            self._sandbox_id, stream, cursor, stream_epoch=generation
        )


class ManagedSandboxProvider:
    def __init__(
        self,
        *,
        client: SandboxProviderClient,
        ledger: CodingRuntimeLedger,
        identity: ManagedCodingIdentity,
        allocation_cipher: AllocationCipherFactory,
        profile: SandboxProfile,
        image_digest: str,
        region: str,
        expectation: SandboxdExpectation,
        allowed_env_names: frozenset[str],
        operation_timeout_sec: float = 60.0,
        max_pty_sessions: int = 4,
        kill_switch: Callable[[], bool] = lambda: False,
        clock: Callable[[], datetime] | None = None,
        fence: RuntimeFence | None = None,
        locks: _SharedLocks | None = None,
    ) -> None:
        if _PINNED_IMAGE.fullmatch(image_digest) is None:
            raise SandboxUnavailable("managed_image_unpinned")
        self._client = client
        self._ledger = ledger
        self._identity = identity
        self._allocation_cipher = allocation_cipher
        self._profile = profile
        self._image_digest = image_digest
        self._region = region
        self._expectation = expectation
        self._allowed_env_names = allowed_env_names
        self._operation_timeout_sec = operation_timeout_sec
        self._max_pty_sessions = max_pty_sessions
        self._kill_switch = kill_switch
        self._clock = clock or (lambda: datetime.now(UTC))
        self._fence = fence
        self._locks = locks or _SharedLocks()
        # Connections are per view: a lease view that lets go of its handles
        # must not disconnect another view's sessions.
        self._clients: dict[str, tuple[int, SandboxdClient]] = {}

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

    @property
    def fence(self) -> RuntimeFence | None:
        return self._fence

    def for_lease(self, lease: ExecutionLease) -> ManagedSandboxProvider:
        """A view fenced to one execution lease (see module docstring)."""
        return ManagedSandboxProvider(
            client=self._client,
            ledger=self._ledger,
            identity=self._identity,
            allocation_cipher=self._allocation_cipher,
            profile=self._profile,
            image_digest=self._image_digest,
            region=self._region,
            expectation=self._expectation,
            allowed_env_names=self._allowed_env_names,
            operation_timeout_sec=self._operation_timeout_sec,
            max_pty_sessions=self._max_pty_sessions,
            kill_switch=self._kill_switch,
            clock=self._clock,
            fence=RuntimeFence.from_lease(lease),
            locks=self._locks,
        )

    # ---- create / restore (attach) -------------------------------------------

    async def create(self, *, owner_id: str, limits: SandboxLimits) -> Sandbox:
        await self._admit()
        self._require_own_task(owner_id)
        allocation = await self._ledger.allocation_for_task(owner_id)
        if allocation is None:
            raise SandboxUnavailable("managed_allocation_required")
        runtime = await self._ledger.get_by_allocation(allocation.allocation_id)
        if runtime is None:
            raise SandboxUnavailable("managed_coding_intent_missing")
        if runtime.source_snapshot_id is not None:
            raise SandboxUnavailable("managed_allocation_reserved_for_restore")
        return await self._attach(allocation, runtime, limits=limits)

    async def restore(self, snapshot_id: str, *, owner_id: str) -> Sandbox:
        await self._admit()
        self._require_own_task(owner_id)
        snapshot = await self._ledger.get_snapshot(snapshot_id)
        if snapshot is None or snapshot.task_id != owner_id:
            # Another task's snapshot is indistinguishable from a missing one.
            raise SandboxNotFound(snapshot_id)
        if snapshot.provider != self._client.name:
            raise SandboxUnavailable("managed_snapshot_provider_mismatch")
        await self._require_snapshot_available(snapshot.provider_snapshot_ref, snapshot.expires_at)
        allocation = await self._ledger.allocation_for_task(owner_id)
        runtime = (
            None
            if allocation is None
            else await self._ledger.get_by_allocation(allocation.allocation_id)
        )
        if allocation is None or runtime is None or runtime.source_snapshot_id != snapshot_id:
            raise SandboxUnavailable("managed_restore_target_required")
        return await self._attach(
            allocation,
            runtime,
            limits=runtime.limits,
            expected_checksum=snapshot.content_checksum,
        )

    async def _admit(self) -> None:
        if self._kill_switch():
            raise SandboxUnavailable("managed_kill_switch")
        if self._profile.name in self._locks.negotiated:
            return
        try:
            capabilities = await self._client.probe()
        except ProviderClientError as error:
            raise _provider_failure(error) from None
        negotiate_profile(self._profile, capabilities)
        self._locks.negotiated.add(self._profile.name)

    def _require_own_task(self, task_id: str) -> None:
        if self._fence is not None and self._fence.task_id != task_id:
            raise SandboxPolicyViolation("managed_binding_mismatch")

    async def _attach(
        self,
        allocation: ManagedSandboxAllocation,
        runtime: RuntimeRecord,
        *,
        limits: SandboxLimits,
        expected_checksum: str | None = None,
    ) -> Sandbox:
        if (
            runtime.task_id != allocation.task_id
            or runtime.allocation_generation != allocation.generation
        ):
            raise SandboxUnavailable("managed_runtime_allocation_mismatch")
        if limits != runtime.limits:
            raise SandboxPolicyViolation("managed_binding_mismatch")
        if (
            runtime.profile != self._profile.name
            or runtime.image_digest != self._image_digest
            or runtime.region != self._region
            or runtime.provider != self._client.name
        ):
            raise SandboxUnavailable("managed_runtime_config_mismatch")
        if runtime.state is RuntimeState.QUARANTINED:
            raise SandboxUnavailable("managed_sandbox_quarantined")
        if runtime.state in {RuntimeState.DETACHED, RuntimeState.FAILED}:
            raise SandboxUnavailable("managed_sandbox_released")
        if allocation.state not in ATTACHABLE_ALLOCATION_STATES:
            raise SandboxUnavailable(f"managed_allocation_not_active:{allocation.state.value}")
        if runtime.state is RuntimeState.SUSPENDED:
            return await self.resume(runtime.sandbox_id)
        async with self._locks.lifecycle_lock(runtime.sandbox_id):
            runtime = await self._reload(runtime.sandbox_id)
            if runtime.state is RuntimeState.RUNNING:
                return self._sandbox(runtime)
            if runtime.state is not RuntimeState.INTENT:
                raise SandboxStateConflict(f"{_STATE_VIEW[runtime.state][0].value}->running")
            physical = await self._ledger.get_physical(runtime.sandbox_id, runtime.incarnation)
            if physical is None or physical.state is not PhysicalState.ACTIVE:
                raise SandboxUnavailable("managed_physical_object_unrecorded")
            ref = self._open_allocation_ref(allocation)
            if ref != physical.provider_ref:
                raise SandboxUnavailable("managed_allocation_reference_mismatch")
            info = await self._describe(ref)
            self._verify(runtime, physical, info)
            try:
                client = await self._connect(runtime.sandbox_id, runtime.stream_epoch, ref, runtime)
                if expected_checksum is not None:
                    result = await client.call("checksum", timeout_sec=self._operation_timeout_sec)
                    if result.get("checksum") != expected_checksum:
                        raise SandboxUnavailable("managed_snapshot_checksum_mismatch")
            except SandboxError as error:
                await self._drop_client(runtime.sandbox_id)
                if str(error) == "managed_snapshot_checksum_mismatch":
                    # Never serve this restore target. The allocation plane owns
                    # the object and removes it with the allocation.
                    await self._write(runtime, state=RuntimeState.FAILED, error_code=str(error))
                raise
            hello_revision = client.hello.revision if client.hello else runtime.workspace_revision
            runtime = await self._write(
                runtime,
                state=RuntimeState.RUNNING,
                workspace_revision=max(runtime.workspace_revision, hello_revision),
                error_code=None,
            )
            return self._sandbox(runtime)

    def _open_allocation_ref(self, allocation: ManagedSandboxAllocation) -> str:
        if allocation.provider_ref is None:
            raise SandboxUnavailable("managed_provider_ref_missing")
        sealed = allocation.provider_ref
        if isinstance(sealed, memoryview):
            sealed = bytes(sealed)
        if not isinstance(sealed, bytes):
            raise SandboxUnavailable("managed_allocation_reference_unverifiable")
        try:
            return self._allocation_cipher(allocation).decrypt(sealed)
        except ProviderReferenceCipherError:
            raise SandboxUnavailable("managed_allocation_reference_unverifiable") from None

    def _verify(
        self, runtime: RuntimeRecord, physical: PhysicalRecord, info: ProviderSandboxInfo
    ) -> None:
        verify_owned(
            self._identity,
            runtime,
            incarnation=physical.incarnation,
            idempotency_key=physical.idempotency_key,
            info=info,
        )
        verify_placement(runtime, info)

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

    # ---- ledger writes ----------------------------------------------------

    async def _reload(self, sandbox_id: str) -> RuntimeRecord:
        runtime = await self._ledger.get(sandbox_id)
        if runtime is None:
            raise SandboxNotFound(sandbox_id)
        return runtime

    async def _write(self, runtime: RuntimeRecord, **changes: Any) -> RuntimeRecord:
        return await self._ledger.update(
            runtime.sandbox_id,
            incarnation=runtime.incarnation,
            expected_version=runtime.version,
            changes=changes,
            now=self._clock(),
        )

    async def _check_fence(self) -> None:
        if self._fence is None:
            return
        try:
            await self._ledger.validate_fence(self._fence, now=self._clock())
        except LedgerConflict as error:
            raise SandboxStateConflict("sandbox_fence_stale") from error

    async def _commit_revision(self, sandbox_id: str, revision: int, *, stream_epoch: int) -> None:
        try:
            await self._ledger.commit_revision(
                sandbox_id,
                stream_epoch=stream_epoch,
                revision=revision,
                fence=self._fence,
                now=self._clock(),
            )
        except LedgerConflict as error:
            # The guest reported this revision; the host could not commit it
            # against this epoch / lease. Say which, never silently continue.
            raise _fence_failure(error) from error

    async def _commit_cursor(
        self, sandbox_id: str, stream: str, cursor: int, *, stream_epoch: int
    ) -> None:
        try:
            await self._ledger.commit_cursor(
                sandbox_id,
                stream_epoch=stream_epoch,
                stream=stream,
                cursor=cursor,
                fence=self._fence,
                now=self._clock(),
            )
        except LedgerConflict as error:
            failure = _fence_failure(error)
            if isinstance(failure, SandboxUnavailable):
                raise SandboxStateConflict("stream_generation_changed") from error
            raise failure from error

    async def _quarantine(self, runtime: RuntimeRecord, code: str) -> None:
        try:
            await self._ledger.update(
                runtime.sandbox_id,
                incarnation=runtime.incarnation,
                expected_version=None,
                changes={"state": RuntimeState.QUARANTINED, "error_code": code},
                now=self._clock(),
            )
        except LedgerConflict:
            pass

    # ---- read ---------------------------------------------------------------

    async def get(self, sandbox_id: str) -> Sandbox:
        runtime = await self._ledger.get(sandbox_id)
        if runtime is None or runtime.state is RuntimeState.DETACHED:
            raise SandboxNotFound(sandbox_id)
        return self._sandbox(runtime)

    def _sandbox(self, runtime: RuntimeRecord) -> Sandbox:
        state, healthy = _STATE_VIEW[runtime.state]
        return Sandbox(
            sandbox_id=runtime.sandbox_id,
            owner_id=runtime.task_id,
            state=state,
            limits=runtime.limits,
            created_at=runtime.created_at,
            updated_at=runtime.updated_at,
            workspace_revision=runtime.workspace_revision,
            provider=self.provider_name,
            image_digest=runtime.image_digest,
            expires_at=runtime.expires_at,
            healthy=healthy,
            last_error_code=runtime.error_code,
        )

    async def _running_record(self, sandbox_id: str) -> RuntimeRecord:
        runtime = await self._ledger.get(sandbox_id)
        if runtime is None or runtime.state is RuntimeState.DETACHED:
            raise SandboxNotFound(sandbox_id)
        if runtime.state is not RuntimeState.RUNNING:
            raise SandboxStateConflict(f"{_STATE_VIEW[runtime.state][0].value}->running")
        if self._clock() >= runtime.expires_at:
            raise SandboxStateConflict("sandbox_expired")
        allocation = await self._ledger.allocation(runtime.allocation_id)
        if (
            allocation is None
            or allocation.state not in ATTACHABLE_ALLOCATION_STATES
            or allocation.generation != runtime.allocation_generation
        ):
            # The allocation plane is cleaning (or replaced) this allocation.
            raise SandboxStateConflict("managed_allocation_released")
        return runtime

    async def _current_physical(self, runtime: RuntimeRecord) -> PhysicalRecord:
        physical = await self._ledger.get_physical(runtime.sandbox_id, runtime.incarnation)
        if physical is None or physical.state is not PhysicalState.ACTIVE:
            raise SandboxUnavailable("managed_physical_object_unrecorded")
        assert physical.provider_ref is not None  # ACTIVE implies a ref
        return physical

    # ---- sessions ----------------------------------------------------------

    async def _client_for(self, runtime: RuntimeRecord) -> SandboxdClient:
        async with self._locks.connect_lock(runtime.sandbox_id):
            cached = self._clients.get(runtime.sandbox_id)
            if cached is not None:
                epoch, client = cached
                if epoch == runtime.stream_epoch and not client.closed:
                    return client
                await client.close()
                self._clients.pop(runtime.sandbox_id, None)
            physical = await self._current_physical(runtime)
            assert physical.provider_ref is not None
            info = await self._describe(physical.provider_ref)
            verify_owned(
                self._identity,
                runtime,
                incarnation=physical.incarnation,
                idempotency_key=physical.idempotency_key,
                info=info,
            )
            if info.status is not ProviderSandboxStatus.RUNNING:
                raise SandboxStateConflict(f"provider_{info.status.value}->running")
            return await self._open_client(
                runtime.sandbox_id, runtime.stream_epoch, physical.provider_ref, runtime
            )

    async def _connect(
        self, sandbox_id: str, stream_epoch: int, provider_ref: str, runtime: RuntimeRecord
    ) -> SandboxdClient:
        async with self._locks.connect_lock(sandbox_id):
            await self._drop_client_unlocked(sandbox_id)
            return await self._open_client(sandbox_id, stream_epoch, provider_ref, runtime)

    async def _open_client(
        self, sandbox_id: str, stream_epoch: int, provider_ref: str, runtime: RuntimeRecord
    ) -> SandboxdClient:
        try:
            channel = await self._client.open_channel(provider_ref)
        except ProviderClientError as error:
            raise _provider_failure(error) from None
        client = SandboxdClient(channel, request_timeout_sec=self._operation_timeout_sec)
        await client.handshake(self._expectation, base_revision=runtime.workspace_revision)
        self._clients[sandbox_id] = (stream_epoch, client)
        return client

    async def _drop_client(self, sandbox_id: str) -> None:
        async with self._locks.connect_lock(sandbox_id):
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
        runtime = await self._ledger.get(sandbox_id)
        if runtime is None or runtime.state is RuntimeState.DETACHED:
            raise SandboxNotFound(sandbox_id)
        return SandboxdSession(_Attachment(self, sandbox_id))

    # ---- suspend / resume ---------------------------------------------------

    async def suspend(self, sandbox_id: str) -> Sandbox:
        async with self._locks.lifecycle_lock(sandbox_id):
            runtime = await self._running_record(sandbox_id)
            await self._check_fence()
            physical = await self._current_physical(runtime)
            ref = physical.provider_ref
            assert ref is not None
            verify_owned(
                self._identity,
                runtime,
                incarnation=physical.incarnation,
                idempotency_key=physical.idempotency_key,
                info=await self._describe(ref),
            )
            checksum = await self._checksum(runtime)
            try:
                outcome = await self._client.suspend(ref)
            except ProviderClientError as error:
                # E2B pause refused as busy: the sandbox still runs and the
                # ledger still says so. Nothing to roll back.
                raise _provider_failure(error) from None
            await self._drop_client(sandbox_id)
            if not outcome.terminated:
                runtime = await self._write(runtime, state=RuntimeState.SUSPENDED)
                return self._sandbox(runtime)
            snapshot = outcome.snapshot
            if snapshot is None:
                raise SandboxUnavailable("managed_suspend_snapshot_missing")
            if not outcome.terminate_confirmed:
                # The snapshot exists but the object may still run (and bill).
                # Keep the runtime RUNNING on an object we can still prove.
                raise SandboxUnavailable("managed_suspend_terminate_unconfirmed")
            await self._ledger.put_snapshot(
                self._snapshot_record(runtime, snapshot.snapshot_ref, snapshot.expires_at, checksum)
            )
            now = self._clock()
            await self._ledger.update_physical(
                sandbox_id,
                physical.incarnation,
                changes={
                    "state": PhysicalState.DESTROYED,
                    "destroy_requested_at": now,
                    "destroy_confirmed_at": now,
                },
                now=now,
            )
            runtime = await self._write(
                runtime,
                state=RuntimeState.SUSPENDED,
                resume_snapshot_ref=snapshot.snapshot_ref,
                resume_snapshot_expires_at=snapshot.expires_at,
                workspace_revision=max(runtime.workspace_revision, checksum[1]),
            )
            return self._sandbox(runtime)

    async def resume(self, sandbox_id: str) -> Sandbox:
        runtime = await self._ledger.get(sandbox_id)
        if runtime is None or runtime.state is RuntimeState.DETACHED:
            raise SandboxNotFound(sandbox_id)
        if runtime.state is not RuntimeState.SUSPENDED:
            raise SandboxStateConflict(f"{_STATE_VIEW[runtime.state][0].value}->running")
        await self._check_fence()
        allocation = await self._ledger.allocation(runtime.allocation_id)
        if (
            allocation is None
            or allocation.state not in ATTACHABLE_ALLOCATION_STATES
            or allocation.generation != runtime.allocation_generation
        ):
            raise SandboxStateConflict("managed_allocation_released")
        if runtime.resume_snapshot_ref is None:
            return await self._warm_resume(runtime)
        return await self._cold_resume(runtime, allocation)

    async def _warm_resume(self, runtime: RuntimeRecord) -> Sandbox:
        async with self._locks.lifecycle_lock(runtime.sandbox_id):
            runtime = await self._reload(runtime.sandbox_id)
            if runtime.state is not RuntimeState.SUSPENDED:
                return self._sandbox(runtime)
            physical = await self._current_physical(runtime)
            ref = physical.provider_ref
            assert ref is not None
            verify_owned(
                self._identity,
                runtime,
                incarnation=physical.incarnation,
                idempotency_key=physical.idempotency_key,
                info=await self._describe(ref),
            )
            try:
                info = await self._client.resume(ref, spec=self._spec(runtime, physical, None))
            except ProviderClientError as error:
                raise _provider_failure(error) from None
            self._verify(runtime, physical, info)
            client = await self._connect(runtime.sandbox_id, runtime.stream_epoch, ref, runtime)
            revision = client.hello.revision if client.hello else runtime.workspace_revision
            runtime = await self._write(
                runtime,
                state=RuntimeState.RUNNING,
                workspace_revision=max(revision, runtime.workspace_revision),
            )
            return self._sandbox(runtime)

    def _spec(
        self,
        runtime: RuntimeRecord,
        physical: PhysicalRecord,
        source_snapshot_ref: str | None,
    ):
        remaining = int((runtime.expires_at - self._clock()).total_seconds())
        if remaining <= 0:
            raise SandboxStateConflict("sandbox_expired")
        return build_create_spec(
            self._identity,
            runtime,
            incarnation=physical.incarnation,
            idempotency_key=physical.idempotency_key,
            lifetime_sec=remaining,
            source_snapshot_ref=source_snapshot_ref,
        )

    async def _cold_resume(
        self, runtime: RuntimeRecord, allocation: ManagedSandboxAllocation
    ) -> Sandbox:
        if self._kill_switch():
            raise SandboxUnavailable("managed_kill_switch")
        snapshot_ref = runtime.resume_snapshot_ref
        assert snapshot_ref is not None
        await self._require_snapshot_available(snapshot_ref, runtime.resume_snapshot_expires_at)
        snapshot = await self._ledger.get_snapshot(
            self._identity.snapshot_id(
                sandbox_id=runtime.sandbox_id,
                incarnation=runtime.incarnation,
                provider_snapshot_ref=snapshot_ref,
            )
        )
        if snapshot is None:
            raise SandboxUnavailable("managed_snapshot_unrecorded")
        async with self._locks.lifecycle_lock(runtime.sandbox_id):
            runtime = await self._reload(runtime.sandbox_id)
            if runtime.state is not RuntimeState.SUSPENDED:
                return self._sandbox(runtime)
            replacement, fresh = await self._reserve_replacement(runtime)
            spec = self._spec(runtime, replacement, snapshot_ref)
            info = None if fresh else await self._rediscover(runtime, replacement)
            if info is None:
                info = await self._provider_resume(runtime, replacement, snapshot_ref, spec)
            try:
                verify_owned(
                    self._identity,
                    runtime,
                    incarnation=replacement.incarnation,
                    idempotency_key=replacement.idempotency_key,
                    info=info,
                )
            except OwnershipMismatch:
                await self._quarantine(runtime, "provider_ownership_mismatch")
                raise
            next_epoch = runtime.stream_epoch + 1
            try:
                verify_placement(runtime, info)
                client = await self._connect(runtime.sandbox_id, next_epoch, info.provider_ref, runtime)
                result = await client.call("checksum", timeout_sec=self._operation_timeout_sec)
                if result.get("checksum") != snapshot.content_checksum:
                    raise SandboxUnavailable("managed_snapshot_checksum_mismatch")
            except SandboxError:
                await self._drop_client(runtime.sandbox_id)
                await self._abandon_replacement(runtime, replacement, info.provider_ref)
                raise
            hello_revision = client.hello.revision if client.hello else runtime.workspace_revision
            now = self._clock()
            active = replace(
                replacement,
                provider_ref=info.provider_ref,
                ref_index=self._identity.ref_index(
                    provider=self._client.name, provider_ref=info.provider_ref
                ),
                state=PhysicalState.ACTIVE,
                updated_at=now,
            )
            try:
                runtime = await self._ledger.commit_incarnation(
                    runtime.sandbox_id,
                    expected_version=runtime.version,
                    replacement=active,
                    allocation_ref_ciphertext=self._allocation_cipher(allocation).encrypt(
                        info.provider_ref
                    ),
                    workspace_revision=max(hello_revision, snapshot.workspace_revision),
                    now=now,
                )
            except LedgerConflict as error:
                await self._drop_client(runtime.sandbox_id)
                raise SandboxStateConflict("managed_incarnation_conflict") from error
            return self._sandbox(runtime)

    async def _reserve_replacement(
        self, runtime: RuntimeRecord
    ) -> tuple[PhysicalRecord, bool]:
        incarnation = runtime.incarnation + 1
        key = self._identity.replacement_idempotency_key(
            sandbox_id=runtime.sandbox_id, incarnation=incarnation
        )
        now = self._clock()
        record = PhysicalRecord(
            sandbox_id=runtime.sandbox_id,
            incarnation=incarnation,
            idempotency_key=key,
            ownership_digest=self._identity.physical_digest(physical_identity(runtime, incarnation)),
            state=PhysicalState.CREATING,
            created_at=now,
            updated_at=now,
        )
        stored = await self._ledger.put_physical(record)
        if stored is not None:
            return stored, True
        existing = await self._ledger.get_physical(runtime.sandbox_id, incarnation)
        if existing is None or existing.idempotency_key != key:
            raise SandboxStateConflict("managed_incarnation_conflict")
        if existing.state is PhysicalState.DESTROYED:
            # A previous attempt was abandoned; the key is spent.
            raise SandboxUnavailable("managed_replacement_abandoned")
        return existing, False

    async def _rediscover(
        self, runtime: RuntimeRecord, physical: PhysicalRecord
    ) -> ProviderSandboxInfo | None:
        try:
            found = await self._client.find(physical.idempotency_key)
        except ProviderClientError as error:
            raise SandboxUnavailable(f"managed_rediscovery_{error.kind.value}") from None
        if len(found) >= 2:
            await self._quarantine(runtime, "duplicate_provider_objects")
            raise SandboxUnavailable("managed_sandbox_quarantined")
        return found[0] if found else None

    async def _provider_resume(
        self,
        runtime: RuntimeRecord,
        physical: PhysicalRecord,
        snapshot_ref: str,
        spec,
    ) -> ProviderSandboxInfo:
        try:
            return await self._client.resume(snapshot_ref, spec=spec)
        except ProviderClientError as error:
            if error.ambiguous or error.kind is ProviderErrorKind.CONFLICT:
                # The replacement may exist. Resolve by rediscovery only; a second
                # create here is how orphans leak money.
                found = await self._rediscover(runtime, physical)
                if found is None:
                    raise SandboxUnavailable("managed_allocation_ambiguous") from None
                return found
            raise _provider_failure(error) from None

    async def _abandon_replacement(
        self, runtime: RuntimeRecord, physical: PhysicalRecord, provider_ref: str
    ) -> None:
        """Destroy a replacement we will not serve; the caller's error wins."""
        now = self._clock()
        try:
            await self._ledger.update_physical(
                runtime.sandbox_id,
                physical.incarnation,
                changes={
                    "provider_ref": provider_ref,
                    "ref_index": self._identity.ref_index(
                        provider=self._client.name, provider_ref=provider_ref
                    ),
                    "state": PhysicalState.DESTROY_PENDING,
                    "destroy_requested_at": now,
                },
                now=now,
            )
            outcome = await self._client.destroy(provider_ref)
        except (ProviderClientError, LedgerConflict):
            return
        if outcome.confirmed or outcome.not_found:
            try:
                await self._ledger.update_physical(
                    runtime.sandbox_id,
                    physical.incarnation,
                    changes={"state": PhysicalState.DESTROYED, "destroy_confirmed_at": self._clock()},
                    now=self._clock(),
                )
            except LedgerConflict:
                pass

    # ---- snapshot -----------------------------------------------------------

    async def _checksum(self, runtime: RuntimeRecord) -> tuple[str, int]:
        client = await self._client_for(runtime)
        result = await client.call("checksum", timeout_sec=self._operation_timeout_sec)
        checksum = result.get("checksum")
        revision = result.get("revision")
        if not isinstance(checksum, str) or not isinstance(revision, int):
            raise SandboxUnavailable("sandboxd_response_invalid")
        return checksum, revision

    def _snapshot_record(
        self,
        runtime: RuntimeRecord,
        provider_snapshot_ref: str,
        expires_at: datetime | None,
        checksum: tuple[str, int],
    ) -> SnapshotRecord:
        return SnapshotRecord(
            snapshot_id=self._identity.snapshot_id(
                sandbox_id=runtime.sandbox_id,
                incarnation=runtime.incarnation,
                provider_snapshot_ref=provider_snapshot_ref,
            ),
            sandbox_id=runtime.sandbox_id,
            allocation_id=runtime.allocation_id,
            task_id=runtime.task_id,
            incarnation=runtime.incarnation,
            provider=self._client.name,
            provider_snapshot_ref=provider_snapshot_ref,
            workspace_revision=checksum[1],
            content_checksum=checksum[0],
            image_digest=runtime.image_digest,
            profile=runtime.profile,
            region=runtime.region,
            limits=runtime.limits,
            created_at=self._clock(),
            expires_at=expires_at,
        )

    async def snapshot(self, sandbox_id: str) -> Snapshot:
        async with self._locks.lifecycle_lock(sandbox_id):
            runtime = await self._running_record(sandbox_id)
            physical = await self._current_physical(runtime)
            ref = physical.provider_ref
            assert ref is not None
            verify_owned(
                self._identity,
                runtime,
                incarnation=physical.incarnation,
                idempotency_key=physical.idempotency_key,
                info=await self._describe(ref),
            )
            checksum = await self._checksum(runtime)
            try:
                provider_snapshot = await self._client.snapshot(ref)
            except ProviderClientError as error:
                raise _provider_failure(error) from None
            if provider_snapshot.connections_dropped:
                # E2B: the sandbox is RUNNING again but every live connection
                # dropped. Reconnect lazily; journals replay from cursors.
                await self._drop_client(sandbox_id)
            snapshot = self._snapshot_record(
                runtime, provider_snapshot.snapshot_ref, provider_snapshot.expires_at, checksum
            )
            await self._ledger.put_snapshot(snapshot)
            await self._commit_revision(sandbox_id, checksum[1], stream_epoch=runtime.stream_epoch)
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
        """Let go. Never deletes the vendor object (the allocation plane does).

        A lease view drops only its own handles. Without a lease the runtime is
        recorded `detached`, so the task can no longer attach to it.
        """
        await self._drop_client(sandbox_id)
        if self._fence is not None:
            return
        runtime = await self._ledger.get(sandbox_id)
        if runtime is None or runtime.state is RuntimeState.DETACHED:
            return
        try:
            await self._ledger.update(
                sandbox_id,
                incarnation=runtime.incarnation,
                expected_version=None,
                changes={"state": RuntimeState.DETACHED},
                now=self._clock(),
            )
        except LedgerConflict:
            return

    async def close(self) -> None:
        for sandbox_id in list(self._clients):
            await self._drop_client(sandbox_id)


@dataclass(frozen=True, slots=True)
class ManagedBackend:
    """Everything a managed provider needs that config alone cannot supply."""

    client: SandboxProviderClient
    ledger: CodingRuntimeLedger
    image_digest: str
    ownership_key: bytes
    allocation_cipher: AllocationCipherFactory
    sandboxd_digest: str | None = None

    def __repr__(self) -> str:  # never print the key
        return f"ManagedBackend(client={self.client.name!r}, image_digest={self.image_digest!r})"


SERVABLE_PROVIDERS = frozenset({"e2b", "modal"})


def _resolve_backend(config, backends: Mapping[str, ManagedBackend] | None) -> ManagedBackend:
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
    return backend


def _identity_for(backend: ManagedBackend) -> ManagedCodingIdentity:
    try:
        return ManagedCodingIdentity(backend.ownership_key)
    except ValueError:
        raise SandboxUnavailable("managed_coding_ownership_key_invalid") from None


def create_managed_sandbox_provider(
    config,
    *,
    backends: Mapping[str, ManagedBackend] | None = None,
) -> ManagedSandboxProvider:
    """Build the provider named by `sandbox.managed.provider`. Fail closed.

    `e2b` and `modal` need an injected `ManagedBackend` (provider client with a
    real SDK binding, durable runtime ledger, pinned image, ownership key, and the
    allocation reference cipher). Any other name -- including `docker` and
    `fake` -- has no guest daemon to serve.
    """
    backend = _resolve_backend(config, backends)
    managed = config.managed
    profile = get_profile(managed.coding_profile)
    digest = managed.sandboxd_digest or backend.sandboxd_digest
    expectation = (
        SandboxdExpectation(bundle_digest=digest) if digest else SandboxdExpectation.bundled()
    )
    return ManagedSandboxProvider(
        client=backend.client,
        ledger=backend.ledger,
        identity=_identity_for(backend),
        allocation_cipher=backend.allocation_cipher,
        profile=profile,
        image_digest=backend.image_digest,
        region=managed.region,
        expectation=expectation,
        allowed_env_names=frozenset(config.execution.allowed_env_names),
        operation_timeout_sec=config.execution.command_timeout_sec,
        max_pty_sessions=config.streams.pty_max_sessions,
        kill_switch=lambda: managed.global_kill_switch,
    )


def create_managed_coding_adapter(
    config,
    *,
    backends: Mapping[str, ManagedBackend] | None = None,
) -> ManagedCodingAllocationAdapter:
    """The allocation-plane adapter for the same backend. Fail closed the same way."""
    backend = _resolve_backend(config, backends)
    return ManagedCodingAllocationAdapter(
        client=backend.client,
        ledger=backend.ledger,
        identity=_identity_for(backend),
    )


__all__ = [
    "AllocationCipherFactory",
    "ManagedBackend",
    "ManagedSandboxProvider",
    "SERVABLE_PROVIDERS",
    "create_managed_coding_adapter",
    "create_managed_sandbox_provider",
]

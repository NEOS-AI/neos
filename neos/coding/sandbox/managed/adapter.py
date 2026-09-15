"""Allocation-plane adapter for managed coding sandboxes.

관리형 할당 평면(`ManagedSandboxAllocationService`, `ManagedSandboxCleanupService`)은
`ManagedSandboxAdapter` 계약으로 vendor object 를 만들고 정리한다. 이 어댑터가 그
계약을 코딩 provider client 위에 구현한다 -- **할당 프로토콜은 바꾸지 않는다**
(docs/PLAN_260913.md §B2 "하지 말 것").

* `allocate` 는 코딩 intent(`coding_managed_runtime`, 상태 `intent`)가 없으면
  vendor 를 부르지 않는다. intent 의 profile / image / region / expiry / 자원 한도가
  할당 요청과 정확히 같아야 한다. physical 행을 **create 전에** 기록하고, 두
  digest(레거시 + HMAC)를 metadata 에 싣는다.
* create 결과가 불명확하면(timeout / transport / 5xx / 409) `ManagedAdapterTimeoutError`
  로 올린다. 할당 서비스가 `RECOVERY_PENDING` 으로 적고 다음 `advance()` 는
  `find_by_idempotency_key` 로 재발견만 한다 -- 두 번째 create 는 없다.
* `destroy` 는 논리 샌드박스의 **모든** incarnation 을 정리한다. Modal cold resume 이
  object 를 교체해도 옛 object 가 청구를 계속하지 않게 한다. 소유권을 증명하지 못한
  object 는 지우지 않는다.
* suspend / resume / snapshot 은 코딩 provider(`provider.py`)가 소유한다. 이
  어댑터로 부르면 거절한다 -- 두 경로가 같은 object 의 lifecycle 을 나눠 가지면
  원장이 둘 중 하나를 모른다.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from neos.coding.managed.adapters.base import (
    AllocationResult,
    DestroyResult,
    LifecycleResult,
    ManagedAdapterCapabilityError,
    ManagedAdapterError,
    ManagedAdapterNotFoundError,
    ManagedAdapterOwnershipError,
    ManagedAdapterTimeoutError,
    ManagedAdapterValidationError,
    ManagedAllocationRequest,
    ManagedNetworkPolicy,
    ProviderHealthProbe,
    ProviderSandboxState,
    SnapshotResult,
)
from neos.coding.managed.domain import (
    ManagedSandboxAllocation,
    ManagedSandboxCapabilities,
    ManagedSandboxState,
    ProviderCircuitState,
)
from neos.coding.sandbox.base import (
    SandboxError,
    SandboxLimits,
    SandboxNotFound,
    SandboxStateConflict,
)
from neos.coding.sandbox.managed.clients.base import (
    ProviderClientError,
    ProviderCreateSpec,
    ProviderErrorKind,
    ProviderSandboxInfo,
    SandboxProviderClient,
)
from neos.coding.sandbox.managed.identity import (
    METADATA_OWNERSHIP_DIGEST,
    ManagedCodingIdentity,
)
from neos.coding.sandbox.managed.ledger import (
    CodingRuntimeLedger,
    LedgerConflict,
    PhysicalRecord,
    PhysicalState,
    RuntimeRecord,
    RuntimeState,
)
from neos.coding.sandbox.managed.ownership import (
    is_owned,
    legacy_digest,
    physical_identity,
    verify_placement,
)
from neos.coding.sandbox.managed.profiles import (
    SandboxProfile,
    get_profile,
    negotiate_profile,
)

# 코딩 lifecycle 은 provider 가 소유하므로 할당 평면에는 pause/snapshot 을 주장하지
# 않는다. 기존 할당 어댑터(e2b.py / modal.py)의 상수는 건드리지 않는다 (§8).
CODING_ALLOCATION_CAPABILITIES = ManagedSandboxCapabilities(
    pause_resume=False,
    filesystem_snapshot=False,
    memory_snapshot=False,
    portable_archive=True,
    network_block_all=True,
    network_allowlist=False,
    region_pin=True,
    idempotent_allocate=True,
    metadata_rediscovery=True,
)


def _resource_envelope(limits: SandboxLimits) -> tuple[float, int, int, int]:
    """vendor object 에 걸리는 자원. 명령별 timeout / 출력 cap 은 sandboxd 가 강제한다."""
    return (limits.cpu_count, limits.memory_bytes, limits.pids, limits.workspace_bytes)


async def prepare_coding_intent(
    *,
    ledger: CodingRuntimeLedger,
    identity: ManagedCodingIdentity,
    allocation: ManagedSandboxAllocation,
    owner_id: str,
    profile: SandboxProfile,
    image_digest: str,
    sandboxd_digest: str,
    limits: SandboxLimits,
    now: datetime,
    source_snapshot_id: str | None = None,
) -> RuntimeRecord:
    """Record the coding intent an admitted allocation will be built from.

    Call it after admission and **before** the allocation's first `advance()`.
    With `source_snapshot_id` the allocation becomes the prepared restore target
    for that snapshot (same task only).
    """
    if allocation.state is not ManagedSandboxState.ADMITTED:
        raise SandboxStateConflict(
            f"managed_intent_requires_admitted:{allocation.state.value}"
        )
    if allocation.absolute_expires_at <= now:
        raise SandboxStateConflict("managed_allocation_expired")
    revision = 0
    if source_snapshot_id is not None:
        snapshot = await ledger.get_snapshot(source_snapshot_id)
        if snapshot is None or snapshot.task_id != allocation.task_id:
            raise SandboxNotFound(source_snapshot_id)
        if snapshot.provider != allocation.provider:
            raise SandboxStateConflict("managed_snapshot_provider_mismatch")
        revision = snapshot.workspace_revision
    record = RuntimeRecord(
        sandbox_id=identity.sandbox_id(allocation_id=allocation.allocation_id),
        allocation_id=allocation.allocation_id,
        allocation_generation=allocation.generation,
        tenant_id=allocation.tenant_id,
        task_id=allocation.task_id,
        owner_id=owner_id,
        provider=allocation.provider,
        image_digest=image_digest,
        sandboxd_digest=sandboxd_digest,
        profile=profile.name,
        network_policy=profile.network.as_record(),
        region=allocation.region,
        limits=limits,
        expires_at=allocation.absolute_expires_at,
        state=RuntimeState.INTENT,
        incarnation=1,
        stream_epoch=1,
        workspace_revision=revision,
        version=1,
        created_at=now,
        updated_at=now,
        source_snapshot_id=source_snapshot_id,
    )
    return await ledger.put_intent(record)


class ManagedCodingAllocationAdapter:
    def __init__(
        self,
        *,
        client: SandboxProviderClient,
        ledger: CodingRuntimeLedger,
        identity: ManagedCodingIdentity,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._ledger = ledger
        self._identity = identity
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def provider(self) -> str:
        return self._client.name

    @property
    def capabilities(self) -> ManagedSandboxCapabilities:
        return CODING_ALLOCATION_CAPABILITIES

    # ---- allocate -------------------------------------------------------------

    async def allocate(self, request: ManagedAllocationRequest) -> AllocationResult:
        runtime = await self._ledger.get_by_allocation(request.allocation_id)
        if runtime is None:
            raise ManagedAdapterValidationError("coding_intent_missing")
        if runtime.state is not RuntimeState.INTENT:
            raise ManagedAdapterValidationError(
                f"coding_intent_not_pending:{runtime.state.value}"
            )
        self._check_request(runtime, request)
        await self._negotiate(runtime)
        source_ref = await self._source_snapshot_ref(runtime)
        physical = await self._reserve_physical(runtime, request.idempotency_key)
        spec = self._spec(
            runtime,
            idempotency_key=request.idempotency_key,
            source_snapshot_ref=source_ref,
        )
        try:
            info = await self._client.create(spec)
        except ProviderClientError as error:
            if error.ambiguous or error.kind is ProviderErrorKind.CONFLICT:
                # The object may exist. The allocation service records
                # RECOVERY_PENDING and the next advance() only rediscovers.
                raise ManagedAdapterTimeoutError("coding_allocate_ambiguous") from None
            raise _adapter_error(error) from None
        await self._adopt(runtime, physical, info)
        return AllocationResult(
            provider_ref=info.provider_ref,
            ownership_digest=request.ownership_digest,
            state=ManagedSandboxState.ACTIVE,
        )

    def _check_request(self, runtime: RuntimeRecord, request: ManagedAllocationRequest) -> None:
        mismatches = []
        if request.image_identity != runtime.image_digest:
            mismatches.append("image")
        if request.region != runtime.region:
            mismatches.append("region")
        if request.network_policy is not ManagedNetworkPolicy.BLOCK_ALL:
            mismatches.append("network")
        if request.absolute_expires_at != runtime.expires_at:
            mismatches.append("expiry")
        if _resource_envelope(request.resource_limits) != _resource_envelope(runtime.limits):
            mismatches.append("limits")
        if request.ownership_digest != legacy_digest(runtime):
            mismatches.append("ownership")
        if mismatches:
            raise ManagedAdapterValidationError(
                "coding_intent_mismatch:" + ",".join(mismatches)
            )

    async def _negotiate(self, runtime: RuntimeRecord) -> None:
        try:
            profile = get_profile(runtime.profile)
            capabilities = await self._client.probe()
            negotiate_profile(profile, capabilities)
        except ProviderClientError as error:
            raise _adapter_error(error) from None
        except SandboxError as error:
            raise ManagedAdapterValidationError(str(error)) from None

    async def _source_snapshot_ref(self, runtime: RuntimeRecord) -> str | None:
        if runtime.source_snapshot_id is None:
            return None
        snapshot = await self._ledger.get_snapshot(runtime.source_snapshot_id)
        if snapshot is None or snapshot.task_id != runtime.task_id:
            raise ManagedAdapterValidationError("coding_snapshot_unrecorded")
        if snapshot.expires_at is not None and self._clock() >= snapshot.expires_at:
            raise ManagedAdapterValidationError("coding_snapshot_expired")
        try:
            exists = await self._client.snapshot_exists(snapshot.provider_snapshot_ref)
        except ProviderClientError as error:
            raise _adapter_error(error) from None
        if not exists:
            raise ManagedAdapterValidationError("coding_snapshot_not_found")
        return snapshot.provider_snapshot_ref

    async def _reserve_physical(
        self, runtime: RuntimeRecord, idempotency_key: str
    ) -> PhysicalRecord:
        now = self._clock()
        record = PhysicalRecord(
            sandbox_id=runtime.sandbox_id,
            incarnation=1,
            idempotency_key=idempotency_key,
            ownership_digest=self._identity.physical_digest(physical_identity(runtime, 1)),
            state=PhysicalState.CREATING,
            created_at=now,
            updated_at=now,
        )
        stored = await self._ledger.put_physical(record)
        if stored is not None:
            return stored
        existing = await self._ledger.get_physical(runtime.sandbox_id, 1)
        if existing is None or existing.idempotency_key != idempotency_key:
            raise ManagedAdapterValidationError("coding_physical_conflict")
        if existing.state is not PhysicalState.CREATING:
            raise ManagedAdapterValidationError(
                f"coding_physical_not_pending:{existing.state.value}"
            )
        return existing

    def _spec(
        self,
        runtime: RuntimeRecord,
        *,
        idempotency_key: str,
        source_snapshot_ref: str | None,
        incarnation: int = 1,
    ) -> ProviderCreateSpec:
        remaining = int((runtime.expires_at - self._clock()).total_seconds())
        if remaining <= 0:
            raise ManagedAdapterValidationError("lifetime already elapsed")
        return build_create_spec(
            self._identity,
            runtime,
            incarnation=incarnation,
            idempotency_key=idempotency_key,
            lifetime_sec=remaining,
            source_snapshot_ref=source_snapshot_ref,
        )

    async def _adopt(
        self, runtime: RuntimeRecord, physical: PhysicalRecord, info: ProviderSandboxInfo
    ) -> None:
        if not is_owned(
            self._identity,
            runtime,
            incarnation=physical.incarnation,
            idempotency_key=physical.idempotency_key,
            info=info,
        ):
            # Not provably ours: never destroy it, never record it.
            raise ManagedAdapterOwnershipError("coding_ownership_mismatch")
        try:
            verify_placement(runtime, info)
        except SandboxError as error:
            # Ours, but not what the profile promised (e.g. network left open).
            # Do not serve it; destroy it and fail the allocation closed.
            await self._abandon(runtime, physical, info.provider_ref)
            raise ManagedAdapterValidationError(str(error)) from None
        await self._ledger.update_physical(
            runtime.sandbox_id,
            physical.incarnation,
            changes={
                "provider_ref": info.provider_ref,
                "ref_index": self._identity.ref_index(
                    provider=self._client.name, provider_ref=info.provider_ref
                ),
                "state": PhysicalState.ACTIVE,
            },
            now=self._clock(),
        )

    async def _abandon(
        self, runtime: RuntimeRecord, physical: PhysicalRecord, provider_ref: str
    ) -> None:
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
            await self._ledger.update_physical(
                runtime.sandbox_id,
                physical.incarnation,
                changes={"state": PhysicalState.DESTROYED, "destroy_confirmed_at": self._clock()},
                now=self._clock(),
            )

    # ---- rediscovery / inspect -----------------------------------------------------

    async def find_by_idempotency_key(self, idempotency_key: str) -> ProviderSandboxState | None:
        physical = await self._ledger.find_physical_by_idempotency_key(idempotency_key)
        try:
            found = await self._client.find(idempotency_key)
        except ProviderClientError:
            raise ManagedAdapterTimeoutError("coding_rediscovery_unavailable") from None
        if physical is None:
            # No coding row: whatever carries this key is not provably ours.
            if not found:
                return None
            return _unverified(found[0], idempotency_key)
        runtime = await self._require_runtime(physical.sandbox_id)
        if len(found) >= 2:
            await self._quarantine(runtime, "duplicate_provider_objects")
            raise ManagedAdapterOwnershipError("coding_duplicate_provider_objects")
        if not found:
            return None
        info = found[0]
        if not is_owned(
            self._identity,
            runtime,
            incarnation=physical.incarnation,
            idempotency_key=idempotency_key,
            info=info,
        ):
            return _unverified(info, idempotency_key)
        await self._adopt(runtime, physical, info)
        return ProviderSandboxState(
            provider_ref=info.provider_ref,
            allocation_id=runtime.allocation_id,
            idempotency_key=idempotency_key,
            state=ManagedSandboxState.ACTIVE,
            ownership_digest=legacy_digest(runtime),
            ownership_verified=True,
        )

    async def inspect(self, provider_ref: str) -> ProviderSandboxState:
        physical = await self._physical_for_ref(provider_ref)
        runtime = await self._require_runtime(physical.sandbox_id)
        try:
            info = await self._client.describe(provider_ref)
        except ProviderClientError as error:
            raise _adapter_error(error) from None
        verified = is_owned(
            self._identity,
            runtime,
            incarnation=physical.incarnation,
            idempotency_key=physical.idempotency_key,
            info=info,
        )
        return ProviderSandboxState(
            provider_ref=provider_ref,
            allocation_id=runtime.allocation_id,
            idempotency_key=physical.idempotency_key,
            state=ManagedSandboxState.ACTIVE,
            ownership_digest=info.metadata.get(METADATA_OWNERSHIP_DIGEST, ""),
            ownership_verified=verified,
        )

    # ---- lifecycle owned by the coding provider -----------------------------------

    async def suspend(self, provider_ref: str) -> LifecycleResult:
        raise ManagedAdapterCapabilityError("coding_lifecycle_owned_by_provider")

    async def resume(self, provider_ref: str) -> LifecycleResult:
        raise ManagedAdapterCapabilityError("coding_lifecycle_owned_by_provider")

    async def snapshot(self, provider_ref: str) -> SnapshotResult:
        raise ManagedAdapterCapabilityError("coding_lifecycle_owned_by_provider")

    # ---- destroy ------------------------------------------------------------------

    async def destroy(self, provider_ref: str, *, ownership_digest: str) -> DestroyResult:
        physical = await self._physical_for_ref(provider_ref)
        runtime = await self._require_runtime(physical.sandbox_id)
        if ownership_digest != legacy_digest(runtime):
            raise ManagedAdapterOwnershipError("ownership_digest_mismatch")
        confirmed = True
        for row in await self._ledger.list_physical(runtime.sandbox_id):
            if row.state is PhysicalState.DESTROYED:
                continue
            if not await self._destroy_physical(runtime, row):
                confirmed = False
        if confirmed and runtime.state is not RuntimeState.DETACHED:
            try:
                await self._ledger.update(
                    runtime.sandbox_id,
                    incarnation=runtime.incarnation,
                    expected_version=None,
                    changes={"state": RuntimeState.DETACHED},
                    now=self._clock(),
                )
            except LedgerConflict:
                pass
        return DestroyResult(confirmed=confirmed, not_found=False, ownership_verified=True)

    async def _destroy_physical(self, runtime: RuntimeRecord, row: PhysicalRecord) -> bool:
        """True once this incarnation is confirmed gone."""
        if row.provider_ref is None:
            # The create may have landed without a recorded ref.
            try:
                found = await self._client.find(row.idempotency_key)
            except ProviderClientError:
                return False
            if not found:
                await self._confirm_destroyed(runtime, row)
                return True
            candidates = found
        else:
            try:
                candidates = (await self._client.describe(row.provider_ref),)
            except ProviderClientError as error:
                if error.kind is ProviderErrorKind.NOT_FOUND:
                    await self._confirm_destroyed(runtime, row)
                    return True
                return False
        for info in candidates:
            if not is_owned(
                self._identity,
                runtime,
                incarnation=row.incarnation,
                idempotency_key=row.idempotency_key,
                info=info,
            ):
                raise ManagedAdapterOwnershipError("coding_ownership_mismatch")
        now = self._clock()
        if row.state is not PhysicalState.DESTROY_PENDING:
            ref = candidates[0].provider_ref
            row = await self._ledger.update_physical(
                runtime.sandbox_id,
                row.incarnation,
                changes={
                    "provider_ref": ref,
                    "ref_index": self._identity.ref_index(provider=self._client.name, provider_ref=ref),
                    "state": PhysicalState.DESTROY_PENDING,
                    "destroy_requested_at": now,
                },
                now=now,
            )
        all_gone = True
        for info in candidates:
            try:
                outcome = await self._client.destroy(info.provider_ref)
            except ProviderClientError as error:
                if error.kind is ProviderErrorKind.NOT_FOUND:
                    continue
                all_gone = False
                continue
            if not (outcome.confirmed or outcome.not_found):
                all_gone = False
        if all_gone:
            await self._confirm_destroyed(runtime, row)
        return all_gone

    async def _confirm_destroyed(self, runtime: RuntimeRecord, row: PhysicalRecord) -> None:
        now = self._clock()
        await self._ledger.update_physical(
            runtime.sandbox_id,
            row.incarnation,
            changes={
                "state": PhysicalState.DESTROYED,
                "destroy_requested_at": row.destroy_requested_at or now,
                "destroy_confirmed_at": now,
            },
            now=now,
        )

    # ---- health --------------------------------------------------------------------

    async def health(self, region: str) -> ProviderHealthProbe:
        try:
            await self._client.probe()
        except ProviderClientError:
            state = ProviderCircuitState.UNAVAILABLE
        else:
            state = ProviderCircuitState.HEALTHY
        return ProviderHealthProbe(provider=self.provider, region=region, state=state)

    # ---- helpers -------------------------------------------------------------------

    async def _physical_for_ref(self, provider_ref: str) -> PhysicalRecord:
        physical = await self._ledger.find_physical_by_ref_index(
            self._identity.ref_index(provider=self._client.name, provider_ref=provider_ref)
        )
        if physical is None:
            # Never act on an object the coding ledger has no record of.
            raise ManagedAdapterOwnershipError("coding_physical_object_unrecorded")
        return physical

    async def _require_runtime(self, sandbox_id: str) -> RuntimeRecord:
        runtime = await self._ledger.get(sandbox_id)
        if runtime is None:
            raise ManagedAdapterOwnershipError("coding_runtime_unrecorded")
        return runtime

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


def build_create_spec(
    identity: ManagedCodingIdentity,
    runtime: RuntimeRecord,
    *,
    incarnation: int,
    idempotency_key: str,
    lifetime_sec: int,
    source_snapshot_ref: str | None,
) -> ProviderCreateSpec:
    physical = physical_identity(runtime, incarnation)
    return ProviderCreateSpec(
        allocation_id=runtime.allocation_id,
        idempotency_key=idempotency_key,
        provider_name=identity.provider_name(
            sandbox_id=runtime.sandbox_id, incarnation=incarnation
        ),
        metadata=identity.metadata(
            physical,
            idempotency_key=idempotency_key,
            legacy_ownership_digest=legacy_digest(runtime),
        ),
        image=runtime.image_digest,
        region=runtime.region,
        network=get_profile(runtime.profile).network,
        limits=runtime.limits,
        lifetime_sec=lifetime_sec,
        source_snapshot_ref=source_snapshot_ref,
    )


def _unverified(info: ProviderSandboxInfo, idempotency_key: str) -> ProviderSandboxState:
    return ProviderSandboxState(
        provider_ref=info.provider_ref,
        allocation_id=info.metadata.get("neos_allocation_id", ""),
        idempotency_key=idempotency_key,
        state=ManagedSandboxState.ACTIVE,
        ownership_digest=info.metadata.get(METADATA_OWNERSHIP_DIGEST, ""),
        ownership_verified=False,
    )


def _adapter_error(error: ProviderClientError) -> ManagedAdapterError:
    if error.kind is ProviderErrorKind.NOT_FOUND:
        return ManagedAdapterNotFoundError(str(error))
    return ManagedAdapterError(str(error))

"""`SandboxProvider` backed by the managed sandbox adapter plane.

The coding loop only knows `SandboxProvider`. This module lets it run on any
`ManagedSandboxAdapter` (Docker shadow, E2B, Modal, ...) without a vendor SDK
reaching the loop:

* lifecycle (allocate / inspect / suspend / resume / snapshot / destroy) goes
  through the adapter and its ownership metadata;
* the workspace session goes through a `ManagedSessionOpener` -- the local
  provider for Docker shadow, a `SandboxExecTransport` for remote providers.

Allocation is behind `ManagedAllocator`. `AdapterDirectAllocator` calls the
adapter directly and enforces the global kill switch, capability, and network
policy. It does **not** reserve quota or write the managed allocation ledger:
routing `create()` through admission + `ManagedSandboxAllocationService`
needs tenant and run context `SandboxProvider.create()` does not carry, and
no concrete `AdmissionPolicy` exists yet. That allocator is follow-up work
(docs/PLAN_260913.md B3), not a silent omission.

Fail-closed rules: an allocate timeout is resolved by rediscovery only (never
a second create); unverified ownership is refused; restore is refused;
suspend on a provider without pause/resume is refused, not ignored.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from neos.coding.managed.adapters.base import (
    ManagedAdapterCapabilityError,
    ManagedAdapterError,
    ManagedAdapterNotFoundError,
    ManagedAdapterTimeoutError,
    ManagedAllocationRequest,
    ManagedNetworkPolicy,
    ManagedSandboxAdapter,
    require_capability,
)
from neos.coding.managed.allocation import provider_error_code
from neos.coding.managed.domain import ManagedSandboxState
from neos.coding.sandbox.base import (
    Sandbox,
    SandboxLimits,
    SandboxNotFound,
    SandboxSession,
    SandboxState,
    SandboxStateConflict,
    SandboxUnavailable,
    Snapshot,
)
from neos.coding.sandbox.events import SandboxWatcherHub
from neos.coding.sandbox.remote import (
    RemoteSandboxSession,
    RemoteSessionRecord,
    SandboxExecTransport,
)

_IDEMPOTENCY_PREFIX = "coding-task"
_PENDING_STATES = frozenset(
    {
        ManagedSandboxState.REQUESTED,
        ManagedSandboxState.ADMITTED,
        ManagedSandboxState.ALLOCATING,
        ManagedSandboxState.RECOVERY_PENDING,
    }
)


def _idempotency_key(owner_id: str, nonce: str) -> str:
    return f"{_IDEMPOTENCY_PREFIX}:{owner_id}:{nonce}"


def owner_from_idempotency_key(key: str) -> str | None:
    """Recover the owning task from provider metadata after a restart."""
    prefix, separator, rest = key.partition(":")
    if prefix != _IDEMPOTENCY_PREFIX or not separator:
        return None
    owner, separator, nonce = rest.rpartition(":")
    if not separator or not owner or not nonce:
        return None
    return owner


def _ownership_digest(allocation_id: str, owner_id: str) -> str:
    return hashlib.sha256(f"{allocation_id}:{owner_id}".encode()).hexdigest()


def _sandbox_state(state: ManagedSandboxState) -> tuple[SandboxState, bool]:
    if state is ManagedSandboxState.ACTIVE:
        return SandboxState.RUNNING, True
    if state is ManagedSandboxState.SUSPENDED:
        return SandboxState.SUSPENDED, True
    if state in _PENDING_STATES:
        return SandboxState.CREATING, False
    return SandboxState.DESTROYED, False


def _unavailable(error: ManagedAdapterError) -> SandboxUnavailable:
    return SandboxUnavailable(f"managed_{provider_error_code(error).value}")


@dataclass(frozen=True, slots=True)
class ManagedAllocationGrant:
    provider_ref: str
    ownership_digest: str
    state: ManagedSandboxState
    expires_at: datetime


class ManagedAllocator(Protocol):
    async def allocate(
        self, *, owner_id: str, limits: SandboxLimits
    ) -> ManagedAllocationGrant: ...


class AdapterDirectAllocator:
    """Allocates straight through the adapter. See the module docstring."""

    def __init__(
        self,
        *,
        adapter: ManagedSandboxAdapter,
        region: str,
        image_identity: str,
        max_lifetime: timedelta,
        kill_switch: Callable[[], bool],
        network_policy: ManagedNetworkPolicy = ManagedNetworkPolicy.BLOCK_ALL,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._adapter = adapter
        self._region = region
        self._image_identity = image_identity
        self._max_lifetime = max_lifetime
        self._kill_switch = kill_switch
        self._network_policy = network_policy
        self._clock = clock or (lambda: datetime.now(UTC))

    async def allocate(
        self, *, owner_id: str, limits: SandboxLimits
    ) -> ManagedAllocationGrant:
        if self._kill_switch():
            raise SandboxUnavailable("managed_kill_switch")
        allocation_id = f"alloc_{uuid.uuid4().hex}"
        key = _idempotency_key(owner_id, uuid.uuid4().hex)
        expires_at = self._clock() + self._max_lifetime
        try:
            request = ManagedAllocationRequest(
                allocation_id=allocation_id,
                idempotency_key=key,
                region=self._region,
                image_identity=self._image_identity,
                resource_limits=limits,
                network_policy=self._network_policy,
                ownership_digest=_ownership_digest(allocation_id, owner_id),
                absolute_expires_at=expires_at,
            )
            result = await self._adapter.allocate(request)
        except ManagedAdapterTimeoutError as error:
            # Ambiguous: the provider may have created it. Rediscover; never
            # create again, or the orphan leaks quota and money.
            found = await self._rediscover(key)
            if found is None:
                raise SandboxUnavailable("managed_allocation_ambiguous") from error
            return ManagedAllocationGrant(
                provider_ref=found.provider_ref,
                ownership_digest=found.ownership_digest,
                state=found.state,
                expires_at=expires_at,
            )
        except ManagedAdapterError as error:
            raise _unavailable(error) from error
        return ManagedAllocationGrant(
            provider_ref=result.provider_ref,
            ownership_digest=result.ownership_digest,
            state=result.state,
            expires_at=expires_at,
        )

    async def _rediscover(self, key: str):
        try:
            found = await self._adapter.find_by_idempotency_key(key)
        except ManagedAdapterError:
            return None
        if found is None or not found.ownership_verified:
            return None
        return found


class ManagedSessionOpener(Protocol):
    async def open(
        self,
        *,
        sandbox: Sandbox,
        ensure_running: Callable[[str], Awaitable[None]],
    ) -> SandboxSession: ...

    async def revision(self, sandbox_id: str) -> int | None: ...

    async def forget(self, sandbox_id: str) -> None: ...

    async def close(self) -> None: ...


class LocalProviderSessionOpener:
    """For adapters whose provider ref is a sandbox id of a local provider.

    Docker shadow allocates through `DockerSandboxProvider.create()`, so the
    session is that provider's own session.
    """

    def __init__(self, provider: Any) -> None:
        self._provider = provider

    @property
    def provider(self) -> Any:
        return self._provider

    async def open(
        self,
        *,
        sandbox: Sandbox,
        ensure_running: Callable[[str], Awaitable[None]],
    ) -> SandboxSession:
        try:
            return await self._provider.open_session(sandbox.sandbox_id)
        except SandboxNotFound:
            reconcile = getattr(self._provider, "reconcile", None)
            if reconcile is None:
                raise
            # A restarted process has no in-memory record for a live container.
            await reconcile()
            return await self._provider.open_session(sandbox.sandbox_id)

    async def revision(self, sandbox_id: str) -> int | None:
        try:
            return (await self._provider.get(sandbox_id)).workspace_revision
        except SandboxNotFound:
            return None

    async def forget(self, sandbox_id: str) -> None:
        return None

    async def close(self) -> None:
        await self._provider.close()


class TransportSessionOpener:
    """Remote sessions over `SandboxExecTransport`, one record per sandbox."""

    def __init__(
        self,
        *,
        transport_for: Callable[[str], SandboxExecTransport],
        allowed_env_names: frozenset[str],
        operation_timeout_sec: float,
        watcher_debounce_sec: float = 0.05,
        watcher_replay_events: int = 1024,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._transport_for = transport_for
        self._allowed_env_names = allowed_env_names
        self._operation_timeout_sec = operation_timeout_sec
        self._watcher_debounce_sec = watcher_debounce_sec
        self._watcher_replay_events = watcher_replay_events
        self._clock = clock or (lambda: datetime.now(UTC))
        self._records: dict[str, RemoteSessionRecord] = {}

    async def open(
        self,
        *,
        sandbox: Sandbox,
        ensure_running: Callable[[str], Awaitable[None]],
    ) -> SandboxSession:
        record = self._records.get(sandbox.sandbox_id)
        if record is None:
            record = RemoteSessionRecord(
                sandbox=sandbox,
                watcher=SandboxWatcherHub(
                    debounce_sec=self._watcher_debounce_sec,
                    replay_events=self._watcher_replay_events,
                ),
            )
            self._records[sandbox.sandbox_id] = record
        return RemoteSandboxSession(
            record=record,
            transport=self._transport_for(sandbox.sandbox_id),
            allowed_env_names=self._allowed_env_names,
            operation_timeout_sec=self._operation_timeout_sec,
            ensure_running=ensure_running,
            clock=self._clock,
        )

    async def revision(self, sandbox_id: str) -> int | None:
        record = self._records.get(sandbox_id)
        return None if record is None else record.sandbox.workspace_revision

    async def forget(self, sandbox_id: str) -> None:
        self._records.pop(sandbox_id, None)

    async def close(self) -> None:
        self._records.clear()


@dataclass(slots=True)
class _ManagedRecord:
    sandbox: Sandbox
    ownership_digest: str


class ManagedSandboxProvider:
    """`SandboxProvider` over a managed adapter. Sandbox id == provider ref."""

    def __init__(
        self,
        *,
        adapter: ManagedSandboxAdapter,
        allocator: ManagedAllocator,
        sessions: ManagedSessionOpener,
        image_identity: str,
        default_limits: SandboxLimits,
        create_timeout_sec: float = 30.0,
        poll_interval_sec: float = 0.5,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._adapter = adapter
        self._allocator = allocator
        self._sessions = sessions
        self._image_identity = image_identity
        self._default_limits = default_limits
        self._create_timeout_sec = create_timeout_sec
        self._poll_interval_sec = poll_interval_sec
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sleep = sleep
        self._records: dict[str, _ManagedRecord] = {}
        self._lock = asyncio.Lock()

    @property
    def provider_name(self) -> str:
        return f"managed:{self._adapter.provider}"

    @property
    def image_identity(self) -> str:
        return self._image_identity

    @property
    def local_provider(self) -> Any | None:
        """The local provider behind a Docker-shadow backend, if any."""
        return getattr(self._sessions, "provider", None)

    async def create(self, *, owner_id: str, limits: SandboxLimits) -> Sandbox:
        grant = await self._allocator.allocate(owner_id=owner_id, limits=limits)
        await self._await_active(grant)
        now = self._clock()
        sandbox = Sandbox(
            sandbox_id=grant.provider_ref,
            owner_id=owner_id,
            state=SandboxState.RUNNING,
            limits=limits,
            created_at=now,
            updated_at=now,
            provider=self.provider_name,
            image_digest=self._image_identity,
            expires_at=grant.expires_at,
        )
        async with self._lock:
            self._records[sandbox.sandbox_id] = _ManagedRecord(
                sandbox=sandbox, ownership_digest=grant.ownership_digest
            )
        return sandbox

    async def _await_active(self, grant: ManagedAllocationGrant) -> ManagedSandboxState:
        state = grant.state
        deadline = self._clock() + timedelta(seconds=self._create_timeout_sec)
        while state in _PENDING_STATES and self._clock() < deadline:
            await self._sleep(self._poll_interval_sec)
            try:
                inspected = await self._adapter.inspect(grant.provider_ref)
            except ManagedAdapterError as error:
                await self._destroy_quietly(grant)
                raise _unavailable(error) from error
            state = inspected.state
        if state is not ManagedSandboxState.ACTIVE:
            # Do not leave a half-created sandbox billing with no owner.
            await self._destroy_quietly(grant)
            raise SandboxUnavailable(f"managed_allocation_not_active:{state.value}")
        return state

    async def _destroy_quietly(self, grant: ManagedAllocationGrant) -> None:
        try:
            await self._destroy_ref(grant.provider_ref, grant.ownership_digest)
        except SandboxUnavailable:
            # Cleanup reconciliation owns unconfirmed destroys; the create
            # failure is the error the caller must see.
            pass

    async def get(self, sandbox_id: str) -> Sandbox:
        try:
            inspected = await self._adapter.inspect(sandbox_id)
        except ManagedAdapterNotFoundError as error:
            async with self._lock:
                self._records.pop(sandbox_id, None)
            raise SandboxNotFound(sandbox_id) from error
        except ManagedAdapterError as error:
            raise _unavailable(error) from error
        if not inspected.ownership_verified:
            raise SandboxUnavailable("managed_ownership_unverified")
        state, healthy = _sandbox_state(inspected.state)
        async with self._lock:
            record = self._records.get(sandbox_id)
            if record is None:
                owner = owner_from_idempotency_key(inspected.idempotency_key)
                if owner is None:
                    raise SandboxNotFound(sandbox_id)
                now = self._clock()
                record = _ManagedRecord(
                    sandbox=Sandbox(
                        sandbox_id=sandbox_id,
                        owner_id=owner,
                        state=state,
                        limits=self._default_limits,
                        created_at=now,
                        updated_at=now,
                        provider=self.provider_name,
                        image_digest=self._image_identity,
                        healthy=healthy,
                    ),
                    ownership_digest=inspected.ownership_digest,
                )
                self._records[sandbox_id] = record
            revision = await self._sessions.revision(sandbox_id)
            record.sandbox = replace(
                record.sandbox,
                state=state,
                healthy=healthy,
                last_error_code=None if healthy else inspected.state.value,
                workspace_revision=(
                    record.sandbox.workspace_revision if revision is None else revision
                ),
                updated_at=self._clock(),
            )
            return record.sandbox

    async def suspend(self, sandbox_id: str) -> Sandbox:
        return await self._pause_or_resume(sandbox_id, suspend=True)

    async def resume(self, sandbox_id: str) -> Sandbox:
        return await self._pause_or_resume(sandbox_id, suspend=False)

    async def _pause_or_resume(self, sandbox_id: str, *, suspend: bool) -> Sandbox:
        await self.get(sandbox_id)
        try:
            require_capability(self._adapter.capabilities, "pause_resume")
        except ManagedAdapterCapabilityError as error:
            raise SandboxStateConflict("managed_pause_unsupported") from error
        try:
            if suspend:
                await self._adapter.suspend(sandbox_id)
            else:
                await self._adapter.resume(sandbox_id)
        except ManagedAdapterError as error:
            raise _unavailable(error) from error
        return await self.get(sandbox_id)

    async def snapshot(self, sandbox_id: str) -> Snapshot:
        sandbox = await self.get(sandbox_id)
        try:
            require_capability(self._adapter.capabilities, "filesystem_snapshot")
            result = await self._adapter.snapshot(sandbox_id)
        except ManagedAdapterCapabilityError as error:
            raise SandboxUnavailable("managed_snapshot_unsupported") from error
        except ManagedAdapterError as error:
            raise _unavailable(error) from error
        return Snapshot(
            snapshot_id=result.snapshot_ref,
            source_sandbox_id=sandbox_id,
            workspace_revision=sandbox.workspace_revision,
            created_at=self._clock(),
            content_checksum=f"provider:{result.snapshot_ref}",
            image_digest=self._image_identity,
        )

    async def restore(self, snapshot_id: str, *, owner_id: str) -> Sandbox:
        # Provider snapshots are not portable workspace archives; the managed
        # recovery path is the archive importer on the control plane.
        raise SandboxUnavailable("managed_restore_unsupported")

    async def destroy(self, sandbox_id: str) -> None:
        async with self._lock:
            record = self._records.pop(sandbox_id, None)
        digest = None if record is None else record.ownership_digest
        if digest is None:
            try:
                inspected = await self._adapter.inspect(sandbox_id)
            except ManagedAdapterNotFoundError:
                await self._sessions.forget(sandbox_id)
                return
            except ManagedAdapterError as error:
                raise _unavailable(error) from error
            if not inspected.ownership_verified:
                raise SandboxUnavailable("managed_ownership_unverified")
            digest = inspected.ownership_digest
        await self._destroy_ref(sandbox_id, digest)
        await self._sessions.forget(sandbox_id)

    async def _destroy_ref(self, provider_ref: str, ownership_digest: str) -> None:
        try:
            result = await self._adapter.destroy(
                provider_ref, ownership_digest=ownership_digest
            )
        except ManagedAdapterNotFoundError:
            return
        except ManagedAdapterError as error:
            raise _unavailable(error) from error
        if result.not_found:
            return
        if not result.confirmed:
            raise SandboxUnavailable("managed_destroy_unconfirmed")

    async def open_session(self, sandbox_id: str) -> SandboxSession:
        sandbox = await self.get(sandbox_id)
        return await self._sessions.open(
            sandbox=sandbox, ensure_running=self._ensure_running
        )

    async def _ensure_running(self, sandbox_id: str) -> None:
        record = self._records.get(sandbox_id)
        if record is None:
            raise SandboxNotFound(sandbox_id)
        if record.sandbox.state is not SandboxState.RUNNING:
            raise SandboxStateConflict(f"{record.sandbox.state.value}->running")

    async def close(self) -> None:
        await self._sessions.close()


@dataclass(frozen=True, slots=True)
class ManagedBackend:
    """One servable managed provider: its adapter, sessions, and image."""

    adapter: ManagedSandboxAdapter
    sessions: ManagedSessionOpener
    image_identity: str


def managed_default_limits(config) -> SandboxLimits:
    resources = config.resources
    execution = config.execution
    return SandboxLimits(
        cpu_count=resources.cpu_count,
        memory_bytes=resources.memory_bytes,
        pids=resources.pids,
        workspace_bytes=resources.workspace_bytes,
        command_timeout_sec=execution.command_timeout_sec,
        max_output_bytes=execution.max_output_bytes,
        max_stdin_bytes=execution.max_stdin_bytes,
    )


def create_managed_sandbox_provider(
    config,
    *,
    backends: Mapping[str, ManagedBackend] | None = None,
    docker_provider_factory: Callable[[], Any] | None = None,
) -> ManagedSandboxProvider:
    """Build the managed provider named by `sandbox.managed.provider`.

    `docker` is servable from config alone (Docker shadow adapter over the
    local Docker provider). `e2b` and `modal` need a bound client: pass a
    `ManagedBackend` in `backends`. Anything else is refused -- the `fake`
    adapter has no workspace to serve.
    """
    managed = config.managed
    if not managed.enabled:
        raise SandboxUnavailable("managed_sandbox_disabled")
    name = managed.provider
    backend = (backends or {}).get(name)
    if backend is None:
        if name == "docker":
            if docker_provider_factory is None:
                raise SandboxUnavailable("managed_docker_provider_missing")
            from neos.coding.managed.adapters.docker_shadow import (
                DockerShadowManagedAdapter,
            )

            docker = docker_provider_factory()
            backend = ManagedBackend(
                adapter=DockerShadowManagedAdapter(
                    provider=docker,
                    claim_lease_seconds=managed.claim_lease_seconds,
                ),
                sessions=LocalProviderSessionOpener(docker),
                image_identity=docker.image_identity,
            )
        elif name in {"e2b", "modal"}:
            raise SandboxUnavailable(f"managed_{name}_client_not_bound")
        else:
            raise SandboxUnavailable(f"managed_provider_not_servable:{name}")
    return ManagedSandboxProvider(
        adapter=backend.adapter,
        allocator=AdapterDirectAllocator(
            adapter=backend.adapter,
            region=managed.region,
            image_identity=backend.image_identity,
            max_lifetime=timedelta(seconds=config.lifecycle.max_lifetime_sec),
            kill_switch=lambda: managed.global_kill_switch,
        ),
        sessions=backend.sessions,
        image_identity=backend.image_identity,
        default_limits=managed_default_limits(config),
        create_timeout_sec=config.lifecycle.create_timeout_sec,
    )

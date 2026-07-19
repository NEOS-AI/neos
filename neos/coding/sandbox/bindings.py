from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Callable, Protocol

from neos.coding.sandbox.base import (
    Sandbox,
    SandboxLimits,
    SandboxNotFound,
    SandboxProvider,
    SandboxSession,
    SandboxState,
)


@dataclass(frozen=True, slots=True)
class SandboxBinding:
    task_id: str
    run_id: str
    sandbox_id: str
    provider: str
    image_digest: str | None
    workspace_revision: str
    latest_snapshot_id: str | None
    health_state: str
    mutation_count: int
    version: int


@dataclass(frozen=True, slots=True)
class BoundSandboxSession:
    binding: SandboxBinding
    session: SandboxSession


class SandboxBindingError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class SandboxBindingRepository(Protocol):
    async def get(self, task_id: str) -> SandboxBinding | None: ...

    async def create(
        self, binding: SandboxBinding, *, now: datetime
    ) -> bool: ...

    async def replace(
        self,
        binding: SandboxBinding,
        *,
        expected_version: int,
        now: datetime,
    ) -> SandboxBinding | None: ...

    async def delete(self, task_id: str, *, expected_version: int) -> bool: ...


class SandboxBindingService:
    def __init__(
        self,
        *,
        repository: SandboxBindingRepository,
        provider: SandboxProvider,
        limits: SandboxLimits,
        snapshot_cadence: int,
        image_digest: str | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if snapshot_cadence < 1:
            raise ValueError("snapshot_cadence must be positive")
        self._repository = repository
        self._provider = provider
        self._limits = limits
        self._snapshot_cadence = snapshot_cadence
        self._image_digest = image_digest
        self._clock = clock or (lambda: datetime.now(UTC))

    async def resolve(self, task_id: str, run_id: str) -> BoundSandboxSession:
        current = await self._repository.get(task_id)
        if current is None:
            return await self._create_and_bind(task_id, run_id)
        return await self._resolve_existing(current, run_id)

    async def _create_and_bind(
        self, task_id: str, run_id: str
    ) -> BoundSandboxSession:
        created = await self._provider.create(owner_id=task_id, limits=self._limits)
        candidate = self._binding_from_sandbox(task_id, run_id, created)
        if not await self._repository.create(candidate, now=self._clock()):
            await self._provider.destroy(created.sandbox_id)
            return await self.resolve(task_id, run_id)
        session = await self._provider.open_session(created.sandbox_id)
        return BoundSandboxSession(candidate, session)

    async def _resolve_existing(
        self, current: SandboxBinding, run_id: str
    ) -> BoundSandboxSession:
        self._verify_image(current.image_digest)
        try:
            sandbox = await self._provider.get(current.sandbox_id)
        except SandboxNotFound:
            return await self._restore(current, run_id)
        self._verify_sandbox(current, sandbox)
        if sandbox.state is SandboxState.SUSPENDED:
            sandbox = await self._provider.resume(sandbox.sandbox_id)
        if sandbox.state is not SandboxState.RUNNING or not sandbox.healthy:
            raise SandboxBindingError("sandbox_unhealthy", retryable=True)
        if current.run_id != run_id:
            rebound = await self._repository.replace(
                replace(current, run_id=run_id),
                expected_version=current.version,
                now=self._clock(),
            )
            if rebound is None:
                return await self.resolve(current.task_id, run_id)
            current = rebound
        session = await self._provider.open_session(sandbox.sandbox_id)
        return BoundSandboxSession(current, session)

    async def _restore(
        self, current: SandboxBinding, run_id: str
    ) -> BoundSandboxSession:
        if current.latest_snapshot_id is None:
            raise SandboxBindingError("sandbox_unrecoverable", retryable=True)
        restored = await self._provider.restore(
            current.latest_snapshot_id, owner_id=current.task_id
        )
        try:
            self._verify_image(restored.image_digest)
            candidate = replace(
                current,
                run_id=run_id,
                sandbox_id=restored.sandbox_id,
                provider=restored.provider,
                image_digest=restored.image_digest,
                workspace_revision=str(restored.workspace_revision),
                health_state="healthy",
                mutation_count=0,
            )
            updated = await self._repository.replace(
                candidate,
                expected_version=current.version,
                now=self._clock(),
            )
            if updated is None:
                await self._provider.destroy(restored.sandbox_id)
                return await self.resolve(current.task_id, run_id)
            session = await self._provider.open_session(restored.sandbox_id)
            return BoundSandboxSession(updated, session)
        except Exception:
            # A failed compatibility check leaves no durable owner for the restore.
            if (await self._repository.get(current.task_id)) == current:
                await self._provider.destroy(restored.sandbox_id)
            raise

    async def record_mutation(
        self, task_id: str, *, workspace_revision: int
    ) -> SandboxBinding:
        current = await self._require_binding(task_id)
        mutation_count = current.mutation_count + 1
        snapshot_id = current.latest_snapshot_id
        if mutation_count >= self._snapshot_cadence:
            snapshot = await self._provider.snapshot(current.sandbox_id)
            snapshot_id = snapshot.snapshot_id
            mutation_count = 0
        candidate = replace(
            current,
            workspace_revision=str(workspace_revision),
            latest_snapshot_id=snapshot_id,
            mutation_count=mutation_count,
        )
        updated = await self._repository.replace(
            candidate,
            expected_version=current.version,
            now=self._clock(),
        )
        if updated is None:
            return await self._require_binding(task_id)
        return updated

    async def suspend(self, task_id: str) -> SandboxBinding:
        current = await self._require_binding(task_id)
        snapshot = await self._provider.snapshot(current.sandbox_id)
        candidate = replace(
            current,
            workspace_revision=str(snapshot.workspace_revision),
            latest_snapshot_id=snapshot.snapshot_id,
            health_state="suspended",
            mutation_count=0,
        )
        updated = await self._repository.replace(
            candidate,
            expected_version=current.version,
            now=self._clock(),
        )
        if updated is None:
            raise SandboxBindingError("sandbox_binding_conflict", retryable=True)
        await self._provider.suspend(current.sandbox_id)
        return updated

    async def destroy_terminal(self, task_id: str) -> None:
        current = await self._repository.get(task_id)
        if current is None:
            return
        deleted = await self._repository.delete(
            task_id, expected_version=current.version
        )
        if deleted:
            await self._provider.destroy(current.sandbox_id)

    async def _require_binding(self, task_id: str) -> SandboxBinding:
        current = await self._repository.get(task_id)
        if current is None:
            raise SandboxBindingError("sandbox_binding_missing", retryable=True)
        return current

    def _binding_from_sandbox(
        self, task_id: str, run_id: str, sandbox: Sandbox
    ) -> SandboxBinding:
        self._verify_image(sandbox.image_digest)
        return SandboxBinding(
            task_id=task_id,
            run_id=run_id,
            sandbox_id=sandbox.sandbox_id,
            provider=sandbox.provider,
            image_digest=sandbox.image_digest,
            workspace_revision=str(sandbox.workspace_revision),
            latest_snapshot_id=None,
            health_state="healthy",
            mutation_count=0,
            version=1,
        )

    def _verify_sandbox(
        self, binding: SandboxBinding, sandbox: Sandbox
    ) -> None:
        if sandbox.provider != binding.provider:
            raise SandboxBindingError("sandbox_provider_mismatch", retryable=False)
        if sandbox.image_digest != binding.image_digest:
            raise SandboxBindingError("sandbox_image_mismatch", retryable=False)
        self._verify_image(sandbox.image_digest)

    def _verify_image(self, image_digest: str | None) -> None:
        if self._image_digest is not None and image_digest != self._image_digest:
            raise SandboxBindingError("sandbox_image_mismatch", retryable=False)

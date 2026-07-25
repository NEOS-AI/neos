from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
import json
from typing import Any

from neos.coding.managed.adapters.base import (
    AllocationResult,
    DestroyResult,
    LifecycleResult,
    ManagedAdapterNotFoundError,
    ManagedAdapterOwnershipError,
    ManagedAdapterValidationError,
    ManagedAllocationRequest,
    ProviderHealthProbe,
    ProviderSandboxState,
    SnapshotResult,
    require_capability,
    validate_network_policy,
)
from neos.coding.managed.domain import (
    ManagedSandboxCapabilities,
    ManagedSandboxState,
    ProviderCircuitState,
)
from neos.coding.sandbox.base import SandboxNotFound, SandboxState
from neos.coding.sandbox.docker import DockerSandboxProvider


ALLOCATION_ID_LABEL = "com.neos.coding.managed-allocation-id"
IDEMPOTENCY_KEY_LABEL = "com.neos.coding.managed-idempotency-key"
OWNERSHIP_DIGEST_LABEL = "com.neos.coding.managed-ownership-digest"
SANDBOX_ID_LABEL = "com.neos.coding.sandbox-id"
OWNER_ID_LABEL = "com.neos.coding.owner-id"

_MANAGED_LABELS = (
    ALLOCATION_ID_LABEL,
    IDEMPOTENCY_KEY_LABEL,
    OWNERSHIP_DIGEST_LABEL,
)


class _ManagedLabelRunner:
    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate
        self._labels: ContextVar[Mapping[str, str] | None] = ContextVar(
            "managed_docker_labels",
            default=None,
        )

    @contextmanager
    def binding(self, labels: Mapping[str, str]):
        token = self._labels.set(labels)
        try:
            yield
        finally:
            self._labels.reset(token)

    async def run(self, *args: str, **kwargs):
        labels = self._labels.get()
        if labels and args[0] == "create":
            values = list(args)
            insertion = values.index("--user")
            for key, value in reversed(tuple(labels.items())):
                values[insertion:insertion] = ["--label", f"{key}={value}"]
            args = tuple(values)
        elif labels and args[:2] == ("volume", "create"):
            values = list(args)
            insertion = len(values) - 1
            for key, value in reversed(tuple(labels.items())):
                values[insertion:insertion] = ["--label", f"{key}={value}"]
            args = tuple(values)
        return await self._delegate.run(*args, **kwargs)


class DockerShadowManagedAdapter:
    __slots__ = ("_allocation_lock", "_capabilities", "_provider", "_runner")

    def __init__(self, *, provider: DockerSandboxProvider) -> None:
        self._provider = provider
        self._allocation_lock = asyncio.Lock()
        original_runner = provider._runner
        self._runner = (
            original_runner
            if isinstance(original_runner, _ManagedLabelRunner)
            else _ManagedLabelRunner(original_runner)
        )
        provider._runner = self._runner
        self._capabilities = ManagedSandboxCapabilities(
            pause_resume=True,
            filesystem_snapshot=True,
            memory_snapshot=False,
            portable_archive=True,
            network_block_all=provider._config.network_mode == "none",
            network_allowlist=False,
            region_pin=False,
            idempotent_allocate=True,
            metadata_rediscovery=True,
        )

    @property
    def provider(self) -> str:
        return "docker"

    @property
    def capabilities(self) -> ManagedSandboxCapabilities:
        return self._capabilities

    async def allocate(
        self,
        request: ManagedAllocationRequest,
    ) -> AllocationResult:
        require_capability(self.capabilities, "idempotent_allocate")
        validate_network_policy(self.capabilities, request.network_policy)
        if request.region != "local":
            raise ManagedAdapterValidationError(
                "docker shadow supports only the local region"
            )
        if request.image_identity != self._provider._config.image:
            raise ManagedAdapterValidationError("image_identity_mismatch")
        async with self._allocation_lock:
            existing = await self.find_by_idempotency_key(request.idempotency_key)
            if existing is not None:
                if (
                    existing.allocation_id != request.allocation_id
                    or existing.ownership_digest != request.ownership_digest
                ):
                    raise ManagedAdapterOwnershipError("idempotency_metadata_mismatch")
                return AllocationResult(
                    provider_ref=existing.provider_ref,
                    ownership_digest=existing.ownership_digest,
                    state=existing.state,
                )
            labels = {
                ALLOCATION_ID_LABEL: request.allocation_id,
                IDEMPOTENCY_KEY_LABEL: request.idempotency_key,
                OWNERSHIP_DIGEST_LABEL: request.ownership_digest,
            }
            with self._runner.binding(labels):
                sandbox = await self._provider.create(
                    owner_id=request.ownership_digest,
                    limits=request.resource_limits,
                )
            return AllocationResult(
                provider_ref=sandbox.sandbox_id,
                ownership_digest=request.ownership_digest,
                state=self._managed_state(sandbox.state),
            )

    async def inspect(self, provider_ref: str) -> ProviderSandboxState:
        document = await self._inspect_document(provider_ref)
        return self._state_from_document(document)

    async def suspend(self, provider_ref: str) -> LifecycleResult:
        require_capability(self.capabilities, "pause_resume")
        await self.inspect(provider_ref)
        await self._ensure_provider_record(provider_ref)
        sandbox = await self._provider.suspend(provider_ref)
        return LifecycleResult(
            provider_ref=provider_ref,
            state=self._managed_state(sandbox.state),
        )

    async def resume(self, provider_ref: str) -> LifecycleResult:
        require_capability(self.capabilities, "pause_resume")
        await self.inspect(provider_ref)
        await self._ensure_provider_record(provider_ref)
        sandbox = await self._provider.resume(provider_ref)
        return LifecycleResult(
            provider_ref=provider_ref,
            state=self._managed_state(sandbox.state),
        )

    async def snapshot(self, provider_ref: str) -> SnapshotResult:
        require_capability(self.capabilities, "filesystem_snapshot")
        state = await self.inspect(provider_ref)
        await self._ensure_provider_record(provider_ref)
        snapshot = await self._provider.snapshot(provider_ref)
        return SnapshotResult(
            provider_ref=provider_ref,
            snapshot_ref=snapshot.snapshot_id,
            state=state.state,
        )

    async def destroy(
        self,
        provider_ref: str,
        *,
        ownership_digest: str,
    ) -> DestroyResult:
        state = await self.inspect(provider_ref)
        if not state.ownership_verified or state.ownership_digest != ownership_digest:
            raise ManagedAdapterOwnershipError("ownership_digest_mismatch")
        await self._ensure_provider_record(provider_ref)
        await self._provider.destroy(provider_ref)
        return DestroyResult(
            confirmed=True,
            ownership_verified=True,
        )

    async def find_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> ProviderSandboxState | None:
        require_capability(self.capabilities, "metadata_rediscovery")
        listed = await self._runner.run(
            "ps",
            "--all",
            "--filter",
            f"label={IDEMPOTENCY_KEY_LABEL}={idempotency_key}",
            "--format",
            "{{.ID}}",
            timeout_sec=self._provider._config.operation_timeout_sec,
        )
        container_ids = tuple(
            value for value in listed.stdout.decode().splitlines() if value
        )
        if not container_ids:
            return None
        inspected = await self._runner.run(
            "inspect",
            *container_ids,
            timeout_sec=self._provider._config.operation_timeout_sec,
        )
        documents = self._decode_inspection(inspected.stdout)
        matches = [
            self._state_from_document(document)
            for document in documents
            if (document.get("Config", {}).get("Labels") or {}).get(
                IDEMPOTENCY_KEY_LABEL
            )
            == idempotency_key
        ]
        if len(matches) != 1:
            raise ManagedAdapterOwnershipError("idempotency_metadata_not_unique")
        return matches[0]

    async def health(self, region: str) -> ProviderHealthProbe:
        await self._runner.run(
            "info",
            "--format",
            "{{json .ServerVersion}}",
            timeout_sec=self._provider._config.operation_timeout_sec,
        )
        return ProviderHealthProbe(
            provider=self.provider,
            region=region,
            state=ProviderCircuitState.HEALTHY,
        )

    async def _inspect_document(self, provider_ref: str) -> dict[str, Any]:
        inspected = await self._runner.run(
            "inspect",
            f"neos-{provider_ref}",
            timeout_sec=self._provider._config.operation_timeout_sec,
        )
        documents = self._decode_inspection(inspected.stdout)
        if len(documents) != 1:
            raise ManagedAdapterNotFoundError(provider_ref)
        document = documents[0]
        labels = document.get("Config", {}).get("Labels") or {}
        if labels.get(SANDBOX_ID_LABEL) != provider_ref:
            raise ManagedAdapterOwnershipError("sandbox_id_label_mismatch")
        return document

    def _state_from_document(
        self,
        document: dict[str, Any],
    ) -> ProviderSandboxState:
        labels = document.get("Config", {}).get("Labels") or {}
        if any(not labels.get(name) for name in _MANAGED_LABELS):
            raise ManagedAdapterOwnershipError("managed_metadata_missing")
        provider_ref = labels.get(SANDBOX_ID_LABEL)
        if not provider_ref:
            raise ManagedAdapterOwnershipError("sandbox_id_label_missing")
        if labels.get(OWNER_ID_LABEL) != labels[OWNERSHIP_DIGEST_LABEL]:
            raise ManagedAdapterOwnershipError("ownership_label_mismatch")
        running = bool(document.get("State", {}).get("Running"))
        return ProviderSandboxState(
            provider_ref=provider_ref,
            allocation_id=labels[ALLOCATION_ID_LABEL],
            idempotency_key=labels[IDEMPOTENCY_KEY_LABEL],
            state=(
                ManagedSandboxState.ACTIVE if running else ManagedSandboxState.SUSPENDED
            ),
            ownership_digest=labels[OWNERSHIP_DIGEST_LABEL],
            ownership_verified=True,
        )

    async def _ensure_provider_record(self, provider_ref: str) -> None:
        try:
            await self._provider.get(provider_ref)
        except SandboxNotFound:
            await self._provider.reconcile()
            try:
                await self._provider.get(provider_ref)
            except SandboxNotFound as error:
                raise ManagedAdapterNotFoundError(provider_ref) from error

    @staticmethod
    def _decode_inspection(payload: bytes) -> list[dict[str, Any]]:
        try:
            documents = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ManagedAdapterOwnershipError(
                "docker_inspect_output_invalid"
            ) from error
        if not isinstance(documents, list) or not all(
            isinstance(document, dict) for document in documents
        ):
            raise ManagedAdapterOwnershipError("docker_inspect_output_invalid")
        return documents

    @staticmethod
    def _managed_state(state: SandboxState) -> ManagedSandboxState:
        if state is SandboxState.RUNNING:
            return ManagedSandboxState.ACTIVE
        if state is SandboxState.SUSPENDED:
            return ManagedSandboxState.SUSPENDED
        raise ManagedAdapterValidationError(
            f"unsupported docker sandbox state: {state.value}"
        )

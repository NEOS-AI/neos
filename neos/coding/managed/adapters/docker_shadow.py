from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
from typing import Any
import uuid

from neos.coding.managed.adapters.base import (
    AllocationResult,
    DestroyResult,
    LifecycleResult,
    ManagedAdapterNotFoundError,
    ManagedAdapterOwnershipError,
    ManagedAdapterTimeoutError,
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
from neos.coding.sandbox.base import SandboxError, SandboxNotFound, SandboxState
from neos.coding.sandbox.docker import DockerSandboxProvider


ALLOCATION_ID_LABEL = "com.neos.coding.managed-allocation-id"
IDEMPOTENCY_KEY_LABEL = "com.neos.coding.managed-idempotency-key"
OWNERSHIP_DIGEST_LABEL = "com.neos.coding.managed-ownership-digest"
SANDBOX_ID_LABEL = "com.neos.coding.sandbox-id"
OWNER_ID_LABEL = "com.neos.coding.owner-id"
CLAIM_TOKEN_LABEL = "com.neos.coding.managed-claim-token"

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
                return self._replayed_allocation(existing, request)
            labels = {
                ALLOCATION_ID_LABEL: request.allocation_id,
                IDEMPOTENCY_KEY_LABEL: request.idempotency_key,
                OWNERSHIP_DIGEST_LABEL: request.ownership_digest,
            }
            claim_token = uuid.uuid4().hex
            claim_name = self._claim_volume_name(request.idempotency_key)
            await self._runner.run(
                "volume",
                "create",
                *self._label_args(
                    {
                        **labels,
                        CLAIM_TOKEN_LABEL: claim_token,
                    }
                ),
                claim_name,
                timeout_sec=self._provider._config.create_timeout_sec,
            )
            claim = await self._inspect_volume(claim_name)
            self._verify_resource_metadata(claim, labels, volume=True)
            if claim["Labels"].get(CLAIM_TOKEN_LABEL) != claim_token:
                return await self._wait_for_claim_owner(request)
            with self._runner.binding(labels):
                sandbox = await self._provider.create(
                    owner_id=request.ownership_digest,
                    limits=request.resource_limits,
                )
            ownership_name = self._ownership_volume_name(sandbox.sandbox_id)
            ownership_labels = {
                **labels,
                SANDBOX_ID_LABEL: sandbox.sandbox_id,
                CLAIM_TOKEN_LABEL: claim_token,
            }
            await self._runner.run(
                "volume",
                "create",
                *self._label_args(ownership_labels),
                ownership_name,
                timeout_sec=self._provider._config.create_timeout_sec,
            )
            ownership = await self._inspect_volume(ownership_name)
            self._verify_resource_metadata(
                ownership,
                ownership_labels,
                volume=True,
            )
            await self._remove_volume_if_present(claim_name)
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
        container_name = f"neos-{provider_ref}"
        workspace_name = f"neos-sandbox-{provider_ref}"
        ownership_name = self._ownership_volume_name(provider_ref)
        container = await self._inspect_container_optional(container_name)
        workspace = await self._inspect_volume_optional(workspace_name)
        ownership = await self._inspect_volume_optional(ownership_name)
        resources = (
            (container, False, True),
            (workspace, True, True),
            (ownership, True, True),
        )
        expected = self._expected_destroy_metadata(
            resources,
            provider_ref=provider_ref,
            ownership_digest=ownership_digest,
        )
        claim_name = self._claim_volume_name(expected[IDEMPOTENCY_KEY_LABEL])
        claim = await self._inspect_volume_optional(claim_name)
        if claim is not None:
            self._verify_resource_metadata(claim, expected, volume=True)
        if container is not None:
            await self._ensure_provider_record(provider_ref)
            await self._provider.destroy(provider_ref)
        await self._remove_container_if_present(container_name)
        await self._remove_volume_if_present(workspace_name)
        primary_remaining = (
            await self._inspect_container_optional(container_name),
            await self._inspect_volume_optional(workspace_name),
        )
        if all(resource is None for resource in primary_remaining):
            await self._remove_volume_if_present(ownership_name)
            await self._remove_volume_if_present(claim_name)
        remaining = (
            *primary_remaining,
            await self._inspect_volume_optional(ownership_name),
            await self._inspect_volume_optional(claim_name),
        )
        confirmed = all(resource is None for resource in remaining)
        return DestroyResult(
            confirmed=confirmed,
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
        document = await self._inspect_container_optional(f"neos-{provider_ref}")
        if document is None:
            raise ManagedAdapterNotFoundError(provider_ref)
        labels = document.get("Config", {}).get("Labels") or {}
        if labels.get(SANDBOX_ID_LABEL) != provider_ref:
            raise ManagedAdapterOwnershipError("sandbox_id_label_mismatch")
        return document

    async def _wait_for_claim_owner(
        self,
        request: ManagedAllocationRequest,
    ) -> AllocationResult:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._provider._config.create_timeout_sec
        while loop.time() < deadline:
            existing = await self.find_by_idempotency_key(request.idempotency_key)
            if existing is not None:
                replay = self._replayed_allocation(existing, request)
                ownership = await self._inspect_volume_optional(
                    self._ownership_volume_name(existing.provider_ref)
                )
                if ownership is None:
                    await asyncio.sleep(0.01)
                    continue
                self._verify_resource_metadata(
                    ownership,
                    {
                        ALLOCATION_ID_LABEL: request.allocation_id,
                        IDEMPOTENCY_KEY_LABEL: request.idempotency_key,
                        OWNERSHIP_DIGEST_LABEL: request.ownership_digest,
                        SANDBOX_ID_LABEL: existing.provider_ref,
                    },
                    volume=True,
                )
                return replay
            await asyncio.sleep(0.01)
        raise ManagedAdapterTimeoutError("idempotent_allocation_claim_pending")

    @staticmethod
    def _replayed_allocation(
        existing: ProviderSandboxState,
        request: ManagedAllocationRequest,
    ) -> AllocationResult:
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

    async def _inspect_container_optional(
        self,
        name: str,
    ) -> dict[str, Any] | None:
        inspected = await self._runner.run(
            "inspect",
            name,
            timeout_sec=self._provider._config.operation_timeout_sec,
            allowed_exit_codes=(0, 1),
        )
        if inspected.exit_code == 1:
            return None
        documents = self._decode_inspection(inspected.stdout)
        if len(documents) != 1:
            raise ManagedAdapterOwnershipError("docker_inspect_output_invalid")
        return documents[0]

    async def _inspect_volume(self, name: str) -> dict[str, Any]:
        document = await self._inspect_volume_optional(name)
        if document is None:
            raise ManagedAdapterOwnershipError("managed_resource_missing")
        return document

    async def _inspect_volume_optional(
        self,
        name: str,
    ) -> dict[str, Any] | None:
        inspected = await self._runner.run(
            "volume",
            "inspect",
            name,
            timeout_sec=self._provider._config.operation_timeout_sec,
            allowed_exit_codes=(0, 1),
        )
        if inspected.exit_code == 1:
            return None
        documents = self._decode_inspection(inspected.stdout)
        if len(documents) != 1:
            raise ManagedAdapterOwnershipError("docker_inspect_output_invalid")
        return documents[0]

    async def _remove_container_if_present(self, name: str) -> None:
        if await self._inspect_container_optional(name) is None:
            return
        try:
            await self._runner.run(
                "rm",
                "--force",
                name,
                timeout_sec=self._provider._config.operation_timeout_sec,
            )
        except SandboxError:
            return

    async def _remove_volume_if_present(self, name: str) -> None:
        if await self._inspect_volume_optional(name) is None:
            return
        try:
            await self._runner.run(
                "volume",
                "rm",
                name,
                timeout_sec=self._provider._config.operation_timeout_sec,
            )
        except SandboxError:
            return

    @staticmethod
    def _verify_resource_metadata(
        document: dict[str, Any],
        expected: Mapping[str, str],
        *,
        volume: bool,
    ) -> None:
        labels = (
            document.get("Labels")
            if volume
            else document.get("Config", {}).get("Labels")
        ) or {}
        if any(labels.get(key) != value for key, value in expected.items()):
            raise ManagedAdapterOwnershipError("managed_resource_metadata_mismatch")

    @classmethod
    def _expected_destroy_metadata(
        cls,
        resources: tuple[
            tuple[dict[str, Any] | None, bool, bool],
            ...,
        ],
        *,
        provider_ref: str,
        ownership_digest: str,
    ) -> dict[str, str]:
        expected: dict[str, str] | None = None
        for document, volume, binds_provider_ref in resources:
            if document is None:
                continue
            labels = cls._resource_labels(document, volume=volume)
            if expected is None:
                if labels.get(OWNERSHIP_DIGEST_LABEL) != ownership_digest:
                    raise ManagedAdapterOwnershipError("ownership_digest_mismatch")
                try:
                    expected = {
                        ALLOCATION_ID_LABEL: labels[ALLOCATION_ID_LABEL],
                        IDEMPOTENCY_KEY_LABEL: labels[IDEMPOTENCY_KEY_LABEL],
                        OWNERSHIP_DIGEST_LABEL: ownership_digest,
                    }
                except KeyError as error:
                    raise ManagedAdapterOwnershipError(
                        "managed_resource_metadata_missing"
                    ) from error
            cls._verify_resource_metadata(
                document,
                expected,
                volume=volume,
            )
            if binds_provider_ref and labels.get(SANDBOX_ID_LABEL) != provider_ref:
                raise ManagedAdapterOwnershipError("managed_resource_metadata_mismatch")
            if not volume and labels.get(OWNER_ID_LABEL) != ownership_digest:
                raise ManagedAdapterOwnershipError("managed_resource_metadata_mismatch")
        if expected is None:
            raise ManagedAdapterOwnershipError("managed_resource_missing")
        return expected

    @staticmethod
    def _resource_labels(
        document: dict[str, Any],
        *,
        volume: bool,
    ) -> Mapping[str, str]:
        return (
            document.get("Labels")
            if volume
            else document.get("Config", {}).get("Labels")
        ) or {}

    @staticmethod
    def _claim_volume_name(idempotency_key: str) -> str:
        digest = hashlib.sha256(idempotency_key.encode()).hexdigest()[:32]
        return f"neos-managed-claim-{digest}"

    @staticmethod
    def _ownership_volume_name(provider_ref: str) -> str:
        return f"neos-managed-owner-{provider_ref}"

    @staticmethod
    def _label_args(labels: Mapping[str, str]) -> tuple[str, ...]:
        return tuple(
            value
            for key, label_value in labels.items()
            for value in ("--label", f"{key}={label_value}")
        )

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

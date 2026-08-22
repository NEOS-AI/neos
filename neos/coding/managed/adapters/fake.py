from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from neos.coding.managed.adapters.base import (
    AllocationResult,
    CreateSucceededThenTimedOut,
    DestroyResult,
    LifecycleResult,
    ManagedAdapterError,
    ManagedAdapterNotFoundError,
    ManagedAdapterOwnershipError,
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


_DEFAULT_CAPABILITIES = ManagedSandboxCapabilities(
    pause_resume=True,
    filesystem_snapshot=True,
    memory_snapshot=False,
    portable_archive=True,
    network_block_all=True,
    network_allowlist=False,
    region_pin=True,
    idempotent_allocate=True,
    metadata_rediscovery=True,
)


@dataclass(frozen=True, slots=True)
class FakeAdapterCall:
    operation: str
    arguments: tuple[object, ...]


class FakeManagedSandboxAdapter:
    __slots__ = (
        "_allocate_fault",
        "_calls",
        "_capabilities",
        "_destroy_result",
        "_faults",
        "_idempotency",
        "_records",
        "_requests",
        "_snapshot_sequence",
    )

    def __init__(
        self,
        *,
        capabilities: ManagedSandboxCapabilities = _DEFAULT_CAPABILITIES,
        allocate_fault: ManagedAdapterError | None = None,
        faults: Mapping[str, ManagedAdapterError] | None = None,
        destroy_result: DestroyResult | None = None,
    ) -> None:
        self._capabilities = capabilities
        self._allocate_fault = allocate_fault
        self._faults = dict(faults or {})
        self._destroy_result = destroy_result
        self._records: dict[str, ProviderSandboxState] = {}
        self._idempotency: dict[str, str] = {}
        self._requests: dict[str, ManagedAllocationRequest] = {}
        self._calls: list[FakeAdapterCall] = []
        self._snapshot_sequence = 0

    @property
    def provider(self) -> str:
        return "fake"

    @property
    def capabilities(self) -> ManagedSandboxCapabilities:
        return self._capabilities

    @property
    def calls(self) -> tuple[FakeAdapterCall, ...]:
        return tuple(self._calls)

    @property
    def allocate_calls(self) -> int:
        return self._count("allocate")

    @property
    def rediscovery_calls(self) -> int:
        return self._count("find_by_idempotency_key")

    @property
    def destroy_calls(self) -> int:
        return self._count("destroy")

    async def allocate(
        self,
        request: ManagedAllocationRequest,
    ) -> AllocationResult:
        self._record_call("allocate", request)
        require_capability(self.capabilities, "idempotent_allocate")
        validate_network_policy(self.capabilities, request.network_policy)
        existing_ref = self._idempotency.get(request.idempotency_key)
        if existing_ref is not None:
            if self._requests[request.idempotency_key] != request:
                raise ManagedAdapterError("idempotency_key_request_mismatch")
            return self._allocation_result(self._records[existing_ref])

        if not isinstance(
            self._allocate_fault,
            CreateSucceededThenTimedOut,
        ):
            self._raise_fault("allocate", self._allocate_fault)

        provider_ref = f"fake_{request.allocation_id}"
        state = ProviderSandboxState(
            provider_ref=provider_ref,
            allocation_id=request.allocation_id,
            idempotency_key=request.idempotency_key,
            state=ManagedSandboxState.ACTIVE,
            ownership_digest=request.ownership_digest,
            ownership_verified=True,
        )
        self._records[provider_ref] = state
        self._idempotency[request.idempotency_key] = provider_ref
        self._requests[request.idempotency_key] = request
        if self._allocate_fault is not None:
            fault = self._allocate_fault
            self._allocate_fault = None
            raise fault
        return self._allocation_result(state)

    async def inspect(self, provider_ref: str) -> ProviderSandboxState:
        self._record_call("inspect", provider_ref)
        self._raise_fault("inspect")
        return self._get(provider_ref)

    async def suspend(self, provider_ref: str) -> LifecycleResult:
        self._record_call("suspend", provider_ref)
        require_capability(self.capabilities, "pause_resume")
        self._raise_fault("suspend")
        state = replace(
            self._get(provider_ref),
            state=ManagedSandboxState.SUSPENDED,
        )
        self._records[provider_ref] = state
        return LifecycleResult(provider_ref, state.state)

    async def resume(self, provider_ref: str) -> LifecycleResult:
        self._record_call("resume", provider_ref)
        require_capability(self.capabilities, "pause_resume")
        self._raise_fault("resume")
        state = replace(
            self._get(provider_ref),
            state=ManagedSandboxState.ACTIVE,
        )
        self._records[provider_ref] = state
        return LifecycleResult(provider_ref, state.state)

    async def snapshot(self, provider_ref: str) -> SnapshotResult:
        self._record_call("snapshot", provider_ref)
        require_capability(self.capabilities, "filesystem_snapshot")
        self._raise_fault("snapshot")
        state = self._get(provider_ref)
        self._snapshot_sequence += 1
        return SnapshotResult(
            provider_ref=provider_ref,
            snapshot_ref=f"fake_snapshot_{self._snapshot_sequence:04d}",
            state=state.state,
        )

    async def destroy(
        self,
        provider_ref: str,
        *,
        ownership_digest: str,
    ) -> DestroyResult:
        self._record_call("destroy", provider_ref, ownership_digest)
        self._raise_fault("destroy")
        state = self._get(provider_ref)
        if state.ownership_digest != ownership_digest:
            raise ManagedAdapterOwnershipError("ownership_digest_mismatch")
        if self._destroy_result is not None:
            return self._destroy_result
        del self._records[provider_ref]
        self._idempotency.pop(state.idempotency_key, None)
        # `seed()`로 심은 리소스는 allocate 를 거치지 않아 원본 요청이 없다.
        self._requests.pop(state.idempotency_key, None)
        return DestroyResult(
            confirmed=True,
            ownership_verified=True,
        )

    async def find_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> ProviderSandboxState | None:
        self._record_call("find_by_idempotency_key", idempotency_key)
        require_capability(self.capabilities, "metadata_rediscovery")
        self._raise_fault("find_by_idempotency_key")
        provider_ref = self._idempotency.get(idempotency_key)
        if provider_ref is None:
            return None
        return self._records[provider_ref]

    async def health(self, region: str) -> ProviderHealthProbe:
        self._record_call("health", region)
        self._raise_fault("health")
        return ProviderHealthProbe(
            provider=self.provider,
            region=region,
            state=ProviderCircuitState.HEALTHY,
        )

    def seed(
        self,
        *,
        provider_ref: str,
        allocation_id: str,
        idempotency_key: str,
        ownership_digest: str,
        state: ManagedSandboxState = ManagedSandboxState.ACTIVE,
    ) -> None:
        """이미 provider 쪽에 리소스가 있는 상태를 만든다.

        `allocate()`를 거치지 않고 시작해야 하는 테스트(정리·재발견 등)를
        위한 것이다 -- `forget_all()`의 반대 방향이다. `_requests`는 채우지
        않는다: 그건 `allocate()`가 같은 키로 다시 불렸을 때 요청이 바뀌지
        않았는지 대조하는 용도라서, allocate 를 거치지 않은 리소스에는
        대조할 원본 요청이 애초에 없다.
        """
        self._records[provider_ref] = ProviderSandboxState(
            provider_ref=provider_ref,
            allocation_id=allocation_id,
            idempotency_key=idempotency_key,
            state=state,
            ownership_digest=ownership_digest,
            ownership_verified=True,
        )
        self._idempotency[idempotency_key] = provider_ref

    def forget_all(self) -> None:
        """내부 기록을 모두 비운다 -- 재발견이 아무것도 못 찾게 만드는 테스트
        전용 메서드다.

        provider 쪽 메타데이터가 사라진 상황(운영 사고, 리전 장애 등)을
        흉내 내 `find_by_idempotency_key()`가 `None`을 내게 한다.
        """
        self._records.clear()
        self._idempotency.clear()
        self._requests.clear()

    def _get(self, provider_ref: str) -> ProviderSandboxState:
        try:
            return self._records[provider_ref]
        except KeyError as error:
            raise ManagedAdapterNotFoundError(provider_ref) from error

    def _record_call(self, operation: str, *arguments: object) -> None:
        self._calls.append(FakeAdapterCall(operation, arguments))

    def _raise_fault(
        self,
        operation: str,
        direct: ManagedAdapterError | None = None,
    ) -> None:
        fault = direct or self._faults.pop(operation, None)
        if fault is not None:
            if direct is self._allocate_fault:
                self._allocate_fault = None
            raise fault

    def _count(self, operation: str) -> int:
        return sum(call.operation == operation for call in self._calls)

    @staticmethod
    def _allocation_result(state: ProviderSandboxState) -> AllocationResult:
        return AllocationResult(
            provider_ref=state.provider_ref,
            ownership_digest=state.ownership_digest,
            state=state.state,
        )

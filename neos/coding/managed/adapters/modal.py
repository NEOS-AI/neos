"""Modal 벤치마크 어댑터.

E2B 어댑터와 같은 규율(SDK 미임포트, 좁은 클라이언트 프로토콜, 메타데이터
소유권)을 따르되 두 가지가 다르다.

1. **수명 상한 24시간.** Modal 의 제약이라 요청 단계에서 거절한다 -- 넘겨
   보내고 provider 가 거절하게 두면 그 실패가 원장에 `PROVIDER_*` 오류로
   기록돼, 우리 정책 위반이 provider 장애처럼 보인다.
2. **일시정지/재개가 없다.** 능력표가 `pause_resume=False` 이고 호출하면
   `ManagedAdapterCapabilityError` 다. 조용히 무시하면 컨트롤 플레인은
   정지시킨 줄 알고 사용자는 요금을 계속 낸다.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

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
from neos.coding.managed.adapters.e2b import (
    ALLOCATION_ID_KEY,
    IDEMPOTENCY_KEY,
    OWNERSHIP_DIGEST_KEY,
)
from neos.coding.managed.domain import (
    ManagedSandboxCapabilities,
    ManagedSandboxState,
    ProviderCircuitState,
)


MAX_LIFETIME_SECONDS = 24 * 3600

MODAL_CAPABILITIES = ManagedSandboxCapabilities(
    pause_resume=False,
    filesystem_snapshot=True,
    memory_snapshot=False,
    portable_archive=True,
    network_block_all=True,
    network_allowlist=False,
    region_pin=True,
    idempotent_allocate=True,
    metadata_rediscovery=True,
)


@dataclass
class ModalSandboxRecord:
    sandbox_id: str
    metadata: dict[str, str] = field(default_factory=dict)
    block_network: bool = True


class ModalClient(Protocol):
    async def create(
        self,
        *,
        image: str,
        metadata: Mapping[str, str],
        timeout_seconds: int,
        block_network: bool,
    ) -> ModalSandboxRecord: ...

    async def get(self, sandbox_id: str) -> ModalSandboxRecord | None: ...

    async def find_by_metadata(
        self, key: str, value: str
    ) -> ModalSandboxRecord | None: ...

    async def snapshot_filesystem(self, sandbox_id: str) -> str: ...

    async def terminate(self, sandbox_id: str) -> bool: ...

    async def healthy_region(self, region: str) -> bool: ...


class ModalManagedSandboxAdapter:
    def __init__(self, *, client: ModalClient, clock=None) -> None:
        self._client = client
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def provider(self) -> str:
        return "modal"

    @property
    def capabilities(self) -> ManagedSandboxCapabilities:
        return MODAL_CAPABILITIES

    async def allocate(
        self, request: ManagedAllocationRequest
    ) -> AllocationResult:
        validate_network_policy(self.capabilities, request.network_policy)
        record = await self._client.create(
            image=request.image_identity,
            metadata={
                ALLOCATION_ID_KEY: request.allocation_id,
                IDEMPOTENCY_KEY: request.idempotency_key,
                OWNERSHIP_DIGEST_KEY: request.ownership_digest,
            },
            timeout_seconds=self._lifetime(request),
            # 계산하지 않고 **항상 참**이다. 정책에서 유도하면 언젠가
            # 유도식이 틀리고, 그 틀림은 격리가 깨진 뒤에야 보인다.
            block_network=True,
        )
        return AllocationResult(
            provider_ref=record.sandbox_id,
            ownership_digest=request.ownership_digest,
            state=ManagedSandboxState.ACTIVE,
        )

    async def inspect(self, provider_ref: str) -> ProviderSandboxState:
        return _state_of(await self._require(provider_ref))

    async def suspend(self, provider_ref: str) -> LifecycleResult:
        require_capability(self.capabilities, "pause_resume")
        raise AssertionError("unreachable")  # pragma: no cover

    async def resume(self, provider_ref: str) -> LifecycleResult:
        require_capability(self.capabilities, "pause_resume")
        raise AssertionError("unreachable")  # pragma: no cover

    async def snapshot(self, provider_ref: str) -> SnapshotResult:
        require_capability(self.capabilities, "filesystem_snapshot")
        await self._require(provider_ref)
        snapshot_ref = await self._client.snapshot_filesystem(provider_ref)
        return SnapshotResult(
            provider_ref=provider_ref,
            snapshot_ref=snapshot_ref,
            # 파일시스템 스냅샷은 실행을 끊지 않는다.
            state=ManagedSandboxState.ACTIVE,
        )

    async def destroy(
        self, provider_ref: str, *, ownership_digest: str
    ) -> DestroyResult:
        record = await self._require(provider_ref)
        if record.metadata.get(OWNERSHIP_DIGEST_KEY) != ownership_digest:
            raise ManagedAdapterOwnershipError("ownership_digest_mismatch")
        confirmed = await self._client.terminate(provider_ref)
        return DestroyResult(
            confirmed=confirmed,
            not_found=False,
            ownership_verified=True,
        )

    async def find_by_idempotency_key(
        self, idempotency_key: str
    ) -> ProviderSandboxState | None:
        require_capability(self.capabilities, "metadata_rediscovery")
        record = await self._client.find_by_metadata(
            IDEMPOTENCY_KEY, idempotency_key
        )
        return None if record is None else _state_of(record)

    async def health(self, region: str) -> ProviderHealthProbe:
        healthy = await self._client.healthy_region(region)
        return ProviderHealthProbe(
            provider=self.provider,
            region=region,
            state=(
                ProviderCircuitState.HEALTHY
                if healthy
                else ProviderCircuitState.UNAVAILABLE
            ),
        )

    def _lifetime(self, request: ManagedAllocationRequest) -> int:
        seconds = int(
            (request.absolute_expires_at - self._clock()).total_seconds()
        )
        if seconds <= 0:
            raise ManagedAdapterValidationError("lifetime already elapsed")
        if seconds > MAX_LIFETIME_SECONDS:
            # 상한은 **포함**이다 -- 24시간짜리 벤치마크가 경계에서 죽지
            # 않도록 `>` 로 비교한다.
            raise ManagedAdapterValidationError(
                f"modal max lifetime is {MAX_LIFETIME_SECONDS} seconds"
            )
        return seconds

    async def _require(self, provider_ref: str) -> ModalSandboxRecord:
        record = await self._client.get(provider_ref)
        if record is None:
            raise ManagedAdapterNotFoundError(provider_ref)
        return record


def create_modal_adapter(
    *,
    enabled: bool,
    token_id: str | None,
    token_secret: str | None,
    client: ModalClient | None = None,
) -> ModalManagedSandboxAdapter:
    """opt-in 팩토리. `create_e2b_adapter` 와 같은 이유로 추측하지 않는다."""
    if not enabled:
        raise RuntimeError("modal_opt_in_disabled")
    if not token_id or not token_secret:
        raise RuntimeError("modal_credentials_missing")
    if client is None:
        raise RuntimeError(
            "modal_client_not_bound: inject a ModalClient implementation; "
            "the vendor SDK binding is intentionally absent until it can be "
            "exercised against a real account"
        )
    return ModalManagedSandboxAdapter(client=client)


def _state_of(record: ModalSandboxRecord) -> ProviderSandboxState:
    return ProviderSandboxState(
        provider_ref=record.sandbox_id,
        allocation_id=record.metadata.get(ALLOCATION_ID_KEY, ""),
        idempotency_key=record.metadata.get(IDEMPOTENCY_KEY, ""),
        state=ManagedSandboxState.ACTIVE,
        ownership_digest=record.metadata.get(OWNERSHIP_DIGEST_KEY, ""),
        ownership_verified=bool(record.metadata.get(OWNERSHIP_DIGEST_KEY)),
    )

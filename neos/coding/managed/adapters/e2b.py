"""E2B 벤치마크 어댑터.

**벤더 SDK 를 임포트하지 않는다.** 이 모듈이 아는 것은 우리가 요구하는 좁은
클라이언트 프로토콜(`E2BClient`)뿐이고, 하는 일은 그 프로토콜과 관리형 어댑터
계약 사이의 번역이다. SDK 임포트와 크리덴셜 로딩은 opt-in 팩토리
(`create_e2b_adapter`) 안에서만 일어난다 -- 임포트만으로 크리덴셜을 찾고
네트워크를 여는 SDK 가 있고, 그것이 기본 테스트 경로에서 돌면 스위트가 더는
결정론적이지 않다.

**소유권은 메타데이터에 박는다.** `neos_allocation_id`·
`neos_idempotency_key`·`neos_ownership_digest` 셋이 재발견과 정리의 유일한
근거다. 이것이 없으면 "이 샌드박스가 우리 것인가"에 답할 방법이 없고,
Task 6의 정리 서비스는 아무것도 CLEANED 로 적을 수 없다.
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
from neos.coding.managed.domain import (
    ManagedSandboxCapabilities,
    ManagedSandboxState,
    ProviderCircuitState,
)


ALLOCATION_ID_KEY = "neos_allocation_id"
IDEMPOTENCY_KEY = "neos_idempotency_key"
OWNERSHIP_DIGEST_KEY = "neos_ownership_digest"

E2B_CAPABILITIES = ManagedSandboxCapabilities(
    pause_resume=True,
    filesystem_snapshot=True,
    # 메모리 스냅샷은 주장하지 않는다 -- 확인하지 못한 벤더 사실을 능력표에
    # 적으면 컨트롤 플레인이 그것을 믿고 계획을 세운다.
    memory_snapshot=False,
    portable_archive=True,
    network_block_all=True,
    network_allowlist=False,
    region_pin=True,
    idempotent_allocate=True,
    metadata_rediscovery=True,
)


@dataclass
class E2BSandboxRecord:
    """클라이언트가 돌려주는 최소 레코드."""

    sandbox_id: str
    metadata: dict[str, str] = field(default_factory=dict)
    paused: bool = False


class E2BClient(Protocol):
    """우리가 E2B 에 **요구하는** 표면. 벤더 API 전체가 아니다."""

    async def create(
        self,
        *,
        template: str,
        metadata: Mapping[str, str],
        timeout_seconds: int,
    ) -> E2BSandboxRecord: ...

    async def get(self, sandbox_id: str) -> E2BSandboxRecord | None: ...

    async def find_by_metadata(
        self, key: str, value: str
    ) -> E2BSandboxRecord | None: ...

    async def pause(self, sandbox_id: str) -> None: ...

    async def resume(self, sandbox_id: str) -> None: ...

    async def snapshot(self, sandbox_id: str) -> str: ...

    async def kill(self, sandbox_id: str) -> bool: ...

    async def healthy_region(self, region: str) -> bool: ...


class E2BManagedSandboxAdapter:
    def __init__(self, *, client: E2BClient, clock=None) -> None:
        self._client = client
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def provider(self) -> str:
        return "e2b"

    @property
    def capabilities(self) -> ManagedSandboxCapabilities:
        return E2B_CAPABILITIES

    async def allocate(
        self, request: ManagedAllocationRequest
    ) -> AllocationResult:
        validate_network_policy(self.capabilities, request.network_policy)
        record = await self._client.create(
            template=request.image_identity,
            metadata=_metadata_for(request),
            timeout_seconds=_bounded_lifetime(request, now=self._clock()),
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
        await self._require(provider_ref)
        await self._client.pause(provider_ref)
        return LifecycleResult(provider_ref, ManagedSandboxState.SUSPENDED)

    async def resume(self, provider_ref: str) -> LifecycleResult:
        require_capability(self.capabilities, "pause_resume")
        await self._require(provider_ref)
        await self._client.resume(provider_ref)
        return LifecycleResult(provider_ref, ManagedSandboxState.ACTIVE)

    async def snapshot(self, provider_ref: str) -> SnapshotResult:
        """⚠️ E2B 스냅샷은 **실행 중 연결을 끊는다.**

        스냅샷 뒤에 같은 세션을 계속 쓸 수 있다고 가정하면 워크스페이스
        스트림이 조용히 죽는다 -- 상태를 `SUSPENDED`로 보고해 호출자가
        재연결이 필요하다는 것을 알게 한다.
        """
        require_capability(self.capabilities, "filesystem_snapshot")
        await self._require(provider_ref)
        snapshot_ref = await self._client.snapshot(provider_ref)
        return SnapshotResult(
            provider_ref=provider_ref,
            snapshot_ref=snapshot_ref,
            state=ManagedSandboxState.SUSPENDED,
        )

    async def destroy(
        self, provider_ref: str, *, ownership_digest: str
    ) -> DestroyResult:
        # 소유권 대조가 kill 보다 **먼저**다. 순서를 뒤집으면 남의 리소스를
        # 지운 뒤에 그것이 남의 것이었음을 알게 된다.
        record = await self._require(provider_ref)
        if record.metadata.get(OWNERSHIP_DIGEST_KEY) != ownership_digest:
            raise ManagedAdapterOwnershipError("ownership_digest_mismatch")
        confirmed = await self._client.kill(provider_ref)
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
        # "없다"는 정상적인 답이다 -- 예외로 만들면 복구 경로가 그것을 장애로
        # 읽고 provider 서킷을 잘못 내린다.
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

    async def _require(self, provider_ref: str) -> E2BSandboxRecord:
        record = await self._client.get(provider_ref)
        if record is None:
            raise ManagedAdapterNotFoundError(provider_ref)
        return record


def create_e2b_adapter(
    *,
    enabled: bool,
    api_key: str | None,
    client: E2BClient | None = None,
) -> E2BManagedSandboxAdapter:
    """opt-in 팩토리. **여기 밖에서는 벤더 SDK 를 건드리지 않는다.**

    클라이언트를 주입하지 않으면 `e2b_client_not_bound` 로 **멈춘다.**
    검증되지 않은 SDK 호출을 여기에 심어 두면 '구현됐다'고 보이지만 실제로는
    아무도 실행해 본 적이 없는 코드가 된다 -- 이 저장소가 반복해서 다친
    "성공처럼 보이는 실패"의 한 모양이다. 실제 결합은 크리덴셜을 가진
    환경에서 opt-in 스모크(`CODING_TEST_E2B=1`)와 함께 들어와야 한다.
    """
    if not enabled:
        raise RuntimeError("e2b_opt_in_disabled")
    if not api_key:
        raise RuntimeError("e2b_credentials_missing")
    if client is None:
        raise RuntimeError(
            "e2b_client_not_bound: inject an E2BClient implementation; "
            "the vendor SDK binding is intentionally absent until it can be "
            "exercised against a real account"
        )
    return E2BManagedSandboxAdapter(client=client)


def _metadata_for(request: ManagedAllocationRequest) -> dict[str, str]:
    return {
        ALLOCATION_ID_KEY: request.allocation_id,
        IDEMPOTENCY_KEY: request.idempotency_key,
        OWNERSHIP_DIGEST_KEY: request.ownership_digest,
    }


def _bounded_lifetime(
    request: ManagedAllocationRequest, *, now: datetime
) -> int:
    """provider 에 무한 수명을 요청하지 않는다 -- 절대 만료가 상한이다."""
    seconds = int((request.absolute_expires_at - now).total_seconds())
    if seconds <= 0:
        raise ManagedAdapterValidationError("lifetime already elapsed")
    return seconds


def _state_of(record: E2BSandboxRecord) -> ProviderSandboxState:
    return ProviderSandboxState(
        provider_ref=record.sandbox_id,
        allocation_id=record.metadata.get(ALLOCATION_ID_KEY, ""),
        idempotency_key=record.metadata.get(IDEMPOTENCY_KEY, ""),
        state=(
            ManagedSandboxState.SUSPENDED
            if record.paused
            else ManagedSandboxState.ACTIVE
        ),
        ownership_digest=record.metadata.get(OWNERSHIP_DIGEST_KEY, ""),
        # 메타데이터가 실제로 붙어 있을 때만 소유권이 증명된 것이다.
        ownership_verified=bool(record.metadata.get(OWNERSHIP_DIGEST_KEY)),
    )

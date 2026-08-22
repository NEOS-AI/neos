"""관리형 샌드박스의 소유자 조회와 관리자 조치.

두 서비스가 있고 **관객이 다르다.**

- `ManagedSandboxStatusService` — 소유자용. `projection`이 접은 것만 낸다.
- `ManagedSandboxAdminService` — 운영자용. 그래도 provider 참조와 raw 에러는
  싣지 않는다: 봉인된 참조를 평문으로 꺼낼 이유가 운영자에게도 없다
  (그것을 여는 유일한 자리는 정리 서비스의 destroy 호출이다).

> ⚠️ **드레인은 지금 프로세스 로컬이다.** `ProviderHealthCircuit`이 인메모리라
> (045에 서킷 상태 컬럼이 없다 -- CA8) API 프로세스에서 드레인을 켜도 Celery
> 워커의 서킷은 모른다. 그래서 응답에 `scope`를 실어 **그 사실을 계약에
> 적는다** -- 조용히 안 듣는 것보다 낫다. 진짜 드레인은 서킷 상태를 영속화한
> 뒤에야 가능하다.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from neos.coding.managed.domain import ManagedSandboxState, ProviderCircuitState
from neos.coding.managed.projection import (
    OwnerSandboxStatus,
    project_owner_sandbox_status,
)


class ProviderDrainRegistry(Protocol):
    def set_drained(self, *, provider: str, region: str, drained: bool) -> None: ...

    def is_drained(self, *, provider: str, region: str) -> bool: ...


@dataclass
class InProcessProviderDrainRegistry:
    """드레인 상태를 프로세스 안에만 들고 있는 기본 구현.

    영속화가 생기면 이 자리를 갈아 끼운다. 지금은 `scope="process_local"`이
    응답에 실려 호출자가 그 한계를 알 수 있다.
    """

    def __post_init__(self) -> None:
        self._drained: set[tuple[str, str]] = set()

    def set_drained(self, *, provider: str, region: str, drained: bool) -> None:
        key = (provider, region)
        if drained:
            self._drained.add(key)
        else:
            self._drained.discard(key)

    def is_drained(self, *, provider: str, region: str) -> bool:
        return (provider, region) in self._drained


class ManagedSandboxStatusService:
    """소유자에게 보일 샌드박스 상태 하나."""

    def __init__(self, *, repository) -> None:
        self._repository = repository

    async def owner_status(
        self, *, task_id: str, owner_id: str
    ) -> OwnerSandboxStatus | None:
        found = await self._repository.read_owner_sandbox(
            task_id=task_id, owner_id=owner_id
        )
        if found is None:
            # 비소유자와 "샌드박스 없음"을 **같은 답**으로 낸다. 둘을 구별하면
            # 남의 태스크가 존재한다는 사실이 샌다.
            return None
        allocation, updated_at = found
        return project_owner_sandbox_status(allocation, updated_at=updated_at)


class ManagedSandboxAdminService:
    """운영자 조치 셋 -- 드레인, 정리 재시도, 복구 승인."""

    def __init__(
        self,
        *,
        repository,
        archives=None,
        drains: ProviderDrainRegistry | None = None,
        circuit=None,
        clock=None,
    ) -> None:
        self._repository = repository
        self._archives = archives
        self._drains = drains or InProcessProviderDrainRegistry()
        self._circuit = circuit
        self._clock = clock or (lambda: datetime.now(UTC))

    async def drain_provider(
        self, *, provider: str, region: str, drained: bool
    ) -> dict:
        """provider/region 하나를 신규 admission 에서 뺀다.

        기존 할당은 건드리지 않는다 -- 드레인은 "더 안 받는다"이지 "지금 있는
        것을 죽인다"가 아니다. 정리·조정도 계속 돈다(그것을 멈추면 드레인이
        곧 자원 방치가 된다).
        """
        self._drains.set_drained(provider=provider, region=region, drained=drained)
        return {
            "provider": provider,
            "region": region,
            "drained": drained,
            "circuit": (
                ProviderCircuitState.UNAVAILABLE.value
                if drained
                else ProviderCircuitState.HEALTHY.value
            ),
            # 계약에 한계를 적는다 -- 모듈 docstring 의 경고 참조.
            "scope": "process_local",
        }

    async def retry_cleanup(self, *, allocation_id: str) -> dict:
        state: ManagedSandboxState = await self._repository.clear_cleanup_retry(
            allocation_id, now=self._clock()
        )
        return {"allocation_id": allocation_id, "state": state.value}

    async def approve_recovery(
        self, *, allocation_id: str, archive_checksum: str, operator_id: str
    ) -> dict:
        if self._archives is None:
            raise RuntimeError("managed_sandbox_archive_service_unavailable")
        recovered = await self._archives.approve_recovery(
            allocation_id=allocation_id,
            archive_checksum=archive_checksum,
            operator_id=operator_id,
        )
        # 새 할당 식별자와 세대만 낸다 -- provider 참조도 아카이브 본문도 아니다.
        return {
            "allocation_id": recovered.allocation_id,
            "generation": recovered.generation,
            "state": recovered.state.value,
        }

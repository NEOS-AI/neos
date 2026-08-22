"""관리형 샌드박스의 소유자 조회와 관리자 조치.

두 서비스가 있고 **관객이 다르다.**

- `ManagedSandboxStatusService` — 소유자용. `projection`이 접은 것만 낸다.
- `ManagedSandboxAdminService` — 운영자용. 그래도 provider 참조와 raw 에러는
  싣지 않는다: 봉인된 참조를 평문으로 꺼낼 이유가 운영자에게도 없다
  (그것을 여는 유일한 자리는 정리 서비스의 destroy 호출이다).

> ✅ **드레인은 2026-08-23부터 내구적이다** (마이그레이션 046, CA8·CA11 종결).
> `PostgresProviderHealthStore` 가 `coding_sandbox_provider_health` 에 쓰므로
> API 프로세스에서 켠 드레인을 Celery 워커의 admission 이 곧바로 본다.
> 응답의 `scope` 는 이제 `"cluster"` 다 -- 그 값이 계약이므로 다시 프로세스
> 로컬로 되돌리려면 이 문자열도 함께 바뀌어야 한다.
"""

from datetime import UTC, datetime
from typing import Protocol

from neos.coding.managed.domain import ManagedSandboxState
from neos.coding.managed.health import (
    ProviderHealthRecord,
    resolve_admission_health,
)
from neos.coding.managed.projection import (
    OwnerSandboxStatus,
    project_owner_sandbox_status,
)


class ProviderDrainStore(Protocol):
    """드레인을 **모든 프로세스가 보는 곳**에 쓰는 계약 (마이그레이션 046)."""

    async def set_drained(
        self,
        *,
        provider: str,
        region: str,
        drained: bool,
        operator_id: str | None = None,
    ) -> ProviderHealthRecord: ...


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
        archiver=None,
        drains: ProviderDrainStore | None = None,
        clock=None,
    ) -> None:
        self._repository = repository
        self._archives = archives
        # `archiver(allocation_id) -> PortableArchiveManifest`. 콜러블로 받는
        # 이유는 아카이브를 뜨려면 provider 세션과 할당별 cipher 가 필요한데,
        # 그 조립은 런타임의 일이지 이 서비스의 일이 아니기 때문이다.
        self._archiver = archiver
        self._drains = drains
        self._clock = clock or (lambda: datetime.now(UTC))

    async def drain_provider(
        self,
        *,
        provider: str,
        region: str,
        drained: bool,
        operator_id: str | None = None,
    ) -> dict:
        """provider/region 하나를 신규 admission 에서 뺀다.

        기존 할당은 건드리지 않는다 -- 드레인은 "더 안 받는다"이지 "지금 있는
        것을 죽인다"가 아니다. 정리·조정도 계속 돈다(그것을 멈추면 드레인이
        곧 자원 방치가 된다).

        응답의 `circuit` 은 **드레인과 관측을 합친 뒤의 값**이다. 드레인을
        풀었다고 무조건 `healthy` 를 내지 않는다 -- 장애 중인 provider 를
        잠깐 드레인했다 푸는 것만으로 서킷이 초기화된 것처럼 보이면 안 된다.
        """
        if self._drains is None:
            raise RuntimeError("managed_sandbox_drain_store_unavailable")
        record = await self._drains.set_drained(
            provider=provider,
            region=region,
            drained=drained,
            operator_id=operator_id,
        )
        return {
            "provider": provider,
            "region": region,
            "drained": record.drained,
            "circuit": resolve_admission_health(record).value,
            "scope": "cluster",
        }

    async def archive_allocation(self, *, allocation_id: str) -> dict:
        """살아 있는 할당의 워크스페이스를 지금 아카이브로 뜬다.

        **복구의 재료를 만드는 유일한 경로다.** 아카이브는 샌드박스가 건강할
        때 떠 둬야 의미가 있다 -- `MANUAL_RECOVERY_REQUIRED` 에 빠진 뒤에는
        워크스페이스에 접근할 방법이 없다(그래서 이 조치는 그 전에 쓴다).

        상태를 바꾸지 않는다. 아카이브를 뜨는 것은 라이프사이클 전이가 아니라
        부수적인 기록이다.
        """
        if self._archiver is None:
            raise RuntimeError("managed_sandbox_archiver_unavailable")
        manifest = await self._archiver(allocation_id)
        return {
            "allocation_id": allocation_id,
            "archive_id": manifest.archive_id,
            "checksum": manifest.checksum,
            "content_bytes": manifest.content_bytes,
            "expires_at": manifest.expires_at,
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

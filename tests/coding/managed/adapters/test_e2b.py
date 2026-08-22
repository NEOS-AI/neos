"""E2B 벤치마크 어댑터 -- **주입된 클라이언트**로만 검사한다.

이 스위트는 벤더 SDK 를 임포트하지 않는다. 어댑터가 하는 일은 우리 계약을
좁은 클라이언트 프로토콜로 옮기는 번역이고, 그 번역이 이 파일의 전부다.
실제 SDK 결합은 opt-in 팩토리 안에서만 일어난다
(`tests/coding/managed/integration/test_e2b_opt_in.py`).
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from neos.coding.managed.adapters import (
    E2BManagedSandboxAdapter,
    ManagedAdapterCapabilityError,
    ManagedAdapterNotFoundError,
    ManagedAdapterOwnershipError,
    ManagedAdapterValidationError,
    ManagedNetworkPolicy,
)
from neos.coding.managed.adapters.e2b import E2BSandboxRecord, create_e2b_adapter
from neos.coding.managed.domain import ManagedSandboxState, ProviderCircuitState
from tests.coding.managed.adapters.conformance import (
    NOW,
    allocation_request,
    assert_managed_adapter_conformance,
)


pytestmark = pytest.mark.no_db


@dataclass
class FakeE2BClient:
    """E2B 가 제공한다고 우리가 **요구하는** 최소 표면.

    `reconnect_required`는 스냅샷이 실행 중 연결을 끊는다는 사실을 흉내 낸다 --
    스냅샷 뒤에 같은 세션을 계속 쓸 수 있다고 가정하면 워크스페이스 스트림이
    조용히 죽는다.
    """

    records: dict[str, E2BSandboxRecord] = field(default_factory=dict)
    reconnect_required: bool = False
    healthy: bool = True
    kill_result: bool = True
    sequence: int = 0
    calls: list[str] = field(default_factory=list)

    async def create(
        self, *, template: str, metadata: dict, timeout_seconds: int
    ) -> E2BSandboxRecord:
        self.calls.append("create")
        existing = self._by_idempotency(metadata["neos_idempotency_key"])
        if existing is not None:
            return existing
        self.sequence += 1
        record = E2BSandboxRecord(
            sandbox_id=f"e2b_{self.sequence}",
            metadata=dict(metadata),
            paused=False,
        )
        self.records[record.sandbox_id] = record
        return record

    async def get(self, sandbox_id: str) -> E2BSandboxRecord | None:
        self.calls.append("get")
        return self.records.get(sandbox_id)

    async def find_by_metadata(self, key: str, value: str) -> E2BSandboxRecord | None:
        self.calls.append("find_by_metadata")
        for record in self.records.values():
            if record.metadata.get(key) == value:
                return record
        return None

    async def pause(self, sandbox_id: str) -> None:
        self.calls.append("pause")
        self.records[sandbox_id].paused = True

    async def resume(self, sandbox_id: str) -> None:
        self.calls.append("resume")
        self.records[sandbox_id].paused = False

    async def snapshot(self, sandbox_id: str) -> str:
        self.calls.append("snapshot")
        # E2B 스냅샷은 실행 중 연결을 끊는다.
        self.reconnect_required = True
        return f"snap_{sandbox_id}"

    async def kill(self, sandbox_id: str) -> bool:
        self.calls.append("kill")
        self.records.pop(sandbox_id, None)
        return self.kill_result

    async def healthy_region(self, region: str) -> bool:
        self.calls.append("healthy_region")
        return self.healthy

    def _by_idempotency(self, value: str) -> E2BSandboxRecord | None:
        for record in self.records.values():
            if record.metadata.get("neos_idempotency_key") == value:
                return record
        return None


def _adapter(client: FakeE2BClient | None = None) -> E2BManagedSandboxAdapter:
    return E2BManagedSandboxAdapter(
        client=client or FakeE2BClient(), clock=lambda: NOW
    )


async def test_e2b_passes_the_shared_adapter_conformance() -> None:
    """공유 적합성 스위트가 이 어댑터에도 그대로 성립해야 한다.

    성립하지 않으면 provider 를 바꿀 때 컨트롤 플레인이 provider 별 분기를
    갖게 되고, 그것이 바로 어댑터 포트가 존재하는 이유를 무너뜨린다.
    """
    await assert_managed_adapter_conformance(_adapter())


async def test_e2b_maps_pause_resume_and_snapshot_disconnect() -> None:
    client = FakeE2BClient()
    adapter = _adapter(client)

    result = await adapter.allocate(allocation_request("idem_1"))
    await adapter.snapshot(result.provider_ref)

    assert adapter.capabilities.pause_resume is True
    assert client.reconnect_required is True


async def test_e2b_binds_allocation_idempotency_and_ownership_in_metadata() -> None:
    """메타데이터가 소유권 증명의 유일한 근거다.

    이것이 없으면 재발견도 정리도 "이 샌드박스가 우리 것인가"에 답할 수 없다.
    """
    client = FakeE2BClient()
    request = allocation_request("idem_1")

    await _adapter(client).allocate(request)

    metadata = next(iter(client.records.values())).metadata
    assert metadata["neos_allocation_id"] == request.allocation_id
    assert metadata["neos_idempotency_key"] == request.idempotency_key
    assert metadata["neos_ownership_digest"] == request.ownership_digest


async def test_e2b_rediscovers_by_idempotency_key() -> None:
    client = FakeE2BClient()
    adapter = _adapter(client)
    created = await adapter.allocate(allocation_request("idem_1"))

    found = await adapter.find_by_idempotency_key("idem_1")

    assert found is not None
    assert found.provider_ref == created.provider_ref
    assert found.ownership_verified is True


async def test_e2b_rediscovery_of_an_unknown_key_is_none_not_an_error() -> None:
    """"없다"는 정상적인 답이다 -- 예외로 만들면 복구 경로가 그것을 장애로 읽는다."""
    assert await _adapter().find_by_idempotency_key("idem_absent") is None


async def test_e2b_refuses_an_allowlist_network_policy() -> None:
    """지원하지 않는 능력은 **typed 오류**로 거절한다.

    조용히 block_all 로 낮추면 사용자는 허용목록이 걸린 줄 알고, 조용히
    올리면 격리가 깨진다.
    """
    with pytest.raises(ManagedAdapterCapabilityError):
        await _adapter().allocate(
            allocation_request(
                "idem_1", network_policy=ManagedNetworkPolicy.ALLOWLIST
            )
        )


async def test_e2b_destroy_verifies_ownership_before_killing() -> None:
    client = FakeE2BClient()
    adapter = _adapter(client)
    created = await adapter.allocate(allocation_request("idem_1"))

    with pytest.raises(ManagedAdapterOwnershipError):
        await adapter.destroy(created.provider_ref, ownership_digest="sha256:other")

    assert "kill" not in client.calls


async def test_e2b_destroy_of_a_missing_sandbox_raises_not_found() -> None:
    """리소스가 없으면 소유권을 **대조할 메타데이터 자체가 없다.**

    그래서 예외로 올린다. Task 6의 정리 서비스는 이 갈래를
    `CLEANUP_UNCONFIRMED` 로 읽는다 -- `DestroyResult(not_found=True,
    ownership_verified=True)`(대조에 성공한 사라짐)와 구별해야 하는 이유다.
    """
    client = FakeE2BClient()
    adapter = _adapter(client)
    created = await adapter.allocate(allocation_request("idem_1"))
    await client.kill(created.provider_ref)

    with pytest.raises(ManagedAdapterNotFoundError):
        await adapter.destroy(
            created.provider_ref, ownership_digest=created.ownership_digest
        )


async def test_e2b_inspect_of_a_missing_sandbox_raises_not_found() -> None:
    with pytest.raises(ManagedAdapterNotFoundError):
        await _adapter().inspect("e2b_absent")


async def test_e2b_reports_health_per_region() -> None:
    client = FakeE2BClient(healthy=False)

    probe = await _adapter(client).health("local")

    assert probe.provider == "e2b"
    assert probe.region == "local"
    assert probe.state is ProviderCircuitState.UNAVAILABLE


async def test_e2b_suspend_reports_the_suspended_state() -> None:
    client = FakeE2BClient()
    adapter = _adapter(client)
    created = await adapter.allocate(allocation_request("idem_1"))

    suspended = await adapter.suspend(created.provider_ref)

    assert suspended.state is ManagedSandboxState.SUSPENDED
    assert client.records[created.provider_ref].paused is True


async def test_e2b_passes_a_bounded_timeout_to_the_client() -> None:
    """provider 에 무한 수명을 요청하지 않는다 -- 절대 만료가 상한이다."""
    captured: dict[str, int] = {}

    class _CapturingClient(FakeE2BClient):
        async def create(self, *, template, metadata, timeout_seconds):
            captured["timeout_seconds"] = timeout_seconds
            return await super().create(
                template=template, metadata=metadata, timeout_seconds=timeout_seconds
            )

    await _adapter(_CapturingClient()).allocate(
        allocation_request("idem_1", lifetime_seconds=600)
    )

    assert captured["timeout_seconds"] == 600


async def test_e2b_rejects_an_already_expired_request() -> None:
    with pytest.raises(ManagedAdapterValidationError, match="lifetime"):
        await _adapter().allocate(
            allocation_request("idem_1", lifetime_seconds=0)
        )


def test_the_opt_in_factory_never_imports_the_sdk_without_credentials() -> None:
    """기본 경로에서 벤더 SDK 를 임포트하지 않는다.

    임포트만으로도 크리덴셜 탐색·네트워크 초기화를 하는 SDK 가 있고, 그것이
    테스트 환경에서 조용히 돌면 이 스위트는 더 이상 결정론적이지 않다.
    """
    with pytest.raises(RuntimeError, match="e2b_opt_in_disabled"):
        create_e2b_adapter(enabled=False, api_key=None)


def test_the_opt_in_factory_refuses_to_guess_a_client_binding() -> None:
    """플래그가 켜져도 클라이언트가 없으면 **정확한 사유로 멈춘다.**

    검증되지 않은 SDK 호출을 여기에 심어 두면 '구현됐다'고 보이지만 실제로는
    아무도 실행해 본 적이 없는 코드가 된다 -- 이 저장소가 반복해서 다친
    '성공처럼 보이는 실패'의 한 모양이다.
    """
    with pytest.raises(RuntimeError, match="e2b_client_not_bound"):
        create_e2b_adapter(enabled=True, api_key="secret")


def test_the_opt_in_factory_accepts_an_injected_client() -> None:
    adapter = create_e2b_adapter(
        enabled=True, api_key="secret", client=FakeE2BClient()
    )

    assert isinstance(adapter, E2BManagedSandboxAdapter)
    assert adapter.provider == "e2b"


def test_the_adapter_clock_defaults_to_utc_now() -> None:
    adapter = E2BManagedSandboxAdapter(client=FakeE2BClient())

    assert adapter._clock().tzinfo is UTC
    assert isinstance(adapter._clock(), datetime)

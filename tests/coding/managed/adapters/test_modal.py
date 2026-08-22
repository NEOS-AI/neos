"""Modal 벤치마크 어댑터 -- 주입된 클라이언트로만 검사한다.

E2B 와 다른 점 둘을 특히 본다.
1. **24시간 수명 상한** -- Modal 의 제약이라 어댑터가 요청 단계에서 거절한다.
2. **일시정지/재개가 없다** -- 능력이 없으면 typed 오류다. 조용히 무시하면
   컨트롤 플레인은 정지시킨 줄 알고 사용자는 요금을 계속 낸다.
"""

from dataclasses import dataclass, field

import pytest

from neos.coding.managed.adapters import (
    ManagedAdapterCapabilityError,
    ManagedAdapterNotFoundError,
    ManagedAdapterOwnershipError,
    ManagedAdapterValidationError,
    ManagedNetworkPolicy,
    ModalManagedSandboxAdapter,
)
from neos.coding.managed.adapters.modal import (
    ModalSandboxRecord,
    create_modal_adapter,
)
from neos.coding.managed.domain import ProviderCircuitState
from tests.coding.managed.adapters.conformance import (
    NOW,
    allocation_request,
    assert_managed_adapter_conformance,
)


pytestmark = pytest.mark.no_db


@dataclass
class FakeModalClient:
    records: dict[str, ModalSandboxRecord] = field(default_factory=dict)
    healthy: bool = True
    sequence: int = 0
    calls: list[str] = field(default_factory=list)

    async def create(
        self, *, image: str, metadata: dict, timeout_seconds: int, block_network: bool
    ) -> ModalSandboxRecord:
        self.calls.append("create")
        for record in self.records.values():
            if record.metadata.get("neos_idempotency_key") == metadata[
                "neos_idempotency_key"
            ]:
                return record
        self.sequence += 1
        record = ModalSandboxRecord(
            sandbox_id=f"modal_{self.sequence}",
            metadata=dict(metadata),
            block_network=block_network,
        )
        self.records[record.sandbox_id] = record
        return record

    async def get(self, sandbox_id: str) -> ModalSandboxRecord | None:
        self.calls.append("get")
        return self.records.get(sandbox_id)

    async def find_by_metadata(self, key: str, value: str) -> ModalSandboxRecord | None:
        self.calls.append("find_by_metadata")
        for record in self.records.values():
            if record.metadata.get(key) == value:
                return record
        return None

    async def snapshot_filesystem(self, sandbox_id: str) -> str:
        self.calls.append("snapshot_filesystem")
        return f"modalsnap_{sandbox_id}"

    async def terminate(self, sandbox_id: str) -> bool:
        self.calls.append("terminate")
        self.records.pop(sandbox_id, None)
        return True

    async def healthy_region(self, region: str) -> bool:
        self.calls.append("healthy_region")
        return self.healthy


def _adapter(client: FakeModalClient | None = None) -> ModalManagedSandboxAdapter:
    return ModalManagedSandboxAdapter(
        client=client or FakeModalClient(), clock=lambda: NOW
    )


async def test_modal_passes_the_shared_adapter_conformance() -> None:
    """일시정지가 없어도 같은 스위트를 통과한다 -- typed 거절이 계약이다."""
    await assert_managed_adapter_conformance(_adapter())


async def test_modal_caps_lifetime_at_twenty_four_hours() -> None:
    with pytest.raises(ManagedAdapterValidationError, match="max lifetime"):
        await _adapter().allocate(
            allocation_request("idem_1", lifetime_seconds=86_401)
        )


async def test_modal_accepts_exactly_twenty_four_hours() -> None:
    """상한은 포함이다 -- 경계에서 한 칸 틀리면 24시간짜리 벤치마크가 안 돈다."""
    result = await _adapter().allocate(
        allocation_request("idem_1", lifetime_seconds=86_400)
    )

    assert result.provider_ref.startswith("modal_")


async def test_modal_always_blocks_outbound_network() -> None:
    """기본이 차단이다. 어댑터가 이 값을 계산하지 않고 **항상 참으로** 넘긴다."""
    client = FakeModalClient()

    await _adapter(client).allocate(allocation_request("idem_1"))

    assert all(record.block_network for record in client.records.values())


async def test_modal_refuses_an_allowlist_network_policy() -> None:
    with pytest.raises(ManagedAdapterCapabilityError):
        await _adapter().allocate(
            allocation_request(
                "idem_1", network_policy=ManagedNetworkPolicy.ALLOWLIST
            )
        )


async def test_modal_has_no_pause_resume() -> None:
    """능력이 없으면 typed 오류다 -- 조용히 성공한 척하면 요금이 계속 나간다."""
    adapter = _adapter()
    created = await adapter.allocate(allocation_request("idem_1"))

    assert adapter.capabilities.pause_resume is False
    with pytest.raises(ManagedAdapterCapabilityError):
        await adapter.suspend(created.provider_ref)
    with pytest.raises(ManagedAdapterCapabilityError):
        await adapter.resume(created.provider_ref)


async def test_modal_allocate_is_idempotent_on_the_same_key() -> None:
    client = FakeModalClient()
    adapter = _adapter(client)
    request = allocation_request("idem_1")

    first = await adapter.allocate(request)
    second = await adapter.allocate(request)

    assert first.provider_ref == second.provider_ref
    assert len(client.records) == 1


async def test_modal_binds_bounded_identities_in_user_metadata() -> None:
    client = FakeModalClient()
    request = allocation_request("idem_1")

    await _adapter(client).allocate(request)

    metadata = next(iter(client.records.values())).metadata
    assert metadata["neos_allocation_id"] == request.allocation_id
    assert metadata["neos_idempotency_key"] == request.idempotency_key
    assert metadata["neos_ownership_digest"] == request.ownership_digest


async def test_modal_destroy_verifies_ownership_first() -> None:
    client = FakeModalClient()
    adapter = _adapter(client)
    created = await adapter.allocate(allocation_request("idem_1"))

    with pytest.raises(ManagedAdapterOwnershipError):
        await adapter.destroy(created.provider_ref, ownership_digest="sha256:other")

    assert "terminate" not in client.calls


async def test_modal_destroy_confirms_and_verifies() -> None:
    adapter = _adapter()
    created = await adapter.allocate(allocation_request("idem_1"))

    result = await adapter.destroy(
        created.provider_ref, ownership_digest=created.ownership_digest
    )

    assert result.confirmed is True
    assert result.ownership_verified is True


async def test_modal_inspect_of_a_missing_sandbox_raises_not_found() -> None:
    with pytest.raises(ManagedAdapterNotFoundError):
        await _adapter().inspect("modal_absent")


async def test_modal_reports_health_per_region() -> None:
    probe = await _adapter(FakeModalClient(healthy=True)).health("us-east")

    assert probe.provider == "modal"
    assert probe.region == "us-east"
    assert probe.state is ProviderCircuitState.HEALTHY


async def test_modal_snapshot_is_filesystem_only() -> None:
    adapter = _adapter()
    created = await adapter.allocate(allocation_request("idem_1"))

    snapshot = await adapter.snapshot(created.provider_ref)

    assert adapter.capabilities.filesystem_snapshot is True
    assert adapter.capabilities.memory_snapshot is False
    assert snapshot.snapshot_ref.startswith("modalsnap_")


def test_the_opt_in_factory_requires_both_tokens() -> None:
    with pytest.raises(RuntimeError, match="modal_opt_in_disabled"):
        create_modal_adapter(enabled=False, token_id=None, token_secret=None)
    with pytest.raises(RuntimeError, match="modal_credentials_missing"):
        create_modal_adapter(enabled=True, token_id="id", token_secret=None)


def test_the_opt_in_factory_refuses_to_guess_a_client_binding() -> None:
    with pytest.raises(RuntimeError, match="modal_client_not_bound"):
        create_modal_adapter(enabled=True, token_id="id", token_secret="secret")


def test_the_opt_in_factory_accepts_an_injected_client() -> None:
    adapter = create_modal_adapter(
        enabled=True,
        token_id="id",
        token_secret="secret",
        client=FakeModalClient(),
    )

    assert isinstance(adapter, ModalManagedSandboxAdapter)
    assert adapter.provider == "modal"

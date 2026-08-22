from datetime import UTC, datetime, timedelta

import pytest

from neos.coding.managed.adapters import (
    ManagedAdapterCapabilityError,
    ManagedAllocationRequest,
    ManagedNetworkPolicy,
)
from neos.coding.managed.domain import ManagedSandboxState
from neos.coding.sandbox.base import SandboxLimits


NOW = datetime(2026, 7, 25, 12, tzinfo=UTC)
IMAGE = "neos-sandbox@sha256:" + "a" * 64


def allocation_request(
    idempotency_key: str = "idem_1",
    *,
    network_policy: ManagedNetworkPolicy = ManagedNetworkPolicy.BLOCK_ALL,
    lifetime_seconds: int = 4 * 3600,
) -> ManagedAllocationRequest:
    """`lifetime_seconds`는 `absolute_expires_at`을 `NOW` 기준으로 민다.

    수명 자체를 담는 필드는 계약에 없다 -- 있는 것은 절대 만료 시각뿐이다.
    provider 별 수명 상한(예: Modal 의 24시간)을 검사하는 어댑터는 자기 시계로
    `absolute_expires_at - now`를 계산하므로, 테스트도 같은 방식으로 만든다.
    """
    return ManagedAllocationRequest(
        allocation_id="msa_1",
        idempotency_key=idempotency_key,
        region="local",
        image_identity=IMAGE,
        resource_limits=SandboxLimits.safe_defaults(),
        network_policy=network_policy,
        ownership_digest="sha256:owner",
        absolute_expires_at=NOW + timedelta(seconds=lifetime_seconds),
    )


async def assert_managed_adapter_conformance(adapter) -> None:
    """모든 관리형 어댑터가 지켜야 하는 계약.

    **능력 인식형이다.** 일시정지/재개를 지원하지 않는 provider(예: Modal)도
    이 스위트를 통과해야 한다 -- 다만 통과하는 방법이 다르다: 지원하면
    상태가 바뀌고, 지원하지 않으면 `ManagedAdapterCapabilityError` 로
    거절한다. **조용히 성공한 척하는 것은 어느 쪽도 아니다** -- 컨트롤
    플레인이 정지시킨 줄 알고 사용자는 요금을 계속 내게 된다.

    이 분기를 스위트 밖으로 빼면 provider 마다 다른 테스트를 쓰게 되고,
    그 순간 "공유 적합성"이라는 말이 의미를 잃는다.
    """
    request = allocation_request(idempotency_key="idem_1")
    created = await adapter.allocate(request)
    replay = await adapter.allocate(request)
    assert replay.provider_ref == created.provider_ref
    assert created.state is ManagedSandboxState.ACTIVE
    assert await adapter.find_by_idempotency_key("idem_1") == (
        await adapter.inspect(created.provider_ref)
    )
    if adapter.capabilities.pause_resume:
        suspended = await adapter.suspend(created.provider_ref)
        assert suspended.state is ManagedSandboxState.SUSPENDED
        resumed = await adapter.resume(created.provider_ref)
        assert resumed.state is ManagedSandboxState.ACTIVE
    else:
        for operation in (adapter.suspend, adapter.resume):
            with pytest.raises(ManagedAdapterCapabilityError):
                await operation(created.provider_ref)
    destroyed = await adapter.destroy(
        created.provider_ref,
        ownership_digest=created.ownership_digest,
    )
    assert destroyed.confirmed is True
    assert destroyed.ownership_verified is True

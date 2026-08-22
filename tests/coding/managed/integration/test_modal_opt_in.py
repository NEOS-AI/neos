"""Modal opt-in 스모크.

**기본은 skip 이고, skip 사유가 정확하다.** "설정이 없다"를 뭉뚱그리면
다음 사람이 무엇을 켜야 하는지 알 수 없고, 결국 아무도 켜지 않는다.

켜려면 둘 다 필요하다:
    CODING_TEST_MODAL=1
    MODAL_TOKEN_ID=<id>
    MODAL_TOKEN_SECRET=<secret>

그리고 켜져도 이 스모크는 **샌드박스를 하나만** 만들고, 수명을 300초 이하로
두고, 네트워크를 차단하고, `finally` 에서 반드시 파괴한다. 벤치마크가 고아
리소스를 남기면 그 비용은 어느 리포트에도 안 나타나고 청구서에만 나타난다.

> ⚠️ 지금은 벤더 SDK 결합이 **의도적으로 비어 있다**(`create_modal_adapter` 가
> `modal_client_not_bound` 로 멈춘다). 검증되지 않은 SDK 호출을 저장소에 심어
> 두면 '구현됐다'고 보이지만 아무도 실행해 본 적이 없는 코드가 된다. 이
> 스모크는 그 결합이 들어오는 순간 그것을 실제로 돌릴 자리로 먼저 만들어 둔
> 것이다 -- 플래그가 켜져 있으면 정확히 그 미결합을 보고하고 실패한다.
"""

import os
from datetime import UTC, datetime, timedelta

import pytest

from neos.coding.managed.adapters import (
    ManagedNetworkPolicy,
    create_modal_adapter,
)
from neos.coding.managed.adapters.base import ManagedAllocationRequest
from neos.coding.managed.benchmark import run_managed_sandbox_benchmark
from neos.coding.sandbox.base import SandboxLimits


MAX_SMOKE_LIFETIME_SECONDS = 300
COST_CEILING_MICROS = 50_000


def _requirements() -> tuple[bool, str | None]:
    if os.getenv("CODING_TEST_MODAL") != "1":
        return False, "set CODING_TEST_MODAL=1 to run the Modal smoke"
    if not (os.getenv("MODAL_TOKEN_ID") and os.getenv("MODAL_TOKEN_SECRET")):
        return False, (
            "set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET to run the Modal smoke"
        )
    return True, None


@pytest.mark.integration
async def test_modal_smoke_allocates_and_always_destroys() -> None:
    enabled, reason = _requirements()
    if not enabled:
        pytest.skip(reason)

    import time

    now = datetime.now(UTC)
    request = ManagedAllocationRequest(
        allocation_id=f"msa_smoke_{int(now.timestamp())}",
        idempotency_key=f"idem_smoke_{int(now.timestamp())}",
        region=os.getenv("MODAL_REGION", "us-east"),
        image_identity=os.getenv("MODAL_IMAGE", "python:3.12-slim"),
        resource_limits=SandboxLimits.safe_defaults(),
        network_policy=ManagedNetworkPolicy.BLOCK_ALL,
        ownership_digest=f"sha256:smoke{int(now.timestamp())}",
        absolute_expires_at=now
        + timedelta(seconds=MAX_SMOKE_LIFETIME_SECONDS),
    )
    adapter = create_modal_adapter(
        enabled=True,
        token_id=os.environ["MODAL_TOKEN_ID"],
        token_secret=os.environ["MODAL_TOKEN_SECRET"],
    )

    report = await run_managed_sandbox_benchmark(
        adapter,
        request,
        region=request.region,
        cost_micros_per_second=int(os.getenv("MODAL_COST_MICROS_PER_SEC", "100")),
        monotonic=time.monotonic,
    )

    assert report.provider == "modal"
    assert report.network_block_verified is True
    assert report.rediscovery_verified is True
    # 비용 상한을 넘으면 벤치마크 자체가 사고다.
    assert report.estimated_cost_micros <= COST_CEILING_MICROS


def test_the_smoke_is_skipped_with_an_exact_reason_by_default() -> None:
    """스모크가 왜 안 돌았는지가 **정확한 문장**으로 남아야 한다."""
    enabled, reason = _requirements()

    if enabled:
        assert reason is None
    else:
        assert reason is not None
        assert "CODING_TEST_MODAL" in reason or "MODAL_TOKEN" in reason

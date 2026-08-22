"""provider 비교용 벤치마크 러너.

**결과에 식별자가 없다.** provider·region 과 밀리초 숫자, 불리언 둘, 비용
추정치뿐이다 -- 샌드박스 id·명령 출력·raw 에러는 어느 것도 직렬화되지
않는다. 벤치마크 결과는 리포트로 나가고 리포트는 대개 공유되기 때문이다.

⚠️ **`network_block_verified` 가 무엇을 증명하는지 넘겨짚지 말 것.**
이것은 *정책* 확인이다 -- 어댑터가 `network_block_all` 능력을 선언했고
`BLOCK_ALL` 요청을 거절 없이 받아들였다는 뜻이다. 샌드박스 안에서 실제로
바깥으로 나가지 못하는지를 **경험적으로** 확인하려면 명령을 실행해야 하고,
그것은 관리형 어댑터 포트가 아니라 실행 데이터 플레인의 일이다. 그 확인은
opt-in 스모크가 데이터 플레인을 함께 들 때 붙어야 한다.
"""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from neos.coding.managed.adapters.base import (
    ManagedAdapterCapabilityError,
    ManagedAllocationRequest,
    ManagedNetworkPolicy,
    ManagedSandboxAdapter,
)


@dataclass(frozen=True, slots=True)
class ManagedSandboxBenchmark:
    provider: str
    region: str
    allocation_ms: int
    inspect_ms: int
    snapshot_ms: int | None
    resume_ms: int | None
    cleanup_ms: int
    network_block_verified: bool
    rediscovery_verified: bool
    estimated_cost_micros: int

    def to_report(self) -> dict:
        """공유해도 되는 형태. 식별자가 없다는 것이 이 메서드의 요점이다."""
        return asdict(self)


class _Stopwatch:
    """단조 시계 기반 밀리초 측정.

    `datetime.now()` 를 쓰지 않는다 -- 벤치마크 도중 시스템 시계가 조정되면
    음수 구간이 나오고, 그 음수가 리포트에 그대로 실린다.
    """

    def __init__(self, monotonic) -> None:
        self._monotonic = monotonic

    async def measure(self, awaitable_factory):
        started = self._monotonic()
        result = await awaitable_factory()
        return result, max(0, int((self._monotonic() - started) * 1000))


async def run_managed_sandbox_benchmark(
    adapter: ManagedSandboxAdapter,
    request: ManagedAllocationRequest,
    *,
    region: str,
    cost_micros_per_second: int,
    monotonic,
    clock=None,
) -> ManagedSandboxBenchmark:
    """할당 → 조회 → 스냅샷 → 재개 → 재발견 → 정리를 한 번씩 재고 정리한다.

    **반드시 정리한다.** 중간에 무엇이 실패하든 `finally` 에서 destroy 를
    부른다 -- 벤치마크가 고아 샌드박스를 남기면 그 비용은 아무 리포트에도
    나타나지 않고 청구서에만 나타난다.

    지원하지 않는 능력은 `None` 으로 기록한다. 0 으로 적으면 "0ms 에 끝났다"와
    "할 수 없다"가 같은 숫자가 되어 provider 비교가 거짓말을 한다.
    """
    if request.network_policy is not ManagedNetworkPolicy.BLOCK_ALL:
        raise ValueError("benchmark must run with the blocked network policy")
    clock = clock or (lambda: datetime.now(UTC))
    watch = _Stopwatch(monotonic)
    started_at = clock()
    provider_ref: str | None = None
    snapshot_ms: int | None = None
    resume_ms: int | None = None
    rediscovery_verified = False

    try:
        allocated, allocation_ms = await watch.measure(
            lambda: adapter.allocate(request)
        )
        provider_ref = allocated.provider_ref
        _inspected, inspect_ms = await watch.measure(
            lambda: adapter.inspect(provider_ref)
        )
        if adapter.capabilities.filesystem_snapshot:
            _snapshot, snapshot_ms = await watch.measure(
                lambda: adapter.snapshot(provider_ref)
            )
        if adapter.capabilities.pause_resume:
            await adapter.suspend(provider_ref)
            _resumed, resume_ms = await watch.measure(
                lambda: adapter.resume(provider_ref)
            )
        if adapter.capabilities.metadata_rediscovery:
            found = await adapter.find_by_idempotency_key(request.idempotency_key)
            rediscovery_verified = (
                found is not None
                and found.provider_ref == provider_ref
                and found.ownership_verified
            )
    finally:
        cleanup_ms = 0
        if provider_ref is not None:
            _destroyed, cleanup_ms = await watch.measure(
                lambda: adapter.destroy(
                    provider_ref, ownership_digest=request.ownership_digest
                )
            )

    elapsed_seconds = max(0, int((clock() - started_at).total_seconds()))
    return ManagedSandboxBenchmark(
        provider=adapter.provider,
        region=region,
        allocation_ms=allocation_ms,
        inspect_ms=inspect_ms,
        snapshot_ms=snapshot_ms,
        resume_ms=resume_ms,
        cleanup_ms=cleanup_ms,
        network_block_verified=_network_block_verified(adapter),
        rediscovery_verified=rediscovery_verified,
        estimated_cost_micros=elapsed_seconds * cost_micros_per_second,
    )


def _network_block_verified(adapter: ManagedSandboxAdapter) -> bool:
    """정책 확인 -- 모듈 docstring 의 경고를 함께 읽을 것."""
    try:
        return bool(adapter.capabilities.network_block_all)
    except ManagedAdapterCapabilityError:  # pragma: no cover - 방어적
        return False

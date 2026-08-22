"""관리형 컨트롤 플레인의 Celery 진입점 -- 조립과 경계만 한다.

`neos.coding.workers.celery_runtime` 이 코딩 루프에 대해 하는 일과 같은
자리다: DB 매니저를 열고, config 로 서비스를 조립하고, 끝나면 닫는다.
판정은 전부 `lifecycle`·`allocation` 이 하고 여기서는 하지 않는다.

**브로커로 나가는 것은 식별자 둘뿐이다** -- `allocation_id` 와 기대 세대.
provider 참조·에러 본문·저장소 URL·프롬프트는 메시지에 싣지 않는다. 브로커
로그와 결과 백엔드가 그것을 영구 보존하기 때문이다 (플랜 Global Constraints).
"""

import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from neos.coding.managed.adapters import (
    ManagedAdapterError,
    ManagedSandboxAdapter,
    ProviderHealthProbe,
)
from neos.coding.managed.allocation import provider_error_code
from neos.coding.managed.health import ProviderObservation
from neos.coding.managed.lifecycle import (
    CleanupOutcome,
    ManagedSandboxCleanupService,
    ManagedSandboxLifecycleReconciler,
    ReconciliationOutcome,
)
from neos.coding.managed.repository import PostgresManagedSandboxRepository
from neos.config.schema import AppConfig
from neos.config.settings import settings
from neos.database.connection import DatabaseManager
from neos.observability.metrics import metrics


logger = logging.getLogger(__name__)

ALLOCATE_TASK = "neos.coding.managed.allocate"
RECONCILE_TASK = "neos.coding.managed.reconcile"
CLEANUP_TASK = "neos.coding.managed.cleanup"
RECONCILE_QUOTA_TASK = "neos.coding.managed.reconcile_quota"
PROBE_HEALTH_TASK = "neos.coding.managed.probe_health"


def managed_control_plane_enabled(config: AppConfig) -> bool:
    """`sandbox.managed.enabled` 하나에만 묶인다.

    `global_kill_switch`는 여기 들어오지 않는다 -- 그것은 **신규 admission**
    을 막는 스위치이지 정리를 막는 스위치가 아니다. 둘을 묶으면 킬 스위치를
    켜 둔 시간만큼 이미 만들어진 provider 리소스가 아무도 정리하지 않는 채로
    돌아간다 (플랜 Task 6 Step 4: "cleanup and reconciliation remain
    scheduled while the global admission kill switch is active").
    """
    return config.sandbox.managed.enabled


def dispatch_reconciliation(
    outcome: ReconciliationOutcome,
    *,
    dispatcher,
    queue: str,
    generations: Mapping[str, int],
) -> dict[str, int]:
    """발견 결과를 각자의 태스크로 내보낸다.

    한 건의 발행 실패가 배치를 죽이지 않는다 -- 다음 조정 주기가 같은 후보를
    다시 찾아내므로 재시도는 저절로 되고, 여기서 예외를 올리면 나머지 정리가
    통째로 밀린다 (`reconcile_coding_tasks`가 이미 쓰는 규율과 같다).
    """
    counts = {"cleanup": 0, "recovery": 0, "failed": 0}
    work = [
        (CLEANUP_TASK, "cleanup", candidate.allocation_id)
        for candidate in outcome.cleanup
    ] + [(ALLOCATE_TASK, "recovery", allocation_id) for allocation_id in outcome.recovery]
    for name, bucket, allocation_id in work:
        try:
            dispatcher.send_task(
                name,
                kwargs={
                    "allocation_id": allocation_id,
                    "expected_generation": generations.get(allocation_id),
                },
                queue=queue,
            )
        except Exception:
            counts["failed"] += 1
            # allocation_id 는 로그 extra 에만 넣는다 -- 메트릭 라벨이 아니다.
            logger.exception(
                "Managed sandbox dispatch failed",
                extra={"managed_task": name, "allocation_id": allocation_id},
            )
        else:
            counts[bucket] += 1
    return counts


async def probe_provider_health(
    *,
    adapters: Mapping[str, ManagedSandboxAdapter],
    region: str,
    circuit,
) -> tuple[ProviderHealthProbe, ...]:
    """어댑터마다 헬스 프로브 1회. 실패도 **관측으로** 바꿔 서킷에 넣는다.

    예외를 그대로 올리면 서킷이 장애를 못 본다 -- 프로브의 존재 이유가
    사라진다. 그래서 실패는 `ProviderErrorCode`로 정규화해 관측으로 남기고
    프로브 결과 목록에서는 뺀다.
    """
    probes: list[ProviderHealthProbe] = []
    for provider, adapter in sorted(adapters.items()):
        try:
            probe = await adapter.health(region)
        except ManagedAdapterError as error:
            circuit.observe(
                ProviderObservation(
                    provider=provider,
                    region=region,
                    error_code=provider_error_code(error),
                    is_health_probe=True,
                )
            )
            continue
        circuit.observe(
            ProviderObservation(
                provider=probe.provider,
                region=probe.region,
                error_code=probe.error_code,
                is_health_probe=True,
            )
        )
        probes.append(probe)
    return tuple(probes)


async def reconcile_managed_sandboxes(
    *,
    database_manager: DatabaseManager | None = None,
    dispatcher=None,
    now: datetime | None = None,
) -> dict[str, int]:
    """조정 1회: 후보 발견 → 각자의 태스크로 발행."""
    config = settings.config
    if not managed_control_plane_enabled(config):
        return {"cleanup": 0, "recovery": 0, "failed": 0}
    managed = config.sandbox.managed
    moment = now or datetime.now(UTC)
    manager = database_manager or DatabaseManager()
    try:
        await manager.initialize()
        repository = PostgresManagedSandboxRepository(manager.get_session)
        reconciler = ManagedSandboxLifecycleReconciler(
            repository=repository,
            cleanup_slo_seconds=managed.cleanup_slo_seconds,
            metrics=metrics,
        )
        outcome = await reconciler.reconcile(
            limit=managed.cleanup_batch_size, now=moment
        )
        generations = await _generations_for(repository, outcome)
    finally:
        await manager.close()
    if outcome.slo_breached:
        # 원장에는 개별 행마다 남지만 "밀렸다"는 사실 자체는 어디에도 안 남는다.
        logger.warning(
            "Managed sandbox cleanup backlog exceeds SLO",
            extra={"pending": len(outcome.cleanup)},
        )
    return dispatch_reconciliation(
        outcome,
        dispatcher=dispatcher or _celery_dispatcher(),
        queue=settings.CODING_CELERY_QUEUE,
        generations=generations,
    )


async def _generations_for(
    repository: PostgresManagedSandboxRepository,
    outcome: ReconciliationOutcome,
) -> dict[str, int]:
    """발행할 메시지에 실을 기대 세대를 모은다.

    읽지 못한 것은 그냥 뺀다 -- 기대 세대 없는 메시지는 워커가 원장에서 다시
    읽으므로 안전하고, 여기서 실패해 배치를 죽이는 것보다 낫다.
    """
    generations: dict[str, int] = {}
    ids = [candidate.allocation_id for candidate in outcome.cleanup]
    ids.extend(outcome.recovery)
    for allocation_id in ids:
        try:
            allocation = await repository.read_allocation(allocation_id)
        except LookupError:
            continue
        generations[allocation_id] = allocation.generation
    return generations


async def advance_managed_allocation(
    *,
    allocation_id: str,
    worker_id: str,
    expected_generation: int | None = None,
    database_manager: DatabaseManager | None = None,
):
    """할당을 한 칸 전진시킨다 (`ManagedSandboxAllocationService.advance()`)."""
    from neos.coding.runtime import (
        _managed_provider_reference_cipher,
        create_managed_sandbox_allocation_service,
    )
    from neos.coding.sandbox.factory import create_sandbox_provider

    config = settings.config
    if not managed_control_plane_enabled(config):
        raise RuntimeError("managed_sandbox_control_plane_disabled")
    manager = database_manager or DatabaseManager()
    provider = create_sandbox_provider(config.sandbox)
    try:
        await manager.initialize()
        repository = PostgresManagedSandboxRepository(manager.get_session)
        allocation = await repository.read_allocation(allocation_id)
        if (
            expected_generation is not None
            and allocation.generation != expected_generation
        ):
            from neos.coding.managed.lifecycle import StaleManagedSandboxGeneration

            raise StaleManagedSandboxGeneration(allocation_id)
        # cipher 는 할당마다 새로 만들어야 한다 -- AAD 가
        # allocation_id:provider:generation 이라서 서비스 생성자에 박아 둘 수
        # 없다 (`_managed_provider_reference_cipher` 문서 참조).
        service = create_managed_sandbox_allocation_service(
            config=config,
            sandboxes=provider,
            repository=repository,
            cipher=_managed_provider_reference_cipher(
                config=config,
                allocation_id=allocation_id,
                provider=allocation.provider,
                generation=allocation.generation,
            ),
        )
        if service is None:
            raise RuntimeError("managed_sandbox_adapter_registry_empty")
        return await service.advance(allocation_id, worker_id=worker_id)
    finally:
        await provider.close()
        await manager.close()


async def clean_managed_allocation(
    *,
    allocation_id: str,
    worker_id: str,
    expected_generation: int | None = None,
    database_manager: DatabaseManager | None = None,
    now: datetime | None = None,
) -> CleanupOutcome:
    """할당 하나를 정리한다."""
    from neos.coding.runtime import (
        _managed_adapter_registry,
        _managed_provider_reference_cipher,
    )
    from neos.coding.sandbox.factory import create_sandbox_provider

    config = settings.config
    if not managed_control_plane_enabled(config):
        raise RuntimeError("managed_sandbox_control_plane_disabled")
    managed = config.sandbox.managed
    moment = now or datetime.now(UTC)
    manager = database_manager or DatabaseManager()
    provider = create_sandbox_provider(config.sandbox)
    try:
        await manager.initialize()
        repository = PostgresManagedSandboxRepository(manager.get_session)
        allocation = await repository.read_allocation(allocation_id)
        service = ManagedSandboxCleanupService(
            repository=repository,
            adapters=_managed_adapter_registry(config=config, sandboxes=provider),
            cipher=_managed_provider_reference_cipher(
                config=config,
                allocation_id=allocation_id,
                provider=allocation.provider,
                generation=allocation.generation,
            ),
            retry_backoff_seconds=managed.cleanup_retry_backoff_seconds,
            lease_seconds=managed.lifecycle_lease_seconds,
        )
        outcome = await service.cleanup(
            allocation_id,
            worker_id=worker_id,
            now=moment,
            expected_generation=expected_generation,
        )
    finally:
        await provider.close()
        await manager.close()
    metrics.coding_sandbox_cleanup_total.labels(
        provider=allocation.provider,
        region=allocation.region,
        outcome=outcome.state.value,
        error_code=(
            outcome.error_code.value if outcome.error_code is not None else "none"
        ),
    ).inc()
    return outcome


async def release_managed_sandbox_quota(
    *, database_manager: DatabaseManager | None = None, now: datetime | None = None
) -> Sequence[str]:
    """만료된 쿼터 예약을 회수한다 (Task 2의 `release_expired_reservations`)."""
    config = settings.config
    if not managed_control_plane_enabled(config):
        return ()
    manager = database_manager or DatabaseManager()
    try:
        await manager.initialize()
        repository = PostgresManagedSandboxRepository(manager.get_session)
        return await repository.release_expired_reservations(
            now=now or datetime.now(UTC),
            limit=config.sandbox.managed.cleanup_batch_size,
        )
    finally:
        await manager.close()


async def probe_managed_sandbox_health(*, circuit=None) -> tuple[str, ...]:
    """설정된 provider 의 헬스를 재고 서킷 게이지를 갱신한다.

    ⚠️ 서킷은 **호출마다 새로 만들어진다.** 045에 서킷 상태를 담을 컬럼이
    없어서(Task 3이 `ProviderHealthCircuit`을 순수 인메모리로 지었다) beat
    호출 사이에 롤링 윈도가 이어지지 않는다. 즉 이 프로브가 지금 하는 일은
    **프로브 1회의 결과를 게이지로 내는 것**이고, 여러 프로브에 걸친 비율
    판정은 하지 못한다. 롤링 판정을 살리려면 서킷 상태를 영속화하는
    마이그레이션이 필요하다 -- 이 트랙의 미해결 항목으로 남긴다.
    """
    from neos.coding.managed.health import ProviderHealthCircuit
    from neos.coding.runtime import _managed_adapter_registry
    from neos.coding.sandbox.factory import create_sandbox_provider

    config = settings.config
    if not managed_control_plane_enabled(config):
        return ()
    managed = config.sandbox.managed
    provider = create_sandbox_provider(config.sandbox)
    try:
        probes = await probe_provider_health(
            adapters=_managed_adapter_registry(config=config, sandboxes=provider),
            region=managed.region,
            circuit=circuit or ProviderHealthCircuit.from_config(managed),
        )
    finally:
        await provider.close()
    for probe in probes:
        metrics.coding_sandbox_provider_circuit.labels(
            provider=probe.provider,
            region=probe.region,
            state=probe.state.value,
        ).set(1)
    return tuple(probe.state.value for probe in probes)


def _celery_dispatcher():
    from neos.workflow.celery_app import app

    return app

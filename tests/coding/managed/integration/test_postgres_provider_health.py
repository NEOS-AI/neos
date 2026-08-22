"""046 의 SQL 을 실제 Postgres 에서 확인한다 (CA8·CA11).

fake 로는 증명할 수 없는 것 셋이 여기 있다.
1. `BOOLEAN[]` 왕복 -- 창이 배열로 나갔다가 그대로 돌아오는가.
2. `ON CONFLICT` 갱신이 **드레인 컬럼을 건드리지 않는가** -- 관측과 결정이
   같은 행을 공유하므로, 한쪽 UPSERT 가 다른 쪽을 지우면 즉시 사고다.
3. 046 의 CHECK 제약(드레인 메타데이터 동반)이 실제로 거는가.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from neos.coding.managed.domain import ProviderCircuitState, ProviderErrorCode
from neos.coding.managed.health import ProviderHealthCircuit, ProviderObservation
from neos.coding.managed.health_store import PostgresProviderHealthStore


NOW = datetime(2026, 8, 23, 12, tzinfo=UTC)


def _store(session_factory, *, window_size: int = 4) -> PostgresProviderHealthStore:
    return PostgresProviderHealthStore(
        session_factory,
        circuit_factory=lambda: ProviderHealthCircuit(
            window_size=window_size, degraded_ratio=0.25, unavailable_ratio=0.5
        ),
        clock=lambda: NOW,
    )


def _failure(provider: str = "e2b") -> ProviderObservation:
    return ProviderObservation(
        provider=provider,
        region="local",
        error_code=ProviderErrorCode.PROVIDER_TIMEOUT,
    )


def _success(provider: str = "e2b", *, probe: bool = False) -> ProviderObservation:
    return ProviderObservation(
        provider=provider, region="local", error_code=None, is_health_probe=probe
    )


@pytest.mark.integration
async def test_an_unknown_provider_reads_as_healthy(
    managed_postgres_session_factory,
) -> None:
    store = _store(managed_postgres_session_factory)

    assert await store.read("e2b", "local") is None
    assert await store.state("e2b", "local") is ProviderCircuitState.HEALTHY


@pytest.mark.integration
async def test_the_window_survives_a_new_store_instance(
    managed_postgres_session_factory,
) -> None:
    """CA8 의 핵심 -- 프로세스가 바뀌어도 판정이 이어진다.

    각 `observe()` 는 새 서킷을 만들어 쓴다. 창이 DB 를 통해 전달되지 않으면
    네 번째 관측이 "첫 실패"로 보이고 서킷은 영원히 HEALTHY 다.
    """
    for _ in range(3):
        await _store(managed_postgres_session_factory).observe(_failure())

    record = await _store(managed_postgres_session_factory).read("e2b", "local")

    assert record is not None
    assert record.failure_window == (True, True, True)

    snapshot = await _store(managed_postgres_session_factory).observe(_failure())

    assert snapshot.observation_count == 4
    assert snapshot.failure_count == 4
    assert snapshot.state is ProviderCircuitState.UNAVAILABLE
    assert await _store(managed_postgres_session_factory).state(
        "e2b", "local"
    ) is ProviderCircuitState.UNAVAILABLE


@pytest.mark.integration
async def test_the_window_is_bounded_by_the_configured_size(
    managed_postgres_session_factory,
) -> None:
    for _ in range(6):
        await _store(managed_postgres_session_factory, window_size=4).observe(
            _failure()
        )

    record = await _store(managed_postgres_session_factory).read("e2b", "local")

    assert record is not None
    assert len(record.failure_window) == 4


@pytest.mark.integration
async def test_a_mixed_window_round_trips_as_booleans(
    managed_postgres_session_factory,
) -> None:
    """`BOOLEAN[]` 왕복. 순서가 뒤집히거나 값이 문자열로 돌아오면 여기서 걸린다."""
    store = _store(managed_postgres_session_factory)
    await store.observe(_failure())
    await store.observe(_success())
    await store.observe(_failure())

    record = await store.read("e2b", "local")

    assert record is not None
    assert record.failure_window == (True, False, True)


# --- 드레인과 관측이 서로를 지우지 않는다 -----------------------------------


@pytest.mark.integration
async def test_a_drain_is_visible_to_a_different_store_instance(
    managed_postgres_session_factory,
) -> None:
    """CA11 의 핵심 -- API 프로세스의 드레인을 워커가 본다."""
    await _store(managed_postgres_session_factory).set_drained(
        provider="e2b", region="local", drained=True, operator_id="admin_1"
    )

    state = await _store(managed_postgres_session_factory).state("e2b", "local")

    assert state is ProviderCircuitState.UNAVAILABLE


@pytest.mark.integration
async def test_a_healthy_observation_does_not_lift_a_drain(
    managed_postgres_session_factory,
) -> None:
    """관측 UPSERT 가 드레인 컬럼을 건드리면 정상 프로브가 운영자를 이긴다."""
    store = _store(managed_postgres_session_factory)
    await store.set_drained(
        provider="e2b", region="local", drained=True, operator_id="admin_1"
    )

    await store.observe(_success(probe=True))

    record = await store.read("e2b", "local")
    assert record is not None
    assert record.drained is True
    assert record.drained_by == "admin_1"
    assert await store.state("e2b", "local") is ProviderCircuitState.UNAVAILABLE


@pytest.mark.integration
async def test_a_drain_does_not_erase_the_observation_window(
    managed_postgres_session_factory,
) -> None:
    """반대 방향도 성립해야 한다 -- 드레인이 관측 이력을 지우면 안 된다."""
    store = _store(managed_postgres_session_factory)
    await store.observe(_failure())
    await store.observe(_failure())

    await store.set_drained(
        provider="e2b", region="local", drained=True, operator_id="admin_1"
    )

    record = await store.read("e2b", "local")
    assert record is not None
    assert record.failure_window == (True, True)


@pytest.mark.integration
async def test_undraining_restores_whatever_the_circuit_observed(
    managed_postgres_session_factory,
) -> None:
    """드레인을 풀면 그동안의 관측이 그대로 다시 보인다.

    드레인 해제를 '건강함'으로 취급하면, 장애 중인 provider 를 잠깐
    드레인했다 푸는 것만으로 서킷이 초기화된다.
    """
    store = _store(managed_postgres_session_factory, window_size=2)
    await store.observe(_failure())
    await store.observe(_failure())
    assert await store.state("e2b", "local") is ProviderCircuitState.UNAVAILABLE
    await store.set_drained(
        provider="e2b", region="local", drained=True, operator_id="admin_1"
    )

    record = await store.set_drained(
        provider="e2b", region="local", drained=False
    )

    assert record.drained is False
    assert record.drained_at is None
    assert record.drained_by is None
    assert await store.state("e2b", "local") is ProviderCircuitState.UNAVAILABLE


@pytest.mark.integration
async def test_providers_and_regions_are_isolated(
    managed_postgres_session_factory,
) -> None:
    """한 provider 의 드레인이 다른 provider 를 막으면 안 된다."""
    store = _store(managed_postgres_session_factory)
    await store.set_drained(
        provider="e2b", region="local", drained=True, operator_id="admin_1"
    )

    assert await store.state("modal", "local") is ProviderCircuitState.HEALTHY
    assert await store.state("e2b", "us-east") is ProviderCircuitState.HEALTHY


@pytest.mark.integration
async def test_the_check_constraint_rejects_half_written_drain_metadata(
    managed_postgres_session_factory,
) -> None:
    """046 의 CHECK 가 실제로 거는지 -- 도메인만 믿지 않는다."""
    with pytest.raises(Exception) as failure:
        async with await managed_postgres_session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        INSERT INTO coding_sandbox_provider_health (
                            provider, region, drained, drained_at, updated_at
                        ) VALUES ('e2b', 'local', TRUE, NULL, :now)
                        """
                    ),
                    {"now": NOW},
                )

    assert "coding_sandbox_provider_health" in str(failure.value)


@pytest.mark.integration
async def test_the_check_constraint_bounds_the_window_length(
    managed_postgres_session_factory,
) -> None:
    """설정이 100을 넘게 바뀌어도 DB 가 먼저 막는다."""
    with pytest.raises(Exception) as failure:
        async with await managed_postgres_session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        INSERT INTO coding_sandbox_provider_health (
                            provider, region, failure_window, updated_at
                        ) VALUES (
                            'e2b', 'local',
                            CAST(:window AS BOOLEAN[]), :now
                        )
                        """
                    ),
                    {"window": [False] * 101, "now": NOW},
                )

    assert "coding_sandbox_provider_health" in str(failure.value)


# --- 드레인이 실제로 admission 을 막는다 -------------------------------------


@pytest.mark.integration
async def test_a_drain_denies_admission_through_the_real_store(
    managed_postgres_session_factory,
) -> None:
    """CA11 이 주장하는 것을 끝까지 확인한다.

    지금까지의 테스트는 저장소가 드레인을 **기억한다**는 것만 봤다. 정작
    중요한 것은 그 기억이 `ManagedSandboxAdmissionService` 의 판정에 실제로
    닿는가다 -- 닿지 않으면 드레인 버튼은 원장만 바꾸고 아무것도 막지 않는다.
    """
    from neos.coding.managed.admission import ManagedSandboxAdmissionService
    from neos.coding.managed.domain import AdmissionReason
    from tests.coding.managed.test_admission import (
        AllowlistedPolicy,
        RecordingAdmissionRepository,
        managed_config,
        request_fixture,
    )

    store = _store(managed_postgres_session_factory)
    repository = RecordingAdmissionRepository()
    service = ManagedSandboxAdmissionService(
        repository=repository,
        policy=AllowlistedPolicy(),
        # 프로토콜이 요구하는 것은 `state()` 하나다 -- 내구 저장소가 그대로
        # 그 자리에 들어간다.
        health=store,
        config=managed_config(),
        clock=lambda: NOW,
    )
    admitted = await service.admit(request_fixture())
    assert admitted.reason is AdmissionReason.ALLOWED

    await store.set_drained(
        provider="fake", region="local", drained=True, operator_id="admin_1"
    )

    # **새** 요청은 막힌다.
    denied = await service.admit(request_fixture(idempotency_key="idem_2"))
    assert denied.reason is AdmissionReason.PROVIDER_UNAVAILABLE

    # 이미 admit 된 키는 결정을 유지한다 -- admit 이 (tenant, idempotency_key)
    # 에 멱등하기 때문이고, 그것이 옳다: 드레인은 **신규** admission 을 막는
    # 스위치이지 이미 내린 결정을 소급해 뒤집는 스위치가 아니다. 뒤집으면
    # 같은 요청을 재시도하는 클라이언트가 이미 만들어진 샌드박스를 잃는다.
    replayed = await service.admit(request_fixture())
    assert replayed.reason is AdmissionReason.ALLOWED

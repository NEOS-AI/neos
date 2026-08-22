"""서킷 상태와 드레인의 **영속화 계약** (CA8·CA11).

045 까지 `ProviderHealthCircuit` 은 순수 인메모리였고, 그래서 두 가지가
깨져 있었다.

* beat 의 헬스 프로브가 호출마다 새 서킷을 만들어 롤링 윈도가 이어지지
  않았다 — **비율 판정이 아예 성립하지 않았다**(CA8).
* API 프로세스에서 켠 드레인을 Celery 워커가 몰랐다(CA11).

둘은 한 뿌리다: 판정의 재료가 프로세스 안에만 있었다. 046 이 그 재료를
밖으로 옮긴다.

이 파일은 SQL 없이 **계약**만 본다 — 저장소가 창을 어떻게 실어 나르고,
드레인과 서킷이 어떻게 합쳐지는지. 실제 SQL 은
`integration/test_postgres_provider_health.py` 가 본다.
"""

from datetime import UTC, datetime

import pytest

from neos.coding.managed.domain import ProviderCircuitState, ProviderErrorCode
from neos.coding.managed.health import (
    ProviderHealthCircuit,
    ProviderHealthRecord,
    ProviderObservation,
    resolve_admission_health,
)


NOW = datetime(2026, 8, 23, 12, tzinfo=UTC)


def _circuit(window_size: int = 4) -> ProviderHealthCircuit:
    return ProviderHealthCircuit(
        window_size=window_size, degraded_ratio=0.25, unavailable_ratio=0.5
    )


# --- 창을 실어 나른다 -------------------------------------------------------


def test_a_restored_window_continues_the_judgement_instead_of_restarting() -> None:
    """이것이 CA8 의 핵심이다.

    프로세스가 바뀌어도 **같은 창 위에서** 다음 관측이 판정돼야 한다.
    새 서킷으로 다시 시작하면 실패 3건을 이미 본 상태에서도 비율이 0 이라
    영원히 HEALTHY 로 보인다.
    """
    first = _circuit()
    for _ in range(3):
        first.observe(
            ProviderObservation(
                provider="e2b",
                region="local",
                error_code=ProviderErrorCode.PROVIDER_TIMEOUT,
            )
        )
    window, state = first.export("e2b", "local")

    # 다른 프로세스를 흉내 낸다 -- 완전히 새 서킷이다.
    second = _circuit()
    second.restore("e2b", "local", failure_window=window, state=state)
    snapshot = second.observe(
        ProviderObservation(
            provider="e2b",
            region="local",
            error_code=ProviderErrorCode.PROVIDER_TIMEOUT,
        )
    )

    assert snapshot.observation_count == 4
    assert snapshot.failure_count == 4
    assert snapshot.state is ProviderCircuitState.UNAVAILABLE


def test_export_of_an_untouched_provider_is_empty_and_healthy() -> None:
    assert _circuit().export("e2b", "local") == ((), ProviderCircuitState.HEALTHY)


def test_a_restored_window_longer_than_the_configured_size_keeps_the_newest() -> None:
    """설정이 줄었을 때 **가장 최근** 관측이 남아야 한다.

    앞을 남기고 뒤를 버리면 방금 일어난 장애가 창에서 사라지고, 서킷은
    한참 전의 평온을 근거로 판정한다.
    """
    circuit = _circuit(window_size=2)

    circuit.restore(
        "e2b", "local", failure_window=[False, False, True, True],
        state=ProviderCircuitState.HEALTHY,
    )

    window, _state = circuit.export("e2b", "local")
    assert window == (True, True)


def test_restore_round_trips_through_export() -> None:
    circuit = _circuit()
    circuit.restore(
        "e2b",
        "local",
        failure_window=[True, False, True],
        state=ProviderCircuitState.DEGRADED,
    )

    assert circuit.export("e2b", "local") == (
        (True, False, True),
        ProviderCircuitState.DEGRADED,
    )


# --- 드레인과 서킷은 따로 산다 ----------------------------------------------


def test_a_drained_provider_is_unavailable_whatever_the_circuit_says() -> None:
    """운영자의 결정이 관측을 이긴다."""
    record = ProviderHealthRecord(
        provider="e2b",
        region="local",
        circuit_state=ProviderCircuitState.HEALTHY,
        failure_window=(),
        drained=True,
        drained_at=NOW,
        drained_by="admin_1",
    )

    assert resolve_admission_health(record) is ProviderCircuitState.UNAVAILABLE


def test_a_healthy_probe_does_not_erase_an_operator_drain() -> None:
    """드레인을 서킷과 같은 칸에 저장하면 정상 프로브 한 번이 그것을 지운다.

    046 이 컬럼을 나눈 이유가 이것이고, 이 테스트가 그 분리를 고정한다.
    """
    circuit = _circuit()
    circuit.restore(
        "e2b", "local", failure_window=(), state=ProviderCircuitState.HEALTHY
    )
    circuit.observe(
        ProviderObservation(
            provider="e2b", region="local", error_code=None, is_health_probe=True
        )
    )
    window, state = circuit.export("e2b", "local")

    record = ProviderHealthRecord(
        provider="e2b",
        region="local",
        circuit_state=state,
        failure_window=window,
        # 드레인은 서킷이 만지는 값이 아니다 -- 별도 컬럼에서 온다.
        drained=True,
        drained_at=NOW,
        drained_by="admin_1",
    )

    assert state is ProviderCircuitState.HEALTHY
    assert resolve_admission_health(record) is ProviderCircuitState.UNAVAILABLE


def test_an_undrained_provider_reports_its_circuit_state() -> None:
    record = ProviderHealthRecord(
        provider="e2b",
        region="local",
        circuit_state=ProviderCircuitState.DEGRADED,
        failure_window=(True,),
        drained=False,
    )

    assert resolve_admission_health(record) is ProviderCircuitState.DEGRADED


def test_a_missing_record_reads_as_healthy() -> None:
    """한 번도 관측되지 않은 provider 는 건강한 것으로 본다.

    반대로 두면(=기본 UNAVAILABLE) 새 provider 를 추가하는 순간 아무도
    admission 을 받지 못하고, 그 원인이 원장 어디에도 안 남는다.
    """
    assert resolve_admission_health(None) is ProviderCircuitState.HEALTHY


def test_drain_metadata_is_required_together() -> None:
    """드레인됐는데 언제·누가가 없으면 감사 기록이 반쪽이다.

    046 의 CHECK 제약과 같은 규칙을 도메인에서도 강제한다.
    """
    with pytest.raises(ValueError, match="drained_at"):
        ProviderHealthRecord(
            provider="e2b",
            region="local",
            circuit_state=ProviderCircuitState.HEALTHY,
            failure_window=(),
            drained=True,
            drained_at=None,
        )


def test_an_undrained_record_must_not_carry_drain_metadata() -> None:
    with pytest.raises(ValueError, match="drained_at"):
        ProviderHealthRecord(
            provider="e2b",
            region="local",
            circuit_state=ProviderCircuitState.HEALTHY,
            failure_window=(),
            drained=False,
            drained_at=NOW,
        )

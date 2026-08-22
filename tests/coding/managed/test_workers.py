"""관리형 컨트롤 플레인의 Celery 진입점(`neos.coding.managed.workers`) 테스트.

여기서 보는 것은 **조립과 경계**다: 관리형이 꺼져 있으면 아무 일도 하지
않는가, 킬 스위치가 정리를 멈추지는 않는가, 브로커로 나가는 메시지에 식별자
둘 말고 아무것도 싣지 않는가. 서비스 내부 판정은 `test_lifecycle.py`가 본다.
"""

from datetime import UTC, datetime, timedelta

import pytest

from neos.coding.managed import workers
from neos.coding.managed.domain import ProviderCircuitState
from neos.coding.managed.lifecycle import CleanupCandidate, ReconciliationOutcome
from neos.config.schema import AppConfig


NOW = datetime(2026, 8, 22, 12, tzinfo=UTC)


def _config(**managed) -> AppConfig:
    config = AppConfig()
    for name, value in managed.items():
        setattr(config.sandbox.managed, name, value)
    return config


def test_managed_control_plane_is_disabled_by_default() -> None:
    assert workers.managed_control_plane_enabled(_config()) is False


def test_the_kill_switch_does_not_disable_cleanup_or_reconciliation() -> None:
    """킬 스위치는 **신규 admission** 만 막는다.

    정리를 같이 멈추면 이미 만들어진 provider 리소스가 킬 스위치를 켜 둔
    시간만큼 그대로 살아 있게 된다 -- 비용이 새고 fail-closed 의 의미가
    뒤집힌다.
    """
    config = _config(enabled=True, global_kill_switch=True)

    assert workers.managed_control_plane_enabled(config) is True


class _RecordingDispatcher:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict]] = []

    def send_task(self, name, *, kwargs, queue):
        self.messages.append((name, dict(kwargs)))
        del queue


async def test_reconcile_dispatches_only_identifiers(monkeypatch) -> None:
    """브로커 페이로드에는 allocation_id 와 세대만 들어간다.

    provider 참조·에러 본문·저장소 URL 이 메시지로 새면 브로커 로그와 결과
    백엔드가 그것을 영구 보존한다 (플랜 Global Constraints).
    """
    dispatcher = _RecordingDispatcher()
    outcome = ReconciliationOutcome(
        cleanup=(
            CleanupCandidate(
                allocation_id="msa_1",
                provider="fake",
                region="local",
                pending_since=NOW - timedelta(seconds=5),
            ),
        ),
        recovery=("msa_2",),
        slo_breached=False,
    )

    counts = workers.dispatch_reconciliation(
        outcome,
        dispatcher=dispatcher,
        queue="coding",
        generations={"msa_1": 3, "msa_2": 4},
    )

    assert counts == {"cleanup": 1, "recovery": 1, "failed": 0}
    assert dispatcher.messages == [
        (
            "neos.coding.managed.cleanup",
            {"allocation_id": "msa_1", "expected_generation": 3},
        ),
        (
            "neos.coding.managed.allocate",
            {"allocation_id": "msa_2", "expected_generation": 4},
        ),
    ]


async def test_a_failed_publish_does_not_stop_the_batch() -> None:
    """한 건의 발행 실패가 나머지 정리를 막지 않는다.

    다음 조정 주기가 같은 후보를 다시 찾아내므로 재시도는 저절로 된다 --
    여기서 예외를 올리면 배치 전체가 죽는 쪽이 더 나쁘다.
    """

    class _FlakyDispatcher(_RecordingDispatcher):
        def send_task(self, name, *, kwargs, queue):
            if kwargs["allocation_id"] == "msa_1":
                raise RuntimeError("broker unreachable")
            super().send_task(name, kwargs=kwargs, queue=queue)

    dispatcher = _FlakyDispatcher()
    outcome = ReconciliationOutcome(
        cleanup=(
            CleanupCandidate(
                allocation_id="msa_1",
                provider="fake",
                region="local",
                pending_since=NOW,
            ),
        ),
        recovery=("msa_2",),
        slo_breached=False,
    )

    counts = workers.dispatch_reconciliation(
        outcome,
        dispatcher=dispatcher,
        queue="coding",
        generations={},
    )

    assert counts == {"cleanup": 0, "recovery": 1, "failed": 1}
    assert [name for name, _ in dispatcher.messages] == ["neos.coding.managed.allocate"]


async def test_missing_generation_publishes_without_an_expectation() -> None:
    """세대를 모르면 기대값 없이 보낸다 -- 워커가 원장에서 다시 읽는다."""
    dispatcher = _RecordingDispatcher()
    outcome = ReconciliationOutcome(
        cleanup=(), recovery=("msa_2",), slo_breached=False
    )

    workers.dispatch_reconciliation(
        outcome, dispatcher=dispatcher, queue="coding", generations={}
    )

    assert dispatcher.messages == [
        (
            "neos.coding.managed.allocate",
            {"allocation_id": "msa_2", "expected_generation": None},
        )
    ]


# --- 헬스 프로브 ----------------------------------------------------------


class _StubAdapter:
    def __init__(self, probe) -> None:
        self._probe = probe
        self.regions: list[str] = []

    async def health(self, region: str):
        self.regions.append(region)
        return self._probe


async def test_probe_health_records_one_observation_per_adapter() -> None:
    from neos.coding.managed.adapters import ProviderHealthProbe

    adapter = _StubAdapter(
        ProviderHealthProbe(
            provider="fake", region="local", state=ProviderCircuitState.HEALTHY
        )
    )
    observed: list[tuple[str, str, ProviderCircuitState]] = []

    class _Circuit:
        def observe(self, observation):
            observed.append(
                (observation.provider, observation.region, observation.error_code)
            )

    probes = await workers.probe_provider_health(
        adapters={"fake": adapter}, region="local", circuit=_Circuit()
    )

    assert adapter.regions == ["local"]
    assert [probe.state for probe in probes] == [ProviderCircuitState.HEALTHY]
    assert observed == [("fake", "local", None)]


async def test_probe_health_turns_a_raised_failure_into_an_observation() -> None:
    """프로브가 예외로 죽으면 서킷이 장애를 **못 본다** -- 그게 가장 나쁘다."""
    from neos.coding.managed.adapters import ManagedAdapterTimeoutError
    from neos.coding.managed.domain import ProviderErrorCode

    class _FailingAdapter:
        async def health(self, region: str):
            raise ManagedAdapterTimeoutError("probe timed out")

    observed = []

    class _Circuit:
        def observe(self, observation):
            observed.append(observation.error_code)

    probes = await workers.probe_provider_health(
        adapters={"fake": _FailingAdapter()}, region="local", circuit=_Circuit()
    )

    assert probes == ()
    assert observed == [ProviderErrorCode.PROVIDER_TIMEOUT]


@pytest.mark.parametrize(
    "entry",
    [
        "reconcile-managed-sandboxes",
        "reconcile-managed-sandbox-quota",
        "probe-managed-sandbox-health",
    ],
)
def test_beat_entries_are_named_and_removable(entry: str) -> None:
    from neos.workflow.celery_app import configure_managed_sandbox_beat_schedule

    schedule: dict = {}
    configure_managed_sandbox_beat_schedule(
        schedule, enabled=True, reconciliation_interval=11.0, health_interval=13.0
    )
    assert entry in schedule

    configure_managed_sandbox_beat_schedule(
        schedule, enabled=False, reconciliation_interval=11.0, health_interval=13.0
    )
    assert entry not in schedule

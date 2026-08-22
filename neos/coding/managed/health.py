from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from neos.coding.managed.domain import ProviderCircuitState, ProviderErrorCode
from neos.config.schema import ManagedSandboxConfig


_ROLLING_FAILURE_CODES = frozenset(
    {
        ProviderErrorCode.PROVIDER_TIMEOUT,
        ProviderErrorCode.PROVIDER_RATE_LIMITED,
        ProviderErrorCode.PROVIDER_SERVER_ERROR,
        ProviderErrorCode.PROVIDER_CAPACITY,
    }
)


@dataclass(frozen=True, slots=True)
class ProviderObservation:
    provider: str
    region: str
    error_code: ProviderErrorCode | None
    is_health_probe: bool = False

    def __post_init__(self) -> None:
        if not self.provider:
            raise ValueError("provider must not be empty")
        if not self.region:
            raise ValueError("region must not be empty")


@dataclass(frozen=True, slots=True)
class ProviderHealthRecord:
    """`coding_sandbox_provider_health` 한 행의 도메인 형태 (마이그레이션 046).

    **드레인과 서킷 상태는 서로 다른 값이다.** 합치면 정상 프로브 한 번이
    운영자의 드레인을 지운다 -- 046이 컬럼을 나눈 이유이고, 둘을 합치는 것은
    읽는 쪽(`resolve_admission_health`)의 일이다.
    """

    provider: str
    region: str
    circuit_state: ProviderCircuitState
    failure_window: tuple[bool, ...]
    drained: bool
    drained_at: datetime | None = None
    drained_by: str | None = None

    def __post_init__(self) -> None:
        if self.drained and self.drained_at is None:
            # 언제 드레인됐는지 없으면 감사 기록이 반쪽이다. 046의 CHECK 와
            # 같은 규칙을 도메인에서도 강제한다.
            raise ValueError("drained record requires drained_at")
        if not self.drained and (
            self.drained_at is not None or self.drained_by is not None
        ):
            raise ValueError("undrained record must not carry drained_at metadata")


def resolve_admission_health(
    record: "ProviderHealthRecord | None",
) -> ProviderCircuitState:
    """신규 admission 이 보는 하나의 값으로 접는다.

    드레인이 서킷을 **이긴다** -- 운영자의 결정이 관측보다 우선이다.

    행이 없으면 `HEALTHY` 다. 반대로 두면(=기본 `UNAVAILABLE`) 새 provider 를
    추가하는 순간 아무도 admission 을 받지 못하고, 그 원인이 원장 어디에도
    남지 않는다.
    """
    if record is None:
        return ProviderCircuitState.HEALTHY
    if record.drained:
        return ProviderCircuitState.UNAVAILABLE
    return record.circuit_state


@dataclass(frozen=True, slots=True)
class ProviderHealthSnapshot:
    provider: str
    region: str
    state: ProviderCircuitState
    observation_count: int
    failure_count: int

    @property
    def failure_ratio(self) -> float:
        if self.observation_count == 0:
            return 0.0
        return self.failure_count / self.observation_count


class ProviderErrorMapper:
    """Maps adapter exception types to stable, non-sensitive provider codes."""

    def __init__(
        self,
        *,
        timeout_errors: Iterable[type[BaseException]] = (),
        rate_limited_errors: Iterable[type[BaseException]] = (),
        server_errors: Iterable[type[BaseException]] = (),
        auth_errors: Iterable[type[BaseException]] = (),
        capacity_errors: Iterable[type[BaseException]] = (),
    ) -> None:
        self._categories = (
            (tuple(auth_errors), ProviderErrorCode.PROVIDER_AUTH_ERROR),
            (tuple(rate_limited_errors), ProviderErrorCode.PROVIDER_RATE_LIMITED),
            (tuple(timeout_errors), ProviderErrorCode.PROVIDER_TIMEOUT),
            (tuple(server_errors), ProviderErrorCode.PROVIDER_SERVER_ERROR),
            (tuple(capacity_errors), ProviderErrorCode.PROVIDER_CAPACITY),
        )

    def normalize(self, error: BaseException) -> ProviderErrorCode:
        for exception_types, code in self._categories:
            if exception_types and isinstance(error, exception_types):
                return code
        return ProviderErrorCode.OTHER


class ProviderHealthCircuit:
    """Per-provider rolling health circuit for provider control-plane failures."""

    def __init__(
        self,
        *,
        window_size: int,
        degraded_ratio: float,
        unavailable_ratio: float,
    ) -> None:
        if window_size <= 0:
            raise ValueError("window_size must be positive")
        if not 0 <= degraded_ratio <= unavailable_ratio <= 1:
            raise ValueError(
                "failure ratios must satisfy 0 <= degraded <= unavailable <= 1"
            )
        self._window_size = window_size
        self._degraded_ratio = degraded_ratio
        self._unavailable_ratio = unavailable_ratio
        self._windows: dict[tuple[str, str], deque[bool]] = {}
        self._states: dict[tuple[str, str], ProviderCircuitState] = {}

    @classmethod
    def from_config(cls, config: ManagedSandboxConfig) -> "ProviderHealthCircuit":
        return cls(
            window_size=config.health_window_size,
            degraded_ratio=config.degraded_failure_ratio,
            unavailable_ratio=config.unavailable_failure_ratio,
        )

    def restore(
        self,
        provider: str,
        region: str,
        *,
        failure_window: Iterable[bool],
        state: ProviderCircuitState,
    ) -> None:
        """영속화된 창과 상태를 그대로 되살린다.

        `PostgresProviderHealthStore` 가 관측 한 건을 처리할 때 쓴다:
        DB 에서 창을 꺼내 여기에 넣고, `observe()` 한 번을 돌리고, 결과를 다시
        저장한다. **비율 판정을 SQL 로 옮기지 않기 위한 것**이다 -- 판정이 두
        곳에 생기면 언젠가 갈라지고, 갈라진 쪽은 아무도 모른다.

        창이 `window_size` 보다 길면 뒤에서부터 자른다. 설정이 줄었을 때
        옛 창을 그대로 받으면 `deque(maxlen=...)` 이 앞을 버리는데, 그러면
        가장 최근 관측이 아니라 가장 오래된 관측이 남는다.
        """
        window = deque(failure_window, maxlen=self._window_size)
        key = (provider, region)
        self._windows[key] = window
        self._states[key] = state

    def export(
        self, provider: str, region: str
    ) -> tuple[tuple[bool, ...], ProviderCircuitState]:
        """`restore()` 의 역방향. 저장할 창과 상태를 낸다."""
        key = (provider, region)
        return (
            tuple(self._windows.get(key, ())),
            self._states.get(key, ProviderCircuitState.HEALTHY),
        )

    def observe(self, observation: ProviderObservation) -> ProviderHealthSnapshot:
        key = (observation.provider, observation.region)
        state = self._states.get(key, ProviderCircuitState.HEALTHY)

        if observation.error_code is ProviderErrorCode.PROVIDER_AUTH_ERROR:
            self._record(key, failed=True)
            self._states[key] = ProviderCircuitState.UNAVAILABLE
        elif observation.error_code in _ROLLING_FAILURE_CODES:
            self._record(key, failed=True)
            self._states[key] = self._failed_state(key, state)
        elif observation.error_code is None:
            self._record(key, failed=False)
            self._states[key] = self._successful_state(
                key,
                state,
                is_health_probe=observation.is_health_probe,
            )

        return self.snapshot(observation.provider, observation.region)

    def observe_user_failure(
        self,
        provider: str,
        region: str,
        reason: str,
    ) -> ProviderHealthSnapshot:
        """Ignore user/tool failures so they cannot alter provider health."""
        del reason
        return self.snapshot(provider, region)

    def snapshot(self, provider: str, region: str) -> ProviderHealthSnapshot:
        key = (provider, region)
        window = self._windows.get(key, ())
        return ProviderHealthSnapshot(
            provider=provider,
            region=region,
            state=self._states.get(key, ProviderCircuitState.HEALTHY),
            observation_count=len(window),
            failure_count=sum(window),
        )

    async def state(self, provider: str, region: str) -> ProviderCircuitState:
        return self.snapshot(provider, region).state

    def _record(self, key: tuple[str, str], *, failed: bool) -> None:
        window = self._windows.setdefault(key, deque(maxlen=self._window_size))
        window.append(failed)

    def _failed_state(
        self,
        key: tuple[str, str],
        current: ProviderCircuitState,
    ) -> ProviderCircuitState:
        if current is ProviderCircuitState.UNAVAILABLE:
            return current
        window = self._windows[key]
        if len(window) < self._window_size:
            return current
        ratio = sum(window) / len(window)
        if ratio >= self._unavailable_ratio:
            return ProviderCircuitState.UNAVAILABLE
        if ratio >= self._degraded_ratio:
            return ProviderCircuitState.DEGRADED
        return current

    def _successful_state(
        self,
        key: tuple[str, str],
        current: ProviderCircuitState,
        *,
        is_health_probe: bool,
    ) -> ProviderCircuitState:
        if current is ProviderCircuitState.UNAVAILABLE:
            return (
                ProviderCircuitState.DEGRADED
                if is_health_probe
                else ProviderCircuitState.UNAVAILABLE
            )
        window = self._windows[key]
        if current is ProviderCircuitState.HEALTHY:
            if len(window) < self._window_size or not any(window):
                return current
            ratio = sum(window) / len(window)
            if ratio >= self._unavailable_ratio:
                return ProviderCircuitState.UNAVAILABLE
            if ratio >= self._degraded_ratio:
                return ProviderCircuitState.DEGRADED
        if current is ProviderCircuitState.DEGRADED:
            if len(window) == self._window_size and not any(window):
                return ProviderCircuitState.HEALTHY
        return current

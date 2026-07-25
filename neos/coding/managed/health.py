from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

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

import pytest

from neos.coding.managed.domain import ProviderCircuitState, ProviderErrorCode
from neos.coding.managed.health import (
    ProviderErrorMapper,
    ProviderHealthCircuit,
    ProviderObservation,
)
from neos.config.schema import ManagedSandboxConfig


def circuit_fixture() -> ProviderHealthCircuit:
    return ProviderHealthCircuit(
        window_size=4,
        degraded_ratio=0.25,
        unavailable_ratio=0.5,
    )


def failure(code: ProviderErrorCode) -> ProviderObservation:
    return ProviderObservation(
        provider="fake",
        region="local",
        error_code=code,
    )


def success(*, probe: bool = False) -> ProviderObservation:
    return ProviderObservation(
        provider="fake",
        region="local",
        error_code=None,
        is_health_probe=probe,
    )


def test_auth_error_opens_circuit_immediately() -> None:
    circuit = circuit_fixture()

    result = circuit.observe(failure(ProviderErrorCode.PROVIDER_AUTH_ERROR))

    assert result.state is ProviderCircuitState.UNAVAILABLE


def test_user_and_tool_errors_do_not_enter_provider_window() -> None:
    circuit = circuit_fixture()
    before = circuit.snapshot("fake", "local")

    circuit.observe_user_failure("fake", "local", "command_failed")

    assert circuit.snapshot("fake", "local") == before


def test_non_provider_errors_do_not_enter_provider_window() -> None:
    circuit = circuit_fixture()

    result = circuit.observe(failure(ProviderErrorCode.POLICY_DENIED))

    assert result == circuit.snapshot("fake", "local")
    assert result.observation_count == 0
    assert result.failure_count == 0


def test_rolling_failures_transition_through_degraded_and_unavailable() -> None:
    circuit = circuit_fixture()
    first_failure = circuit.observe(failure(ProviderErrorCode.PROVIDER_TIMEOUT))

    for _ in range(3):
        degraded = circuit.observe(success())
    circuit.observe(failure(ProviderErrorCode.PROVIDER_SERVER_ERROR))
    unavailable = circuit.observe(failure(ProviderErrorCode.PROVIDER_CAPACITY))

    assert first_failure.state is ProviderCircuitState.HEALTHY
    assert degraded.state is ProviderCircuitState.DEGRADED
    assert unavailable.state is ProviderCircuitState.UNAVAILABLE
    assert unavailable.observation_count == 4
    assert unavailable.failure_count == 2


def test_unavailable_requires_successful_health_probe_before_degrading() -> None:
    circuit = circuit_fixture()
    circuit.observe(failure(ProviderErrorCode.PROVIDER_AUTH_ERROR))

    ordinary_success = circuit.observe(success())
    recovered = circuit.observe(success(probe=True))

    assert ordinary_success.state is ProviderCircuitState.UNAVAILABLE
    assert recovered.state is ProviderCircuitState.DEGRADED


def test_degraded_returns_to_healthy_only_after_a_full_healthy_window() -> None:
    circuit = circuit_fixture()
    circuit.observe(failure(ProviderErrorCode.PROVIDER_TIMEOUT))

    for _ in range(3):
        still_degraded = circuit.observe(success())
    healthy = circuit.observe(success())

    assert still_degraded.state is ProviderCircuitState.DEGRADED
    assert healthy.state is ProviderCircuitState.HEALTHY
    assert healthy.observation_count == 4
    assert healthy.failure_count == 0


class AdapterTimeout(Exception):
    pass


class AdapterAuthError(Exception):
    pass


def test_error_mapper_uses_injected_exception_types_not_messages() -> None:
    mapper = ProviderErrorMapper(
        timeout_errors=(AdapterTimeout,),
        auth_errors=(AdapterAuthError,),
    )

    assert (
        mapper.normalize(AdapterTimeout("credential=top-secret"))
        is ProviderErrorCode.PROVIDER_TIMEOUT
    )
    assert (
        mapper.normalize(AdapterAuthError("timeout"))
        is ProviderErrorCode.PROVIDER_AUTH_ERROR
    )
    assert mapper.normalize(RuntimeError("provider timeout")) is ProviderErrorCode.OTHER


def test_circuit_can_be_built_from_managed_config_thresholds() -> None:
    config = ManagedSandboxConfig(
        health_window_size=4,
        degraded_failure_ratio=0.25,
        unavailable_failure_ratio=0.5,
    )

    circuit = ProviderHealthCircuit.from_config(config)
    circuit.observe(failure(ProviderErrorCode.PROVIDER_TIMEOUT))
    for _ in range(3):
        result = circuit.observe(success())

    assert result.state is ProviderCircuitState.DEGRADED


@pytest.mark.asyncio
async def test_state_is_available_to_admission_health_port() -> None:
    circuit = circuit_fixture()
    circuit.observe(failure(ProviderErrorCode.PROVIDER_TIMEOUT))
    for _ in range(3):
        circuit.observe(success())

    assert await circuit.state("fake", "local") is ProviderCircuitState.DEGRADED

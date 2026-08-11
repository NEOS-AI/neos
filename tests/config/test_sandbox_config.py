import pytest
from pydantic import ValidationError

from neos.config.schema import AppConfig


DIGEST_IMAGE = "neos-sandbox@sha256:" + "a" * 64


def test_development_defaults_to_memory_provider() -> None:
    config = AppConfig.model_validate({"environment": "development"})

    assert config.sandbox.provider == "memory"
    assert config.sandbox.resources.memory_bytes == 512 * 1024 * 1024
    assert config.sandbox.execution.max_stdin_bytes == 1024 * 1024
    assert config.sandbox.workspace.tree_max_entries == 5_000
    assert config.sandbox.workspace.file_max_bytes == 1024 * 1024
    assert config.sandbox.workspace.diff_max_bytes == 2 * 1024 * 1024
    assert config.sandbox.workspace.edit_batch_size == 20
    assert config.sandbox.workspace.ticket_ttl_seconds == 30
    assert config.sandbox.workspace.pty_idle_ttl_seconds == 1_800
    assert config.sandbox.workspace.pty_max_sessions == 3


def test_managed_sandbox_defaults_are_safe_for_shadow_admission() -> None:
    config = AppConfig.model_validate({"environment": "development"})

    assert config.sandbox.managed.enabled is False
    assert config.sandbox.managed.shadow_admission is True
    assert config.sandbox.managed.global_kill_switch is False
    assert config.sandbox.managed.provider == "fake"
    assert config.sandbox.managed.region == "local"
    assert config.sandbox.managed.admission_reevaluation_seconds == 30
    assert config.sandbox.managed.reservation_lease_seconds == 60
    assert config.sandbox.managed.allocation_lease_seconds == 60
    assert config.sandbox.managed.cleanup_batch_size == 100
    assert config.sandbox.managed.cleanup_slo_seconds == 300
    assert config.sandbox.managed.health_window_size == 20
    assert config.sandbox.managed.degraded_failure_ratio == 0.25
    assert config.sandbox.managed.unavailable_failure_ratio == 0.5
    assert config.sandbox.managed.concurrent_quota == 3
    assert config.sandbox.managed.daily_allocation_quota == 50
    assert config.sandbox.managed.daily_active_seconds_quota == 43_200
    assert config.sandbox.managed.archive_bytes_quota == 5 * 1024**3
    assert config.sandbox.managed.daily_cost_micros_quota == 10_000_000


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("admission_reevaluation_seconds", 0),
        ("reservation_lease_seconds", 601),
        ("allocation_lease_seconds", 0),
        ("cleanup_batch_size", 1_001),
        ("health_window_size", 3),
        ("degraded_failure_ratio", 1.1),
        ("unavailable_failure_ratio", -0.1),
        ("concurrent_quota", 0),
        ("daily_allocation_quota", 0),
        ("daily_active_seconds_quota", 0),
        ("archive_bytes_quota", 0),
        ("daily_cost_micros_quota", 0),
    ],
)
def test_managed_sandbox_limits_are_bounded(field: str, value: int | float) -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"sandbox": {"managed": {field: value}}})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tree_max_entries", 20_001),
        ("file_max_bytes", 0),
        ("diff_max_bytes", 0),
        ("edit_batch_size", 101),
        ("ticket_ttl_seconds", 301),
        ("pty_idle_ttl_seconds", 0),
        ("pty_max_sessions", 11),
    ],
)
def test_workspace_gateway_limits_are_bounded(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate(
            {"sandbox": {"workspace": {field: value}}}
        )


@pytest.mark.parametrize(
    "docker",
    [
        {"image": "neos-sandbox:latest"},
        {"image": DIGEST_IMAGE, "network_mode": "bridge"},
        {"image": DIGEST_IMAGE, "user": "0:0"},
    ],
)
def test_production_rejects_unsafe_docker_configuration(docker) -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate(
            {
                "environment": "production",
                "sandbox": {"provider": "docker", "docker": docker},
            }
        )


def test_production_accepts_pinned_isolated_non_root_docker() -> None:
    config = AppConfig.model_validate(
        {
            "environment": "production",
            "sandbox": {
                "enabled": True,
                "provider": "docker",
                "docker": {"image": DIGEST_IMAGE},
            },
        }
    )

    assert config.sandbox.docker.image == DIGEST_IMAGE
    assert config.sandbox.docker.network_mode == "none"


def test_lifecycle_timeout_relationships_are_validated() -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate(
            {
                "sandbox": {
                    "lifecycle": {
                        "idle_timeout_sec": 120,
                        "max_lifetime_sec": 60,
                    }
                }
            }
        )


def test_claim_lease_must_outlast_the_worst_case_create_sequence() -> None:
    """claim_lease_seconds 가 create_timeout_sec 에 비해 너무 짧으면 안 된다.

    짧으면, 아직 create() 를 진행 중인 살아있는 소유자를 죽은 것으로 오판해
    회수한다 -- 같은 idempotency_key 로 컨테이너가 두 개 생기는 사고로 이어진다.
    """
    with pytest.raises(ValidationError):
        AppConfig.model_validate(
            {
                "sandbox": {
                    "lifecycle": {"create_timeout_sec": 30},
                    "managed": {"claim_lease_seconds": 1},
                }
            }
        )


def test_claim_lease_that_comfortably_outlasts_create_is_accepted() -> None:
    config = AppConfig.model_validate(
        {
            "sandbox": {
                "lifecycle": {"create_timeout_sec": 30},
                "managed": {"claim_lease_seconds": 300},
            }
        }
    )

    assert config.sandbox.managed.claim_lease_seconds == 300

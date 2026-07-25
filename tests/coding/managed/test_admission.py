from datetime import UTC, datetime

from neos.coding.managed.admission import (
    AdmissionRequest,
    AdmissionResult,
    ManagedSandboxAdmissionService,
)
from neos.coding.managed.domain import (
    AdmissionDecision,
    AdmissionReason,
    ProviderCircuitState,
)
from neos.config.schema import ManagedSandboxConfig


NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


class AllowlistedPolicy:
    version = "policy-v1"

    def __init__(
        self,
        *,
        tenants: frozenset[str] = frozenset({"tenant_1"}),
        organizations: frozenset[str] = frozenset({"acme"}),
        capabilities: frozenset[str] = frozenset(
            {"network_block_all", "portable_archive"}
        ),
        regions: frozenset[tuple[str, str]] = frozenset({("fake", "local")}),
    ) -> None:
        self.tenants = tenants
        self.organizations = organizations
        self.capabilities = capabilities
        self.regions = regions

    def allows_tenant(self, tenant_id: str) -> bool:
        return tenant_id in self.tenants

    def allows_repository(self, organization: str) -> bool:
        return organization in self.organizations

    def provider_capabilities(self, provider: str) -> frozenset[str]:
        return self.capabilities if provider == "fake" else frozenset()

    def allows_region(self, provider: str, region: str) -> bool:
        return (provider, region) in self.regions


class FixedHealth:
    def __init__(self, state: ProviderCircuitState) -> None:
        self.value = state

    async def state(self, provider: str, region: str) -> ProviderCircuitState:
        return self.value


class OrderedPolicy(AllowlistedPolicy):
    def __init__(self, calls: list[str]) -> None:
        super().__init__()
        self.calls = calls

    def allows_tenant(self, tenant_id: str) -> bool:
        self.calls.append("tenant")
        return super().allows_tenant(tenant_id)

    def allows_repository(self, organization: str) -> bool:
        self.calls.append("repository")
        return super().allows_repository(organization)

    def provider_capabilities(self, provider: str) -> frozenset[str]:
        self.calls.append("capabilities")
        return super().provider_capabilities(provider)

    def allows_region(self, provider: str, region: str) -> bool:
        self.calls.append("region")
        return super().allows_region(provider, region)


class OrderedHealth(FixedHealth):
    def __init__(
        self,
        calls: list[str],
        state: ProviderCircuitState = ProviderCircuitState.HEALTHY,
    ) -> None:
        super().__init__(state)
        self.calls = calls

    async def state(self, provider: str, region: str) -> ProviderCircuitState:
        self.calls.append("health")
        return await super().state(provider, region)


class RecordingAdmissionRepository:
    def __init__(
        self,
        order: list[str] | None = None,
        *,
        preflight_reason: AdmissionReason | None = None,
    ) -> None:
        self.reserve_calls = 0
        self.calls: list[dict[str, object]] = []
        self.preflight_calls: list[dict[str, object]] = []
        self.requests: list[AdmissionRequest] = []
        self.results: dict[tuple[str, str], AdmissionResult] = {}
        self.created_count = 0
        self.order = order
        self.preflight_reason = preflight_reason

    async def preflight_quota(
        self, request: AdmissionRequest, **kwargs
    ) -> AdmissionReason | None:
        if self.order is not None:
            self.order.append("quota")
        self.preflight_calls.append(kwargs)
        return self.preflight_reason

    async def admit(self, request: AdmissionRequest, **kwargs) -> AdmissionResult:
        if self.order is not None:
            self.order.append("durable")
        self.requests.append(request)
        self.calls.append(kwargs)
        key = (request.tenant_id, request.idempotency_key)
        original = self.results.get(key)
        if original is not None:
            return AdmissionResult(
                admission_id=original.admission_id,
                allocation_id=original.allocation_id,
                decision=original.decision,
                reason=original.reason,
                reevaluate_after=original.reevaluate_after,
                created=False,
            )
        decision = kwargs["decision"]
        if decision is AdmissionDecision.ADMITTED:
            self.reserve_calls += 1
        self.created_count += 1
        result = AdmissionResult(
            admission_id=f"adm_{self.created_count}",
            allocation_id=(
                f"alloc_{self.created_count}"
                if decision is AdmissionDecision.ADMITTED
                else None
            ),
            decision=decision,
            reason=kwargs["reason"],
            reevaluate_after=kwargs["reevaluate_after"],
            created=True,
        )
        self.results[key] = result
        return result


def request_fixture(**changes: object) -> AdmissionRequest:
    values: dict[str, object] = {
        "tenant_id": "tenant_1",
        "task_id": "ct_1",
        "run_id": "cr_1",
        "repository_organization": "acme",
        "provider": "fake",
        "region": "local",
        "required_capabilities": frozenset({"network_block_all"}),
        "idempotency_key": "idem_1",
        "estimated_active_seconds": 300,
        "estimated_archive_bytes": 1024,
        "estimated_cost_micros": 500,
    }
    values.update(changes)
    return AdmissionRequest(**values)  # type: ignore[arg-type]


def managed_config(**changes: object) -> ManagedSandboxConfig:
    values: dict[str, object] = {
        "enabled": True,
        "shadow_admission": False,
        "global_kill_switch": False,
        "provider": "fake",
        "region": "local",
    }
    values.update(changes)
    return ManagedSandboxConfig(**values)


def admission_service(
    repository: RecordingAdmissionRepository,
    *,
    policy: AllowlistedPolicy | None = None,
    health: FixedHealth | None = None,
    config: ManagedSandboxConfig | None = None,
) -> ManagedSandboxAdmissionService:
    return ManagedSandboxAdmissionService(
        repository=repository,
        policy=policy or AllowlistedPolicy(),
        health=health or FixedHealth(ProviderCircuitState.HEALTHY),
        config=config or managed_config(),
        clock=lambda: NOW,
    )


async def test_unavailable_provider_denies_before_reserving_quota() -> None:
    repository = RecordingAdmissionRepository()
    service = admission_service(
        repository,
        health=FixedHealth(ProviderCircuitState.UNAVAILABLE),
    )

    result = await service.admit(request_fixture())

    assert result.reason is AdmissionReason.PROVIDER_UNAVAILABLE
    assert repository.reserve_calls == 0


async def test_admission_checks_run_in_fail_closed_order() -> None:
    calls: list[str] = []
    repository = RecordingAdmissionRepository(calls)
    service = admission_service(
        repository,
        policy=OrderedPolicy(calls),
        health=OrderedHealth(calls),
    )

    result = await service.admit(request_fixture())

    assert result.decision is AdmissionDecision.ADMITTED
    assert calls == [
        "tenant",
        "repository",
        "capabilities",
        "quota",
        "health",
        "region",
        "durable",
    ]


async def test_over_quota_wins_before_unavailable_provider_and_region_gates() -> None:
    calls: list[str] = []
    repository = RecordingAdmissionRepository(
        calls,
        preflight_reason=AdmissionReason.QUOTA_EXCEEDED,
    )
    service = admission_service(
        repository,
        policy=OrderedPolicy(calls),
        health=OrderedHealth(calls, ProviderCircuitState.UNAVAILABLE),
    )

    result = await service.admit(request_fixture())

    assert result.decision is AdmissionDecision.DENIED
    assert result.reason is AdmissionReason.QUOTA_EXCEEDED
    assert calls == [
        "tenant",
        "repository",
        "capabilities",
        "quota",
        "durable",
    ]
    assert repository.reserve_calls == 0


async def test_kill_switch_short_circuits_every_external_check() -> None:
    calls: list[str] = []
    repository = RecordingAdmissionRepository(calls)
    service = admission_service(
        repository,
        policy=OrderedPolicy(calls),
        health=OrderedHealth(calls),
        config=managed_config(global_kill_switch=True),
    )

    result = await service.admit(request_fixture())

    assert result.reason is AdmissionReason.KILL_SWITCH
    assert calls == ["durable"]
    assert repository.reserve_calls == 0


async def test_same_idempotency_key_returns_original_admission() -> None:
    repository = RecordingAdmissionRepository()
    service = admission_service(repository)

    first = await service.admit(request_fixture(idempotency_key="idem_1"))
    second = await service.admit(request_fixture(idempotency_key="idem_1"))

    assert second == AdmissionResult(
        admission_id=first.admission_id,
        allocation_id=first.allocation_id,
        decision=first.decision,
        reason=first.reason,
        reevaluate_after=first.reevaluate_after,
        created=False,
    )
    assert repository.created_count == 1


async def test_idempotency_replay_is_scoped_to_tenant() -> None:
    repository = RecordingAdmissionRepository()
    service = admission_service(
        repository,
        policy=AllowlistedPolicy(tenants=frozenset({"tenant_1", "tenant_2"})),
    )

    first = await service.admit(
        request_fixture(tenant_id="tenant_1", idempotency_key="idem_shared")
    )
    second = await service.admit(
        request_fixture(tenant_id="tenant_2", idempotency_key="idem_shared")
    )

    assert first.admission_id != second.admission_id
    assert first.created is True
    assert second.created is True
    assert repository.created_count == 2


async def test_policy_and_capability_denials_happen_before_quota() -> None:
    cases = [
        (
            request_fixture(tenant_id="tenant_2"),
            AllowlistedPolicy(),
            managed_config(),
            AdmissionReason.TENANT_NOT_ALLOWED,
        ),
        (
            request_fixture(repository_organization="other"),
            AllowlistedPolicy(),
            managed_config(),
            AdmissionReason.REPOSITORY_NOT_ALLOWED,
        ),
        (
            request_fixture(required_capabilities=frozenset({"memory_snapshot"})),
            AllowlistedPolicy(),
            managed_config(),
            AdmissionReason.PROVIDER_UNAVAILABLE,
        ),
        (
            request_fixture(region="elsewhere"),
            AllowlistedPolicy(),
            managed_config(),
            AdmissionReason.REGION_UNAVAILABLE,
        ),
        (
            request_fixture(),
            AllowlistedPolicy(),
            managed_config(global_kill_switch=True),
            AdmissionReason.KILL_SWITCH,
        ),
    ]

    for request, policy, config, expected_reason in cases:
        repository = RecordingAdmissionRepository()
        result = await admission_service(
            repository, policy=policy, config=config
        ).admit(request)
        assert result.reason is expected_reason
        assert repository.reserve_calls == 0


async def test_admitted_request_passes_exact_quota_and_lease_values() -> None:
    repository = RecordingAdmissionRepository()
    config = managed_config(
        reservation_lease_seconds=75,
        admission_reevaluation_seconds=45,
        concurrent_quota=7,
        daily_allocation_quota=23,
        daily_active_seconds_quota=12_345,
        archive_bytes_quota=54_321,
        daily_cost_micros_quota=88_000,
    )

    result = await admission_service(repository, config=config).admit(request_fixture())

    assert result.decision is AdmissionDecision.ADMITTED
    assert result.reason is AdmissionReason.ALLOWED
    assert repository.calls == [
        {
            "decision": AdmissionDecision.ADMITTED,
            "reason": AdmissionReason.ALLOWED,
            "now": NOW,
            "reevaluate_after": None,
            "reservation_expires_at": datetime(2026, 7, 25, 12, 1, 15, tzinfo=UTC),
            "concurrent_quota": 7,
            "daily_quota": 23,
            "daily_active_seconds_quota": 12_345,
            "archive_bytes_quota": 54_321,
            "daily_cost_micros_quota": 88_000,
        }
    ]
    assert repository.preflight_calls == [
        {
            "now": NOW,
            "concurrent_quota": 7,
            "daily_quota": 23,
            "daily_active_seconds_quota": 12_345,
            "archive_bytes_quota": 54_321,
            "daily_cost_micros_quota": 88_000,
        }
    ]


async def test_service_threads_evaluated_policy_version_to_repository() -> None:
    repository = RecordingAdmissionRepository()
    policy = AllowlistedPolicy()
    policy.version = "canary-policy-2026-07-25"

    await admission_service(repository, policy=policy).admit(request_fixture())

    assert (
        getattr(repository.requests[0], "policy_version", None)
        == "canary-policy-2026-07-25"
    )


async def test_denial_gets_bounded_reevaluation_and_no_reservation_lease() -> None:
    repository = RecordingAdmissionRepository()
    config = managed_config(admission_reevaluation_seconds=45)

    result = await admission_service(
        repository,
        config=config,
        health=FixedHealth(ProviderCircuitState.DEGRADED),
    ).admit(request_fixture())

    assert result.reason is AdmissionReason.PROVIDER_DEGRADED
    assert result.reevaluate_after == datetime(2026, 7, 25, 12, 0, 45, tzinfo=UTC)
    assert repository.calls[0]["reservation_expires_at"] is None

# Managed Sandbox Control Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a durable, fail-closed managed sandbox control plane that enforces admission and quota, tracks provider health and allocation lifecycle, proves cleanup, supports operator-approved portable recovery, and exposes bounded task status.

**Architecture:** Keep the existing `SandboxProvider` and `SandboxSession` as the execution data plane. Add a separate `neos.coding.managed` package whose PostgreSQL ledger, application services, Celery reconcilers, and capability-aware adapters own admission, allocation, health, archive recovery, and cleanup. The browser consumes a bounded owner-scoped projection and never receives provider references or raw errors.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy/PostgreSQL, Celery, Prometheus, HTTPX/injected provider clients, Next.js 15, React 19, TypeScript, Node test runner, opt-in E2B and Modal benchmark smoke tests.

## Global Constraints

- Work inline on the current `dev` branch; do not create a worktree unless the user changes execution mode.
- Preserve `.env.template` and the three unrelated untracked 2026-07-11 deep-analysis documents.
- New allocation is fail-closed when the selected provider is unavailable.
- Existing allocations remain pinned to their original provider and region.
- Never automatically fail over an allocation or provider snapshot across providers.
- Cross-provider recovery requires a verified portable archive and an operator decision bound to its checksum.
- No provider API call occurs before a durable admitted decision and quota reservation.
- An ambiguous allocation result moves to `recovery_pending`; it must not trigger a second allocation until absence is proven or a new generation is approved.
- Every managed allocation mutation compares version and fencing token.
- Provider credentials, provider response bodies, repository URLs, prompts, file content, terminal streams, command values, and raw exceptions never enter broker payloads, public events, general logs, or metric labels.
- Task, run, tenant, allocation, sandbox, repository, path, and actor IDs are not metric labels.
- Provider `NotFound` counts as cleaned only after stored ownership metadata matches the expected allocation.
- Rollback disables new admission but retains inspect, same-provider recovery, archive, and cleanup paths.
- Use tests before implementation, run focused verification per task, and commit only that task's files.

---

### Task 1: Managed Sandbox Domain, Configuration, and Migration 045

**Files:**
- Create: `neos/coding/managed/__init__.py`
- Create: `neos/coding/managed/domain.py`
- Create: `db/migrations/045_add_coding_managed_sandboxes.sql`
- Modify: `neos/config/schema.py`
- Modify: `config/neos.default.yaml`
- Create: `tests/coding/managed/test_domain.py`
- Create: `tests/coding/test_migration_045_contract.py`
- Modify: `tests/config/test_sandbox_config.py`

**Interfaces:**
- Consumes: existing coding task/run identities and `StrictConfigModel`.
- Produces: `AdmissionDecision`, `AdmissionReason`, `ManagedSandboxState`, `ProviderCircuitState`, `ProviderErrorCode`, `ManagedSandboxAllocation`, `ManagedSandboxCapabilities`, and `ManagedSandboxConfig`.

- [ ] **Step 1: Write failing domain and migration tests**

```python
from datetime import UTC, datetime, timedelta

import pytest

from neos.coding.managed.domain import (
    ManagedSandboxAllocation,
    ManagedSandboxState,
    ProviderErrorCode,
)

NOW = datetime(2026, 7, 25, tzinfo=UTC)


def test_nonterminal_allocation_requires_live_lease_and_fence() -> None:
    allocation = ManagedSandboxAllocation(
        allocation_id="msa_1",
        tenant_id="tenant_1",
        task_id="ct_1",
        run_id="cr_1",
        provider="fake",
        region="local",
        provider_ref=None,
        ownership_digest=None,
        state=ManagedSandboxState.ADMITTED,
        generation=1,
        fencing_token=3,
        lease_expires_at=NOW + timedelta(minutes=1),
        absolute_expires_at=NOW + timedelta(hours=4),
        version=1,
        error_code=None,
        snapshot_ref=None,
        archive_ref=None,
    )
    assert allocation.claimable_at(NOW) is False


def test_cleaned_allocation_cannot_retain_provider_ref() -> None:
    with pytest.raises(ValueError, match="cleaned allocation"):
        ManagedSandboxAllocation(
            allocation_id="msa_1", tenant_id="tenant_1", task_id="ct_1",
            run_id="cr_1", provider="fake", region="local",
            provider_ref="encrypted:ref", ownership_digest="sha256:owner",
            state=ManagedSandboxState.CLEANED, generation=1, fencing_token=3,
            lease_expires_at=None, absolute_expires_at=NOW, version=2,
            error_code=ProviderErrorCode.PROVIDER_NOT_FOUND,
            snapshot_ref=None, archive_ref=None,
        )
```

Migration contract:

```python
from pathlib import Path


def test_migration_045_has_single_current_generation_and_cleanup_ledger() -> None:
    sql = Path("db/migrations/045_add_coding_managed_sandboxes.sql").read_text()
    assert "CREATE TABLE coding_sandbox_admissions" in sql
    assert "CREATE TABLE coding_managed_sandboxes" in sql
    assert "CREATE TABLE coding_sandbox_cleanup_attempts" in sql
    assert "idx_coding_managed_sandboxes_current_task" in sql
    assert "WHERE cleaned_at IS NULL" in sql
    assert "provider_response" not in sql
    assert "prompt" not in sql
```

- [ ] **Step 2: Run tests and confirm missing contracts**

Run:

```bash
.venv/bin/pytest -q tests/coding/managed/test_domain.py \
  tests/coding/test_migration_045_contract.py \
  tests/config/test_sandbox_config.py
```

Expected: import, migration, and managed configuration failures.

- [ ] **Step 3: Implement immutable domain contracts**

Implement exact stable enums:

```python
class AdmissionDecision(StrEnum):
    ADMITTED = "admitted"
    DENIED = "denied"


class AdmissionReason(StrEnum):
    ALLOWED = "allowed"
    KILL_SWITCH = "kill_switch"
    TENANT_NOT_ALLOWED = "tenant_not_allowed"
    REPOSITORY_NOT_ALLOWED = "repository_not_allowed"
    QUOTA_EXCEEDED = "quota_exceeded"
    BUDGET_EXCEEDED = "budget_exceeded"
    PROVIDER_DEGRADED = "provider_degraded"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    REGION_UNAVAILABLE = "region_unavailable"


class ManagedSandboxState(StrEnum):
    REQUESTED = "requested"
    ADMITTED = "admitted"
    ALLOCATING = "allocating"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    RECOVERY_PENDING = "recovery_pending"
    MANUAL_RECOVERY_REQUIRED = "manual_recovery_required"
    CLEANUP_PENDING = "cleanup_pending"
    CLEANUP_RETRY = "cleanup_retry"
    CLEANED = "cleaned"
    FAILED = "failed"


class ProviderCircuitState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
```

`ProviderErrorCode` must contain only the codes in the approved spec. Define
`ManagedSandboxCapabilities` as a frozen dataclass of nine booleans and
`ManagedSandboxAllocation` as the frozen value used in the test. Validate
positive generation/fence/version, timezone-aware deadlines, and terminal
provider-reference cleanup. Add an explicit transition map and:

```python
def transition_allocation(
    allocation: ManagedSandboxAllocation,
    target: ManagedSandboxState,
    *,
    now: datetime,
    error_code: ProviderErrorCode | None = None,
) -> ManagedSandboxAllocation:
    if target not in _ALLOWED_ALLOCATION_TRANSITIONS[allocation.state]:
        raise InvalidManagedSandboxTransition(
            f"{allocation.state.value}->{target.value}"
        )
    updated = replace(
        allocation,
        state=target,
        version=allocation.version + 1,
        error_code=error_code,
    )
    if target is ManagedSandboxState.CLEANED:
        updated = replace(
            updated,
            provider_ref=None,
            ownership_digest=None,
            lease_expires_at=None,
        )
    return updated
```

The function increments `version`, rejects transitions outside the state graph,
and clears lease/provider references when entering `CLEANED`.

- [ ] **Step 4: Add migration and configuration**

Migration 045 creates the three approved tables. Store provider references as
`BYTEA`. Admission rows use `task_id REFERENCES coding_tasks(task_id) ON DELETE
CASCADE`; managed allocations use `ON DELETE RESTRICT` so a task cannot erase
an unconfirmed provider resource; cleanup attempts cascade from their managed
allocation. Use CHECK constraints for every stable state and add:

```sql
CREATE UNIQUE INDEX idx_coding_managed_sandboxes_current_task
ON coding_managed_sandboxes(task_id)
WHERE cleaned_at IS NULL
  AND state NOT IN ('cleaned', 'failed');
```

Add:

```python
class ManagedSandboxConfig(StrictConfigModel):
    enabled: bool = False
    shadow_admission: bool = True
    global_kill_switch: bool = False
    provider: str = "fake"
    region: str = "local"
    admission_reevaluation_seconds: int = Field(default=30, gt=0, le=300)
    reservation_lease_seconds: int = Field(default=60, gt=0, le=600)
    allocation_lease_seconds: int = Field(default=60, gt=0, le=600)
    cleanup_batch_size: int = Field(default=100, gt=0, le=1000)
    cleanup_slo_seconds: int = Field(default=300, gt=0)
    health_window_size: int = Field(default=20, ge=4, le=100)
    degraded_failure_ratio: float = Field(default=0.25, ge=0, le=1)
    unavailable_failure_ratio: float = Field(default=0.5, ge=0, le=1)
    concurrent_quota: int = Field(default=3, gt=0, le=100)
    daily_allocation_quota: int = Field(default=50, gt=0)
    daily_active_seconds_quota: int = Field(default=43_200, gt=0)
    archive_bytes_quota: int = Field(default=5 * 1024**3, gt=0)
    daily_cost_micros_quota: int = Field(default=10_000_000, gt=0)
```

Nest it at `sandbox.managed` and mirror exact defaults in
`config/neos.default.yaml`.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/pytest -q tests/coding/managed/test_domain.py \
  tests/coding/test_migration_045_contract.py \
  tests/config/test_sandbox_config.py
.venv/bin/ruff check neos/coding/managed/domain.py \
  tests/coding/managed/test_domain.py tests/coding/test_migration_045_contract.py
git diff --check
git add neos/coding/managed db/migrations/045_add_coding_managed_sandboxes.sql \
  neos/config/schema.py config/neos.default.yaml \
  tests/coding/managed/test_domain.py tests/coding/test_migration_045_contract.py \
  tests/config/test_sandbox_config.py
git commit -m "feat(coding): define managed sandbox lifecycle"
```

### Task 2: Durable Admission and Quota Reservation

**Files:**
- Create: `neos/coding/managed/repository.py`
- Create: `neos/coding/managed/admission.py`
- Create: `tests/coding/managed/test_admission.py`
- Create: `tests/coding/managed/test_repository.py`
- Create: `tests/coding/managed/integration/test_postgres_admission.py`

**Interfaces:**
- Consumes: Task 1 enums/configuration and the existing SQLAlchemy
  `SessionFactory`.
- Produces: `AdmissionRequest`, `AdmissionResult`,
  `PostgresManagedSandboxRepository.admit`,
  `release_expired_reservations`, and `ManagedSandboxAdmissionService`.

- [ ] **Step 1: Write failing admission-order and concurrency tests**

```python
async def test_unavailable_provider_denies_before_reserving_quota() -> None:
    repository = RecordingAdmissionRepository(active=0)
    service = ManagedSandboxAdmissionService(
        repository=repository,
        policy=allowlisted_policy(),
        health=FixedHealth(ProviderCircuitState.UNAVAILABLE),
        config=managed_config(),
    )

    result = await service.admit(request_fixture(idempotency_key="idem_1"))

    assert result.reason is AdmissionReason.PROVIDER_UNAVAILABLE
    assert repository.reserve_calls == 0


async def test_same_idempotency_key_returns_original_admission() -> None:
    repository = InMemoryAdmissionRepository()
    service = admission_service(repository)
    first = await service.admit(request_fixture(idempotency_key="idem_1"))
    second = await service.admit(request_fixture(idempotency_key="idem_1"))
    assert second == first
    assert repository.created_count == 1
```

The PostgreSQL test races four admissions against a concurrent quota of three
using `asyncio.gather` and asserts exactly three admitted rows and reservations.

- [ ] **Step 2: Run tests and verify the missing service/repository failures**

```bash
.venv/bin/pytest -q tests/coding/managed/test_admission.py \
  tests/coding/managed/test_repository.py
```

- [ ] **Step 3: Implement ordered admission**

Define:

```python
@dataclass(frozen=True, slots=True)
class AdmissionRequest:
    tenant_id: str
    task_id: str
    run_id: str
    repository_organization: str
    provider: str
    region: str
    required_capabilities: frozenset[str]
    idempotency_key: str
    estimated_active_seconds: int
    estimated_archive_bytes: int
    estimated_cost_micros: int


@dataclass(frozen=True, slots=True)
class AdmissionResult:
    admission_id: str
    allocation_id: str | None
    decision: AdmissionDecision
    reason: AdmissionReason
    reevaluate_after: datetime | None
    created: bool
```

`ManagedSandboxAdmissionService.admit()` evaluates kill switch, tenant,
repository, health, and region before calling the repository transaction.
Capability validation happens before quota. The repository transaction locks the
tenant quota key, counts current reservations, inserts the admission, reserves
quota, and creates the `ADMITTED` allocation in one commit.

- [ ] **Step 4: Implement lease settlement and PostgreSQL integration**

Repository methods have these exact signatures:

- `admit(request: AdmissionRequest, *, decision: AdmissionDecision, reason:
  AdmissionReason, now: datetime, reevaluate_after: datetime | None,
  reservation_expires_at: datetime | None, concurrent_quota: int, daily_quota:
  int, daily_active_seconds_quota: int, archive_bytes_quota: int,
  daily_cost_micros_quota: int) -> AdmissionResult`
- `settle_reservation(allocation_id: str, *, active_seconds: int,
  archive_bytes: int, cost_micros: int, now: datetime) -> bool`
- `release_expired_reservations(*, now: datetime, limit: int) -> Sequence[str]`

Insert into `coding_sandbox_admissions` with `ON CONFLICT (tenant_id,
idempotency_key)` for exact replay and use a
transaction-scoped PostgreSQL advisory lock derived from tenant ID for quota
serialization. The integration test is guarded by `CODING_TEST_DATABASE_URL`,
matching the existing durability integration pattern.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/pytest -q tests/coding/managed/test_admission.py \
  tests/coding/managed/test_repository.py
.venv/bin/ruff check neos/coding/managed/admission.py \
  neos/coding/managed/repository.py tests/coding/managed
git diff --check
git add neos/coding/managed/admission.py neos/coding/managed/repository.py \
  tests/coding/managed/test_admission.py tests/coding/managed/test_repository.py \
  tests/coding/managed/integration/test_postgres_admission.py
git commit -m "feat(coding): enforce sandbox admission quotas"
```

### Task 3: Provider Health Circuit and Stable Error Mapping

**Files:**
- Create: `neos/coding/managed/health.py`
- Create: `tests/coding/managed/test_health.py`
- Modify: `neos/observability/metrics.py`
- Modify: `tests/coding/test_durability_metrics.py`

**Interfaces:**
- Consumes: `ProviderCircuitState`, `ProviderErrorCode`, and Task 1 thresholds.
- Produces: `ProviderObservation`, `ProviderHealthSnapshot`,
  `ProviderHealthCircuit.observe`, `ProviderErrorMapper.normalize`,
  and fixed-cardinality managed sandbox metrics.

- [ ] **Step 1: Write failing circuit and privacy tests**

```python
def test_auth_error_opens_circuit_immediately() -> None:
    circuit = ProviderHealthCircuit(window_size=4, degraded_ratio=.25,
                                    unavailable_ratio=.5)
    result = circuit.observe(
        ProviderObservation(
            provider="fake", region="local",
            error_code=ProviderErrorCode.PROVIDER_AUTH_ERROR,
        )
    )
    assert result.state is ProviderCircuitState.UNAVAILABLE


def test_user_and_tool_errors_do_not_enter_provider_window() -> None:
    circuit = circuit_fixture()
    before = circuit.snapshot("fake", "local")
    circuit.observe_user_failure("fake", "local", "command_failed")
    assert circuit.snapshot("fake", "local") == before
```

Add a metric source inspection assertion that managed metric labels are subsets
of `provider`, `region`, `operation`, `outcome`, `reason`, and `error_code`.

- [ ] **Step 2: Confirm failures**

```bash
.venv/bin/pytest -q tests/coding/managed/test_health.py \
  tests/coding/test_durability_metrics.py
```

- [ ] **Step 3: Implement error normalization and circuit transitions**

`ProviderErrorMapper` maps injected adapter exceptions by typed category, never
by copying raw text. Unknown exceptions become `OTHER`. The circuit retains only
the last `window_size` success/failure observations for each provider/region.
Authentication errors immediately open it; rate limit, timeout, server, and
capacity failures count in the rolling ratio. A successful bounded health probe
is required to move `UNAVAILABLE -> DEGRADED`, and a full healthy window moves
`DEGRADED -> HEALTHY`.

- [ ] **Step 4: Add metrics**

Add:

```python
coding_sandbox_admission_total{decision,reason}
coding_sandbox_allocation_total{provider,region,outcome,error_code}
coding_sandbox_allocation_duration_seconds{provider,region,outcome}
coding_sandbox_provider_circuit{provider,region,state}
coding_sandbox_cleanup_age_seconds{provider,region}
coding_sandbox_cleanup_total{provider,region,outcome,error_code}
coding_sandbox_archive_total{provider,operation,outcome,error_code}
```

Do not add identities or free-form labels.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/pytest -q tests/coding/managed/test_health.py \
  tests/coding/test_durability_metrics.py
.venv/bin/ruff check neos/coding/managed/health.py \
  tests/coding/managed/test_health.py neos/observability/metrics.py
git diff --check
git add neos/coding/managed/health.py tests/coding/managed/test_health.py \
  neos/observability/metrics.py tests/coding/test_durability_metrics.py
git commit -m "feat(coding): gate providers with health circuits"
```

### Task 4: Capability-aware Adapter Port and Deterministic Fake Adapter

**Files:**
- Create: `neos/coding/managed/adapters/base.py`
- Create: `neos/coding/managed/adapters/fake.py`
- Create: `neos/coding/managed/adapters/docker_shadow.py`
- Create: `neos/coding/managed/adapters/__init__.py`
- Create: `tests/coding/managed/adapters/conformance.py`
- Create: `tests/coding/managed/adapters/test_fake.py`
- Create: `tests/coding/managed/adapters/test_docker_shadow.py`

**Interfaces:**
- Consumes: Task 1 capabilities/states and existing `SandboxProvider`.
- Produces: `ManagedSandboxAdapter`, request/result dataclasses,
  `FakeManagedSandboxAdapter`, `DockerShadowManagedAdapter`, and the adapter
  conformance suite used by real providers.

- [ ] **Step 1: Write failing adapter conformance tests**

```python
async def assert_managed_adapter_conformance(adapter) -> None:
    request = allocation_request(idempotency_key="idem_1")
    created = await adapter.allocate(request)
    replay = await adapter.allocate(request)
    assert replay.provider_ref == created.provider_ref
    assert await adapter.find_by_idempotency_key("idem_1") == (
        await adapter.inspect(created.provider_ref)
    )
    destroyed = await adapter.destroy(
        created.provider_ref, ownership_digest=created.ownership_digest
    )
    assert destroyed.confirmed is True
```

Add explicit tests for an injected “create succeeded then timed out” fault,
capability rejection, network-block capability, and ownership mismatch on
destroy.

- [ ] **Step 2: Confirm missing adapter failures**

```bash
.venv/bin/pytest -q tests/coding/managed/adapters/test_fake.py \
  tests/coding/managed/adapters/test_docker_shadow.py
```

- [ ] **Step 3: Define the adapter port**

Use frozen request/result types. `ManagedSandboxAdapter` is a `Protocol` with
immutable `provider: str` and `capabilities: ManagedSandboxCapabilities`
attributes and these exact async methods:

- `allocate(request: ManagedAllocationRequest) -> AllocationResult`
- `inspect(provider_ref: str) -> ProviderSandboxState`
- `suspend(provider_ref: str) -> LifecycleResult`
- `resume(provider_ref: str) -> LifecycleResult`
- `snapshot(provider_ref: str) -> SnapshotResult`
- `destroy(provider_ref: str, *, ownership_digest: str) -> DestroyResult`
- `find_by_idempotency_key(idempotency_key: str) -> ProviderSandboxState | None`
- `health(region: str) -> ProviderHealthProbe`

`ManagedAllocationRequest` contains allocation ID, idempotency key, region,
image identity, resource limits, network policy, metadata ownership digest, and
absolute expiry. It contains no repository credential or prompt.

- [ ] **Step 4: Implement fake and Docker shadow adapters**

The fake adapter is deterministic, supports injected typed failures, and records
calls. The Docker shadow adapter delegates lifecycle to the current Docker
provider but does not replace production factory wiring yet. It stores the
allocation idempotency key and ownership digest in NEOS labels and verifies them
during inspect/destroy. Declare only capabilities Docker actually supports.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/pytest -q tests/coding/managed/adapters
.venv/bin/ruff check neos/coding/managed/adapters tests/coding/managed/adapters
git diff --check
git add neos/coding/managed/adapters tests/coding/managed/adapters
git commit -m "feat(coding): add managed sandbox adapter port"
```

### Task 5: Fenced Allocation, Ambiguous Outcome Recovery, and Binding

**Files:**
- Create: `neos/coding/managed/allocation.py`
- Create: `neos/coding/managed/crypto.py`
- Modify: `neos/coding/managed/repository.py`
- Modify: `neos/coding/runtime.py`
- Create: `tests/coding/managed/test_allocation.py`
- Create: `tests/coding/managed/test_runtime.py`

**Interfaces:**
- Consumes: admitted rows, `ManagedSandboxAdapter`, error mapper, and existing
  `SandboxBindingService`.
- Produces: `ManagedSandboxAllocationService.advance(allocation_id, worker_id)`,
  `ProviderReferenceCipher`, fenced claim/commit repository methods, and runtime
  adapter registry.

- [ ] **Step 1: Write failing ambiguous-outcome and fencing tests**

```python
async def test_allocate_timeout_rediscovers_without_second_create() -> None:
    adapter = FakeManagedSandboxAdapter(
        allocate_fault=CreateThenTimeout()
    )
    service, repository = allocation_service(adapter=adapter)

    first = await service.advance("msa_1", worker_id="worker_1")
    assert first.state is ManagedSandboxState.RECOVERY_PENDING

    second = await service.advance("msa_1", worker_id="worker_2")
    assert second.state is ManagedSandboxState.ACTIVE
    assert adapter.allocate_calls == 1
    assert adapter.rediscovery_calls == 1


async def test_stale_fencing_token_cannot_commit_provider_ref() -> None:
    lease_one = await repository.claim_allocation("msa_1", "worker_1", NOW)
    lease_two = await repository.reclaim_expired("msa_1", "worker_2", LATER)
    with pytest.raises(StaleManagedSandboxLease):
        await repository.commit_active(lease_one, provider_result(), now=LATER)
    assert await repository.commit_active(lease_two, provider_result(), now=LATER)
```

- [ ] **Step 2: Confirm failures**

```bash
.venv/bin/pytest -q tests/coding/managed/test_allocation.py \
  tests/coding/managed/test_runtime.py
```

- [ ] **Step 3: Implement claim and one-transition advancement**

Repository methods lock the allocation, increment fencing token, set lease
owner/expiry, and return:

```python
@dataclass(frozen=True, slots=True)
class ManagedAllocationLease:
    allocation_id: str
    worker_id: str
    fencing_token: int
    expires_at: datetime
```

`advance()` performs at most one provider operation and one durable state
transition. For `ADMITTED`, commit `ALLOCATING` before calling the adapter. On a
definite typed failure commit `FAILED`; on timeout/connection ambiguity commit
`RECOVERY_PENDING`. For `RECOVERY_PENDING`, call only
`find_by_idempotency_key()`. Absence moves to
`MANUAL_RECOVERY_REQUIRED`; presence commits `ACTIVE` or `SUSPENDED`.

- [ ] **Step 4: Encrypt provider references and bind the data plane**

Define `ProviderReferenceCipher` as a protocol with exact synchronous methods
`encrypt(provider_ref: str) -> bytes` and
`decrypt(encrypted_ref: bytes) -> str`.

The production implementation uses AES-GCM from `cryptography`, a versioned
key supplied through the existing secret configuration, a random 96-bit nonce,
and `allocation_id:provider:generation` as associated data. Tests inject a
deterministic cipher. Decryption/authentication failure maps to
`MANUAL_RECOVERY_REQUIRED` with `provider_auth_error`; plaintext references are
never stored or logged.

After `ACTIVE` commits, construct/update the existing `SandboxBinding` with the
provider session identity through a dedicated binding adapter. Do not copy
managed provider credentials into `coding_sandbox_bindings`. Runtime creates an
adapter registry keyed by configured provider and injects it into the allocation
service. With `managed.enabled=false`, existing Memory/Docker behavior is
unchanged.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/pytest -q tests/coding/managed/test_allocation.py \
  tests/coding/managed/test_runtime.py tests/coding/sandbox/test_runtime_ownership.py
.venv/bin/ruff check neos/coding/managed/allocation.py \
  neos/coding/managed/repository.py tests/coding/managed
git diff --check
git add neos/coding/managed/allocation.py neos/coding/managed/crypto.py \
  neos/coding/managed/repository.py \
  neos/coding/runtime.py tests/coding/managed/test_allocation.py \
  tests/coding/managed/test_runtime.py
git commit -m "feat(coding): recover managed sandbox allocation"
```

### Task 6: Lifecycle Reconciliation, Cleanup SLO, and Celery Delivery

**Files:**
- Create: `neos/coding/managed/lifecycle.py`
- Create: `neos/coding/managed/workers.py`
- Modify: `neos/coding/managed/repository.py`
- Modify: `neos/coding/workers/celery_tasks.py`
- Modify: `neos/workflow/celery_app.py`
- Create: `tests/coding/managed/test_lifecycle.py`
- Create: `tests/coding/managed/test_workers.py`
- Modify: `tests/coding/workers/test_celery_tasks.py`

**Interfaces:**
- Consumes: Task 5 allocation service, task repository, adapter registry, and
  managed configuration.
- Produces: `ManagedSandboxLifecycleReconciler`,
  `ManagedSandboxCleanupService`, Celery allocation/cleanup/reconciliation
  tasks, and cleanup retry discovery.

- [ ] **Step 1: Write failing cleanup and terminal reconciliation tests**

```python
async def test_terminal_task_is_marked_cleanup_pending_then_destroyed() -> None:
    repository, adapter, service = lifecycle_fixture(
        task_status=CodingTaskStatus.COMPLETED
    )
    discovered = await service.reconcile(limit=10, now=NOW)
    assert discovered == ("msa_1",)
    result = await service.cleanup("msa_1", worker_id="cleanup_1", now=NOW)
    assert result.state is ManagedSandboxState.CLEANED
    assert adapter.destroy_calls == 1


async def test_unverified_not_found_remains_cleanup_retry() -> None:
    adapter = fake_adapter(
        destroy_result=DestroyResult(
            confirmed=False,
            not_found=True,
            ownership_verified=False,
        )
    )
    result = await cleanup_service(adapter).cleanup(
        "msa_1", worker_id="cleanup_1", now=NOW
    )
    assert result.state is ManagedSandboxState.CLEANUP_RETRY
    assert result.error_code is ProviderErrorCode.CLEANUP_UNCONFIRMED
```

Also test absolute TTL cleanup while a coding task remains running, bounded
exponential retry `5, 15, 45, 120, 300`, lease expiry recovery, and provider
outage not disabling cleanup discovery.

- [ ] **Step 2: Confirm failures**

```bash
.venv/bin/pytest -q tests/coding/managed/test_lifecycle.py \
  tests/coding/managed/test_workers.py \
  tests/coding/workers/test_celery_tasks.py
```

- [ ] **Step 3: Implement lifecycle and cleanup services**

`reconcile()` selects bounded candidates when task status is terminal/deleted,
absolute expiry has passed, or allocation lease is stale. It atomically moves
them to `CLEANUP_PENDING` or returns recovery candidates. `cleanup()` claims a
new fence, verifies provider ownership, calls destroy, and writes a cleanup
attempt. Confirmed destruction or verified Not Found enters `CLEANED`; all other
results enter `CLEANUP_RETRY` with the exact retry schedule.

- [ ] **Step 4: Add bounded Celery tasks and schedule**

Register:

```text
neos.coding.managed.allocate
neos.coding.managed.reconcile
neos.coding.managed.cleanup
neos.coding.managed.reconcile_quota
neos.coding.managed.probe_health
```

Messages contain only `allocation_id` and expected generation where applicable.
Route them to the existing coding queue initially. Add beat schedules behind
`sandbox.managed.enabled`; cleanup and reconciliation remain scheduled while the
global admission kill switch is active.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/pytest -q tests/coding/managed/test_lifecycle.py \
  tests/coding/managed/test_workers.py tests/coding/workers/test_celery_tasks.py
.venv/bin/ruff check neos/coding/managed neos/coding/workers/celery_tasks.py \
  tests/coding/managed
git diff --check
git add neos/coding/managed/lifecycle.py neos/coding/managed/workers.py \
  neos/coding/managed/repository.py neos/coding/workers/celery_tasks.py \
  neos/workflow/celery_app.py tests/coding/managed/test_lifecycle.py \
  tests/coding/managed/test_workers.py tests/coding/workers/test_celery_tasks.py
git commit -m "feat(coding): reconcile managed sandbox cleanup"
```

### Task 7: Portable Archive and Operator-approved Recovery

**Files:**
- Create: `neos/coding/managed/archive.py`
- Modify: `neos/coding/managed/repository.py`
- Modify: `neos/coding/managed/allocation.py`
- Create: `tests/coding/managed/test_archive.py`
- Create: `tests/coding/managed/test_recovery.py`

**Interfaces:**
- Consumes: existing `SandboxArchive`, adapter/binding session, allocation
  generation/fence, and operator identity.
- Produces: `PortableArchiveManifest`, `PortableArchiveStore`,
  `ManagedSandboxArchiveService`, and
  `ManagedSandboxArchiveService.approve_recovery`.

- [ ] **Step 1: Write failing archive integrity and approval tests**

```python
async def test_checksum_mismatch_never_creates_recovery_generation() -> None:
    store = MemoryArchiveStore(body=b"tampered")
    service, repository = archive_service(
        store=store,
        manifest=manifest(checksum=sha256(b"expected")),
    )
    with pytest.raises(PortableRecoveryConflict, match="archive_invalid"):
        await service.approve_recovery(
            allocation_id="msa_1",
            archive_checksum=sha256(b"expected"),
            operator_id="admin_1",
        )
    assert repository.generation == 1


async def test_approved_recovery_creates_new_fenced_generation() -> None:
    service, repository = valid_archive_service()
    recovered = await service.approve_recovery(
        allocation_id="msa_1",
        archive_checksum=repository.manifest.checksum,
        operator_id="admin_1",
    )
    assert recovered.generation == 2
    assert recovered.state is ManagedSandboxState.ADMITTED
    assert recovered.provider_ref is None
```

- [ ] **Step 2: Confirm failures**

```bash
.venv/bin/pytest -q tests/coding/managed/test_archive.py \
  tests/coding/managed/test_recovery.py
```

- [ ] **Step 3: Implement manifest, store, and verification**

```python
@dataclass(frozen=True, slots=True)
class PortableArchiveManifest:
    archive_id: str
    allocation_id: str
    generation: int
    workspace_revision: str
    checksum: str
    content_bytes: int
    image_identity: str
    toolchain_identity: str
    encryption_key_ref: str
    scan_status: Literal["clean", "rejected"]
    created_at: datetime
    expires_at: datetime
```

`PortableArchiveStore` has bounded `put`, `get`, and `delete` methods and returns
bytes only inside the archive service. Verify archive size, SHA-256, path
normalization through existing archive parsing, scan status, image/toolchain
compatibility, and retention before repository mutation.

- [ ] **Step 4: Implement operator-bound recovery**

The approval transaction locks the source allocation and manifest, verifies
`MANUAL_RECOVERY_REQUIRED`, checksum, operator authorization input, and that no
current generation exists. It closes the source generation and creates
generation + 1 in `ADMITTED` with a fresh fence and quota reservation. Persist a
bounded audit decision containing allocation ID, operator ID, checksum, policy
version, and stable outcome; never store archive body.

On allocation, import the workspace archive into a fresh provider sandbox and
resume the coding run only from its latest durable checkpoint. Do not recreate
PTYs or background processes.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/pytest -q tests/coding/managed/test_archive.py \
  tests/coding/managed/test_recovery.py tests/coding/sandbox/test_archive.py
.venv/bin/ruff check neos/coding/managed/archive.py \
  tests/coding/managed/test_archive.py tests/coding/managed/test_recovery.py
git diff --check
git add neos/coding/managed/archive.py neos/coding/managed/repository.py \
  neos/coding/managed/allocation.py tests/coding/managed/test_archive.py \
  tests/coding/managed/test_recovery.py
git commit -m "feat(coding): recover portable sandbox archives"
```

### Task 8: Owner Projection and Admin Control API

**Files:**
- Create: `neos/coding/managed/projection.py`
- Modify: `neos/api/models/coding_models.py`
- Modify: `neos/api/handlers/coding_handlers.py`
- Create: `neos/api/handlers/coding_admin_handlers.py`
- Modify: `neos/main.py`
- Create: `tests/coding/managed/test_projection.py`
- Create: `tests/api/handlers/test_coding_managed_handlers.py`

**Interfaces:**
- Consumes: managed repository, authenticated owner/admin dependencies, archive
  recovery service, and provider health drain service.
- Produces: owner `sandbox-status` projection and admin drain, cleanup retry,
  and recovery approval endpoints.

- [ ] **Step 1: Write failing authorization and privacy tests**

```python
async def test_owner_status_hides_provider_reference_and_raw_error(client) -> None:
    response = await client.get(
        "/api/v1/coding/tasks/ct_1/sandbox-status",
        headers=owner_headers("u1"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "state": "provider_recovery_pending",
        "can_run": False,
        "can_open_terminal": False,
        "recovered_from_checkpoint": False,
        "updated_at": "2026-07-25T00:00:00Z",
    }
    assert "provider_ref" not in body
    assert "error" not in body


async def test_non_admin_cannot_retry_cleanup(client) -> None:
    response = await client.post(
        "/api/v1/admin/coding/allocations/msa_1/retry-cleanup",
        headers=owner_headers("u1"),
    )
    assert response.status_code == 403
```

Also assert non-owner task status is 404 before allocation lookup and recovery
approval is checksum-bound.

- [ ] **Step 2: Confirm failures**

```bash
.venv/bin/pytest -q tests/coding/managed/test_projection.py \
  tests/api/handlers/test_coding_managed_handlers.py
```

- [ ] **Step 3: Implement bounded projection**

Map internal states to only:

```python
PREPARING = "preparing"
READY = "ready"
SUSPENDED = "suspended"
PROVIDER_RECOVERY_PENDING = "provider_recovery_pending"
OPERATOR_RECOVERY_REQUIRED = "operator_recovery_required"
CLEANING_UP = "cleaning_up"
CLEANED = "cleaned"
```

The response contains state, `can_run`, `can_open_terminal`,
`recovered_from_checkpoint`, and `updated_at`. It contains no provider/region,
reference, allocation identity, circuit detail, or raw error.

- [ ] **Step 4: Implement routes and runtime dependencies**

Add the exact routes approved in the spec. Drain changes only the configured
provider/region circuit override and blocks new admission. Retry cleanup clears
`next_retry_at` after state/fence validation. Recovery approval accepts:

```python
class CodingSandboxRecoveryRequest(BaseModel):
    archive_checksum: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
```

Include the admin router through the existing production authorization graph and
add route classification tests.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/pytest -q tests/coding/managed/test_projection.py \
  tests/api/handlers/test_coding_managed_handlers.py \
  tests/api/handlers/test_query_authorization.py
.venv/bin/ruff check neos/coding/managed/projection.py \
  neos/api/handlers/coding_admin_handlers.py \
  tests/api/handlers/test_coding_managed_handlers.py
git diff --check
git add neos/coding/managed/projection.py neos/api/models/coding_models.py \
  neos/api/handlers/coding_handlers.py neos/api/handlers/coding_admin_handlers.py \
  neos/main.py tests/coding/managed/test_projection.py \
  tests/api/handlers/test_coding_managed_handlers.py
git commit -m "feat(coding): expose managed sandbox status"
```

### Task 9: Browser Sandbox Status and Execution Gating

**Files:**
- Modify: `web/features/coding/api/coding-api.ts`
- Create: `web/features/coding/sandbox/types.ts`
- Create: `web/features/coding/sandbox/sandbox-status-store.ts`
- Create: `web/features/coding/sandbox/use-sandbox-status.ts`
- Create: `web/features/coding/components/coding-sandbox-status.tsx`
- Modify: `web/features/coding/components/coding-task-workspace.tsx`
- Modify: `web/features/coding/components/workspace/coding-terminal.tsx`
- Create: `web/app/(code)/api/coding/tasks/[taskId]/sandbox-status/route.ts`
- Create: `web/tests/source/coding-sandbox-status.test.ts`

**Interfaces:**
- Consumes: Task 8 owner projection and existing authenticated BFF pattern.
- Produces: typed sandbox status polling/store, bounded status UI, and run/PTY
  gating.

- [ ] **Step 1: Write failing source tests**

```typescript
test("provider recovery preserves draft and blocks execution surfaces", () => {
  const state = reduceSandboxStatus(initialSandboxStatus, {
    state: "provider_recovery_pending",
    can_run: false,
    can_open_terminal: false,
    recovered_from_checkpoint: false,
    updated_at: "2026-07-25T00:00:00Z",
  });

  assert.equal(state.canRun, false);
  assert.equal(state.canOpenTerminal, false);
  assert.equal(state.copy, "Provider recovery pending");
});
```

Source assertions must verify the BFF uses GET only, no provider/internal IDs
are accepted by the client type, the composer draft is not cleared, and PTY
create is disabled while file/diff read remains available.

- [ ] **Step 2: Confirm failures**

```bash
cd web
pnpm exec tsx --test tests/source/coding-sandbox-status.test.ts
```

- [ ] **Step 3: Implement type, store, and polling hook**

```typescript
export type CodingSandboxStatus = {
  state:
    | "preparing"
    | "ready"
    | "suspended"
    | "provider_recovery_pending"
    | "operator_recovery_required"
    | "cleaning_up"
    | "cleaned";
  can_run: boolean;
  can_open_terminal: boolean;
  recovered_from_checkpoint: boolean;
  updated_at: string;
};
```

Poll at 5 seconds only while the agent WebSocket is connected or the state is
nonterminal. On network error retain the last status and show a non-destructive
stale indicator. Do not infer provider health from WebSocket state.

- [ ] **Step 4: Implement accessible status and gating**

Render an `aria-live="polite"` compact status beside the task phase. Disable run
submission and terminal creation from server booleans, not copied state names.
Keep file/diff browsing and composer draft intact. When
`recovered_from_checkpoint` becomes true, show “Restored in a new execution
environment” once without exposing provider detail.

- [ ] **Step 5: Verify and commit**

```bash
cd web
pnpm exec tsx --test tests/source/coding-sandbox-status.test.ts
pnpm run test:source
pnpm exec tsc --noEmit
cd ..
git restore web/tsconfig.tsbuildinfo
git diff --check
git add web/features/coding/api/coding-api.ts \
  web/features/coding/sandbox \
  web/features/coding/components/coding-sandbox-status.tsx \
  web/features/coding/components/coding-task-workspace.tsx \
  web/features/coding/components/workspace/coding-terminal.tsx \
  'web/app/(code)/api/coding/tasks/[taskId]/sandbox-status/route.ts' \
  web/tests/source/coding-sandbox-status.test.ts
git commit -m "feat(coding): surface managed sandbox recovery"
```

### Task 10: E2B and Modal Benchmark Adapters, Vertical Slice, and Operations

**Files:**
- Create: `neos/coding/managed/adapters/e2b.py`
- Create: `neos/coding/managed/adapters/modal.py`
- Create: `neos/coding/managed/benchmark.py`
- Modify: `neos/coding/managed/adapters/__init__.py`
- Create: `tests/coding/managed/adapters/test_e2b.py`
- Create: `tests/coding/managed/adapters/test_modal.py`
- Create: `tests/coding/managed/test_vertical_slice.py`
- Create: `tests/coding/managed/integration/test_e2b_opt_in.py`
- Create: `tests/coding/managed/integration/test_modal_opt_in.py`
- Modify: `docs/NEOS_CODING.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: Tasks 1–9 adapter conformance, control plane, archive recovery,
  status projection, and opt-in secrets.
- Produces: two benchmark-only real provider adapters, bounded benchmark report,
  deterministic end-to-end acceptance, and rollout/runbook documentation.

- [ ] **Step 1: Write failing injected-client adapter tests**

E2B and Modal modules define narrow client protocols so default tests do not
import or call vendor SDKs:

```python
async def test_e2b_maps_pause_resume_and_snapshot_disconnect() -> None:
    client = FakeE2BClient()
    adapter = E2BManagedSandboxAdapter(client=client)
    result = await adapter.allocate(allocation_request("idem_1"))
    await adapter.snapshot(result.provider_ref)
    assert adapter.capabilities.pause_resume is True
    assert client.reconnect_required is True


async def test_modal_caps_lifetime_at_twenty_four_hours() -> None:
    adapter = ModalManagedSandboxAdapter(client=FakeModalClient())
    with pytest.raises(ManagedAdapterValidationError, match="max lifetime"):
        await adapter.allocate(
            allocation_request("idem_1", lifetime_seconds=86_401)
        )
```

Both adapters must pass the shared conformance suite with injected clients and
must default to all outbound network blocked.

- [ ] **Step 2: Confirm failures**

```bash
.venv/bin/pytest -q tests/coding/managed/adapters/test_e2b.py \
  tests/coding/managed/adapters/test_modal.py \
  tests/coding/managed/test_vertical_slice.py
```

- [ ] **Step 3: Implement thin benchmark adapters**

Vendor modules translate only allocation, inspect, suspend/resume where
supported, filesystem/snapshot, destroy, metadata rediscovery, and health.
Construction accepts an injected client; SDK import and credential loading occur
only inside opt-in factory functions. Never accept arbitrary tunnel exposure.
E2B metadata binds allocation/idempotency/ownership. Modal uses
`block_network=True`, a maximum 24-hour timeout, and user metadata for the same
bounded identities. Unsupported capabilities return a typed
`ManagedAdapterCapabilityError`.

The benchmark runner returns:

```python
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
```

It serializes no IDs, content, command output, or raw errors.

- [ ] **Step 4: Add deterministic vertical slice and opt-in guards**

The default slice exercises admitted → ambiguous allocation →
rediscovery/active → archive → terminal cleanup → cleaned and asserts public
status/privacy at each stage. Opt-in tests require both provider-specific flags
and credentials:

```text
CODING_TEST_E2B=1 + E2B_API_KEY
CODING_TEST_MODAL=1 + MODAL_TOKEN_ID + MODAL_TOKEN_SECRET
```

Each smoke creates at most one sandbox, sets lifetime ≤ 300 seconds, blocks
network, records a cost ceiling, destroys in `finally`, and skips with an exact
setup reason when prerequisites are absent.

- [ ] **Step 5: Document rollout, rollback, and incident procedures**

Append a managed control-plane operations section to `docs/NEOS_CODING.md`
covering migration 045, shadow admission, Docker comparison, benchmark report,
canary enablement, circuit drain, cleanup SLO, archive recovery approval,
provider exit, secret rotation, and rollback. Add opt-in commands to README.

- [ ] **Step 6: Run full verification and commit**

```bash
.venv/bin/pytest -q tests/coding/managed tests/coding/sandbox \
  tests/api/handlers/test_coding_managed_handlers.py \
  tests/api/handlers/test_query_authorization.py
.venv/bin/ruff check neos/coding/managed tests/coding/managed \
  neos/api/handlers/coding_admin_handlers.py
cd web
pnpm run test:source
pnpm exec tsc --noEmit
cd ..
git restore web/tsconfig.tsbuildinfo
git diff --check
git add neos/coding/managed/adapters/e2b.py \
  neos/coding/managed/adapters/modal.py neos/coding/managed/benchmark.py \
  neos/coding/managed/adapters/__init__.py \
  tests/coding/managed/adapters/test_e2b.py \
  tests/coding/managed/adapters/test_modal.py \
  tests/coding/managed/test_vertical_slice.py \
  tests/coding/managed/integration/test_e2b_opt_in.py \
  tests/coding/managed/integration/test_modal_opt_in.py \
  docs/NEOS_CODING.md README.md
git commit -m "test(coding): verify managed sandbox pilot"
```

## Final Acceptance Gate

Run:

```bash
.venv/bin/pytest -q tests/coding tests/api/handlers/test_query_authorization.py
.venv/bin/ruff check neos/coding neos/api/handlers/coding_handlers.py \
  neos/api/handlers/coding_admin_handlers.py tests/coding
cd web
pnpm run test:source
pnpm exec tsc --noEmit
cd ..
git restore web/tsconfig.tsbuildinfo
git diff --check
```

Expected:

- All deterministic coding, authorization, source, and type tests pass.
- Vendor integration tests skip unless their explicit flags and credentials are
  present.
- No managed allocation can exceed quota under the PostgreSQL race test.
- Ambiguous create recovery performs one provider allocation.
- Provider outage blocks new admission while cleanup discovery still runs.
- Verified Not Found is cleaned; ownership mismatch remains retryable.
- Cross-provider recovery is impossible without checksum-bound admin approval.
- Public status and metrics contain no provider references or sensitive values.

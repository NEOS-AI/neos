# Managed Sandbox Control Plane Design

**Date:** 2026-07-25

**Status:** Approved design

**Scope:** Phase 5 managed sandbox pilot control plane

## 1. Purpose

NEOS currently has a provider-neutral `SandboxProvider` execution contract and
Memory/Docker implementations. The next production boundary is not another
execution API. It is a durable control plane that decides whether a sandbox may
be created, tracks its lifecycle independently of a worker process, blocks new
work during provider incidents, and proves eventual cleanup.

This design keeps `SandboxProvider` as the execution data plane. A separate
`ManagedSandboxControlPlane` owns admission, quota, provider health, allocation
leases, recovery, and cleanup. The first rollout uses a fake managed adapter and
the existing Docker provider as shadow baselines before enabling a paid provider.

The pilot is deliberately fail-closed:

- New tasks are rejected while their selected provider is unavailable.
- Existing tasks may reconnect or recover only on the same provider.
- Automatic cross-provider failover is prohibited.
- An operator may approve cross-provider recovery only from a verified portable
  workspace archive.

## 2. Goals and Non-goals

### 2.1 Goals

- Make every admission and allocation decision durable and idempotent.
- Enforce tenant/canary policy, concurrent quota, budget, and provider health
  before making a provider API call.
- Prevent duplicate allocation after ambiguous provider timeouts.
- Reconcile provider state after worker or API process failure.
- Suspend, resume, archive, and destroy sandboxes through capability-aware
  adapters.
- Meet a measurable cleanup SLO using terminal events, leases, and absolute TTL.
- Preserve a provider exit path through encrypted, checksummed workspace
  archives.
- Expose bounded user and operator states without leaking credentials, provider
  response bodies, or workspace contents.

### 2.2 Non-goals

- Automatic provider selection or cost optimization.
- Live process, memory, PTY, or socket migration between providers.
- Multi-agent coordinator or write-agent fan-out.
- General outbound network access.
- Billing settlement, GitHub App credentials, push, or pull request creation.
- Treating provider snapshots as portable across vendors.

## 3. External Provider Constraints

Provider features are capabilities, not assumptions in the common contract.
These constraints were verified against official documentation on 2026-07-25.

- E2B distinguishes one-to-one pause/resume from one-to-many snapshots. Snapshot
  creation temporarily drops active WebSocket, PTY, and command streams.
- Modal sandboxes have a maximum configured lifetime of 24 hours. Filesystem
  snapshots are appropriate for longer persistence, while memory snapshots have
  tighter retention and restoration constraints.
- Daytona exposes automated stop, pause, archive, and delete intervals, with
  activity semantics that differ from internal process liveness.

References:

- [E2B lifecycle](https://e2b.dev/docs/sandbox/auto-resume)
- [E2B snapshots](https://e2b.dev/docs/sandbox/snapshots)
- [Modal sandboxes](https://modal.com/docs/guide/sandboxes)
- [Modal snapshots](https://modal.com/docs/guide/sandbox-snapshots)
- [Modal networking](https://modal.com/docs/guide/sandbox-networking)
- [Daytona sandboxes](https://www.daytona.io/docs/en/sandboxes/)

Because lifecycle and snapshot semantics differ, the pilot never silently
degrades a requested capability and never restores a vendor snapshot through a
different vendor.

## 4. Architecture

```text
Coding task request
        |
        v
AdmissionService
  - global kill switch
  - tenant/canary policy
  - repository policy
  - quota/budget reservation
  - provider health circuit
        |
        v
ManagedSandboxControlPlane
  - durable allocation state
  - fencing and lease
  - suspend/resume
  - snapshot/archive metadata
  - recovery and cleanup
        |
        v
ManagedSandboxAdapter
        |
        v
Existing SandboxProvider execution data plane
```

The units have intentionally narrow responsibilities:

- `AdmissionService` answers whether a specific request may reserve capacity.
- `ManagedSandboxControlPlane` advances one durable allocation state transition.
- `ManagedSandboxAdapter` translates lifecycle operations to one provider SDK.
- Existing `SandboxProvider` and `SandboxSession` continue to execute file,
  command, watcher, PTY, snapshot, and archive operations.
- Reconcilers advance durable state; browser and API process lifetime do not.

## 5. Durable State Model

### 5.1 Allocation state machine

```text
requested
  -> admitted
  -> allocating
       -> active
       -> recovery_pending
       -> failed

active
  -> suspended
  -> recovery_pending
  -> cleanup_pending

suspended
  -> active
  -> manual_recovery_required
  -> cleanup_pending

recovery_pending
  -> active | suspended
  -> allocating          # operator-approved portable recovery only
  -> manual_recovery_required

cleanup_pending
  -> cleaned
  -> cleanup_retry

cleanup_retry
  -> cleaned
  -> cleanup_retry
```

`paused`, approval waiting, and user waiting coding task states do not imply
sandbox cleanup. Coding terminal states, deletion, allocation absolute TTL, or
an explicit admin kill do.

### 5.2 Tables

#### `coding_sandbox_admissions`

- admission ID and idempotency key
- tenant, task, selected provider, and region
- policy version
- decision and stable reason
- quota reservation identity and expiry
- timestamps

It stores no prompt, file content, repository credential, or provider response.
A repeated idempotency key returns the original admission. Rejected decisions
have a bounded reevaluation expiry.

#### `coding_managed_sandboxes`

- allocation ID, tenant, task, and canonical run binding
- provider and region
- encrypted provider sandbox reference
- allocation generation, version, fencing token, and lease expiry
- lifecycle state and stable error code
- provider snapshot reference and portable archive reference
- image/toolchain identity
- created, updated, absolute expiry, and cleaned timestamps

Only one nonterminal allocation generation may be current for a task. Every
mutation compares version and fencing token.

#### `coding_sandbox_cleanup_attempts`

- allocation and attempt identity
- claimed fencing token
- stable outcome/error code
- next retry time
- started and finished timestamps

Provider response bodies, secrets, command values, and workspace contents are
excluded.

## 6. Admission and Quota

Admission evaluates in a fixed fail-fast order:

```text
global kill switch
-> tenant/canary allowlist
-> repository/organization allowlist
-> concurrent quota
-> daily budget
-> provider circuit
-> region capacity
-> durable admitted decision and quota reservation
```

No provider API runs before the admitted decision and reservation commit.
Initial quotas cover:

- concurrent `allocating` and `active` allocations
- daily allocation count
- accumulated active seconds
- snapshot/archive bytes
- optional provider cost estimate

Reservations have leases. Allocation failure, cleanup completion, and the
reservation reconciler release or settle them. A crashed worker cannot reserve
capacity indefinitely.

The pilot does not choose a provider automatically. A versioned tenant/canary
policy selects one provider and region for new allocations. Existing allocations
remain pinned to their original provider and region.

## 7. Provider Health and Error Taxonomy

Provider health has three public control-plane states:

- `healthy`: new and existing operations are allowed.
- `degraded`: existing operations are allowed; new canary allocation is policy
  controlled.
- `unavailable`: new allocation is blocked; existing allocation may only be
  inspected, recovered on the same provider, archived, or cleaned.

Circuit samples include provider timeout, rate limit, provider 5xx, capacity,
and authentication/account errors. User validation, quota rejection, tool
failure, and sandbox command exit do not affect provider health.

Authentication/account failure opens the circuit immediately. Timeout and 5xx
advance `healthy -> degraded -> unavailable` through a bounded rolling window.
Stable error codes include:

- `provider_timeout`
- `provider_rate_limited`
- `provider_server_error`
- `provider_auth_error`
- `provider_capacity`
- `provider_not_found`
- `quota_exceeded`
- `policy_denied`
- `cleanup_unconfirmed`
- `archive_invalid`
- `other`

Raw exception text never becomes a metric label or public event.

## 8. Adapter Contract

```python
class ManagedSandboxAdapter(Protocol):
    async def allocate(self, request) -> AllocationResult: ...
    async def inspect(self, provider_ref) -> ProviderSandboxState: ...
    async def suspend(self, provider_ref) -> SuspendResult: ...
    async def resume(self, provider_ref) -> ResumeResult: ...
    async def snapshot(self, provider_ref) -> SnapshotResult: ...
    async def destroy(self, provider_ref) -> DestroyResult: ...
    async def find_by_idempotency_key(
        self, idempotency_key
    ) -> ProviderSandboxState | None: ...
    async def health(self, region) -> ProviderHealth: ...
```

Adapters declare capabilities:

- `pause_resume`
- `filesystem_snapshot`
- `memory_snapshot`
- `portable_archive`
- `network_block_all`
- `network_allowlist`
- `region_pin`
- `idempotent_allocate`
- `metadata_rediscovery`

Admission rejects an allocation whose required capability is absent. It never
falls back to a weaker network, retention, or recovery policy.

An ambiguous allocate timeout moves the record to `recovery_pending`. The
reconciler uses the allocation idempotency key and provider metadata to find the
original sandbox. It does not issue another allocate request until absence is
proven or an operator authorizes a new generation.

## 9. Portable Archive and Recovery

Portable recovery exports only the bounded workspace archive. It records:

- archive checksum and byte size
- source image/toolchain identity
- workspace revision
- allocation generation and fencing token
- creation and retention expiry
- encryption key reference
- security scan status

Restore creates a fresh sandbox from an approved base image, validates checksum,
archive paths, image/toolchain compatibility, and scan state, then imports the
workspace. It does not restore memory, process, PTY, socket, or open connection
state. The coding worker resumes from the last durable coding checkpoint and
creates new transient processes.

Cross-provider recovery requires:

1. a verified portable archive;
2. an operator decision bound to the source allocation and archive checksum;
3. a new allocation generation and fencing token;
4. successful restore verification before the task becomes runnable.

## 10. Workers and Reconciliation

- `AllocationWorker` claims admitted records, allocates or rediscovers the
  provider sandbox, and commits one fenced transition.
- `LifecycleReconciler` compares task state, allocation lease, and provider
  state in bounded batches.
- `CleanupWorker` destroys sandboxes with bounded exponential retry and records
  cleanup age.
- `ProviderHealthMonitor` performs low-frequency bounded probes and updates the
  circuit.
- `ArchiveWorker` creates, verifies, restores, and expires portable archives.
- `QuotaReconciler` releases expired reservations and settles usage.

Celery messages contain bounded allocation or task identity only. Credentials,
repository URLs, provider references, prompts, and content do not enter broker
payloads.

Cleanup is driven by both events and periodic reconciliation. A provider
`NotFound` response counts as cleaned only when the stored provider reference
and ownership metadata identify the expected allocation. Otherwise the result is
`cleanup_unconfirmed`.

## 11. API and Browser Projection

Owner-scoped user API:

```text
GET /api/v1/coding/tasks/{task_id}/sandbox-status
```

Admin API:

```text
POST /api/v1/admin/coding/providers/{provider}/drain
POST /api/v1/admin/coding/allocations/{allocation_id}/retry-cleanup
POST /api/v1/admin/coding/allocations/{allocation_id}/approve-recovery
```

The browser receives only these user-facing states:

- preparing environment
- ready
- suspended
- provider recovery pending
- operator recovery required
- cleaning up
- cleaned

`recovery_pending` preserves user input but blocks new model runs and PTY
creation. After portable recovery the UI states that the durable checkpoint was
restored in a new execution environment. Provider sandbox IDs, raw credential
errors, capacity detail, and operator audit data stay private.

## 12. Observability and Audit

Metrics use fixed-cardinality labels:

- admission count by decision and stable reason
- allocation latency/count by provider, region, and outcome
- provider circuit state
- reservation count and quota saturation
- cleanup age, retry count, and cleanup SLO violation
- archive create/restore/verification outcome

Task, run, tenant, allocation, sandbox, repository, path, and actor IDs are not
metric labels. Authorized audit records may retain bounded identities, policy
version, operation, decision, and stable outcome, but never credentials, provider
response bodies, prompts, file content, terminal streams, or command arguments.

## 13. Rollout and Rollback

Rollout:

1. Deploy migration and read-only projection.
2. Run fake adapter with shadow admission decisions.
3. Put the existing Docker provider behind the control plane and compare
   lifecycle outcomes with the current path.
4. Connect at least two real provider adapters in benchmark-only mode.
5. Select one provider/region for allowlisted canary tenants.
6. Expand only after security review, cleanup SLO, and error budget pass.

Rollback first disables new admission. Inspect, same-provider recovery, archive,
and cleanup workers remain active for existing allocations. Durable rows,
provider references, archives, and audit records are preserved. Rollback never
marks an unconfirmed allocation cleaned.

## 14. Verification

Default deterministic tests:

- state transition and invariant property tests
- concurrent quota reservation and lease recovery
- ambiguous allocation timeout without duplicate creation
- provider circuit error classification
- terminal task, deletion, lease, and absolute TTL cleanup
- ownership verification for provider `NotFound`
- lost snapshot and invalid archive checksum
- portable recovery and durable checkpoint resume
- outage admission blocking and bounded browser status
- adapter capability and conformance suites

Opt-in provider benchmarks require explicit provider flags and secrets, enforce a
per-run allocation/time/cost budget, and clean every created resource in a
finally path. Benchmark reports compare:

- cold and warm allocation latency
- command/file/PTY/watcher behavior
- suspend/resume and snapshot latency
- network isolation
- ambiguous timeout rediscovery
- cleanup latency and Not Found semantics
- regional availability and estimated cost

## 15. Acceptance Criteria

- A worker crash after provider allocation cannot create a duplicate sandbox.
- Provider outage blocks new allocation without stopping cleanup reconciliation.
- Existing sandboxes never fail over to another provider automatically.
- Concurrent quota cannot be exceeded under racing requests.
- Terminal and absolute-TTL allocations meet the configured cleanup SLO.
- Every nonterminal allocation has a current lease or is claimable by a
  reconciler.
- Cross-provider recovery requires a verified archive and explicit operator
  approval.
- Browser and public events reveal no provider reference, secret, content, or raw
  exception.
- The existing Memory and Docker conformance suites remain green.

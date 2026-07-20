# Coding Tool Approval Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add exact-tool-call, reconnect-safe human approval for coding workspace writes and commands without weakening existing hard-deny policy or exactly-once mutation recovery.

**Architecture:** Insert a three-way approval evaluator after tool validation and before durable tool claim. A coding-specific PostgreSQL aggregate atomically binds a pending approval to the canonical run, checkpoint, workspace revision, and request hash; owner-scoped decisions and expiry wake the existing checkpoint-fenced worker funnel only after commit. The frontend remains snapshot-first and applies the same typed approval projection through replay and live events.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy async/PostgreSQL, Celery, pytest/pytest-asyncio, TypeScript, React, Next.js route handlers, Node test runner.

## Global Constraints

- Existing schema and command hard denials always run before approval evaluation and cannot be overridden by approval.
- `read_only` tools execute without approval; `workspace_write` and `command` tools require exact-call approval.
- Approval creation is one fenced transaction containing checkpoint, approval, task status, events, and outbox rows.
- No tool-execution claim exists before approval.
- Canonical request hash version `coding-approval-v1` binds task, run, tool call, registered tool name, normalized input, checkpoint, and workspace revision using sorted compact JSON and SHA-256.
- Raw normalized input is not duplicated in `coding_approvals`; it remains in the fenced checkpoint. Event, metric, audit, and frontend projection contain only allowlisted sanitized summary fields.
- Pending approval TTL defaults to exactly `900` seconds and must be positive.
- Expiry wins over approve/deny when `expires_at <= now` inside the decision transaction.
- Duplicate or stale decisions return `409`; missing or non-owned task/approval returns `404`; invalid request schema returns `422`.
- Approval success is not applied optimistically in the browser; durable snapshot/replay/live state is authoritative.
- Worker delivery advances at most one durable safe point and `WAITING_APPROVAL` never schedules automatic continuation.
- Metrics use only fixed-cardinality `risk` and `outcome` labels; IDs, paths, argv, prompts, input, environment, and content never become labels.
- Legacy LangGraph `pending_approvals` and chat approval routes remain unchanged.
- Default CI makes no external model, Docker, or network calls.

---

## File Map

- `neos/coding/domain/approvals.py`: approval enums, immutable records, policy evaluation, hash, and sanitized display summary.
- `db/migrations/042_add_coding_approvals.sql`: coding-specific approval table, constraints, and pending-expiry index.
- `neos/coding/loop/base.py`: repository approval command/query protocol.
- `neos/coding/repositories/run_repository.py`: fenced request, lookup, resolution, and expiry transactions.
- `neos/coding/application/approval_service.py`: owner-scoped decision and post-commit continuation orchestration.
- `neos/coding/loop/anthropic.py`: pre-claim approval gate and durable decision consumption.
- `neos/coding/workers/execution.py`: non-error `WAITING_APPROVAL` worker outcome.
- `neos/coding/workers/celery_tasks.py`, `neos/coding/workers/celery_runtime.py`, `neos/workflow/celery_app.py`: continuation and expiry reconciliation wiring.
- `neos/coding/repositories/projection_repository.py`, `neos/coding/application/snapshot_service.py`: typed coding approval projection.
- `neos/api/models/coding_models.py`, `neos/api/handlers/coding_handlers.py`, `neos/coding/runtime.py`: decision REST contract and dependency wiring.
- `neos/observability/metrics.py`, `neos/coding/sandbox/observability.py`: bounded metrics and sanitized audit lifecycle.
- `web/features/coding/types/projection.ts`, `web/features/coding/stream/projection-reducer.ts`: typed snapshot/replay/live approval state.
- `web/features/coding/api/coding-api.ts`, `web/app/(code)/api/coding/tasks/[taskId]/approvals/[approvalId]/route.ts`: browser decision transport.
- `web/features/coding/components/coding-approval-card.tsx`, `coding-task-workspace.tsx`, `phase-timeline.tsx`: approval UX.

### Task 1: Approval Domain Contract, Strict Configuration, and Migration

**Files:**
- Create: `neos/coding/domain/approvals.py`
- Create: `db/migrations/042_add_coding_approvals.sql`
- Create: `tests/coding/domain/test_approvals.py`
- Create: `tests/coding/test_migration_042_contract.py`
- Modify: `neos/config/schema.py`
- Modify: `tests/config/test_coding_model_config.py`

**Interfaces:**
- Consumes: `ValidatedToolCall`, `ToolRisk` from `neos.coding.tools.registry`.
- Produces: `ApprovalStatus`, `ApprovalDecision`, `ApprovalPolicyOutcome`, `CodingApproval`, `evaluate_approval()`, `canonical_approval_hash()`, and `approval_display_summary()`.

- [ ] **Step 1: Write failing domain and configuration tests**

```python
def test_policy_requires_approval_only_after_hard_validation() -> None:
    read = ValidatedToolCall("read_file.v1", {"path": "README.md"}, ToolRisk.READ_ONLY)
    write = ValidatedToolCall("write_file.v1", {"path": "a.py", "content": "secret"}, ToolRisk.WORKSPACE_WRITE)
    assert evaluate_approval(read) is ApprovalPolicyOutcome.ALLOW
    assert evaluate_approval(write) is ApprovalPolicyOutcome.REQUIRE_APPROVAL


def test_hash_is_deterministic_and_sensitive_to_binding() -> None:
    first = canonical_approval_hash(binding_fixture())
    assert first == canonical_approval_hash(binding_fixture())
    assert first != canonical_approval_hash(binding_fixture(workspace_revision="rev-2"))


def test_display_summary_never_contains_content_or_environment_values() -> None:
    summary = approval_display_summary(execute_call(argv=["pytest", "-q"], env={"TOKEN": "raw-secret"}))
    encoded = json.dumps(summary)
    assert "pytest" in encoded
    assert "raw-secret" not in encoded


def test_coding_approval_ttl_defaults_to_fifteen_minutes() -> None:
    assert AppConfig().coding_model.approval_ttl_seconds == 900
```

- [ ] **Step 2: Run the tests and verify missing contracts**

Run: `.venv/bin/pytest tests/coding/domain/test_approvals.py tests/config/test_coding_model_config.py -q`

Expected: collection fails because `neos.coding.domain.approvals` does not exist.

- [ ] **Step 3: Implement immutable domain values and canonical binding**

```python
class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"


class ApprovalDecision(StrEnum):
    APPROVE = "approve"
    DENY = "deny"


class ApprovalPolicyOutcome(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


def evaluate_approval(call: ValidatedToolCall) -> ApprovalPolicyOutcome:
    if call.risk is ToolRisk.READ_ONLY:
        return ApprovalPolicyOutcome.ALLOW
    return ApprovalPolicyOutcome.REQUIRE_APPROVAL


def canonical_approval_hash(binding: Mapping[str, object]) -> str:
    payload = {"contract": "coding-approval-v1", **binding}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

`approval_display_summary()` must use a per-tool allowlist: expose path for file tools, executable plus bounded argument count for command tools, and never expose content, stdin, or environment values.

- [ ] **Step 4: Add strict config fields**

Add to `CodingModelConfig`:

```python
approval_ttl_seconds: int = Field(default=900, gt=0)
approval_reconciliation_batch_size: int = Field(default=100, gt=0, le=1000)
```

- [ ] **Step 5: Write and contract-test migration 042**

The migration must create `coding_approvals` with the fields from the design, omit raw tool input, enforce unique `(task_id, run_id, tool_call_id)`, valid status/decision combinations, `expires_at > requested_at`, and add:

```sql
CREATE INDEX IF NOT EXISTS idx_coding_approvals_pending_expiry
ON coding_approvals (expires_at, approval_id)
WHERE status = 'pending';
```

Run: `.venv/bin/pytest tests/coding/test_migration_042_contract.py tests/coding/domain/test_approvals.py tests/config/test_coding_model_config.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit domain and migration**

```bash
git add neos/coding/domain/approvals.py neos/config/schema.py db/migrations/042_add_coding_approvals.sql tests/coding/domain/test_approvals.py tests/coding/test_migration_042_contract.py tests/config/test_coding_model_config.py
git commit -m "feat(coding): define durable tool approvals"
```

### Task 2: Atomic Approval Request and Lookup Repository

**Files:**
- Modify: `neos/coding/domain/approvals.py`
- Modify: `neos/coding/loop/base.py`
- Modify: `neos/coding/repositories/run_repository.py`
- Modify: `tests/coding/fakes.py`
- Create: `tests/coding/repositories/test_approval_repository.py`
- Modify: `tests/coding/integration/test_postgres_durability.py`

**Interfaces:**
- Consumes: current execution lease, pending `ToolCallCompleted`, `ValidatedToolCall`, loop state, workspace revision, owner, and expiry.
- Produces: `request_tool_approval(...) -> ApprovalRequestCommit` and `get_tool_approval(task_id, run_id, tool_call_id) -> CodingApproval | None`.

- [ ] **Step 1: Write failing atomic-command tests**

```python
async def test_request_is_one_fenced_checkpoint_approval_status_event_transaction() -> None:
    commit = await repository.request_tool_approval(
        lease=LEASE,
        tool_call=CALL,
        validated=VALIDATED_WRITE,
        loop_state=LOOP_STATE,
        workspace_revision="rev-1",
        requested_at=NOW,
        expires_at=NOW + timedelta(seconds=900),
    )
    sql = "\n".join(session.sql)
    assert "coding_run_leases" in sql and "fencing_token" in sql
    assert "INSERT INTO coding_checkpoints" in sql
    assert "INSERT INTO coding_approvals" in sql
    assert "status = 'waiting_approval'" in sql
    assert sql.count("INSERT INTO coding_events") >= 2
    assert sql.count("INSERT INTO coding_outbox") >= 2
    assert commit.approval.checkpoint_id == commit.checkpoint.checkpoint_id


async def test_duplicate_tool_call_reuses_request_without_duplicate_events() -> None:
    first = await repository.request_tool_approval(**request_kwargs())
    second = await repository.request_tool_approval(**request_kwargs())
    assert second.approval == first.approval
    assert second.created is False
```

Add a real PostgreSQL guarded test proving rollback leaves none of checkpoint, approval, task status, events, or outbox committed when a late statement fails.

- [ ] **Step 2: Run tests and verify missing repository methods**

Run: `.venv/bin/pytest tests/coding/repositories/test_approval_repository.py -q`

Expected: fails because approval repository methods do not exist.

- [ ] **Step 3: Add repository protocol and commit records**

```python
@dataclass(frozen=True, slots=True)
class ApprovalRequestCommit:
    approval: CodingApproval
    checkpoint: CodingCheckpoint
    events: tuple[CodingEvent, ...]
    created: bool


async def request_tool_approval(
    self, *, lease: ExecutionLease, tool_call: ToolCallCompleted,
    validated: ValidatedToolCall, loop_state: Mapping[str, Any],
    workspace_revision: str, requested_at: datetime,
    expires_at: datetime,
) -> ApprovalRequestCommit: ...
```

- [ ] **Step 4: Implement the fenced PostgreSQL transaction**

Lock/validate the lease, canonical running run, and coding task; copy the locked task's `owner_id` into `requested_by`; allocate checkpoint and two task-local event sequences; insert approval with `ON CONFLICT (task_id, run_id, tool_call_id) DO NOTHING`; and only emit events/status transition for a newly created request. An existing row is reusable only when its canonical hash, checkpoint, and workspace revision match; otherwise fail closed with `ApprovalConflict`.

- [ ] **Step 5: Implement in-memory parity and lookup**

The fake must run request/lookup under `_durability_lock`, validate canonical run and lease, and expose deterministic request reuse for loop tests.

- [ ] **Step 6: Run focused and PostgreSQL-guarded tests**

Run: `.venv/bin/pytest tests/coding/repositories/test_approval_repository.py tests/coding/integration/test_postgres_durability.py -q`

Expected: unit tests pass; PostgreSQL cases pass when configured or skip with the existing explicit guard.

- [ ] **Step 7: Commit request durability**

```bash
git add neos/coding/domain/approvals.py neos/coding/loop/base.py neos/coding/repositories/run_repository.py tests/coding/fakes.py tests/coding/repositories/test_approval_repository.py tests/coding/integration/test_postgres_durability.py
git commit -m "feat(coding): persist approval safe points"
```

### Task 3: Atomic Decision, Expiry, and Application Service

**Files:**
- Create: `neos/coding/application/approval_service.py`
- Modify: `neos/coding/domain/approvals.py`
- Modify: `neos/coding/loop/base.py`
- Modify: `neos/coding/repositories/run_repository.py`
- Modify: `tests/coding/fakes.py`
- Create: `tests/coding/application/test_approval_service.py`
- Modify: `tests/coding/repositories/test_approval_repository.py`
- Modify: `tests/coding/integration/test_postgres_durability.py`

**Interfaces:**
- Produces: `CodingApprovalService.resolve(...)`, `CodingApprovalService.expire_pending(limit)`, `ApprovalResolutionCommit`, `ApprovalNotFound`, and `ApprovalConflict`.
- Accepts: async `wake(task_id, expected_checkpoint_id)` callback invoked only after successful commit.

- [ ] **Step 1: Write failing decision race tests**

```python
async def test_expiry_wins_over_user_decision() -> None:
    repository.approval = pending(expires_at=NOW)
    with pytest.raises(ApprovalConflict, match="approval_expired"):
        await service.resolve(
            task_id="ct-1", approval_id="ca-1", owner_id="user-1",
            decision=ApprovalDecision.APPROVE,
        )
    assert repository.approval.status is ApprovalStatus.EXPIRED
    assert wake.calls == [("ct-1", "cc-approval")]


async def test_first_decision_wins_and_second_is_conflict() -> None:
    approved = await service.resolve(**approve_kwargs())
    with pytest.raises(ApprovalConflict, match="approval_already_resolved"):
        await service.resolve(**deny_kwargs())
    assert approved.approval.status is ApprovalStatus.APPROVED


async def test_wake_happens_only_after_commit() -> None:
    repository.raise_before_commit = RuntimeError("db unavailable")
    with pytest.raises(RuntimeError):
        await service.resolve(**approve_kwargs())
    assert wake.calls == []
```

- [ ] **Step 2: Run tests and verify missing service**

Run: `.venv/bin/pytest tests/coding/application/test_approval_service.py -q`

Expected: collection fails because `CodingApprovalService` does not exist.

- [ ] **Step 3: Implement row-locked resolution and batched expiry commands**

Resolution must lock approval, task, canonical run/checkpoint, recompute `coding-approval-v1`, apply expiry before decision, mark hash/revision mismatches `invalidated`, transition task to `running`, append one approval resolution event plus `task.status.changed`, and create matching outbox rows in the same transaction.

Expiry must claim rows using:

```sql
SELECT approval_id
FROM coding_approvals
WHERE status = 'pending' AND expires_at <= :now
ORDER BY expires_at, approval_id
FOR UPDATE SKIP LOCKED
LIMIT :limit
```

- [ ] **Step 4: Implement post-commit application service**

```python
class CodingApprovalService:
    async def resolve(self, *, task_id: str, approval_id: str,
                      owner_id: str, decision: ApprovalDecision):
        commit = await self._repository.resolve_tool_approval(
            task_id=task_id, approval_id=approval_id, owner_id=owner_id,
            decision=decision, now=self._clock(),
        )
        await self._wake(commit.approval.task_id, commit.approval.checkpoint_id)
        return commit
```

For an expired decision, the repository commits expiry and raises/returns a typed expired resolution so the service still wakes the checkpoint before surfacing `ApprovalConflict`.

- [ ] **Step 5: Run decision and concurrency tests**

Run: `.venv/bin/pytest tests/coding/application/test_approval_service.py tests/coding/repositories/test_approval_repository.py tests/coding/integration/test_postgres_durability.py -q`

Expected: all unguarded tests pass; guarded concurrency tests pass or explicitly skip.

- [ ] **Step 6: Commit decision service**

```bash
git add neos/coding/application/approval_service.py neos/coding/domain/approvals.py neos/coding/loop/base.py neos/coding/repositories/run_repository.py tests/coding/fakes.py tests/coding/application/test_approval_service.py tests/coding/repositories/test_approval_repository.py tests/coding/integration/test_postgres_durability.py
git commit -m "feat(coding): resolve and expire approvals atomically"
```

### Task 4: Real Loop Approval Gate and Worker Outcome

**Files:**
- Modify: `neos/coding/loop/anthropic.py`
- Modify: `neos/coding/workers/execution.py`
- Modify: `neos/coding/workers/celery_tasks.py`
- Modify: `tests/coding/loop/test_anthropic_loop.py`
- Modify: `tests/coding/workers/test_execution.py`
- Modify: `tests/coding/workers/test_celery_tasks.py`
- Modify: `tests/coding/test_real_model_tool_loop_crash_recovery.py`

**Interfaces:**
- Consumes: approval evaluator and repository commands from Tasks 1–3.
- Produces: approval-gated safe-point events and `CodingTaskOutcome.WAITING_APPROVAL`.

- [ ] **Step 1: Write failing loop and worker tests**

```python
async def test_workspace_write_requests_approval_before_tool_claim_or_execution() -> None:
    harness = approval_harness(tool_turn("write_file.v1", {"path": "a.py", "content": "x"}))
    events = [event async for event in harness.loop.run(INPUT, None, harness.deps)]
    assert [event.type for event in events] == ["approval.requested", "task.status.changed"]
    assert harness.repository.tool_execution_calls == []
    assert harness.session.write_calls == []


async def test_approved_tool_reuses_existing_claim_execution_path_once() -> None:
    harness = approval_harness_from_checkpoint(status="approved")
    await collect(harness.loop.run(INPUT, harness.checkpoint, harness.deps))
    assert len(harness.session.write_calls) == 1


async def test_denied_tool_commits_canonical_result_without_execution() -> None:
    harness = approval_harness_from_checkpoint(status="denied")
    await collect(harness.loop.run(INPUT, harness.checkpoint, harness.deps))
    assert harness.session.write_calls == []
    assert harness.latest_tool_result.status == "denied"
    assert harness.latest_tool_result.result == {"reason_code": "approval_denied"}
```

Add worker tests that an `approval.requested` checkpoint maps to `WAITING_APPROVAL`, resets no retry budget, and Celery publishes no continuation.

- [ ] **Step 2: Run tests and verify current pre-claim execution**

Run: `.venv/bin/pytest tests/coding/loop/test_anthropic_loop.py tests/coding/workers/test_execution.py tests/coding/workers/test_celery_tasks.py -q`

Expected: new tests fail because writes currently claim and execute immediately.

- [ ] **Step 3: Insert the post-validation pre-claim gate**

For non-read-only calls, lookup the durable approval. If absent, commit a request safe point and yield its events. If pending, yield/return without execution. If approved, recompute binding and continue into the unchanged claim path. If denied/expired/invalidated, create stable denied result codes and commit one model checkpoint.

- [ ] **Step 4: Add explicit worker outcome**

```python
class CodingTaskOutcome(StrEnum):
    COMPLETED = "completed"
    CONTINUING = "continuing"
    WAITING_APPROVAL = "waiting_approval"
    FAILED = "failed"
    LEASE_BUSY = "lease_busy"
    STALE = "stale"
```

Classify `approval.requested` or a durable pending outcome as `WAITING_APPROVAL`. Keep Celery continuation restricted to `CONTINUING` only.

- [ ] **Step 5: Verify crash/redelivery semantics**

Run: `.venv/bin/pytest tests/coding/test_real_model_tool_loop_crash_recovery.py tests/coding/loop/test_anthropic_loop.py tests/coding/workers/test_execution.py tests/coding/workers/test_celery_tasks.py -q`

Expected: approval request, decision resume, and exactly-once mutation tests pass.

- [ ] **Step 6: Commit loop gate**

```bash
git add neos/coding/loop/anthropic.py neos/coding/workers/execution.py neos/coding/workers/celery_tasks.py tests/coding/loop/test_anthropic_loop.py tests/coding/workers/test_execution.py tests/coding/workers/test_celery_tasks.py tests/coding/test_real_model_tool_loop_crash_recovery.py
git commit -m "feat(coding): gate mutations on durable approval"
```

### Task 5: Owner API, Projection, Runtime, Expiry Worker, and Metrics

**Files:**
- Modify: `neos/api/models/coding_models.py`
- Modify: `neos/api/handlers/coding_handlers.py`
- Modify: `neos/coding/runtime.py`
- Modify: `neos/coding/repositories/projection_repository.py`
- Modify: `neos/coding/application/snapshot_service.py`
- Modify: `neos/coding/workers/celery_runtime.py`
- Modify: `neos/coding/workers/celery_tasks.py`
- Modify: `neos/workflow/celery_app.py`
- Modify: `neos/observability/metrics.py`
- Modify: `neos/coding/sandbox/observability.py`
- Modify: `tests/api/handlers/test_coding_handlers.py`
- Modify: `tests/coding/application/test_snapshot_service.py`
- Modify: `tests/coding/workers/test_celery_runtime.py`
- Modify: `tests/coding/workers/test_celery_tasks.py`
- Modify: `tests/coding/test_durability_metrics.py`

**Interfaces:**
- Produces: `POST /coding/tasks/{task_id}/approvals/{approval_id}`, typed approval snapshot, scheduled expiry reconciliation, and approval metrics.

- [ ] **Step 1: Write failing HTTP, snapshot, runtime, and metric tests**

```python
async def test_owner_can_approve_exact_coding_request(client, owner_headers) -> None:
    response = await client.post(
        "/api/v1/coding/tasks/ct-1/approvals/ca-1",
        headers=owner_headers,
        json={"decision": "approve"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "approved"


async def test_non_owner_receives_not_found(client, other_headers) -> None:
    response = await client.post(
        "/api/v1/coding/tasks/ct-1/approvals/ca-1",
        headers=other_headers,
        json={"decision": "deny"},
    )
    assert response.status_code == 404


def test_approval_metrics_have_fixed_cardinality_labels() -> None:
    collector = MetricsCollector()
    assert collector.coding_approval_total._labelnames == ("risk", "outcome")
    assert collector.coding_approval_latency_seconds._labelnames == ("outcome",)
```

- [ ] **Step 2: Run focused tests and verify missing API/wiring**

Run: `.venv/bin/pytest tests/api/handlers/test_coding_handlers.py tests/coding/application/test_snapshot_service.py tests/coding/workers/test_celery_runtime.py tests/coding/workers/test_celery_tasks.py tests/coding/test_durability_metrics.py -q`

Expected: new approval contract tests fail.

- [ ] **Step 3: Add typed API models and handler**

```python
class CodingApprovalDecisionRequest(BaseModel):
    decision: Literal["approve", "deny"]


class CodingApprovalSnapshot(BaseModel):
    approval_id: str
    tool_name: str
    risk: Literal["workspace_write", "command"]
    status: Literal["pending", "approved", "denied", "expired", "invalidated"]
    requested_at: datetime
    expires_at: datetime
    display_summary: dict[str, Any]
```

Map `ApprovalNotFound` to `404`, all stale/already-resolved/expired conflicts to sanitized `409`, and rely on Pydantic for `422`.

- [ ] **Step 4: Replace legacy approval projection**

Change `_approvals()` to read only `coding_approvals` joined through an owned coding task. Return typed fields and never select request hash, actor IDs, or checkpoint loop state into the public approval projection.

- [ ] **Step 5: Wire API and worker-owned services**

Extend `CodingRuntime` with `approvals: CodingApprovalService`. API runtime uses the API DB manager; Celery construction uses its worker-owned manager. The service wake callback must call the existing dispatcher with `expected_checkpoint_id=approval.checkpoint_id` only after commit.

- [ ] **Step 6: Add expiry task and bounded observability**

Register a periodic coding approval expiry task that calls `expire_pending(limit=config.coding_model.approval_reconciliation_batch_size)`. Record only stable risk/outcome labels and emit sanitized lifecycle audit events.

- [ ] **Step 7: Run backend vertical-slice regression**

Run: `.venv/bin/pytest tests/api/handlers/test_coding_handlers.py tests/coding/application/test_snapshot_service.py tests/coding/workers tests/coding/test_durability_metrics.py -q`

Expected: all tests pass.

- [ ] **Step 8: Commit backend delivery surface**

```bash
git add neos/api/models/coding_models.py neos/api/handlers/coding_handlers.py neos/coding/runtime.py neos/coding/repositories/projection_repository.py neos/coding/application/snapshot_service.py neos/coding/workers/celery_runtime.py neos/coding/workers/celery_tasks.py neos/workflow/celery_app.py neos/observability/metrics.py neos/coding/sandbox/observability.py tests/api/handlers/test_coding_handlers.py tests/coding/application/test_snapshot_service.py tests/coding/workers tests/coding/test_durability_metrics.py
git commit -m "feat(coding): expose approval decisions and expiry"
```

### Task 6: Frontend Approval Projection and Decision Transport

**Files:**
- Modify: `web/features/coding/types/projection.ts`
- Modify: `web/features/coding/stream/projection-reducer.ts`
- Modify: `web/features/coding/api/coding-api.ts`
- Create: `web/app/(code)/api/coding/tasks/[taskId]/approvals/[approvalId]/route.ts`
- Create: `web/tests/source/coding-approval-projection.test.ts`
- Create: `web/tests/source/coding-approval-api.test.ts`

**Interfaces:**
- Consumes: typed backend approval snapshot and `approval.*`/`task.status.changed` events.
- Produces: `CodingApprovalView`, convergent `approvalsById`, and `decideCodingApproval()`.

- [ ] **Step 1: Write failing projection convergence tests**

```typescript
test("snapshot and live approval request converge", () => {
  const fromSnapshot = hydrate(snapshotWithApproval(pendingApproval));
  const fromLive = reduceEvent(hydrate(emptySnapshot), approvalRequested(pendingApproval));
  assert.deepEqual(fromLive.approvalsById, fromSnapshot.approvalsById);
});

test("resolution and task status events update durable projection", () => {
  const state = reduceEvent(hydrate(snapshotWithApproval(pendingApproval)), approvalDenied());
  assert.equal(state.approvalsById["ca-1"].status, "denied");
  const waiting = reduceEvent(state, taskStatusChanged("waiting_approval"));
  assert.equal(waiting.task.status, "waiting_approval");
});
```

- [ ] **Step 2: Run tests and verify untyped/missing reducer cases**

Run: `cd web && pnpm exec tsx --test tests/source/coding-approval-projection.test.ts tests/source/coding-approval-api.test.ts`

Expected: tests fail because approval types, reducers, and API do not exist.

- [ ] **Step 3: Add typed approval projection and ordered event cases**

```typescript
export type CodingApprovalStatus =
  | "pending" | "approved" | "denied" | "expired" | "invalidated";

export interface CodingApprovalView {
  approval_id: string;
  tool_name: string;
  risk: "workspace_write" | "command";
  status: CodingApprovalStatus;
  requested_at: string;
  expires_at: string;
  display_summary: Record<string, unknown>;
}
```

Key snapshot and live rows strictly by `approval_id`. Requested events upsert; resolution events update status and retain the row. Add `task.status.changed` to the projection reducer while preserving duplicate/gap sequence behavior.

- [ ] **Step 4: Add browser helper and authenticated Next proxy**

```typescript
export async function decideCodingApproval(
  taskId: string,
  approvalId: string,
  decision: "approve" | "deny",
): Promise<CodingApprovalView> {
  const response = await fetch(
    `/api/coding/tasks/${encodeURIComponent(taskId)}/approvals/${encodeURIComponent(approvalId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision }),
    },
  );
  if (!response.ok) {
    throw await responseError(response, "Could not decide coding approval");
  }
  return response.json();
}
```

The proxy must forward to `/api/v1/coding/tasks/{task}/approvals/{approval}` with `callBackendAPIWithJSON` and preserve backend `404`, `409`, and `422` status.

- [ ] **Step 5: Run source tests and type check**

Run: `cd web && pnpm exec tsx --test tests/source/coding-approval-projection.test.ts tests/source/coding-approval-api.test.ts && pnpm exec tsc --noEmit`

Expected: all pass.

- [ ] **Step 6: Commit projection and transport**

```bash
git add web/features/coding/types/projection.ts web/features/coding/stream/projection-reducer.ts web/features/coding/api/coding-api.ts 'web/app/(code)/api/coding/tasks/[taskId]/approvals/[approvalId]/route.ts' web/tests/source/coding-approval-projection.test.ts web/tests/source/coding-approval-api.test.ts
git commit -m "feat(coding): stream approval decisions to browser"
```

### Task 7: Reconnect-Safe Approval Workspace UX

**Files:**
- Create: `web/features/coding/components/coding-approval-card.tsx`
- Modify: `web/features/coding/components/coding-task-workspace.tsx`
- Modify: `web/features/coding/components/phase-timeline.tsx`
- Create: `web/tests/source/coding-approval-workspace.test.ts`
- Modify: `web/tests/source/coding-phase-workspace.test.ts`

**Interfaces:**
- Consumes: `CodingApprovalView`, `decideCodingApproval()`, projection task status, and connection state.
- Produces: request-scoped approve/deny controls with no optimistic projection mutation.

- [ ] **Step 1: Write failing workspace behavior tests**

Tests must assert that cards render above the steer composer, only sanitized summary fields are rendered, `waiting_approval` appears in header and timeline, buttons require `connection === "live"` and pending status, each card owns submitting/error state, and successful POST does not remove or mutate projection state.

Run: `cd web && pnpm exec tsx --test tests/source/coding-approval-workspace.test.ts`

Expected: fails because `CodingApprovalCard` does not exist.

- [ ] **Step 2: Implement a request-scoped approval card**

```tsx
export function CodingApprovalCard({ taskId, approval, live }: Props) {
  const [submitting, setSubmitting] = useState<"approve" | "deny" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const disabled = !live || approval.status !== "pending" || submitting !== null;

  async function decide(decision: "approve" | "deny") {
    setSubmitting(decision);
    setError(null);
    try {
      await decideCodingApproval(taskId, approval.approval_id, decision);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "승인 요청을 처리하지 못했습니다.");
    } finally {
      setSubmitting(null);
    }
  }
  // Render only tool_name, risk, expires_at, and display_summary.
}
```

Pass task ID separately from the workspace; do not expand the public backend payload solely for component convenience.

- [ ] **Step 3: Integrate cards and waiting marker**

Render pending approvals before `CodingSteerComposer`. Pass `connection === "live"`. Add an explicit `waiting_approval` marker to both workspace header and `PhaseTimeline` without fabricating a durable phase.

- [ ] **Step 4: Run frontend tests and accessibility/type checks**

Run: `cd web && pnpm exec tsx --test tests/source/coding-approval-workspace.test.ts tests/source/coding-phase-workspace.test.ts && pnpm exec tsc --noEmit`

Expected: all pass; buttons have accessible names and error text uses an alert/live region.

- [ ] **Step 5: Commit approval UX**

```bash
git add web/features/coding/components/coding-approval-card.tsx web/features/coding/components/coding-task-workspace.tsx web/features/coding/components/phase-timeline.tsx web/tests/source/coding-approval-workspace.test.ts web/tests/source/coding-phase-workspace.test.ts
git commit -m "feat(coding): render reconnect-safe approval controls"
```

### Task 8: Crash/Reconnect Vertical Slice, Security Assertions, and Operations Documentation

**Files:**
- Create: `tests/coding/test_tool_approval_vertical_slice.py`
- Modify: `tests/coding/test_real_model_tool_loop_crash_recovery.py`
- Modify: `tests/coding/test_durability_metrics.py`
- Modify: `web/tests/source/coding-projection-store.test.ts`
- Modify: `docs/NEOS_CODING.md`

**Interfaces:**
- Verifies the complete backend/frontend durable contract without external network calls.

- [ ] **Step 1: Write end-to-end in-memory approval tests**

Cover request commit before sandbox execution, browser-equivalent snapshot state, worker crash after request, approval decision, replacement worker execution exactly once, denial/expiry continuation, stale checkpoint delivery rejection, and sanitized events/metrics.

```python
async def test_crash_reconnect_approve_executes_mutation_once(tmp_path) -> None:
    harness = await ApprovalVerticalSlice.create(tmp_path)
    requested = await harness.advance_until_approval()
    assert harness.write_count == 0
    restored = await harness.reconnect_snapshot()
    assert restored.approvals[0].approval_id == requested.approval_id
    await harness.approve(requested.approval_id)
    await harness.replace_worker_and_finish()
    assert harness.write_count == 1
    assert (await harness.reconnect_snapshot()).task.status == "completed"
```

- [ ] **Step 2: Add security regression assertions**

Assert raw file content, stdin, environment values, full argv, prompt, IDs, and paths are absent from approval event payloads, metric labels, audit metadata, and public approval snapshot except explicitly allowlisted display fields.

- [ ] **Step 3: Add frontend replay equivalence fixture**

Feed the same approval lifecycle once as REST snapshot plus live tail and once as full replay; assert serialized projection states are deeply equal and duplicate resolution events do not regress status.

- [ ] **Step 4: Document operations and rollback**

Update `docs/NEOS_CODING.md` with TTL/config fields, API contract, event types, reconciliation behavior, metrics, failure modes, rollout order, and rollback rule that pending approvals never auto-execute while the feature is disabled.

- [ ] **Step 5: Run complete scoped verification from a clean process**

```bash
.venv/bin/pytest tests/coding tests/api/handlers/test_coding_handlers.py tests/config/test_coding_model_config.py -q
cd web && pnpm test:source && pnpm exec tsc --noEmit
```

Expected: all deterministic tests pass; Docker/PostgreSQL/Anthropic integration tests only skip under their existing explicit guards.

- [ ] **Step 6: Run static and secret/diff checks**

```bash
.venv/bin/ruff check neos/coding neos/api/handlers/coding_handlers.py neos/api/models/coding_models.py tests/coding tests/api/handlers/test_coding_handlers.py
git diff --check
git status --short
```

Verify no credentials, sandbox workspace, raw approval input fixture, generated recording, or oversized output is tracked.

- [ ] **Step 7: Commit verified vertical slice**

```bash
git add tests/coding/test_tool_approval_vertical_slice.py tests/coding/test_real_model_tool_loop_crash_recovery.py tests/coding/test_durability_metrics.py web/tests/source/coding-projection-store.test.ts docs/NEOS_CODING.md
git commit -m "test(coding): verify durable approval recovery"
```

## Final Reviewer Checklist

- [ ] Compare every requirement in `docs/superpowers/specs/2026-07-21-coding-tool-approval-design.md` with Tasks 1–8.
- [ ] Confirm approval creation and resolution each have one explicit transaction boundary and all wake-ups occur after commit.
- [ ] Confirm no approval path can bypass hard-deny validation or create a tool claim before approval.
- [ ] Confirm pending, approved, denied, expired, and invalidated paths are deterministic after crash and redelivery.
- [ ] Confirm REST snapshot, event replay, and live frontend reducers converge to the same serialized state.
- [ ] Confirm legacy chat approval tables, endpoints, SSE behavior, and tests remain unchanged.
- [ ] Run `git diff --check`, scoped backend/frontend verification, and review commits in dependency order.

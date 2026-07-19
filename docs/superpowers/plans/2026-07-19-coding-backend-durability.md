# Coding Backend Durability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make coding phase execution crash-consistent on PostgreSQL with atomic checkpoint commits, recoverable steering claims, durable instructions, and task-scoped execution fencing.

**Architecture:** Add domain-level lease and commit contracts, then implement them as business-unit transactions in `PostgresCodingRunRepository`. `CodingRunService` acquires an execution lease and delegates phase/tool/steering state transitions to those atomic commands; it no longer treats process memory as canonical state. Fast SQL contract tests run everywhere, while an opt-in PostgreSQL integration suite proves FK ordering, rollback, and contention against a real database.

**Tech Stack:** Python 3.12, asyncio, SQLAlchemy async sessions, PostgreSQL 15+, pytest, Prometheus client.

## Global Constraints

- `coding_events.checkpoint_id` remains an immediate foreign key to `coding_checkpoints.checkpoint_id`.
- Checkpoint insert, completion event/outbox insert, phase completion, and task sequence update share one transaction.
- Execution lease TTL defaults to 30 seconds; heartbeat interval defaults to 10 seconds.
- Every mutating durable command validates `task_id`, `run_id`, `worker_id`, and `fencing_token`.
- A stale worker raises `StaleExecutionLease`; normal lease contention returns `None`.
- Checkpoint `loop_state_json` always preserves `current_instruction`; only `pending_instruction` is cleared after the first resumed phase.
- Metrics use fixed `phase` and `outcome` labels only. IDs and user-controlled text are forbidden labels.
- This plan does not add the development worker supervisor, Celery queue, real model adapter, sandbox execution, or frontend changes.
- Preserve unrelated user changes in `.env.template`, `AGENTS.md`, `docs/claude_code_spec.md`, and deep-analysis documents.

---

## File Structure

### New files

- `db/migrations/040_add_coding_execution_leases.sql` — lease, steering claim, and tool claim schema changes.
- `neos/coding/domain/durability.py` — immutable lease/claim/commit result types and durability errors.
- `tests/coding/test_migration_040_contract.py` — migration text contract.
- `tests/coding/repositories/test_durability_repository.py` — transaction command SQL/order mapping tests.
- `tests/coding/integration/test_postgres_durability.py` — real PostgreSQL FK, rollback, fencing, and contention tests.

### Modified files

- `neos/coding/loop/base.py` — repository protocol for lease, phase, tool, and commit commands.
- `neos/coding/loop/fake.py` — use durable command boundaries and preserve canonical instruction.
- `neos/coding/repositories/run_repository.py` — PostgreSQL atomic commands.
- `neos/coding/application/run_service.py` — worker identity, lease acquisition, durable restore, and steering application.
- `neos/coding/events/store.py` — in-memory atomic command implementation used by the test runtime only if responsibility remains local; otherwise leave event sequencing with the in-memory durability repository.
- `tests/coding/fakes.py` — deterministic in-memory implementation of the new contracts.
- `tests/coding/application/test_run_service.py` — lease/restore/steering service behavior.
- `tests/coding/loop/test_fake_loop.py` — atomic loop behavior.
- `tests/coding/test_durable_phase_vertical_slice.py` — crash, concurrency, and instruction restore integration.
- `neos/observability/metrics.py` — lease contention metric and corrected resume semantics.

---

### Task 1: Durability Domain Contracts and Migration

**Files:**
- Create: `neos/coding/domain/durability.py`
- Create: `db/migrations/040_add_coding_execution_leases.sql`
- Create: `tests/coding/test_migration_040_contract.py`
- Create: `tests/coding/domain/test_durability.py`

**Interfaces:**
- Consumes: existing `CodingRun`, `CodingPhase`, `CodingCheckpoint`, `CodingEvent`.
- Produces: `ExecutionLease`, `ToolExecutionDisposition`, `ToolExecutionClaim`, `PhaseStart`, `PhaseCheckpointCommit`, `SteeringApplication`, `RunAlreadyLeased`, `StaleExecutionLease`.

- [ ] **Step 1: Write failing domain tests**

```python
from datetime import UTC, datetime, timedelta

import pytest

from neos.coding.domain.durability import ExecutionLease, StaleExecutionLease


NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


def test_execution_lease_requires_positive_fencing_token() -> None:
    with pytest.raises(ValueError, match="fencing token"):
        ExecutionLease(
            task_id="ct_1",
            run_id="cr_1",
            worker_id="worker-a",
            fencing_token=0,
            acquired_at=NOW,
            expires_at=NOW + timedelta(seconds=30),
        )


def test_execution_lease_rejects_non_future_expiry() -> None:
    with pytest.raises(ValueError, match="expires_at"):
        ExecutionLease(
            task_id="ct_1",
            run_id="cr_1",
            worker_id="worker-a",
            fencing_token=1,
            acquired_at=NOW,
            expires_at=NOW,
        )


def test_stale_execution_lease_is_a_distinct_runtime_error() -> None:
    assert issubclass(StaleExecutionLease, RuntimeError)
```

- [ ] **Step 2: Write failing migration contract test**

```python
from pathlib import Path


def test_migration_adds_execution_and_claim_leases() -> None:
    sql = Path("db/migrations/040_add_coding_execution_leases.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS coding_run_leases" in sql
    assert "fencing_token BIGINT NOT NULL" in sql
    assert "UNIQUE (task_id, run_id, fencing_token)" in sql
    assert "ADD COLUMN IF NOT EXISTS claimed_by" in sql
    assert "ADD COLUMN IF NOT EXISTS claim_expires_at" in sql
    assert "CHECK (status IN ('claimed', 'completed', 'failed'))" in sql
    assert "idx_coding_steering_claimable" in sql
```

- [ ] **Step 3: Run RED**

Run: `.venv/bin/pytest -q tests/coding/domain/test_durability.py tests/coding/test_migration_040_contract.py`

Expected: collection fails because `durability.py` and migration 040 do not exist.

- [ ] **Step 4: Add domain types**

```python
# neos/coding/domain/durability.py
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping

from neos.coding.domain.events import CodingEvent
from neos.coding.domain.phases import CodingCheckpoint, CodingPhase, CodingRun, SteeringRequest


class RunAlreadyLeased(RuntimeError):
    pass


class StaleExecutionLease(RuntimeError):
    pass


class ToolExecutionDisposition(StrEnum):
    CLAIMED = "claimed"
    COMPLETED = "completed"
    BUSY = "busy"


@dataclass(frozen=True, slots=True)
class ExecutionLease:
    task_id: str
    run_id: str
    worker_id: str
    fencing_token: int
    acquired_at: datetime
    expires_at: datetime
    recovered: bool = False

    def __post_init__(self) -> None:
        if self.fencing_token < 1:
            raise ValueError("fencing token must be positive")
        if self.expires_at <= self.acquired_at:
            raise ValueError("expires_at must follow acquired_at")


@dataclass(frozen=True, slots=True)
class ToolExecutionClaim:
    disposition: ToolExecutionDisposition
    tool_call_id: str
    lease: ExecutionLease
    result: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class PhaseStart:
    phase: CodingPhase
    event: CodingEvent | None
    resumed: bool


@dataclass(frozen=True, slots=True)
class PhaseCheckpointCommit:
    checkpoint: CodingCheckpoint
    event: CodingEvent
    phase: CodingPhase


@dataclass(frozen=True, slots=True)
class SteeringApplication:
    request: SteeringRequest
    checkpoint: CodingCheckpoint
    previous_run: CodingRun
    run: CodingRun
    lease: ExecutionLease
    event: CodingEvent
```

- [ ] **Step 5: Add migration 040**

```sql
CREATE TABLE IF NOT EXISTS coding_run_leases (
    task_id VARCHAR(64) PRIMARY KEY
        REFERENCES coding_tasks(task_id) ON DELETE CASCADE,
    run_id VARCHAR(64) NOT NULL
        REFERENCES coding_runs(run_id) ON DELETE CASCADE,
    worker_id VARCHAR(128) NOT NULL,
    fencing_token BIGINT NOT NULL CHECK (fencing_token > 0),
    acquired_at TIMESTAMPTZ NOT NULL,
    heartbeat_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    UNIQUE (task_id, run_id, fencing_token)
);

ALTER TABLE coding_steering_requests
    ADD COLUMN IF NOT EXISTS claimed_by VARCHAR(128),
    ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS claim_expires_at TIMESTAMPTZ;

ALTER TABLE coding_tool_executions
    ADD COLUMN IF NOT EXISTS worker_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS fencing_token BIGINT,
    ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS claim_expires_at TIMESTAMPTZ;

ALTER TABLE coding_tool_executions
    DROP CONSTRAINT IF EXISTS coding_tool_executions_status_check;
ALTER TABLE coding_tool_executions
    ADD CONSTRAINT coding_tool_executions_status_check
    CHECK (status IN ('claimed', 'completed', 'failed'));

CREATE INDEX IF NOT EXISTS idx_coding_run_leases_expiry
    ON coding_run_leases(expires_at);
CREATE INDEX IF NOT EXISTS idx_coding_steering_claimable
    ON coding_steering_requests(task_id, claim_expires_at, requested_at)
    WHERE status IN ('pending', 'claimed');
```

- [ ] **Step 6: Run GREEN and migration regression**

Run: `.venv/bin/pytest -q tests/coding/domain/test_durability.py tests/coding/test_migration_039_contract.py tests/coding/test_migration_040_contract.py`

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add neos/coding/domain/durability.py db/migrations/040_add_coding_execution_leases.sql tests/coding/domain/test_durability.py tests/coding/test_migration_040_contract.py
git commit -m "feat: define coding durability contracts"
```

---

### Task 2: Execution Lease and Durable Tool Claims

**Files:**
- Modify: `neos/coding/loop/base.py`
- Modify: `neos/coding/repositories/run_repository.py`
- Modify: `tests/coding/fakes.py`
- Create: `tests/coding/repositories/test_durability_repository.py`

**Interfaces:**
- Consumes: Task 1 `ExecutionLease`, `ToolExecutionClaim`, `ToolExecutionDisposition`, `StaleExecutionLease`.
- Produces: `acquire_execution_lease(...)`, `renew_execution_lease(...)`, `release_execution_lease(...)`, `claim_tool_execution(...)`, `complete_tool_execution(...)` on both PostgreSQL and in-memory repositories.

- [ ] **Step 1: Write failing lease repository tests**

```python
async def test_acquire_lease_uses_one_atomic_upsert() -> None:
    session = FakeSession(rows=[("ct_1", "cr_1", "worker-a", 3, NOW, EXPIRES)])
    repository = repository_for(session)

    lease = await repository.acquire_execution_lease(
        task_id="ct_1", run_id="cr_1", worker_id="worker-a",
        now=NOW, expires_at=EXPIRES,
    )

    sql = "\n".join(session.sql)
    assert "INSERT INTO coding_run_leases" in sql
    assert "expires_at <= :now" in sql
    assert "fencing_token + 1" in sql
    assert lease is not None and lease.fencing_token == 3


async def test_renew_rejects_stale_fencing_token() -> None:
    session = FakeSession(rows=[])
    repository = repository_for(session)

    with pytest.raises(StaleExecutionLease):
        await repository.renew_execution_lease(LEASE, now=NOW, expires_at=EXPIRES)

    assert "fencing_token = :fencing_token" in "\n".join(session.sql)
```

- [ ] **Step 2: Write failing tool claim tests**

```python
async def test_tool_claim_is_written_before_execution() -> None:
    session = FakeSession(rows=[("claimed", None)])
    repository = repository_for(session)

    claim = await repository.claim_tool_execution(
        lease=LEASE,
        tool_call_id="tool_1",
        now=NOW,
        claim_expires_at=EXPIRES,
    )

    sql = "\n".join(session.sql)
    assert "INSERT INTO coding_tool_executions" in sql
    assert "fencing_token" in sql
    assert claim.disposition is ToolExecutionDisposition.CLAIMED


async def test_completed_tool_claim_returns_persisted_result() -> None:
    session = FakeSession(rows=[("completed", {"ok": True})])
    repository = repository_for(session)

    claim = await repository.claim_tool_execution(
        lease=LEASE,
        tool_call_id="tool_1",
        now=NOW,
        claim_expires_at=EXPIRES,
    )

    assert claim.disposition is ToolExecutionDisposition.COMPLETED
    assert claim.result == {"ok": True}
```

- [ ] **Step 3: Run RED**

Run: `.venv/bin/pytest -q tests/coding/repositories/test_durability_repository.py`

Expected: fails because lease and tool claim methods do not exist.

- [ ] **Step 4: Extend the loop repository protocol**

```python
class CodingRunRepository(Protocol):
    async def acquire_execution_lease(
        self, *, task_id: str, run_id: str, worker_id: str,
        now: datetime, expires_at: datetime,
    ) -> ExecutionLease | None: ...

    async def renew_execution_lease(
        self, lease: ExecutionLease, *, now: datetime, expires_at: datetime
    ) -> ExecutionLease: ...

    async def release_execution_lease(self, lease: ExecutionLease) -> None: ...

    async def claim_tool_execution(
        self, *, lease: ExecutionLease, tool_call_id: str,
        now: datetime, claim_expires_at: datetime,
    ) -> ToolExecutionClaim: ...

    async def complete_tool_execution(
        self, claim: ToolExecutionClaim, *, result: Mapping[str, Any],
        now: datetime,
    ) -> CodingEvent: ...
```

- [ ] **Step 5: Implement PostgreSQL lease commands**

Use one `INSERT ... ON CONFLICT (task_id) DO UPDATE ... WHERE` statement for acquisition. Map no returned row to `None`. Renewal and release must include all four fencing predicates:

```sql
WHERE task_id = :task_id
  AND run_id = :run_id
  AND worker_id = :worker_id
  AND fencing_token = :fencing_token
```

If renewal returns no row, raise `StaleExecutionLease`. Release is idempotent for the current holder but must never delete a newer token.

- [ ] **Step 6: Implement PostgreSQL tool claim commands**

Use a single transaction per command. `claim_tool_execution` must lock the task lease first, validate fencing, then insert or reclaim only when `claim_expires_at <= now`. `complete_tool_execution` updates only the matching claimed row and appends `tool.completed` plus outbox in that same transaction. A zero-row update raises `StaleExecutionLease`.

- [ ] **Step 7: Implement deterministic in-memory commands**

Add `execution_leases`, `tool_claims`, and an `asyncio.Lock` to `InMemoryCodingRunRepository`. Apply the same expiry and token rules; do not shortcut fencing checks in tests.

- [ ] **Step 8: Run GREEN and existing repository tests**

Run: `.venv/bin/pytest -q tests/coding/repositories/test_durability_repository.py tests/coding/repositories/test_run_repository.py`

Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add neos/coding/loop/base.py neos/coding/repositories/run_repository.py tests/coding/fakes.py tests/coding/repositories/test_durability_repository.py
git commit -m "feat: fence coding workers and tool claims"
```

---

### Task 3: Atomic Phase Start and Checkpoint Commit

**Files:**
- Modify: `neos/coding/loop/base.py`
- Modify: `neos/coding/loop/fake.py`
- Modify: `neos/coding/repositories/run_repository.py`
- Modify: `neos/coding/persistence/postgres.py`
- Modify: `tests/coding/fakes.py`
- Modify: `tests/coding/loop/test_fake_loop.py`
- Modify: `tests/coding/repositories/test_durability_repository.py`

**Interfaces:**
- Consumes: Task 2 execution lease and tool claim commands.
- Produces: `begin_phase(...) -> PhaseStart`, `commit_phase_checkpoint(...) -> PhaseCheckpointCommit`, and guarded event append behavior.

- [ ] **Step 1: Write failing SQL ordering test**

```python
async def test_phase_checkpoint_is_one_transaction_and_satisfies_fk_order() -> None:
    session = FakeSession(rows=[None, (11,)])
    repository = repository_for(session)

    commit = await repository.commit_phase_checkpoint(
        lease=LEASE,
        phase=ACTIVE_PHASE,
        tool_call_id="tool_1",
        result={"summary": "done"},
        loop_state={
            "phase_index": 0,
            "transcript": [],
            "current_instruction": "Fix it",
            "pending_instruction": None,
        },
        workspace_revision="rev_1",
        now=NOW,
    )

    sql = "\n".join(session.sql)
    assert sql.index("INSERT INTO coding_checkpoints") < sql.index(
        "INSERT INTO coding_events"
    )
    assert sql.index("INSERT INTO coding_events") < sql.index(
        "INSERT INTO coding_event_outbox"
    )
    assert "UPDATE coding_phases" in sql
    assert commit.checkpoint.seq == commit.event.seq == 11
```

- [ ] **Step 2: Write failing append guard test**

```python
async def test_generic_append_rejects_checkpoint_identity() -> None:
    service = PostgresCodingService(session_factory)

    with pytest.raises(ValueError, match="atomic checkpoint command"):
        await service.append(
            task_id="ct_1",
            event_type="phase.completed",
            payload={},
            checkpoint_id="cc_1",
        )
```

- [ ] **Step 3: Write failing loop command test**

```python
async def test_fake_loop_uses_atomic_phase_commands() -> None:
    repository = InMemoryCodingRunRepository(active_run=RUN)
    lease = await repository.acquire_execution_lease(
        task_id="ct_1", run_id="cr_1", worker_id="worker-a",
        now=NOW, expires_at=EXPIRES,
    )

    events = [event async for event in loop.run(INPUT, None, deps(repository, lease))]

    assert repository.begin_phase_calls == 5
    assert repository.phase_commit_calls == 5
    assert all("current_instruction" in cp.loop_state for cp in repository.checkpoints)
    assert events[-1].type == "run.completed"
```

- [ ] **Step 4: Run RED**

Run: `.venv/bin/pytest -q tests/coding/repositories/test_durability_repository.py tests/coding/loop/test_fake_loop.py`

Expected: fails because atomic phase commands and lease-aware loop dependencies do not exist.

- [ ] **Step 5: Add atomic phase protocol**

```python
@dataclass(frozen=True, slots=True)
class LoopDependencies:
    repository: CodingRunRepository
    events: CodingLoopEventSink
    lease: ExecutionLease


class CodingRunRepository(Protocol):
    async def begin_phase(
        self, *, lease: ExecutionLease, kind: CodingPhaseKind, now: datetime
    ) -> PhaseStart: ...

    async def commit_phase_checkpoint(
        self, *, lease: ExecutionLease, phase: CodingPhase,
        tool_call_id: str, result: Mapping[str, Any],
        loop_state: Mapping[str, Any], workspace_revision: str,
        now: datetime,
    ) -> PhaseCheckpointCommit: ...
```

- [ ] **Step 6: Implement `begin_phase` transaction**

Lock and validate the current lease. Return an existing active phase for the same run without emitting a second event. Otherwise lock the task, calculate the next attempt in SQL, insert the active phase, allocate a task sequence, and append `phase.started` plus outbox before commit.

- [ ] **Step 7: Implement `commit_phase_checkpoint` transaction**

Within one `session.begin()` block: lock/validate lease, allocate `last_seq`, construct checkpoint ID from run/phase identity, insert checkpoint, insert event, insert outbox, complete phase, and return mapped domain objects. Call `wake_outbox` only after the transaction exits successfully.

- [ ] **Step 8: Guard generic checkpoint append**

At the beginning of `PostgresCodingService.append`, add:

```python
if checkpoint_id is not None:
    raise ValueError(
        "checkpoint-linked events require an atomic checkpoint command"
    )
```

Keep `_append_in_session` usable by the durability repository so it can insert an already-existing checkpoint identity in its transaction.

- [ ] **Step 9: Refactor fake loop**

Use `begin_phase`, `claim_tool_execution`, `complete_tool_execution`, and `commit_phase_checkpoint`. Build each loop state with:

```python
current_instruction = (
    str(checkpoint.loop_state["current_instruction"])
    if checkpoint
    else input.instruction
)
loop_state = {
    "phase_index": index,
    "transcript": list(transcript),
    "current_instruction": current_instruction,
    "pending_instruction": None,
}
```

- [ ] **Step 10: Run GREEN**

Run: `.venv/bin/pytest -q tests/coding/repositories/test_durability_repository.py tests/coding/loop/test_fake_loop.py tests/coding/persistence/test_postgres_service.py`

Expected: all tests pass.

- [ ] **Step 11: Commit**

```bash
git add neos/coding/loop/base.py neos/coding/loop/fake.py neos/coding/repositories/run_repository.py neos/coding/persistence/postgres.py tests/coding/fakes.py tests/coding/loop/test_fake_loop.py tests/coding/repositories/test_durability_repository.py
git commit -m "feat: commit coding checkpoints atomically"
```

---

### Task 4: Recoverable Atomic Steering and Run Transition

**Files:**
- Modify: `neos/coding/loop/base.py`
- Modify: `neos/coding/repositories/run_repository.py`
- Modify: `tests/coding/fakes.py`
- Modify: `neos/coding/application/run_service.py`
- Modify: `tests/coding/application/test_run_service.py`
- Modify: `tests/coding/repositories/test_durability_repository.py`

**Interfaces:**
- Consumes: Task 3 execution lease and atomic checkpoint infrastructure.
- Produces: `apply_steering_at_safe_point(...) -> SteeringApplication | None` and `commit_interruption(...) -> SteeringApplication`.

- [ ] **Step 1: Write failing expired-claim SQL test**

```python
async def test_safe_steering_reclaims_expired_claim_and_transitions_run_atomically() -> None:
    session = FakeSession(rows=[STEERING_ROW, (21,)])
    repository = repository_for(session)

    applied = await repository.apply_steering_at_safe_point(
        lease=LEASE,
        checkpoint=CHECKPOINT,
        worker_id="worker-a",
        claim_expires_at=EXPIRES,
        now=NOW,
    )

    sql = "\n".join(session.sql)
    assert "claim_expires_at <= :now" in sql
    assert "INSERT INTO coding_checkpoints" in sql
    assert "UPDATE coding_steering_requests" in sql
    assert "UPDATE coding_runs" in sql
    assert "INSERT INTO coding_runs" in sql
    assert "UPDATE coding_run_leases" in sql
    assert applied is not None and applied.run.attempt == 2
```

- [ ] **Step 2: Write failing service recovery test**

```python
async def test_new_worker_reclaims_steering_after_claim_expiry() -> None:
    harness = DurableCodingHarness()
    task = await harness.create_task(owner_id="u1", prompt="Fix it")
    await harness.advance_until(task.task_id, phase="implement")
    await harness.steer(
        task_id=task.task_id, owner_id="u1",
        instruction="Inspect cache first", mode=SteeringMode.SAFE_POINT,
    )
    harness.repository.crash_after_steering_claim_once = True

    with pytest.raises(SimulatedWorkerCrash):
        await harness.advance_one_safe_point(task.task_id, worker_id="worker-a")
    harness.clock.advance(seconds=31)
    await harness.advance_one_safe_point(task.task_id, worker_id="worker-b")

    assert harness.repository.applied_steering[-1].instruction == "Inspect cache first"
    assert harness.repository.active_run.attempt == 2
```

- [ ] **Step 3: Run RED**

Run: `.venv/bin/pytest -q tests/coding/repositories/test_durability_repository.py tests/coding/application/test_run_service.py tests/coding/test_durable_phase_vertical_slice.py`

Expected: fails because steering is still claimed and applied across separate transactions.

- [ ] **Step 4: Add steering command protocol**

```python
async def apply_steering_at_safe_point(
    self, *, lease: ExecutionLease, checkpoint: CodingCheckpoint,
    worker_id: str, claim_expires_at: datetime, now: datetime,
) -> SteeringApplication | None: ...

async def commit_interruption(
    self, *, lease: ExecutionLease, request: SteeringRequest,
    workspace_revision: str, process_stopped: bool,
    now: datetime,
) -> SteeringApplication: ...
```

- [ ] **Step 5: Implement atomic safe steering**

Use one transaction and the exact sequence in the design: validate lease; select pending or expired claimed steering with `FOR UPDATE SKIP LOCKED`; allocate seq; insert steering checkpoint before its event; apply steering; cancel old run; insert next attempt; update lease run ID and increment fencing token; insert outbox; return the new lease/run/checkpoint/event.

- [ ] **Step 6: Implement atomic interruption commit**

Keep process interruption outside the DB transaction. Only after `process_stopped=True`, call `commit_interruption` to perform checkpoint/event/steering/run/lease changes atomically. If interruption raises or returns false, keep the run running and restore the steering request to `pending` using a fenced repository command.

- [ ] **Step 7: Refactor `CodingRunService.on_safe_point` and `_interrupt_active_run`**

Replace direct `claim_pending_steering`, event append, checkpoint save, run update, and run creation calls with the two atomic commands. Return the `SteeringApplication` so `advance_one_safe_point` continues with its returned run and lease.

- [ ] **Step 8: Run GREEN**

Run: `.venv/bin/pytest -q tests/coding/repositories/test_durability_repository.py tests/coding/application/test_run_service.py tests/coding/test_durable_phase_vertical_slice.py`

Expected: all tests pass, including expired steering reclaim.

- [ ] **Step 9: Commit**

```bash
git add neos/coding/loop/base.py neos/coding/repositories/run_repository.py tests/coding/fakes.py neos/coding/application/run_service.py tests/coding/application/test_run_service.py tests/coding/repositories/test_durability_repository.py tests/coding/test_durable_phase_vertical_slice.py
git commit -m "feat: apply coding steering atomically"
```

---

### Task 5: Durable Service Restore, Lease Lifecycle, and Metrics

**Files:**
- Modify: `neos/coding/application/run_service.py`
- Modify: `neos/coding/runtime.py`
- Modify: `neos/observability/metrics.py`
- Modify: `tests/coding/application/test_run_service.py`
- Modify: `tests/coding/test_durable_phase_vertical_slice.py`
- Create: `tests/coding/test_durability_metrics.py`

**Interfaces:**
- Consumes: Tasks 2–4 lease, phase, tool, checkpoint, and steering commands.
- Produces: `advance_one_safe_point(task_id, worker_id)`, durable instruction restoration, corrected resume metric, lease contention metric.

- [ ] **Step 1: Write failing instruction restore test**

```python
async def test_new_worker_restores_instruction_from_checkpoint() -> None:
    harness = DurableCodingHarness()
    task = await harness.create_task(owner_id="u1", prompt="Fix the cache")
    await harness.advance_one_safe_point(task.task_id, worker_id="worker-a")

    harness.replace_worker()
    await harness.advance_one_safe_point(task.task_id, worker_id="worker-b")

    assert harness.loop_inputs[-1].instruction == "Fix the cache"
    assert harness.repository.checkpoints[-1].loop_state["current_instruction"] == (
        "Fix the cache"
    )
```

- [ ] **Step 2: Write failing concurrency test**

```python
async def test_two_workers_cannot_advance_same_task() -> None:
    harness = DurableCodingHarness(block_first_worker_after_lease=True)
    task = await harness.create_task(owner_id="u1", prompt="Fix it")

    first = asyncio.create_task(
        harness.advance_one_safe_point(task.task_id, worker_id="worker-a")
    )
    await harness.first_worker_has_lease.wait()

    with pytest.raises(RunAlreadyLeased):
        await harness.advance_one_safe_point(task.task_id, worker_id="worker-b")

    harness.release_first_worker.set()
    await first
    assert harness.completed_phase_count("understand", attempt=1) == 1
```

- [ ] **Step 3: Write failing metric semantics test**

```python
def test_coding_metrics_expose_only_bounded_labels() -> None:
    collector = EnterpriseMetricsCollector(CollectorRegistry())

    assert collector.coding_phase_duration_seconds._labelnames == ("phase",)
    assert collector.coding_resume_total._labelnames == ("outcome",)
    assert collector.coding_lease_contention_total._labelnames == ("outcome",)


async def test_normal_safe_point_continuation_is_not_counted_as_resume() -> None:
    metrics = RecordingCodingMetrics()
    harness = DurableCodingHarness(metrics=metrics)
    task = await harness.create_task(owner_id="u1", prompt="Fix it")

    await harness.advance_one_safe_point(task.task_id, worker_id="worker-a")
    await harness.advance_one_safe_point(task.task_id, worker_id="worker-a")

    assert metrics.resume_outcomes == []
```

- [ ] **Step 4: Run RED**

Run: `.venv/bin/pytest -q tests/coding/application/test_run_service.py tests/coding/test_durable_phase_vertical_slice.py tests/coding/test_durability_metrics.py`

Expected: fails because instruction is process-local, service has no worker ID, and resume metrics count every checkpoint continuation.

- [ ] **Step 5: Refactor service lease lifecycle**

Change the public signature to:

```python
async def advance_one_safe_point(
    self, *, task_id: str, worker_id: str
) -> CodingEvent | None:
```

Acquire a 30-second lease before reading mutable loop state. If acquisition returns `None`, increment `coding_lease_contention_total{outcome="busy"}` and raise `RunAlreadyLeased`. Restore instruction from `checkpoint.loop_state["current_instruction"]`; only use the task prompt for a checkpoint-free first run. Remove `_instructions` entirely. Renew between safe points and release on terminal completion or cancellation. Never release a stale token.

- [ ] **Step 6: Distinguish resume from continuation**

Count `coding_resume_total` only when `ExecutionLease.recovered` is true. PostgreSQL acquisition sets it when the upsert replaces an expired lease owned by another worker for an already-started active run. Initial acquisition and same-worker renewal set it to false. The in-memory implementation follows the same rule.

- [ ] **Step 7: Add lease metric**

```python
self.coding_lease_contention_total = Counter(
    "coding_lease_contention_total",
    "Durable coding execution lease outcomes",
    ["outcome"],
    registry=self.registry,
)
```

Allowed outcomes are exactly `acquired`, `busy`, and `stale_write`.

- [ ] **Step 8: Update runtime wiring**

Keep fake-loop startup disabled by default. The runtime factory continues to inject the loop and metrics but does not add a supervisor in this plan. Any direct development caller must supply a stable `worker_id` for the worker lifetime.

- [ ] **Step 9: Run GREEN**

Run: `.venv/bin/pytest -q tests/coding/application/test_run_service.py tests/coding/test_durable_phase_vertical_slice.py tests/coding/test_durability_metrics.py`

Expected: all tests pass.

- [ ] **Step 10: Commit**

```bash
git add neos/coding/application/run_service.py neos/coding/runtime.py neos/observability/metrics.py tests/coding/application/test_run_service.py tests/coding/test_durable_phase_vertical_slice.py tests/coding/test_durability_metrics.py
git commit -m "feat: restore fenced coding runs durably"
```

---

### Task 6: Real PostgreSQL Fault and Concurrency Verification

**Files:**
- Create: `tests/coding/integration/test_postgres_durability.py`
- Modify: `tests/conftest.py`
- Modify: `docs/NEOS_CODING.md`

**Interfaces:**
- Consumes: completed durability repository and service contracts.
- Produces: opt-in real PostgreSQL proof for FK ordering, rollback, lease contention, stale fencing, and steering recovery.

- [ ] **Step 1: Add opt-in PostgreSQL fixture**

```python
@pytest.fixture
async def coding_postgres_session_factory():
    url = os.getenv("CODING_TEST_DATABASE_URL")
    if not url:
        pytest.skip("CODING_TEST_DATABASE_URL is not configured")
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        for migration in (
            "db/migrations/038_add_coding_phase0.sql",
            "db/migrations/039_add_coding_runs_checkpoints.sql",
            "db/migrations/040_add_coding_execution_leases.sql",
        ):
            sql = Path(migration).read_text()
            for statement in sql.split(";"):
                if statement.strip():
                    await connection.exec_driver_sql(statement)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async def session_factory():
        return maker()
    try:
        yield session_factory
    finally:
        async with engine.begin() as connection:
            await connection.exec_driver_sql(
                "TRUNCATE coding_event_outbox, coding_events, "
                "coding_tool_executions, coding_steering_requests, "
                "coding_run_leases, coding_checkpoints, coding_phases, "
                "coding_runs, coding_tasks CASCADE"
            )
        await engine.dispose()
```

If migrations 038 depend on shared tables not present in a clean database, CI must provision the normal NEOS test schema before this fixture runs; do not weaken the test by mocking PostgreSQL.

- [ ] **Step 2: Add FK and atomic rollback test**

```python
@pytest.mark.integration
async def test_checkpoint_event_fk_and_phase_commit_are_atomic(runtime) -> None:
    task, run, lease, phase = await runtime.seed_active_phase()

    committed = await runtime.repository.commit_phase_checkpoint(
        lease=lease, phase=phase, tool_call_id="tool_1",
        result={"summary": "done"},
        loop_state={
            "phase_index": 0,
            "transcript": [],
            "current_instruction": "Fix it",
            "pending_instruction": None,
        },
        workspace_revision="rev_1", now=NOW,
    )

    assert committed.event.checkpoint_id == committed.checkpoint.checkpoint_id
    assert await runtime.count("coding_checkpoints") == 1
    assert await runtime.count("coding_events", type="phase.completed") == 1
    assert await runtime.phase_status(phase.phase_id) == "completed"
```

Add a second case that installs a temporary PostgreSQL `BEFORE INSERT` trigger on
`coding_events` which raises when `NEW.type = 'phase.completed'`. Call
`commit_phase_checkpoint`, assert the database exception, then drop the trigger and
function in `finally`. Assert checkpoint/event/outbox/phase counts equal their
pre-call baselines. This injects a real statement-boundary failure without adding a
production test hook.

- [ ] **Step 3: Add lease contention and fencing test**

```python
@pytest.mark.integration
async def test_only_one_worker_holds_lease_and_stale_write_is_rejected(runtime) -> None:
    task, run = await runtime.seed_run()
    first, second = await asyncio.gather(
        runtime.acquire(run, "worker-a"),
        runtime.acquire(run, "worker-b"),
    )
    winner = first or second
    assert winner is not None
    assert (first is None) != (second is None)

    runtime.clock.advance(seconds=31)
    replacement = await runtime.acquire(run, "worker-c")
    assert replacement is not None
    assert replacement.fencing_token > winner.fencing_token
    with pytest.raises(StaleExecutionLease):
        await runtime.repository.renew_execution_lease(
            winner, now=runtime.now, expires_at=runtime.expires_at
        )
```

- [ ] **Step 4: Add expired steering recovery test**

Queue steering, claim it with worker A, advance the database clock beyond `claim_expires_at`, then apply it with worker B. Assert one applied steering row, one steering checkpoint/event, old run cancelled, new run running, and lease fencing token increased exactly once.

- [ ] **Step 5: Run PostgreSQL integration GREEN**

Run: `CODING_TEST_DATABASE_URL=postgresql+asyncpg://neos:neos@localhost:5432/neos_test .venv/bin/pytest -q -m integration tests/coding/integration/test_postgres_durability.py`

Expected: all durability integration tests pass. If the local database is unavailable, record the skipped local result and require this exact command in CI before merge.

- [ ] **Step 6: Update implementation status**

Append to the durable phase checkpoint in `docs/NEOS_CODING.md`:

```markdown
- PostgreSQL atomic phase/checkpoint commit: 구현 완료
- Execution lease, fencing token, expired steering recovery: 구현 완료
- Durable instruction restore and tool claim: 구현 완료
- Development worker supervisor and automatic task startup: 다음 vertical slice로 이관
```

- [ ] **Step 7: Run full backend regression**

Run: `.venv/bin/pytest -q tests/coding tests/api/handlers/test_coding_handlers.py tests/api/handlers/test_coding_ws_handlers.py tests/api/test_coding_production_registration.py`

Expected: all tests pass; PostgreSQL integration tests may skip only when `CODING_TEST_DATABASE_URL` is absent.

- [ ] **Step 8: Run static and diff checks**

Run: `.venv/bin/python -m compileall -q neos/coding tests/coding`

Expected: exit 0.

Run: `git diff --check`

Expected: no output.

- [ ] **Step 9: Review requirements**

Confirm from test evidence that:

- checkpoint-linked events cannot be inserted through generic append;
- phase completion has no partial commit boundary;
- only one worker holds a valid task lease;
- stale fencing writes are rejected;
- expired steering claims are recoverable;
- original instruction survives a new service instance;
- completed tools are not executed twice;
- metric labels contain no IDs or user input;
- runtime supervisor and frontend changes remain out of scope.

- [ ] **Step 10: Commit**

```bash
git add tests/coding/integration/test_postgres_durability.py tests/conftest.py docs/NEOS_CODING.md
git commit -m "test: verify coding backend durability"
```

---

## Execution Notes

- Work on the current `dev` branch only if the user explicitly chooses inline execution there; otherwise create an isolated worktree before Task 1.
- Run tools sequentially according to the repository `AGENTS.md` safety protocol.
- Do not stage unrelated modified or untracked user files.
- After each task, inspect `git status --short`, run the task-specific GREEN command, and commit only the listed files.
- After Task 6, use `superpowers:verification-before-completion` before reporting completion.

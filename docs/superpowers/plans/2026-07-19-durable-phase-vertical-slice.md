# Durable Phase Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a durable fake coding run that advances through Understand, Plan, Implement, Verify, and Review, survives browser reconnect through a full snapshot, and supports safe-point and immediate steering.

**Architecture:** PostgreSQL stores task runs, checkpoints, control requests, and canonical coding events. A provider-neutral fake loop exercises the same run/checkpoint interfaces that the later model and sandbox loop will consume. The browser initializes a task-scoped external projection store from REST, then applies ordered WebSocket events into the same projection used by the Phase timeline UI.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, PostgreSQL JSONB, pytest, Next.js 16, React 19, TypeScript 5.9, `useSyncExternalStore`, Node test runner.

## Global Constraints

- PostgreSQL plus the existing coding outbox remains the only durable event source.
- A task-level event sequence never resets when a new run starts.
- Every event carries all applicable `run_id`, `turn_id`, and `tool_call_id` identifiers.
- Phase history is append-only; returning to an earlier phase creates a new attempt.
- Every model turn and every simulated write or command boundary creates a checkpoint.
- `tool_call_id` is the idempotency key for completed tool work.
- Safe-point steering applies after the active step checkpoints; immediate steering creates an interruption checkpoint and a new run.
- `resync_required` triggers a full REST snapshot refresh rather than a cursor-zero reconnect loop.
- The UI distinguishes restored checkpoint state from a caught-up live connection.
- This plan does not connect a real model, execute untrusted commands, provision a sandbox, or implement multi-agent coordination.
- Existing coding authorization, Redis transport, replay continuity, outbox, and unrelated chat behavior remain unchanged.

---

## File Structure

### Backend

- `neos/coding/domain/phases.py`: phase, run, checkpoint, and steering value objects.
- `neos/coding/application/run_service.py`: run lifecycle and control transitions.
- `neos/coding/application/snapshot_service.py`: full task projection snapshot builder.
- `neos/coding/loop/base.py`: provider-neutral resumable loop interfaces.
- `neos/coding/loop/fake.py`: deterministic five-phase loop used by this slice.
- `neos/coding/repositories/run_repository.py`: PostgreSQL run/checkpoint/control persistence.
- `neos/coding/repositories/projection_repository.py`: ordered projection reads for snapshots.
- `neos/api/models/coding_models.py`: snapshot and steering request/response schemas.
- `neos/api/handlers/coding_handlers.py`: snapshot and steering routes.
- `db/migrations/039_add_coding_runs_checkpoints.sql`: durable run/control schema.

### Frontend

- `web/features/coding/types/projection.ts`: snapshot and projected state types.
- `web/features/coding/stream/projection-reducer.ts`: pure snapshot/event reducer.
- `web/features/coding/stream/coding-projection-store.ts`: task-scoped external store.
- `web/features/coding/stream/use-coding-stream.ts`: REST bootstrap, replay, and full resync.
- `web/features/coding/api/coding-api.ts`: snapshot and steering clients.
- `web/features/coding/components/phase-timeline.tsx`: five-phase history.
- `web/features/coding/components/phase-card.tsx`: phase result and active state.
- `web/features/coding/components/coding-detail-panel.tsx`: contextual detail projection.
- `web/features/coding/components/coding-steer-composer.tsx`: two steering actions.
- `web/features/coding/components/coding-task-workspace.tsx`: assembled workspace shell.

---

### Task 1: Durable Run, Phase, Checkpoint, and Control Contracts

**Files:**
- Create: `neos/coding/domain/phases.py`
- Create: `db/migrations/039_add_coding_runs_checkpoints.sql`
- Create: `tests/coding/domain/test_phases.py`
- Create: `tests/coding/test_migration_039_contract.py`
- Modify: `neos/coding/domain/events.py`

**Interfaces:**
- Produces: `CodingPhaseKind`, `CodingPhaseStatus`, `CodingRunStatus`, `SteeringMode`.
- Produces: `CodingPhase`, `CodingRun`, `CodingCheckpoint`, `SteeringRequest` dataclasses.
- Produces: `make_event(..., checkpoint_id: str | None = None) -> CodingEvent`.
- Database produces: `coding_runs`, `coding_checkpoints`, `coding_steering_requests`.

- [ ] **Step 1: Write failing domain tests**

```python
from datetime import UTC, datetime

import pytest

from neos.coding.domain.phases import (
    CodingPhaseKind,
    CodingPhaseStatus,
    next_phase_attempt,
)


def test_reentering_phase_appends_attempt_instead_of_rewriting_history() -> None:
    phases = [
        (CodingPhaseKind.UNDERSTAND, 1),
        (CodingPhaseKind.PLAN, 1),
        (CodingPhaseKind.IMPLEMENT, 1),
    ]

    phase = next_phase_attempt(
        task_id="ct_1",
        run_id="cr_1",
        kind=CodingPhaseKind.UNDERSTAND,
        existing=phases,
        now=datetime(2026, 7, 19, tzinfo=UTC),
    )

    assert phase.attempt == 2
    assert phase.status is CodingPhaseStatus.ACTIVE


def test_phase_attempt_must_be_positive() -> None:
    with pytest.raises(ValueError, match="attempt"):
        next_phase_attempt(
            task_id="ct_1",
            run_id="cr_1",
            kind=CodingPhaseKind.PLAN,
            existing=[(CodingPhaseKind.PLAN, 0)],
            now=datetime(2026, 7, 19, tzinfo=UTC),
        )
```

- [ ] **Step 2: Write failing migration contract test**

```python
from pathlib import Path


def test_migration_creates_durable_run_checkpoint_and_steering_tables() -> None:
    sql = Path("db/migrations/039_add_coding_runs_checkpoints.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS coding_runs" in sql
    assert "CREATE TABLE IF NOT EXISTS coding_checkpoints" in sql
    assert "CREATE TABLE IF NOT EXISTS coding_steering_requests" in sql
    assert "UNIQUE (task_id, phase_kind, attempt)" in sql
    assert "UNIQUE (task_id, tool_call_id)" in sql
    assert "loop_state_json JSONB NOT NULL" in sql
    assert "mode VARCHAR(32) NOT NULL" in sql
```

- [ ] **Step 3: Run RED**

Run: `.venv/bin/pytest -q tests/coding/domain/test_phases.py tests/coding/test_migration_039_contract.py`

Expected: collection fails because `neos.coding.domain.phases` and migration 039 do not exist.

- [ ] **Step 4: Implement domain values and event checkpoint identity**

```python
# neos/coding/domain/phases.py
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping, Sequence


class CodingPhaseKind(StrEnum):
    UNDERSTAND = "understand"
    PLAN = "plan"
    IMPLEMENT = "implement"
    VERIFY = "verify"
    REVIEW = "review"


class CodingPhaseStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


class CodingRunStatus(StrEnum):
    RUNNING = "running"
    INTERRUPTING = "interrupting"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SteeringMode(StrEnum):
    SAFE_POINT = "safe_point"
    INTERRUPT_NOW = "interrupt_now"


@dataclass(frozen=True, slots=True)
class CodingPhase:
    phase_id: str
    task_id: str
    run_id: str
    kind: CodingPhaseKind
    attempt: int
    status: CodingPhaseStatus
    started_at: datetime
    completed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CodingRun:
    run_id: str
    task_id: str
    attempt: int
    status: CodingRunStatus
    resume_from_checkpoint_id: str | None
    started_at: datetime
    completed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CodingCheckpoint:
    checkpoint_id: str
    task_id: str
    run_id: str
    seq: int
    loop_state: Mapping[str, Any]
    workspace_revision: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SteeringRequest:
    steering_id: str
    task_id: str
    mode: SteeringMode
    instruction: str
    requested_at: datetime
    applied_checkpoint_id: str | None = None


def next_phase_attempt(
    *, task_id: str, run_id: str, kind: CodingPhaseKind,
    existing: Sequence[tuple[CodingPhaseKind, int]], now: datetime,
) -> CodingPhase:
    attempts = [attempt for phase_kind, attempt in existing if phase_kind is kind]
    if any(attempt < 1 for attempt in attempts):
        raise ValueError("phase attempt must be positive")
    attempt = max(attempts, default=0) + 1
    return CodingPhase(
        phase_id=f"cp_{run_id}_{kind.value}_{attempt}",
        task_id=task_id,
        run_id=run_id,
        kind=kind,
        attempt=attempt,
        status=CodingPhaseStatus.ACTIVE,
        started_at=now,
    )
```

Add `checkpoint_id: str | None = None` to `CodingEvent` and `make_event`, and pass it through event serialization in the API and Redis transport.

- [ ] **Step 5: Create migration 039**

```sql
CREATE TABLE IF NOT EXISTS coding_runs (
    run_id VARCHAR(64) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL REFERENCES coding_tasks(task_id) ON DELETE CASCADE,
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    status VARCHAR(32) NOT NULL,
    resume_from_checkpoint_id VARCHAR(64),
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    UNIQUE (task_id, attempt)
);

CREATE TABLE IF NOT EXISTS coding_checkpoints (
    checkpoint_id VARCHAR(64) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL REFERENCES coding_tasks(task_id) ON DELETE CASCADE,
    run_id VARCHAR(64) NOT NULL REFERENCES coding_runs(run_id) ON DELETE CASCADE,
    seq BIGINT NOT NULL,
    loop_state_json JSONB NOT NULL,
    workspace_revision VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (task_id, seq)
);

ALTER TABLE coding_runs
    ADD CONSTRAINT fk_coding_runs_resume_checkpoint
    FOREIGN KEY (resume_from_checkpoint_id)
    REFERENCES coding_checkpoints(checkpoint_id);

CREATE TABLE IF NOT EXISTS coding_phases (
    phase_id VARCHAR(128) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL REFERENCES coding_tasks(task_id) ON DELETE CASCADE,
    run_id VARCHAR(64) NOT NULL REFERENCES coding_runs(run_id) ON DELETE CASCADE,
    phase_kind VARCHAR(32) NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    status VARCHAR(32) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    UNIQUE (task_id, phase_kind, attempt)
);

CREATE TABLE IF NOT EXISTS coding_tool_executions (
    task_id VARCHAR(64) NOT NULL REFERENCES coding_tasks(task_id) ON DELETE CASCADE,
    tool_call_id VARCHAR(128) NOT NULL,
    run_id VARCHAR(64) NOT NULL REFERENCES coding_runs(run_id) ON DELETE CASCADE,
    status VARCHAR(32) NOT NULL,
    result_json JSONB,
    completed_at TIMESTAMPTZ,
    PRIMARY KEY (task_id, tool_call_id),
    UNIQUE (task_id, tool_call_id)
);

CREATE TABLE IF NOT EXISTS coding_steering_requests (
    steering_id VARCHAR(64) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL REFERENCES coding_tasks(task_id) ON DELETE CASCADE,
    mode VARCHAR(32) NOT NULL,
    instruction TEXT NOT NULL,
    status VARCHAR(32) NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL,
    applied_checkpoint_id VARCHAR(64) REFERENCES coding_checkpoints(checkpoint_id)
);

CREATE INDEX IF NOT EXISTS idx_coding_runs_task_attempt
    ON coding_runs(task_id, attempt DESC);
CREATE INDEX IF NOT EXISTS idx_coding_checkpoints_task_seq
    ON coding_checkpoints(task_id, seq DESC);
CREATE INDEX IF NOT EXISTS idx_coding_steering_pending
    ON coding_steering_requests(task_id, requested_at)
    WHERE status = 'pending';
```

- [ ] **Step 6: Run GREEN**

Run: `.venv/bin/pytest -q tests/coding/domain/test_phases.py tests/coding/domain/test_events.py tests/coding/test_migration_039_contract.py tests/coding/transport/test_redis_events.py`

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

```bash
git add neos/coding/domain/phases.py neos/coding/domain/events.py neos/api/handlers/coding_handlers.py neos/coding/transport/redis_events.py db/migrations/039_add_coding_runs_checkpoints.sql tests/coding/domain/test_phases.py tests/coding/test_migration_039_contract.py tests/coding/domain/test_events.py tests/coding/transport/test_redis_events.py
git commit -m "feat: define durable coding run contracts"
```

---

### Task 2: Run, Checkpoint, Tool Idempotency, and Steering Repository

**Files:**
- Create: `neos/coding/repositories/run_repository.py`
- Create: `tests/coding/fakes.py`
- Create: `tests/coding/repositories/test_run_repository.py`

**Interfaces:**
- Consumes: domain values from Task 1 and `SessionFactory` from `neos/coding/persistence/postgres.py`.
- Produces: `CodingRunRepository.create_run(...)`, `latest_run(...)`, `save_checkpoint(...)`, `latest_checkpoint(...)`.
- Produces: `completed_tool_result(task_id, tool_call_id)`, `record_tool_result(...)`.
- Produces: `queue_steering(...)`, `claim_pending_steering(task_id)`.
- Produces for later tests: `InMemoryCodingRunRepository` in `tests/coding/fakes.py` implementing the same methods and recording `checkpoints`, `tool_execution_calls`, `created_runs`, `interrupt_calls`, and `applied_steering`.

- [ ] **Step 1: Write failing repository contract tests**

```python
async def test_checkpoint_and_tool_result_are_idempotent() -> None:
    session = FakeSession()
    repository = PostgresCodingRunRepository(lambda: async_session(session))
    checkpoint = checkpoint_fixture(seq=7)

    await repository.save_checkpoint(checkpoint)
    await repository.record_tool_result(
        task_id="ct_1",
        run_id="cr_1",
        tool_call_id="tool_1",
        result={"ok": True},
        completed_at=NOW,
    )
    await repository.record_tool_result(
        task_id="ct_1",
        run_id="cr_2",
        tool_call_id="tool_1",
        result={"ok": False},
        completed_at=NOW,
    )

    sql = "\n".join(session.sql)
    assert "ON CONFLICT (task_id, tool_call_id) DO NOTHING" in sql
    assert "INSERT INTO coding_checkpoints" in sql


async def test_claim_pending_steering_uses_skip_locked() -> None:
    repository, session = repository_with_fake_session()

    await repository.claim_pending_steering("ct_1")

    assert "FOR UPDATE SKIP LOCKED" in "\n".join(session.sql)
```

The test fake implements the cross-task repository contract explicitly:

```python
# tests/coding/fakes.py
class InMemoryCodingRunRepository:
    def __init__(self, *, completed_tools=None, active_run=None) -> None:
        self.completed_tools = dict(completed_tools or {})
        self.active_run = active_run
        self.checkpoints = []
        self.tool_execution_calls = []
        self.created_runs = []
        self.interrupt_calls = []
        self.applied_steering = []

    async def save_checkpoint(self, checkpoint) -> None:
        self.checkpoints.append(checkpoint)

    async def completed_tool_result(self, task_id, tool_call_id):
        return self.completed_tools.get(tool_call_id)

    async def record_tool_result(self, **record) -> None:
        self.tool_execution_calls.append(record)
        self.completed_tools.setdefault(record["tool_call_id"], record["result"])
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/pytest -q tests/coding/repositories/test_run_repository.py`

Expected: collection fails because `PostgresCodingRunRepository` does not exist.

- [ ] **Step 3: Implement the repository**

```python
class PostgresCodingRunRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def save_checkpoint(self, checkpoint: CodingCheckpoint) -> None:
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("""
                    INSERT INTO coding_checkpoints
                        (checkpoint_id, task_id, run_id, seq,
                         loop_state_json, workspace_revision, created_at)
                    VALUES
                        (:checkpoint_id, :task_id, :run_id, :seq,
                         CAST(:state AS JSONB), :workspace_revision, :created_at)
                    ON CONFLICT (checkpoint_id) DO NOTHING
                    """),
                    checkpoint_params(checkpoint),
                )

    async def record_tool_result(
        self, *, task_id: str, run_id: str, tool_call_id: str,
        result: Mapping[str, Any], completed_at: datetime,
    ) -> None:
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("""
                    INSERT INTO coding_tool_executions
                        (task_id, tool_call_id, run_id, status,
                         result_json, completed_at)
                    VALUES
                        (:task_id, :tool_call_id, :run_id, 'completed',
                         CAST(:result AS JSONB), :completed_at)
                    ON CONFLICT (task_id, tool_call_id) DO NOTHING
                    """),
                    {
                        "task_id": task_id,
                        "tool_call_id": tool_call_id,
                        "run_id": run_id,
                        "result": json.dumps(dict(result)),
                        "completed_at": completed_at,
                    },
                )
```

Implement `claim_pending_steering` as one transaction selecting the oldest
pending row with `FOR UPDATE SKIP LOCKED`, changing it to `claimed`, and mapping
it to `SteeringRequest`. `completed_tool_result` returns persisted JSON only for
`status = 'completed'`.

- [ ] **Step 4: Run GREEN**

Run: `.venv/bin/pytest -q tests/coding/repositories/test_run_repository.py tests/coding/persistence/test_postgres_service.py`

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add neos/coding/repositories/run_repository.py tests/coding/fakes.py tests/coding/repositories/test_run_repository.py
git commit -m "feat: persist coding runs and checkpoints"
```

---

### Task 3: Provider-Neutral Durable Fake Loop

**Files:**
- Create: `neos/coding/loop/__init__.py`
- Create: `neos/coding/loop/base.py`
- Create: `neos/coding/loop/fake.py`
- Create: `tests/coding/loop/test_fake_loop.py`

**Interfaces:**
- Consumes: `CodingRunRepository` contract from Task 2.
- Consumes: an event sink `append(task_id, event_type, payload, run_id, turn_id, tool_call_id, checkpoint_id)`.
- Produces: `LoopCheckpointState`, `CodingLoop.run(input, checkpoint, deps) -> AsyncIterator[CodingEvent]`.
- Produces: `FakeDurableCodingLoop` with deterministic phase steps.

- [ ] **Step 1: Write failing loop tests**

```python
async def test_fake_loop_runs_all_phases_and_checkpoints_each_step() -> None:
    repository = InMemoryCodingRunRepository()
    sink = RecordingEventSink()
    loop = FakeDurableCodingLoop(clock=lambda: NOW)

    events = [
        event
        async for event in loop.run(
            LoopInput(task_id="ct_1", run_id="cr_1", instruction="Fix it"),
            checkpoint=None,
            deps=LoopDependencies(repository=repository, events=sink),
        )
    ]

    assert [event.payload["phase"] for event in events if event.type == "phase.started"] == [
        "understand", "plan", "implement", "verify", "review"
    ]
    assert len(repository.checkpoints) == 5
    assert events[-1].type == "run.completed"


async def test_completed_tool_is_not_reexecuted_after_resume() -> None:
    repository = InMemoryCodingRunRepository(completed_tools={"tool_edit": {"ok": True}})
    loop = FakeDurableCodingLoop(clock=lambda: NOW)

    events = [event async for event in loop.run(INPUT, CHECKPOINT_AFTER_PLAN, deps(repository))]

    assert repository.tool_execution_calls == []
    assert any(event.type == "tool.completed" for event in events)
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/pytest -q tests/coding/loop/test_fake_loop.py`

Expected: collection fails because `neos.coding.loop` does not exist.

- [ ] **Step 3: Define loop ports**

```python
# neos/coding/loop/base.py
from dataclasses import dataclass
from typing import AsyncIterator, Mapping, Protocol

from neos.coding.domain.events import CodingEvent
from neos.coding.domain.phases import CodingCheckpoint


@dataclass(frozen=True, slots=True)
class LoopInput:
    task_id: str
    run_id: str
    instruction: str


@dataclass(frozen=True, slots=True)
class LoopCheckpointState:
    phase_index: int
    transcript: tuple[Mapping[str, object], ...]
    pending_instruction: str | None
    workspace_revision: str


@dataclass(frozen=True, slots=True)
class LoopDependencies:
    repository: "CodingRunRepository"
    events: "CodingLoopEventSink"


class CodingLoop(Protocol):
    def run(
        self,
        input: LoopInput,
        checkpoint: CodingCheckpoint | None,
        deps: LoopDependencies,
    ) -> AsyncIterator[CodingEvent]: ...
```

- [ ] **Step 4: Implement deterministic phase execution**

```python
PHASES = (
    CodingPhaseKind.UNDERSTAND,
    CodingPhaseKind.PLAN,
    CodingPhaseKind.IMPLEMENT,
    CodingPhaseKind.VERIFY,
    CodingPhaseKind.REVIEW,
)


class FakeDurableCodingLoop:
    def __init__(self, *, clock: Callable[[], datetime]) -> None:
        self._clock = clock

    async def run(self, input, checkpoint, deps):
        start_index = checkpoint.loop_state["phase_index"] + 1 if checkpoint else 0
        for index, phase in enumerate(PHASES[start_index:], start=start_index):
            yield await deps.events.append(
                task_id=input.task_id,
                event_type="phase.started",
                payload={"phase": phase.value, "attempt": 1, "index": index},
                run_id=input.run_id,
            )
            tool_call_id = f"fake_{phase.value}_{index}"
            persisted = await deps.repository.completed_tool_result(
                input.task_id, tool_call_id
            )
            if persisted is None:
                persisted = {"summary": f"{phase.value} completed"}
                await deps.repository.record_tool_result(
                    task_id=input.task_id,
                    run_id=input.run_id,
                    tool_call_id=tool_call_id,
                    result=persisted,
                    completed_at=self._clock(),
                )
            completed = await deps.events.append(
                task_id=input.task_id,
                event_type="phase.completed",
                payload={"phase": phase.value, "attempt": 1, **persisted},
                run_id=input.run_id,
                tool_call_id=tool_call_id,
            )
            await deps.repository.save_checkpoint(
                checkpoint_from_event(completed, phase_index=index)
            )
            yield completed
        yield await deps.events.append(
            task_id=input.task_id,
            event_type="run.completed",
            payload={"status": "completed"},
            run_id=input.run_id,
        )
```

- [ ] **Step 5: Run GREEN**

Run: `.venv/bin/pytest -q tests/coding/loop/test_fake_loop.py tests/coding/domain/test_phases.py`

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```bash
git add neos/coding/loop tests/coding/loop
git commit -m "feat: add durable fake coding loop"
```

---

### Task 4: Run Coordinator and Two Steering Modes

**Files:**
- Create: `neos/coding/application/run_service.py`
- Modify: `neos/coding/domain/errors.py`
- Modify: `neos/api/models/coding_models.py`
- Modify: `neos/api/handlers/coding_handlers.py`
- Modify: `neos/coding/runtime.py`
- Create: `tests/coding/application/test_run_service.py`
- Modify: `tests/api/handlers/test_coding_handlers.py`

**Interfaces:**
- Consumes: fake loop and run repository from Tasks 2–3.
- Produces: `CodingRunService.start(task_id, instruction)`, `steer(...)`, `stop(...)`.
- Produces: `RunInterrupter.interrupt(run_id) -> InterruptionResult` and `InProcessRunInterrupter`.
- Produces: `CodingTaskNotFound(CodingDomainError)`.
- Produces: `POST /api/v1/coding/tasks/{task_id}/steer`.
- Request: `{"instruction": str, "mode": "safe_point" | "interrupt_now"}`.

- [ ] **Step 1: Write failing steering service tests**

```python
async def test_safe_point_steering_is_applied_after_checkpoint() -> None:
    repository = InMemoryCodingRunRepository()
    service = make_run_service(repository)

    steering = await service.steer(
        task_id="ct_1",
        owner_id="u1",
        instruction="Also update docs",
        mode=SteeringMode.SAFE_POINT,
    )
    await service.on_safe_point(task_id="ct_1", checkpoint_id="cc_5")

    assert steering.mode is SteeringMode.SAFE_POINT
    assert repository.applied_steering[0].applied_checkpoint_id == "cc_5"
    assert repository.interrupt_calls == []


async def test_interrupt_steering_creates_new_run_from_interruption_checkpoint() -> None:
    repository = InMemoryCodingRunRepository(active_run=run_fixture("cr_1"))
    service = make_run_service(repository)

    await service.steer(
        task_id="ct_1",
        owner_id="u1",
        instruction="Stop editing auth and inspect cache",
        mode=SteeringMode.INTERRUPT_NOW,
    )

    assert repository.interrupt_calls == ["cr_1"]
    assert repository.created_runs[-1].resume_from_checkpoint_id == "cc_interrupt"
```

- [ ] **Step 2: Write failing API authorization test**

```python
def test_foreign_user_cannot_steer_coding_task() -> None:
    response = foreign_client.post(
        "/api/v1/coding/tasks/ct_owned/steer",
        json={"instruction": "exfiltrate", "mode": "interrupt_now"},
    )

    assert response.status_code == 404
```

- [ ] **Step 3: Run RED**

Run: `.venv/bin/pytest -q tests/coding/application/test_run_service.py tests/api/handlers/test_coding_handlers.py`

Expected: fails because the service and steering route do not exist.

- [ ] **Step 4: Define coordinator errors and interruption port**

```python
# neos/coding/domain/errors.py
class CodingTaskNotFound(CodingDomainError):
    """The task is absent or not owned by the requesting user."""


# neos/coding/application/run_service.py
@dataclass(frozen=True, slots=True)
class InterruptionResult:
    workspace_revision: str
    process_stopped: bool


class RunInterrupter(Protocol):
    async def interrupt(self, run_id: str) -> InterruptionResult: ...


class InProcessRunInterrupter:
    async def interrupt(self, run_id: str) -> InterruptionResult:
        return InterruptionResult(
            workspace_revision=f"fake-interrupt:{run_id}",
            process_stopped=True,
        )
```

- [ ] **Step 5: Implement coordinator semantics**

```python
class CodingRunService:
    async def steer(
        self, *, task_id: str, owner_id: str,
        instruction: str, mode: SteeringMode,
    ) -> SteeringRequest:
        if await self._tasks.get_owned(task_id, owner_id) is None:
            raise CodingTaskNotFound(task_id)
        request = SteeringRequest(
            steering_id=f"cs_{uuid4().hex}",
            task_id=task_id,
            mode=mode,
            instruction=instruction,
            requested_at=self._clock(),
        )
        await self._runs.queue_steering(request)
        await self._events.append(
            task_id=task_id,
            event_type="steer.queued",
            payload={"steering_id": request.steering_id, "mode": mode.value},
        )
        if mode is SteeringMode.INTERRUPT_NOW:
            await self._interrupt_active_run(task_id, request)
        return request
```

`_interrupt_active_run` marks the active run `interrupting`, invokes the injected
`RunInterrupter`, writes an interruption checkpoint containing the reconciled
workspace revision, marks the old run `cancelled`, and creates a new run with
`resume_from_checkpoint_id` set to that checkpoint.

- [ ] **Step 6: Add request schema and route**

```python
class CodingSteerRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=100_000)
    mode: Literal["safe_point", "interrupt_now"] = "safe_point"


@router.post("/tasks/{task_id}/steer", status_code=202)
async def steer_coding_task(
    task_id: str,
    body: CodingSteerRequest,
    current_user: User = Depends(get_current_user),
    runs: CodingRunService = Depends(get_coding_run_service),
):
    try:
        steering = await runs.steer(
            task_id=task_id,
            owner_id=current_user.user_id,
            instruction=body.instruction,
            mode=SteeringMode(body.mode),
        )
    except CodingTaskNotFound:
        raise HTTPException(status_code=404, detail="Coding task not found")
    return {"steering_id": steering.steering_id, "mode": steering.mode.value}
```

- [ ] **Step 7: Run GREEN**

Run: `.venv/bin/pytest -q tests/coding/application/test_run_service.py tests/api/handlers/test_coding_handlers.py`

Expected: all selected tests pass.

- [ ] **Step 8: Commit**

```bash
git add neos/coding/application/run_service.py neos/coding/domain/errors.py neos/api/models/coding_models.py neos/api/handlers/coding_handlers.py neos/coding/runtime.py tests/coding/application/test_run_service.py tests/api/handlers/test_coding_handlers.py
git commit -m "feat: add coding run steering controls"
```

---

### Task 5: Full Durable Projection Snapshot

**Files:**
- Create: `neos/coding/application/snapshot_service.py`
- Create: `neos/coding/repositories/projection_repository.py`
- Modify: `neos/api/models/coding_models.py`
- Modify: `neos/api/handlers/coding_handlers.py`
- Create: `tests/coding/application/test_snapshot_service.py`
- Modify: `tests/api/handlers/test_coding_handlers.py`

**Interfaces:**
- Consumes: task/run/checkpoint/event repositories.
- Produces: `CodingProjectionSnapshot` containing `task`, `active_run`, `phases`, `tools`, `approvals`, `todos`, `workspace`, `latest_checkpoint`, and `head_seq`.
- Produces: immutable `CodingProjectionRows` as the repository-to-service boundary.
- Replaces the minimal response of `GET /coding/tasks/{task_id}/snapshot` while preserving existing task fields.

- [ ] **Step 1: Write failing projection test**

```python
async def test_snapshot_is_one_consistent_head_projection() -> None:
    repository = ProjectionFixtureRepository(head_seq=14)
    service = CodingSnapshotService(repository)

    snapshot = await service.get_owned("ct_1", "u1")

    assert snapshot is not None
    assert snapshot.head_seq == 14
    assert snapshot.active_run.run_id == "cr_2"
    assert [(phase.kind.value, phase.attempt) for phase in snapshot.phases] == [
        ("understand", 1),
        ("plan", 1),
        ("implement", 1),
        ("understand", 2),
    ]
    assert snapshot.latest_checkpoint.seq <= snapshot.head_seq
```

- [ ] **Step 2: Write failing full snapshot API test**

```python
def test_snapshot_returns_phase_and_checkpoint_state() -> None:
    response = owner_client.get("/api/v1/coding/tasks/ct_1/snapshot")

    assert response.status_code == 200
    body = response.json()
    assert body["head_seq"] == 14
    assert body["active_run"]["run_id"] == "cr_2"
    assert body["phases"][0]["kind"] == "understand"
    assert body["connection_basis"] == "checkpoint"
```

- [ ] **Step 3: Run RED**

Run: `.venv/bin/pytest -q tests/coding/application/test_snapshot_service.py tests/api/handlers/test_coding_handlers.py`

Expected: fails because the full snapshot types and service do not exist.

- [ ] **Step 4: Implement a repeatable-read projection query**

```python
@dataclass(frozen=True, slots=True)
class CodingProjectionRows:
    task: CodingTaskRow
    runs: tuple[CodingRunRow, ...]
    phases: tuple[CodingPhaseRow, ...]
    tools: tuple[CodingToolExecutionRow, ...]
    approvals: tuple[CodingApprovalRow, ...]
    todos: tuple[CodingTodoRow, ...]
    workspace: CodingWorkspaceRow
    latest_checkpoint: CodingCheckpointRow | None
    head_seq: int


class PostgresCodingProjectionRepository:
    async def get_owned_snapshot(
        self, task_id: str, owner_id: str
    ) -> CodingProjectionRows | None:
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
                task = await owned_task_row(session, task_id, owner_id)
                if task is None:
                    return None
                runs = await run_rows(session, task_id)
                phases = await phase_rows(session, task_id)
                tools = await tool_rows(session, task_id)
                approvals = await pending_approval_rows(session, task_id)
                todos = await todo_rows(session, task_id)
                workspace = await workspace_row(session, task_id)
                checkpoint = await latest_checkpoint_row(session, task_id)
                return CodingProjectionRows(
                    task=task,
                    runs=runs,
                    phases=phases,
                    tools=tools,
                    approvals=approvals,
                    todos=todos,
                    workspace=workspace,
                    latest_checkpoint=checkpoint,
                    head_seq=int(task.last_seq),
                )
```

The repository orders phases by `started_at, attempt`, tools by completion time,
and selects only non-expired pending approvals and steering requests. The service
maps rows into immutable response values and sets `connection_basis="checkpoint"`.

- [ ] **Step 5: Extend Pydantic response models**

```python
class CodingPhaseSnapshot(BaseModel):
    phase_id: str
    run_id: str
    kind: str
    attempt: int
    status: str
    started_at: datetime
    completed_at: datetime | None


class CodingRunSnapshot(BaseModel):
    run_id: str
    attempt: int
    status: str
    resume_from_checkpoint_id: str | None


class CodingToolSnapshot(BaseModel):
    tool_call_id: str
    run_id: str
    status: str
    result: dict[str, Any] | None


class CodingWorkspaceSnapshot(BaseModel):
    revision: str
    git_head: str | None
    changed_files: list[str]


class CodingCheckpointSnapshot(BaseModel):
    checkpoint_id: str
    run_id: str
    seq: int
    loop_state: dict[str, Any]
    workspace_revision: str
    created_at: datetime


class CodingProjectionSnapshotResponse(BaseModel):
    task: CodingTaskResponse
    active_run: CodingRunSnapshot | None
    phases: list[CodingPhaseSnapshot]
    tools: list[CodingToolSnapshot]
    approvals: list[dict[str, Any]]
    todos: list[dict[str, Any]]
    workspace: CodingWorkspaceSnapshot
    latest_checkpoint: CodingCheckpointSnapshot | None
    head_seq: int
    connection_basis: Literal["checkpoint"]
```

- [ ] **Step 6: Run GREEN**

Run: `.venv/bin/pytest -q tests/coding/application/test_snapshot_service.py tests/api/handlers/test_coding_handlers.py tests/coding/test_phase0_vertical_slice.py`

Expected: all selected tests pass; update the phase-zero snapshot assertion to accept the new fields without changing replay ordering.

- [ ] **Step 7: Commit**

```bash
git add neos/coding/application/snapshot_service.py neos/coding/repositories/projection_repository.py neos/api/models/coding_models.py neos/api/handlers/coding_handlers.py tests/coding/application/test_snapshot_service.py tests/api/handlers/test_coding_handlers.py tests/coding/test_phase0_vertical_slice.py
git commit -m "feat: expose durable coding projection snapshot"
```

---

### Task 6: Frontend Projection Store and Automatic Full Resync

**Files:**
- Create: `web/features/coding/types/projection.ts`
- Create: `web/features/coding/stream/projection-reducer.ts`
- Create: `web/features/coding/stream/coding-projection-store.ts`
- Modify: `web/features/coding/api/coding-api.ts`
- Modify: `web/features/coding/stream/use-coding-stream.ts`
- Create: `web/tests/source/coding-projection-store.test.ts`
- Modify: `web/tests/source/coding-stream-client.test.ts`

**Interfaces:**
- Consumes: full snapshot response and canonical coding events.
- Produces: `CodingProjectionState`, `reduceSnapshot`, `reduceProjectionEvent`.
- Produces: `getCodingProjectionStore(taskId)` with `getSnapshot`, `subscribe`, `replaceSnapshot`, `applyEvent`, `setConnectionBasis`.
- Produces: `getCodingTaskSnapshot(taskId)` API client.

- [ ] **Step 1: Write failing pure projection tests**

```typescript
test("snapshot plus replay converges with uninterrupted live projection", () => {
  const live = events.reduce(reduceProjectionEvent, emptyProjection("ct_1"));
  const restored = replayEvents.reduce(
    reduceProjectionEvent,
    reduceSnapshot(snapshotAtSeq4)
  );

  assert.deepEqual(restored.phases, live.phases);
  assert.deepEqual(restored.tools, live.tools);
  assert.equal(restored.appliedSeq, live.appliedSeq);
});


test("phase history appends a second attempt", () => {
  const state = eventsWithSecondUnderstand.reduce(
    reduceProjectionEvent,
    emptyProjection("ct_1")
  );

  assert.deepEqual(
    state.phases.map((phase) => [phase.kind, phase.attempt]),
    [["understand", 1], ["plan", 1], ["implement", 1], ["understand", 2]]
  );
});
```

- [ ] **Step 2: Write failing resync source test**

```typescript
test("resync_required refetches snapshot instead of becoming terminal", () => {
  const hook = readFileSync("features/coding/stream/use-coding-stream.ts", "utf8");

  assert.match(hook, /getCodingTaskSnapshot/);
  assert.match(hook, /replaceSnapshot/);
  assert.doesNotMatch(hook, /Full coding snapshot resync required/);
});
```

- [ ] **Step 3: Run RED**

Run: `corepack pnpm@10.26.1 --dir web exec tsx --test tests/source/coding-projection-store.test.ts tests/source/coding-stream-client.test.ts`

Expected: fails because the projection modules and snapshot bootstrap do not exist.

- [ ] **Step 4: Implement projection types and reducer**

```typescript
export type CodingProjectionState = {
  taskId: string;
  appliedSeq: number;
  connectionBasis: "empty" | "checkpoint" | "live";
  activeRun: CodingRunView | null;
  phases: CodingPhaseView[];
  toolsById: Record<string, CodingToolView>;
  approvalsById: Record<string, CodingApprovalView>;
  todos: CodingTodoView[];
  workspace: CodingWorkspaceView;
};

export function reduceProjectionEvent(
  state: CodingProjectionState,
  event: CodingEvent
): CodingProjectionState {
  if (event.seq <= state.appliedSeq) return state;
  if (event.seq !== state.appliedSeq + 1) {
    return { ...state, gap: { expected: state.appliedSeq + 1, received: event.seq } };
  }
  if (event.type === "phase.started") {
    return appendStartedPhase(state, event);
  }
  if (event.type === "phase.completed" || event.type === "phase.failed") {
    return finishPhase(state, event);
  }
  if (event.type.startsWith("tool.")) {
    return projectToolEvent(state, event);
  }
  return { ...state, appliedSeq: event.seq };
}
```

- [ ] **Step 5: Implement task-scoped external store**

```typescript
export function createCodingProjectionStore(taskId: string) {
  let state = emptyProjection(taskId);
  const listeners = new Set<() => void>();
  const emit = () => listeners.forEach((listener) => listener());

  return {
    getSnapshot: () => state,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    replaceSnapshot(snapshot: CodingProjectionSnapshot) {
      state = reduceSnapshot(snapshot);
      emit();
    },
    applyEvent(event: CodingEvent) {
      state = reduceProjectionEvent(state, event);
      emit();
    },
    setConnectionBasis(basis: CodingProjectionState["connectionBasis"]) {
      state = { ...state, connectionBasis: basis };
      emit();
    },
  };
}
```

Cache one store per task ID and remove it when no subscribers remain and the task
is terminal.

- [ ] **Step 6: Bootstrap and resync the stream hook**

```typescript
async function hydrateFromSnapshot() {
  const snapshot = await getCodingTaskSnapshot(taskId);
  store.replaceSnapshot(snapshot);
  afterSeq.current = snapshot.head_seq;
  writeCursor(taskId, snapshot.head_seq);
}

async function connect() {
  await hydrateFromSnapshot();
  const authorization = await getCodingWsTicket(taskId);
  openSocket(authorization, afterSeq.current);
}

if (envelope.type === "resync_required") {
  socket?.close(1012, "Refreshing full coding snapshot");
  await hydrateFromSnapshot();
  reconnectImmediately();
  return;
}

if (envelope.type === "caught_up") {
  store.setConnectionBasis("live");
}
```

Guard hydration with a monotonically increasing generation number so a stale
snapshot response cannot replace a newer task state after disposal or another
resync.

- [ ] **Step 7: Run GREEN and typecheck**

Run: `corepack pnpm@10.26.1 --dir web exec tsx --test tests/source/coding-projection-store.test.ts tests/source/coding-stream-client.test.ts`

Expected: all selected tests pass.

Run: `corepack pnpm@10.26.1 --dir web exec tsc --noEmit`

Expected: exit 0. Restore `web/tsconfig.tsbuildinfo` after the command if it changes.

- [ ] **Step 8: Commit**

```bash
git add web/features/coding/types/projection.ts web/features/coding/stream/projection-reducer.ts web/features/coding/stream/coding-projection-store.ts web/features/coding/api/coding-api.ts web/features/coding/stream/use-coding-stream.ts web/tests/source/coding-projection-store.test.ts web/tests/source/coding-stream-client.test.ts
git commit -m "feat: restore coding workspace projection"
```

---

### Task 7: Phase Timeline, Contextual Detail, and Steering Composer

**Files:**
- Create: `web/features/coding/components/phase-timeline.tsx`
- Create: `web/features/coding/components/phase-card.tsx`
- Create: `web/features/coding/components/coding-detail-panel.tsx`
- Create: `web/features/coding/components/coding-steer-composer.tsx`
- Modify: `web/features/coding/components/coding-task-workspace.tsx`
- Modify: `web/features/coding/api/coding-api.ts`
- Create: `web/tests/source/coding-phase-workspace.test.ts`

**Interfaces:**
- Consumes: Task 6 projection store through `useSyncExternalStore`.
- Produces: Phase-oriented workspace with selected detail entity.
- Produces: `steerCodingTask(taskId, instruction, mode)` API client.

- [ ] **Step 1: Write failing component source contract test**

```typescript
test("workspace is phase-oriented and exposes both steering actions", () => {
  const workspace = readFileSync(
    "features/coding/components/coding-task-workspace.tsx",
    "utf8"
  );
  const timeline = readFileSync(
    "features/coding/components/phase-timeline.tsx",
    "utf8"
  );
  const composer = readFileSync(
    "features/coding/components/coding-steer-composer.tsx",
    "utf8"
  );

  assert.match(workspace, /PhaseTimeline/);
  assert.match(workspace, /CodingDetailPanel/);
  assert.match(timeline, /Understand/);
  assert.match(timeline, /Review/);
  assert.match(composer, /safe_point/);
  assert.match(composer, /interrupt_now/);
});
```

- [ ] **Step 2: Run RED**

Run: `corepack pnpm@10.26.1 --dir web exec tsx --test tests/source/coding-phase-workspace.test.ts`

Expected: fails because the Phase workspace components do not exist.

- [ ] **Step 3: Implement the Phase timeline**

```tsx
const PHASE_LABELS = {
  understand: "Understand",
  plan: "Plan",
  implement: "Implement",
  verify: "Verify",
  review: "Review",
} as const;

export function PhaseTimeline({ phases, onSelect }: PhaseTimelineProps) {
  return (
    <ol aria-label="Coding task phases" className="space-y-3">
      {phases.map((phase) => (
        <li key={phase.phaseId}>
          <PhaseCard
            phase={phase}
            label={`${PHASE_LABELS[phase.kind]}${phase.attempt > 1 ? ` #${phase.attempt}` : ""}`}
            defaultExpanded={
              phase.status === "active" ||
              phase.status === "blocked" ||
              phase.status === "failed"
            }
            onSelect={onSelect}
          />
        </li>
      ))}
    </ol>
  );
}
```

- [ ] **Step 4: Implement contextual detail and composer**

```tsx
export function CodingDetailPanel({ selection, projection }: DetailProps) {
  if (selection?.kind === "tool") {
    const tool = projection.toolsById[selection.id];
    return tool.type === "command"
      ? <TerminalPreview tool={tool} />
      : <ToolDetail tool={tool} />;
  }
  if (selection?.kind === "phase") {
    return <PhaseDetail phaseId={selection.id} projection={projection} />;
  }
  return <WorkspaceSummary workspace={projection.workspace} />;
}


export function CodingSteerComposer({ taskId, disabled }: Props) {
  const [instruction, setInstruction] = useState("");
  const submit = async (mode: "safe_point" | "interrupt_now") => {
    const value = instruction.trim();
    if (!value) return;
    await steerCodingTask(taskId, value, mode);
    setInstruction("");
  };
  return (
    <form onSubmit={(event) => { event.preventDefault(); void submit("safe_point"); }}>
      <textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} />
      <button disabled={disabled}>After current step</button>
      <button type="button" onClick={() => void submit("interrupt_now")}>Interrupt now</button>
    </form>
  );
}
```

The interrupt action opens a confirmation dialog only when the projection marks
the active tool `interruptible=false`; otherwise it submits directly. Connection
basis appears in the header as “Checkpoint restored” until `caught_up`, then
changes to “Live”.

- [ ] **Step 5: Assemble workspace and add steering client**

```typescript
export async function steerCodingTask(
  taskId: string,
  instruction: string,
  mode: "safe_point" | "interrupt_now"
): Promise<{ steering_id: string; mode: string }> {
  const response = await fetch(
    `/api/coding/tasks/${encodeURIComponent(taskId)}/steer`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instruction, mode }),
    }
  );
  if (!response.ok) {
    throw await responseError(response, "Could not steer coding task");
  }
  return response.json();
}
```

Use a two-column desktop layout with the Phase timeline in the main column and
the contextual detail panel on the right. On narrow screens, show the detail
panel as a full-screen sheet while keeping the composer pinned below the phase
timeline.

- [ ] **Step 6: Run GREEN, Biome, and typecheck**

Run: `corepack pnpm@10.26.1 --dir web exec tsx --test tests/source/coding-phase-workspace.test.ts tests/source/coding-projection-store.test.ts tests/source/coding-stream-client.test.ts`

Expected: all selected tests pass.

Run: `corepack pnpm@10.26.1 --dir web exec biome check features/coding tests/source/coding-phase-workspace.test.ts`

Expected: no diagnostics.

Run: `corepack pnpm@10.26.1 --dir web exec tsc --noEmit`

Expected: exit 0. Restore `web/tsconfig.tsbuildinfo` if generated.

- [ ] **Step 7: Commit**

```bash
git add web/features/coding/components/phase-timeline.tsx web/features/coding/components/phase-card.tsx web/features/coding/components/coding-detail-panel.tsx web/features/coding/components/coding-steer-composer.tsx web/features/coding/components/coding-task-workspace.tsx web/features/coding/api/coding-api.ts web/tests/source/coding-phase-workspace.test.ts
git commit -m "feat: add coding phase workspace"
```

---

### Task 8: Vertical Slice Integration, Fault Recovery, and Verification

**Files:**
- Create: `tests/coding/test_durable_phase_vertical_slice.py`
- Create: `web/tests/source/coding-phase-reconnect.test.ts`
- Modify: `neos/coding/runtime.py`
- Modify: `neos/observability/metrics.py`
- Modify: `docs/NEOS_CODING.md`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: one runtime-wired durable fake loop suitable for development feature-flag use.
- Produces metrics: `coding_phase_duration_seconds`, `coding_checkpoint_total`, `coding_steering_latency_seconds`, `coding_resume_total`.

- [ ] **Step 1: Write failing end-to-end service test**

```python
async def test_reconnect_and_safe_point_steer_preserve_phase_history() -> None:
    harness = DurableCodingHarness()
    task = await harness.create_task(owner_id="u1", prompt="Fix it")
    await harness.advance_until(task.task_id, phase="implement")
    before = await harness.snapshot(task.task_id, "u1")

    await harness.steer(
        task_id=task.task_id,
        owner_id="u1",
        instruction="Inspect cache first",
        mode=SteeringMode.SAFE_POINT,
    )
    await harness.advance_one_safe_point(task.task_id)
    after = await harness.snapshot(task.task_id, "u1")

    assert before.connection_basis == "checkpoint"
    assert after.head_seq > before.head_seq
    assert after.latest_checkpoint.loop_state["pending_instruction"] is None
    assert [(phase.kind.value, phase.attempt) for phase in after.phases][-1] == (
        "understand", 2
    )
```

- [ ] **Step 2: Write failing crash-resume idempotency test**

```python
async def test_worker_crash_after_tool_completion_does_not_repeat_tool() -> None:
    harness = DurableCodingHarness(crash_after_tool="fake_implement_2")
    task = await harness.create_task(owner_id="u1", prompt="Fix it")

    await harness.run_until_crash(task.task_id)
    await harness.resume_with_new_worker(task.task_id)

    assert harness.tool_execution_count("fake_implement_2") == 1
    assert (await harness.snapshot(task.task_id, "u1")).active_run.status == "running"
```

- [ ] **Step 3: Write failing frontend reconnect convergence test**

```typescript
test("restored checkpoint becomes live after replay", () => {
  const store = createCodingProjectionStore("ct_1");
  store.replaceSnapshot(snapshotAtSeq10);
  assert.equal(store.getSnapshot().connectionBasis, "checkpoint");

  for (const event of events11Through14) store.applyEvent(event);
  store.setConnectionBasis("live");

  assert.equal(store.getSnapshot().appliedSeq, 14);
  assert.equal(store.getSnapshot().connectionBasis, "live");
  assert.deepEqual(store.getSnapshot().phases, uninterruptedProjection.phases);
});
```

- [ ] **Step 4: Run RED**

Run: `.venv/bin/pytest -q tests/coding/test_durable_phase_vertical_slice.py`

Expected: fails because the integrated harness and runtime wiring do not exist.

Run: `corepack pnpm@10.26.1 --dir web exec tsx --test tests/source/coding-phase-reconnect.test.ts`

Expected: fails until the shared projection fixtures and convergence behavior are wired.

- [ ] **Step 5: Wire development runtime and metrics**

```python
def create_development_coding_runtime() -> CodingRuntime:
    runs = PostgresCodingRunRepository(db_manager.get_session)
    events = PostgresCodingService(
        db_manager.get_session,
        wake_outbox=coding_outbox_dispatcher.wake,
    )
    loop = FakeDurableCodingLoop(clock=lambda: datetime.now(UTC))
    coordinator = CodingRunService(
        tasks=PostgresCodingTaskRepository(db_manager.get_session),
        runs=runs,
        events=events,
        loop=loop,
        interrupter=InProcessRunInterrupter(),
    )
    return CodingRuntime(events=events, runs=coordinator)
```

Define the integration harness in the test module as a thin owner-scoped wrapper
around this runtime, never as a second implementation:

```python
class DurableCodingHarness:
    def __init__(self, *, crash_after_tool: str | None = None) -> None:
        self.runtime = create_test_coding_runtime(
            crash_after_tool=crash_after_tool
        )

    async def create_task(self, *, owner_id: str, prompt: str):
        return await self.runtime.events.create_task(
            owner_id=owner_id, prompt=prompt
        )

    async def snapshot(self, task_id: str, owner_id: str):
        return await self.runtime.snapshots.get_owned(task_id, owner_id)

    def tool_execution_count(self, tool_call_id: str) -> int:
        return self.runtime.test_probe.tool_execution_count(tool_call_id)
```

`create_test_coding_runtime` injects `InMemoryCodingRunRepository`, the regular
in-memory task/event stores, `FakeDurableCodingLoop`, and a `CrashProbe` that
raises once after persisting the configured tool result. `advance_until`,
`advance_one_safe_point`, `run_until_crash`, and `resume_with_new_worker` call
public `CodingRunService` methods; they do not mutate repositories directly.

Guard automatic fake-run startup with `settings.CODING_FAKE_LOOP_ENABLED`, default
`False`. Tests instantiate the runtime directly and never depend on process-global
background tasks.

Record phase duration at `phase.completed` or `phase.failed`, increment checkpoint
count after a committed checkpoint, observe steering latency when a request is
applied, and increment resume count with `outcome="success" | "recovery_required"`.
Labels contain phase kind and outcome only; IDs and user-controlled text are not
metric labels.

- [ ] **Step 6: Document the completed slice and deferred boundaries**

Update `docs/NEOS_CODING.md` Phase 1/2 status with:

```markdown
### Durable Phase vertical slice checkpoint

- Canonical run, phase, checkpoint, tool, and steering events: implemented
- Full REST projection snapshot and automatic browser resync: implemented
- Phase-oriented workspace and two steering actions: implemented
- Durable fake loop and crash-resume idempotency: implemented
- Real model adapter, sandbox commands, and permission execution: deferred to the next vertical slice
```

- [ ] **Step 7: Run GREEN**

Run: `.venv/bin/pytest -q tests/coding tests/api/handlers/test_coding_handlers.py tests/api/handlers/test_coding_ws_handlers.py tests/api/test_coding_production_registration.py`

Expected: all backend coding tests pass.

Run: `corepack pnpm@10.26.1 --dir web test:source`

Expected: all frontend source tests pass.

Run: `corepack pnpm@10.26.1 --dir web exec tsc --noEmit`

Expected: exit 0. Restore `web/tsconfig.tsbuildinfo` if generated.

Run: `git diff --check`

Expected: no output.

- [ ] **Step 8: Review requirements**

Confirm from test evidence that:

- five phases appear in order and phase attempts remain append-only;
- every safe point writes a durable checkpoint;
- completed tool calls do not execute twice after resume;
- safe-point steering waits for a checkpoint;
- immediate steering creates an interruption checkpoint and new run;
- foreign users cannot read or steer tasks;
- full snapshot plus replay converges with uninterrupted state;
- `resync_required` refreshes the snapshot without an infinite reconnect loop;
- checkpoint state and live state have distinct UI labels;
- no prompt, credential, task ID, or user input is used as a metric label.

- [ ] **Step 9: Commit**

```bash
git add tests/coding/test_durable_phase_vertical_slice.py web/tests/source/coding-phase-reconnect.test.ts neos/coding/runtime.py neos/observability/metrics.py docs/NEOS_CODING.md
git commit -m "test: verify durable coding phase slice"
```

---

## Follow-Up Plans

After this plan passes its reviewer gate, create separate specs and plans for:

1. Real provider-neutral model streaming and context compaction.
2. Docker/managed sandbox tool runtime and process-group interruption.
3. Deterministic permission normalization, approval execution, and audit.
4. Rich diff, terminal, file-tree, and mobile detail-panel implementations.

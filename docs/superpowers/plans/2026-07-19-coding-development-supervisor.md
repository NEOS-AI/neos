# Coding Development Supervisor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically start, resume, and finish durable fake coding tasks in development without manual run-service calls.

**Architecture:** Add fenced atomic run lifecycle commands, then build a development-only asyncio supervisor that combines post-commit task notifications with PostgreSQL reconciliation. Process-local queue and task maps reduce latency and duplicate work, while the existing execution lease remains the cross-process correctness boundary.

**Tech Stack:** Python 3.12, asyncio, FastAPI lifespan, SQLAlchemy async sessions, PostgreSQL, pytest, Prometheus client

## Global Constraints

- Activate the supervisor only when `CODING_FAKE_LOOP_ENABLED=true`.
- Do not add Celery coding workers, a cross-process wake bus, real model execution, or sandbox commands.
- Reconciliation interval is 2 seconds and discovery batch size is 100 tasks.
- Retry backoffs are exactly 1, 2, and 4 seconds.
- Graceful shutdown timeout is 10 seconds.
- `RunAlreadyLeased` is expected competition and must not be recorded as failure.
- Direct `queued -> running` is allowed only when `ensure_run_started` receives `development_mode=True`; do not relax the production domain transition table.
- All run/task lifecycle state, terminal events, and outbox rows commit atomically.
- Metric labels must remain bounded and must not contain task IDs, worker IDs, exception text, or user input.
- Preserve unrelated modified and untracked files in the existing `dev` worktree.

## File Structure

- `neos/coding/domain/durability.py` — lifecycle command result types.
- `neos/coding/loop/base.py` — repository protocol for atomic run lifecycle and discovery.
- `neos/coding/repositories/run_repository.py` — PostgreSQL lifecycle transactions and runnable-task query.
- `neos/coding/application/run_service.py` — application-level start, safe-point, completion, failure, and lease cleanup.
- `neos/coding/loop/fake.py` — phase producer that no longer appends a generic terminal event.
- `neos/coding/workers/development_supervisor.py` — focused development scheduling component.
- `neos/coding/persistence/postgres.py` — post-commit task-created notifier for the production-shaped API service.
- `neos/coding/application/task_service.py` — matching notifier behavior for the in-memory application service.
- `neos/coding/runtime.py` — optional supervisor construction and development wiring.
- `neos/main.py` — supervisor lifespan start and stop.
- `neos/observability/metrics.py` — bounded supervisor metrics.
- `tests/coding/repositories/test_run_lifecycle_repository.py` — SQL transaction contracts.
- `tests/coding/application/test_run_service.py` — lifecycle and lease cleanup behavior.
- `tests/coding/workers/test_development_supervisor.py` — supervisor unit tests.
- `tests/coding/test_development_supervisor_vertical_slice.py` — automatic execution and recovery slice.
- `tests/coding/persistence/test_postgres_service.py` — notifier post-commit behavior.
- `tests/api/test_coding_production_registration.py` — disabled-by-default production boundary.
- `docs/NEOS_CODING.md` — implementation checkpoint.

---

### Task 1: Atomic Run Start and Terminal Lifecycle Commands

**Files:**
- Modify: `neos/coding/domain/durability.py`
- Modify: `neos/coding/loop/base.py`
- Modify: `neos/coding/repositories/run_repository.py`
- Modify: `tests/coding/fakes.py`
- Create: `tests/coding/repositories/test_run_lifecycle_repository.py`

**Interfaces:**
- Consumes: `ExecutionLease`, repository event/outbox helpers, `CodingRun`, and `CodingRunStatus`.
- Produces: `RunLifecycleCommit`, `ensure_run_started`, `complete_run`, `fail_run`, and `claimable_task_ids`.

- [ ] **Step 1: Write failing lifecycle SQL contract tests**

```python
async def test_ensure_run_started_commits_task_run_event_and_outbox() -> None:
    session = FakeSession(rows=[TASK_ROW, None, (0,), (1,)])
    repository = repository_for(session)

    run = await repository.ensure_run_started(
        task_id="ct_1", instruction="Fix it", development_mode=True, now=NOW
    )

    sql = "\n".join(session.sql)
    assert "FOR UPDATE" in sql
    assert "INSERT INTO coding_runs" in sql
    assert "SET status = 'running'" in sql
    assert "INSERT INTO coding_events" in sql
    assert "INSERT INTO coding_event_outbox" in sql
    assert run.attempt == 1


async def test_ensure_run_started_returns_existing_running_run() -> None:
    session = FakeSession(rows=[TASK_ROW, RUN_ROW])
    repository = repository_for(session)

    run = await repository.ensure_run_started(
        task_id="ct_1", instruction="Fix it", development_mode=True, now=NOW
    )

    assert run.run_id == "cr_1"
    assert "INSERT INTO coding_runs" not in "\n".join(session.sql)


async def test_complete_run_is_fenced_and_atomic() -> None:
    session = FakeSession(rows=[("ct_1",), RUN_ROW, (8,), ("cr_1",)])
    repository = repository_for(session)

    committed = await repository.complete_run(lease=LEASE, now=NOW)

    sql = "\n".join(session.sql)
    assert "fencing_token = :fencing_token" in sql
    assert "SET status = 'completed'" in sql
    assert "run.completed" in sql
    assert committed.run.status is CodingRunStatus.COMPLETED


async def test_fail_run_persists_only_normalized_error_code() -> None:
    session = FakeSession(rows=[("ct_1",), RUN_ROW, (9,), ("cr_1",)])
    repository = repository_for(session)

    committed = await repository.fail_run(
        lease=LEASE, error_code="supervisor_retry_exhausted", now=NOW
    )

    assert committed.event.payload == {
        "status": "failed",
        "error_code": "supervisor_retry_exhausted",
    }
```

- [ ] **Step 2: Run the tests to verify RED**

Run:

```bash
.venv/bin/pytest -q tests/coding/repositories/test_run_lifecycle_repository.py
```

Expected: failures because the lifecycle result type and repository commands do not exist.

- [ ] **Step 3: Add the lifecycle result and protocol methods**

Add to `neos/coding/domain/durability.py`:

```python
@dataclass(frozen=True, slots=True)
class RunLifecycleCommit:
    run: CodingRun
    event: CodingEvent
```

Add to `CodingRunRepository` in `neos/coding/loop/base.py`:

```python
async def ensure_run_started(
    self,
    *,
    task_id: str,
    instruction: str,
    development_mode: bool,
    now: datetime,
) -> CodingRun:
    raise NotImplementedError

async def complete_run(
    self, *, lease: ExecutionLease, now: datetime
) -> RunLifecycleCommit:
    raise NotImplementedError

async def fail_run(
    self, *, lease: ExecutionLease, error_code: str, now: datetime
) -> RunLifecycleCommit:
    raise NotImplementedError

async def claimable_task_ids(self, *, limit: int) -> tuple[str, ...]:
    raise NotImplementedError
```

- [ ] **Step 4: Implement PostgreSQL atomic lifecycle commands**

Implement `ensure_run_started()` with one `session.begin()` transaction:

```python
task_result = await session.execute(
    text(
        """
        SELECT task_id, prompt, status
        FROM coding_tasks
        WHERE task_id = :task_id AND deleted_at IS NULL
        FOR UPDATE
        """
    ),
    {"task_id": task_id},
)
```

Return an existing running run when present. Otherwise select `MAX(attempt)`, insert one running run, update the task to `running`, allocate one sequence, and insert `run.started` plus outbox through `_insert_event_in_session()`.

Before creating a run, require `development_mode is True` when the locked task
status is `queued`. Add a failing test proving `development_mode=False` rejects
the fast path without inserting a run. Do not modify `_ALLOWED_TRANSITIONS` in
`neos/coding/domain/models.py`.

Implement terminal commands with this shared internal shape:

```python
await self._validate_lease_in_session(session, lease, now=now)
run = await self._load_run_for_update(session, lease.run_id)
seq = await self._allocate_sequence_in_session(
    session, task_id=lease.task_id, now=now
)
event = await self._insert_event_in_session(
    session,
    task_id=lease.task_id,
    seq=seq,
    event_type=event_type,
    payload=payload,
    now=now,
    run_id=lease.run_id,
)
await session.execute(
    text(
        """
        UPDATE coding_runs SET status = :status, completed_at = :now
        WHERE run_id = :run_id AND task_id = :task_id AND status = 'running'
        RETURNING run_id
        """
    ),
    params,
)
await session.execute(
    text(
        """
        UPDATE coding_tasks SET status = :status, updated_at = :now
        WHERE task_id = :task_id
        """
    ),
    params,
)
```

Reject any failed update as `StaleExecutionLease`. Call the outbox wake callback only after the transaction exits.

- [ ] **Step 5: Implement runnable discovery and in-memory parity**

Use this PostgreSQL query:

```sql
SELECT task.task_id
FROM coding_tasks task
WHERE task.deleted_at IS NULL
  AND task.status IN ('queued', 'running')
  AND NOT EXISTS (
      SELECT 1 FROM coding_runs run
      WHERE run.task_id = task.task_id
        AND run.status IN ('completed', 'cancelled', 'failed')
  )
ORDER BY task.last_activity_at, task.task_id
LIMIT :limit
```

Add equivalent lock-protected lifecycle methods and oldest-first discovery to `InMemoryCodingRunRepository`. Store task states needed by the supervisor tests without weakening the existing lease checks.

- [ ] **Step 6: Run GREEN and regression tests**

Run:

```bash
.venv/bin/pytest -q tests/coding/repositories/test_run_lifecycle_repository.py tests/coding/repositories/test_durability_repository.py tests/coding/loop/test_fake_loop.py
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add neos/coding/domain/durability.py neos/coding/loop/base.py neos/coding/repositories/run_repository.py tests/coding/fakes.py tests/coding/repositories/test_run_lifecycle_repository.py
git commit -m "feat: commit coding run lifecycle atomically"
```

---

### Task 2: Application Lifecycle Driver and Safe Exception Cleanup

**Files:**
- Modify: `neos/coding/application/run_service.py`
- Modify: `neos/coding/loop/fake.py`
- Modify: `tests/coding/application/test_run_service.py`
- Modify: `tests/coding/test_durable_phase_vertical_slice.py`

**Interfaces:**
- Consumes: Task 1 lifecycle commands and existing 30-second execution leases.
- Produces: `ensure_started(task_id)`, `fail_active_run(task_id, worker_id, error_code)`, and atomic terminal behavior from `advance_one_safe_point()`.

- [ ] **Step 1: Write failing application lifecycle tests**

```python
async def test_ensure_started_is_idempotent_and_uses_task_prompt() -> None:
    service, repository = await make_durable_run_service(prompt="Fix cache")

    first = await service.ensure_started(task_id="ct_1")
    second = await service.ensure_started(task_id="ct_1")

    assert first == second
    assert repository.ensure_started_instructions == ["Fix cache", "Fix cache"]


async def test_caught_exception_releases_lease_for_retry() -> None:
    service, repository = await make_failing_run_service()

    with pytest.raises(RuntimeError, match="transient"):
        await service.advance_one_safe_point(
            task_id="ct_1", worker_id="worker-a"
        )

    assert repository.execution_leases["ct_1"].expires_at == NOW


async def test_no_remaining_phase_completes_run_and_task_atomically() -> None:
    service, repository = await make_completed_phase_service()

    event = await service.advance_one_safe_point(
        task_id="ct_1", worker_id="worker-a"
    )

    assert event.type == "run.completed"
    assert repository.active_run.status is CodingRunStatus.COMPLETED
    assert repository.task_statuses["ct_1"] == "completed"
```

- [ ] **Step 2: Run the tests to verify RED**

Run:

```bash
.venv/bin/pytest -q tests/coding/application/test_run_service.py tests/coding/test_durable_phase_vertical_slice.py
```

Expected: failures because application lifecycle methods and atomic completion are absent.

- [ ] **Step 3: Add idempotent start and fenced failure methods**

Add to `CodingRunService`:

```python
async def ensure_started(self, *, task_id: str) -> CodingRun:
    task = await self._tasks.get(task_id)
    if task is None:
        raise CodingTaskNotFound(task_id)
    return await self._runs.ensure_run_started(
        task_id=task_id,
        instruction=task.prompt,
        development_mode=True,
        now=self._clock(),
    )

async def fail_active_run(
    self, *, task_id: str, worker_id: str, error_code: str
):
    run = await self._runs.latest_run(task_id)
    if run is None:
        raise RuntimeError(f"coding run does not exist: {task_id}")
    now = self._clock()
    lease = await self._runs.acquire_execution_lease(
        task_id=task_id,
        run_id=run.run_id,
        worker_id=worker_id,
        now=now,
        expires_at=now + timedelta(seconds=30),
    )
    if lease is None:
        raise RunAlreadyLeased(task_id)
    committed = await self._runs.fail_run(
        lease=lease, error_code=error_code, now=now
    )
    await self._release_lease(lease)
    return committed.event
```

- [ ] **Step 4: Make ordinary exceptions release the current lease**

Track whether the worker process still owns the lease. In the `except Exception` path, call `_release_lease(lease)` before re-raising. Do not translate `asyncio.CancelledError` into run failure. An actual process death does not execute this handler and therefore still leaves the lease for TTL recovery.

Use this structure:

```python
except asyncio.CancelledError:
    raise
except Exception:
    if self._metrics is not None and lease.recovered:
        self._metrics.coding_resume_total.labels(
            outcome="recovery_required"
        ).inc()
    await self._release_lease(lease)
    raise
```

- [ ] **Step 5: Remove generic terminal event append from the fake loop**

In `FakeDurableCodingLoop._run_durable()`, return after the phase iterator is exhausted instead of calling the event sink with `event_type="run.completed"`.

In `advance_one_safe_point()`, distinguish “phase event returned” from generator exhaustion. On exhaustion call:

```python
committed = await self._runs.complete_run(lease=lease, now=self._clock())
await self._release_lease(lease)
return committed.event
```

- [ ] **Step 6: Run GREEN and regression tests**

Run:

```bash
.venv/bin/pytest -q tests/coding/application/test_run_service.py tests/coding/test_durable_phase_vertical_slice.py tests/coding/loop/test_fake_loop.py tests/coding/test_durability_metrics.py
```

Expected: all tests pass, including crash recovery and normal continuation metric semantics.

- [ ] **Step 7: Commit**

```bash
git add neos/coding/application/run_service.py neos/coding/loop/fake.py tests/coding/application/test_run_service.py tests/coding/test_durable_phase_vertical_slice.py
git commit -m "feat: drive coding run lifecycle durably"
```

---

### Task 3: Development Supervisor Core

**Files:**
- Create: `neos/coding/workers/__init__.py`
- Create: `neos/coding/workers/development_supervisor.py`
- Create: `tests/coding/workers/test_development_supervisor.py`

**Interfaces:**
- Consumes: `CodingRunService.ensure_started`, `advance_one_safe_point`, `fail_active_run`, and repository `claimable_task_ids`.
- Produces: `CodingDevelopmentSupervisor.start()`, `notify(task_id)`, `wait_idle()`, `stop()`, and `is_running`.

- [ ] **Step 1: Write failing duplicate-notify and lease-competition tests**

```python
async def test_duplicate_notifications_create_one_local_runner() -> None:
    driver = BlockingDriver()
    supervisor = supervisor_for(driver)
    await supervisor.start()

    assert supervisor.notify("ct_1") is True
    assert supervisor.notify("ct_1") is False
    await driver.started.wait()

    assert driver.ensure_calls == ["ct_1"]
    await supervisor.stop()


async def test_lease_busy_is_expected_exit_without_failure() -> None:
    driver = LeaseBusyDriver()
    supervisor = supervisor_for(driver)
    await supervisor.start()
    supervisor.notify("ct_1")
    await supervisor.wait_idle()

    assert driver.fail_calls == []
    assert supervisor.outcomes == ["lease_busy"]
    await supervisor.stop()
```

- [ ] **Step 2: Write failing bounded-retry test**

```python
async def test_unexpected_error_retries_with_bounded_backoff_then_fails() -> None:
    sleeps = RecordingSleeper()
    driver = AlwaysFailingDriver()
    supervisor = supervisor_for(driver, sleep=sleeps)
    await supervisor.start()
    supervisor.notify("ct_1")
    await supervisor.wait_idle()

    assert sleeps.delays == [1.0, 2.0, 4.0]
    assert driver.advance_calls == 4
    assert driver.fail_calls == [
        ("ct_1", supervisor.worker_id, "supervisor_retry_exhausted")
    ]
    await supervisor.stop()
```

- [ ] **Step 3: Run the tests to verify RED**

Run:

```bash
.venv/bin/pytest -q tests/coding/workers/test_development_supervisor.py
```

Expected: import failure because the supervisor module does not exist.

- [ ] **Step 4: Implement the supervisor state and lifecycle**

Use constructor defaults copied from the spec:

```python
class CodingDevelopmentSupervisor:
    def __init__(
        self,
        *,
        runs,
        work_repository,
        metrics=None,
        reconciliation_interval: float = 2.0,
        discovery_batch_size: int = 100,
        retry_backoffs: tuple[float, ...] = (1.0, 2.0, 4.0),
        shutdown_timeout: float = 10.0,
        sleep=asyncio.sleep,
        worker_id: str | None = None,
    ) -> None:
        self.worker_id = worker_id or f"coding-dev-{uuid4().hex}"
        self._pending: asyncio.Queue[str] = asyncio.Queue()
        self._queued: set[str] = set()
        self._active: dict[str, asyncio.Task] = {}
        self._accepting = False
```

`start()` creates dispatcher and reconciliation tasks. `notify()` returns `False` when stopped, queued, or already active; otherwise it adds the ID to `_queued` and `_pending`.

`wait_idle()` is an awaitable synchronization helper used by tests and orderly
development shutdown. It returns when `_queued` and `_active` are both empty;
implement it with an internal `asyncio.Condition` or `asyncio.Event`, not polling
sleep.

- [ ] **Step 5: Implement dispatch, runner, and reconciliation**

The runner behavior must be exact:

```python
async def _run_task(self, task_id: str) -> None:
    await self._runs.ensure_started(task_id=task_id)
    failures = 0
    while self._accepting:
        try:
            event = await self._runs.advance_one_safe_point(
                task_id=task_id, worker_id=self.worker_id
            )
        except RunAlreadyLeased:
            self._record_outcome("lease_busy")
            return
        except StaleExecutionLease:
            self._record_stale_write()
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            if failures >= len(self._retry_backoffs):
                try:
                    await self._runs.fail_active_run(
                        task_id=task_id,
                        worker_id=self.worker_id,
                        error_code="supervisor_retry_exhausted",
                    )
                except RunAlreadyLeased:
                    self._record_outcome("lease_busy")
                    return
                self._record_outcome("failed")
                return
            delay = self._retry_backoffs[failures]
            failures += 1
            self._record_retry("unexpected")
            await self._sleep(delay)
            continue
        failures = 0
        if event is None or event.type == "run.completed":
            self._record_outcome("completed")
            return
```

Reconciliation calls `claimable_task_ids(limit=batch_size)` and passes every returned ID through `notify()`.

- [ ] **Step 6: Implement graceful stop and shutdown tests**

Add tests asserting that `notify()` returns `False` after stop begins and every tracked runner is done after `stop()`.

`stop()` must:

```python
self._accepting = False
for loop_task in self._loop_tasks:
    loop_task.cancel()
await asyncio.gather(*self._loop_tasks, return_exceptions=True)
for runner in self._active.values():
    runner.cancel()
try:
    await asyncio.wait_for(
        asyncio.gather(*self._active.values(), return_exceptions=True),
        timeout=self._shutdown_timeout,
    )
except TimeoutError:
    for runner in self._active.values():
        runner.cancel()
self._active.clear()
self._queued.clear()
```

- [ ] **Step 7: Run GREEN**

Run:

```bash
.venv/bin/pytest -q tests/coding/workers/test_development_supervisor.py
```

Expected: all supervisor unit tests pass without real sleeps or database access.

- [ ] **Step 8: Commit**

```bash
git add neos/coding/workers/__init__.py neos/coding/workers/development_supervisor.py tests/coding/workers/test_development_supervisor.py
git commit -m "feat: add coding development supervisor"
```

---

### Task 4: Post-Commit Task Notification

**Files:**
- Modify: `neos/coding/application/task_service.py`
- Modify: `neos/coding/persistence/postgres.py`
- Modify: `tests/coding/application/test_task_service.py`
- Modify: `tests/coding/persistence/test_postgres_service.py`

**Interfaces:**
- Consumes: `Callable[[str], bool | None]` supervisor notification callback.
- Produces: `set_task_created_notifier()` on both task creation service implementations.

- [ ] **Step 1: Write failing post-commit notifier tests**

```python
async def test_task_service_notifies_only_after_event_commit() -> None:
    calls = []
    service = CodingTaskService(tasks, events, clock=lambda: NOW)
    service.set_task_created_notifier(calls.append)

    task = await service.create_task(owner_id="u1", prompt="Fix it")

    assert calls == [task.task_id]
    assert (await events.list_after(task.task_id))[0].type == "task.created"


async def test_postgres_notifier_runs_after_transaction_exit() -> None:
    order = []
    session = OrderedFakeSession(order)
    service = postgres_service_for(session)
    service.set_task_created_notifier(lambda task_id: order.append("notify"))

    await service.create_task(owner_id="u1", prompt="Fix it")

    assert order.index("transaction.exit") < order.index("notify")


async def test_notifier_failure_does_not_rollback_created_task() -> None:
    service.set_task_created_notifier(
        lambda task_id: (_ for _ in ()).throw(RuntimeError("wake failed"))
    )
    task = await service.create_task(owner_id="u1", prompt="Fix it")
    assert task.task_id
```

- [ ] **Step 2: Run the tests to verify RED**

Run:

```bash
.venv/bin/pytest -q tests/coding/application/test_task_service.py tests/coding/persistence/test_postgres_service.py
```

Expected: failures because the notifier setter is missing.

- [ ] **Step 3: Implement matching notifier contracts**

In both services add:

```python
def set_task_created_notifier(
    self, notifier: Callable[[str], bool | None] | None
) -> None:
    self._task_created_notifier = notifier

def _notify_task_created(self, task_id: str) -> None:
    if self._task_created_notifier is None:
        return
    try:
        self._task_created_notifier(task_id)
    except Exception:
        logger.exception("Coding task wake notification failed", extra={"task_id": task_id})
```

Initialize the callback to `None`. Call `_notify_task_created(task.task_id)` only after persistence and outbox wake handling have completed.

- [ ] **Step 4: Run GREEN**

Run:

```bash
.venv/bin/pytest -q tests/coding/application/test_task_service.py tests/coding/persistence/test_postgres_service.py
```

Expected: all tests pass and notifier exceptions do not affect task creation.

- [ ] **Step 5: Commit**

```bash
git add neos/coding/application/task_service.py neos/coding/persistence/postgres.py tests/coding/application/test_task_service.py tests/coding/persistence/test_postgres_service.py
git commit -m "feat: notify coding supervisor after task commit"
```

---

### Task 5: Runtime and FastAPI Lifespan Wiring

**Files:**
- Modify: `neos/coding/runtime.py`
- Modify: `neos/main.py`
- Modify: `neos/config/settings.py`
- Create: `tests/coding/test_development_supervisor_vertical_slice.py`
- Modify: `tests/api/test_coding_production_registration.py`

**Interfaces:**
- Consumes: Tasks 1–4 supervisor, discovery, lifecycle, and notifier contracts.
- Produces: optional `CodingRuntime.supervisor`, development-only automatic execution, and graceful application shutdown.

- [ ] **Step 1: Write failing runtime activation tests**

```python
def test_runtime_creates_supervisor_only_with_fake_loop_enabled(monkeypatch) -> None:
    monkeypatch.setattr(settings, "CODING_FAKE_LOOP_ENABLED", True)
    runtime = create_development_coding_runtime()
    assert isinstance(runtime.supervisor, CodingDevelopmentSupervisor)

    monkeypatch.setattr(settings, "CODING_FAKE_LOOP_ENABLED", False)
    runtime = create_development_coding_runtime()
    assert runtime.supervisor is None


def test_production_registration_does_not_start_development_supervisor() -> None:
    assert coding_runtime.supervisor is None
```

- [ ] **Step 2: Write failing automatic execution vertical slice**

```python
async def test_created_task_runs_to_first_checkpoint_without_manual_driver() -> None:
    harness = DevelopmentSupervisorHarness()
    await harness.start()

    task = await harness.tasks.create_task(owner_id="u1", prompt="Fix it")
    await harness.wait_for_checkpoint(task.task_id)

    assert harness.repository.active_run.task_id == task.task_id
    assert harness.repository.checkpoints[0].loop_state["current_instruction"] == "Fix it"
    await harness.stop()


async def test_replacement_supervisor_rediscovers_unfinished_task() -> None:
    harness = DevelopmentSupervisorHarness(stop_after_phase="understand")
    task = await harness.tasks.create_task(owner_id="u1", prompt="Fix it")
    await harness.stop_first_supervisor()

    await harness.start_replacement_supervisor()
    await harness.wait_for_phase(task.task_id, "plan")

    assert harness.completed_phase_count("understand", attempt=1) == 1
    assert harness.completed_phase_count("plan", attempt=1) == 1
```

- [ ] **Step 3: Run the tests to verify RED**

Run:

```bash
.venv/bin/pytest -q tests/coding/test_development_supervisor_vertical_slice.py tests/api/test_coding_production_registration.py
```

Expected: failures because runtime and lifespan do not expose or start a supervisor.

- [ ] **Step 4: Add explicit development settings**

Add environment-backed settings in `neos/config/settings.py`:

```python
CODING_DEV_RECONCILIATION_SECONDS = float(
    os.getenv("CODING_DEV_RECONCILIATION_SECONDS", "2")
)
CODING_DEV_DISCOVERY_BATCH_SIZE = int(
    os.getenv("CODING_DEV_DISCOVERY_BATCH_SIZE", "100")
)
CODING_DEV_SHUTDOWN_SECONDS = float(
    os.getenv("CODING_DEV_SHUTDOWN_SECONDS", "10")
)
```

Validate positive values when constructing the supervisor; invalid values fail startup rather than silently disabling recovery.

- [ ] **Step 5: Wire optional supervisor into `CodingRuntime`**

Change the dataclass:

```python
@dataclass(frozen=True, slots=True)
class CodingRuntime:
    events: Any
    runs: CodingRunService
    snapshots: CodingSnapshotService
    supervisor: CodingDevelopmentSupervisor | None = None
```

In `create_development_coding_runtime()`, create the supervisor only when the fake loop exists. Pass the run service and PostgreSQL run repository, then register `supervisor.notify` through `coding_service.set_task_created_notifier(supervisor.notify)`.

- [ ] **Step 6: Add lifespan start and stop**

After database and coding transport initialization in `neos/main.py`:

```python
if coding_runtime.supervisor is not None:
    await coding_runtime.supervisor.start()
    logger.info("Coding development supervisor started")
```

Before coding transport and database shutdown:

```python
if coding_runtime.supervisor is not None:
    await coding_runtime.supervisor.stop()
    logger.info("Coding development supervisor stopped")
```

Do not add the supervisor coroutine to the generic `background_tasks` cancellation list; its `stop()` method owns its graceful ordering.

- [ ] **Step 7: Run GREEN and API regression**

Run:

```bash
.venv/bin/pytest -q tests/coding/test_development_supervisor_vertical_slice.py tests/api/test_coding_production_registration.py tests/api/handlers/test_coding_handlers.py tests/api/handlers/test_coding_ws_handlers.py
```

Expected: automatic development execution passes, supervisor remains disabled by default, and API/WS behavior is unchanged.

- [ ] **Step 8: Commit**

```bash
git add neos/coding/runtime.py neos/main.py neos/config/settings.py tests/coding/test_development_supervisor_vertical_slice.py tests/api/test_coding_production_registration.py
git commit -m "feat: start coding tasks automatically in development"
```

---

### Task 6: Metrics, PostgreSQL Proof, Documentation, and Full Verification

**Files:**
- Modify: `neos/observability/metrics.py`
- Modify: `tests/coding/test_durability_metrics.py`
- Modify: `tests/coding/integration/test_postgres_durability.py`
- Modify: `docs/NEOS_CODING.md`

**Interfaces:**
- Consumes: completed supervisor and lifecycle implementation.
- Produces: bounded supervisor observability, opt-in PostgreSQL lifecycle proof, and an updated implementation checkpoint.

- [ ] **Step 1: Write failing bounded metric-label test**

```python
def test_supervisor_metrics_use_only_bounded_labels() -> None:
    collector = EnterpriseMetricsCollector(CollectorRegistry())

    assert collector.coding_supervisor_tasks_total._labelnames == ("outcome",)
    assert collector.coding_supervisor_retry_total._labelnames == ("reason",)
    assert collector.coding_supervisor_active_tasks._labelnames == ()
```

- [ ] **Step 2: Add supervisor metrics**

```python
self.coding_supervisor_tasks_total = Counter(
    "coding_supervisor_tasks_total",
    "Development coding supervisor task outcomes",
    ["outcome"],
    registry=self.registry,
)
self.coding_supervisor_retry_total = Counter(
    "coding_supervisor_retry_total",
    "Development coding supervisor retries",
    ["reason"],
    registry=self.registry,
)
self.coding_supervisor_active_tasks = Gauge(
    "coding_supervisor_active_tasks",
    "Active development coding supervisor tasks",
    registry=self.registry,
)
```

Allowed outcomes are `started`, `completed`, `failed`, and `lease_busy`. Allowed retry reason is `unexpected`. No identifiers or exception strings may become labels.

- [ ] **Step 3: Add opt-in PostgreSQL lifecycle tests**

Extend `tests/coding/integration/test_postgres_durability.py` with:

```python
@pytest.mark.integration
async def test_concurrent_start_creates_one_canonical_run(runtime) -> None:
    task = await runtime.seed_task()
    first, second = await asyncio.gather(
        runtime.repository.ensure_run_started(
            task_id=task.task_id,
            instruction=task.prompt,
            development_mode=True,
            now=NOW,
        ),
        runtime.repository.ensure_run_started(
            task_id=task.task_id,
            instruction=task.prompt,
            development_mode=True,
            now=NOW,
        ),
    )
    assert first.run_id == second.run_id
    assert await runtime.count("coding_runs", task_id=task.task_id) == 1
    assert await runtime.count_events(task.task_id, "run.started") == 1
```

Add an injected `BEFORE INSERT` failure for `run.completed` and assert run status, task status, event count, and outbox count all remain at their pre-call baselines.

- [ ] **Step 4: Update implementation checkpoint**

Append to `docs/NEOS_CODING.md`:

```markdown
- Development supervisor notification + PostgreSQL reconciliation: 구현 완료
- Automatic fake-loop task startup and restart recovery: 구현 완료
- Atomic run/task start, completion, and failure lifecycle: 구현 완료
- Production Celery coding worker and cross-process wake bus: 다음 vertical slice로 이관
```

- [ ] **Step 5: Run focused and full verification**

Run:

```bash
.venv/bin/pytest -q tests/coding/workers tests/coding/application/test_run_service.py tests/coding/test_development_supervisor_vertical_slice.py tests/coding/test_durability_metrics.py
```

Expected: all focused tests pass.

Run:

```bash
.venv/bin/pytest -q tests/coding tests/api/handlers/test_coding_handlers.py tests/api/handlers/test_coding_ws_handlers.py tests/api/test_coding_production_registration.py
```

Expected: all backend coding and API/WS regression tests pass. PostgreSQL integration tests may skip only when `CODING_TEST_DATABASE_URL` is absent.

Run:

```bash
CODING_TEST_DATABASE_URL=postgresql+asyncpg://neos:neos@localhost:5432/neos_test .venv/bin/pytest -q -m integration tests/coding/integration/test_postgres_durability.py
```

Expected: all PostgreSQL lifecycle, rollback, lease, and steering tests pass in CI or a prepared local database.

- [ ] **Step 6: Run static checks**

Run:

```bash
.venv/bin/python -m compileall -q neos/coding tests/coding
git diff --check
```

Expected: both commands exit zero with no diff errors.

- [ ] **Step 7: Commit**

```bash
git add neos/observability/metrics.py tests/coding/test_durability_metrics.py tests/coding/integration/test_postgres_durability.py docs/NEOS_CODING.md
git commit -m "test: verify coding development supervisor"
```

---

## Execution Notes

- Execute inline on the current `dev` branch only if the user chooses inline execution again; otherwise use an isolated worktree.
- Follow the repository's sequential tool execution protocol for every command.
- Use test-driven development for each task and preserve RED/GREEN evidence.
- Review task boundaries after every commit; do not fold production Celery work into this plan.

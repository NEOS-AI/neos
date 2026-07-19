# Coding Production Celery Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute durable fake-loop coding tasks on a dedicated production Celery queue with post-commit dispatch, PostgreSQL reconciliation, duplicate-delivery safety, and worker-loss recovery.

**Architecture:** Extract the development supervisor's bounded task-driving policy into a broker-neutral async runner. The API publishes task IDs through a dispatcher port after commit, Celery workers construct process-safe coding runtimes and drive the shared runner, and Celery Beat republishes claimable PostgreSQL tasks to recover enqueue gaps. Delivery is at-least-once; canonical runs, execution leases, fencing tokens, checkpoints, and tool claims make effects safe.

**Tech Stack:** Python 3.12, asyncio, Celery/Kombu, SQLAlchemy async, PostgreSQL, Prometheus, pytest/pytest-asyncio.

## Global Constraints

- Keep `FakeDurableCodingLoop` as the only production worker loop in this slice; real model and sandbox adapters are out of scope.
- Use a dedicated `coding` Celery queue with late acknowledgement, worker-loss rejection, and effective prefetch one.
- Post-commit enqueue failure must never roll back or delete the durable coding task.
- Reconciliation must query PostgreSQL in bounded oldest-first batches and may deliberately redeliver duplicates.
- Never enable `CODING_FAKE_LOOP_ENABLED` and `CODING_CELERY_ENABLED` together; startup must fail.
- Metric labels must use bounded enums only. Task, run, delivery, worker IDs, prompts, and exception strings must not be labels.
- Celery result payloads contain only `task_id` and a bounded outcome; never include prompts, exception strings, transcripts, or tool results.
- Preserve the repository root `AGENTS.md` sequential tool protocol and existing unrelated `.env.template`/untracked changes.

---

## File Map

### New files

- `neos/coding/workers/execution.py` — broker-neutral bounded execution policy and outcome enum.
- `neos/coding/workers/dispatcher.py` — dispatcher protocol, Celery adapter, and bounded dispatch source.
- `neos/coding/workers/celery_runtime.py` — per-delivery database/runtime construction and teardown.
- `neos/coding/workers/celery_tasks.py` — Celery execution and reconciliation entrypoints.
- `tests/coding/workers/test_execution.py` — shared runner unit tests.
- `tests/coding/workers/test_dispatcher.py` — queue publication and metric tests.
- `tests/coding/workers/test_celery_tasks.py` — Celery entrypoint/retry/reconciliation tests.
- `tests/coding/test_celery_worker_vertical_slice.py` — eager-mode automatic execution and duplicate/resume proof.

### Modified files

- `neos/coding/workers/development_supervisor.py` — delegate task driving to the shared runner.
- `neos/coding/workers/__init__.py` — export stable worker interfaces.
- `neos/coding/application/task_service.py` — retain callback compatibility; no Celery import.
- `neos/coding/persistence/postgres.py` — retain post-commit callback compatibility; no Celery import.
- `neos/coding/runtime.py` — choose local supervisor, Celery dispatcher, or neither.
- `neos/workflow/celery_app.py` — register coding task routes, queue, and Beat schedule.
- `neos/config/settings.py` — explicit Celery coding settings.
- `neos/observability/metrics.py` — bounded worker/dispatch/reconciliation metrics.
- `tests/coding/test_durability_metrics.py` — metric-label contracts.
- `tests/api/test_coding_production_registration.py` — activation conflict and production registration.
- `tests/coding/integration/test_postgres_durability.py` — opt-in canonical-run/redelivery proof where applicable.
- `docs/NEOS_CODING.md` — implementation checkpoint and next slice.

---

### Task 1: Extract the Broker-Neutral Coding Task Runner

**Files:**
- Create: `neos/coding/workers/execution.py`
- Create: `tests/coding/workers/test_execution.py`
- Modify: `neos/coding/workers/development_supervisor.py`
- Modify: `tests/coding/workers/test_development_supervisor.py`

**Interfaces:**
- Consumes: `CodingRunService.ensure_started`, `advance_one_safe_point`, `fail_active_run`; `RunAlreadyLeased`; `StaleExecutionLease`.
- Produces: `CodingTaskOutcome`, `CodingTaskExecutionPolicy`, and `CodingTaskRunner.run(task_id, worker_id, failure_error_code, keep_running)`. The runner accepts broker-neutral `propagate_exceptions` so infrastructure errors can escape to Celery.

- [ ] **Step 1: Write failing shared-runner outcome and retry tests**

Create `tests/coding/workers/test_execution.py` with focused fakes and these contracts:

```python
import asyncio
from types import SimpleNamespace

import pytest

from neos.coding.domain.durability import RunAlreadyLeased, StaleExecutionLease
from neos.coding.workers.execution import (
    CodingTaskExecutionPolicy,
    CodingTaskOutcome,
    CodingTaskRunner,
)


class RecordingRuns:
    def __init__(self, effects):
        self.effects = list(effects)
        self.ensure_calls = []
        self.advance_calls = []
        self.fail_calls = []

    async def ensure_started(self, *, task_id):
        self.ensure_calls.append(task_id)

    async def advance_one_safe_point(self, *, task_id, worker_id):
        self.advance_calls.append((task_id, worker_id))
        effect = self.effects.pop(0)
        if isinstance(effect, BaseException):
            raise effect
        return effect

    async def fail_active_run(self, *, task_id, worker_id, error_code):
        self.fail_calls.append((task_id, worker_id, error_code))


async def test_runner_returns_completed_for_terminal_event():
    runs = RecordingRuns([SimpleNamespace(type="run.completed")])
    runner = CodingTaskRunner(runs=runs)
    outcome = await runner.run(
        task_id="ct_1",
        worker_id="worker-1",
        failure_error_code="worker_retry_exhausted",
    )
    assert outcome is CodingTaskOutcome.COMPLETED
    assert runs.ensure_calls == ["ct_1"]


async def test_runner_treats_lease_contention_and_stale_as_bounded_outcomes():
    busy = CodingTaskRunner(runs=RecordingRuns([RunAlreadyLeased("ct_1")]))
    stale = CodingTaskRunner(runs=RecordingRuns([StaleExecutionLease("ct_1")]))
    assert await busy.run(
        task_id="ct_1", worker_id="w1", failure_error_code="worker_retry_exhausted"
    ) is CodingTaskOutcome.LEASE_BUSY
    assert await stale.run(
        task_id="ct_1", worker_id="w2", failure_error_code="worker_retry_exhausted"
    ) is CodingTaskOutcome.STALE


async def test_runner_retries_1_2_4_then_fails_atomically():
    delays = []
    runs = RecordingRuns([RuntimeError("x")] * 4)
    runner = CodingTaskRunner(
        runs=runs,
        policy=CodingTaskExecutionPolicy(retry_backoffs=(1.0, 2.0, 4.0)),
        sleep=lambda delay: delays.append(delay) or asyncio.sleep(0),
    )
    outcome = await runner.run(
        task_id="ct_1",
        worker_id="worker-1",
        failure_error_code="worker_retry_exhausted",
    )
    assert outcome is CodingTaskOutcome.FAILED
    assert delays == [1.0, 2.0, 4.0]
    assert runs.fail_calls == [
        ("ct_1", "worker-1", "worker_retry_exhausted")
    ]


async def test_runner_propagates_configured_infrastructure_exception():
    runs = RecordingRuns([ConnectionError("database unavailable")])
    runner = CodingTaskRunner(
        runs=runs, propagate_exceptions=(ConnectionError,)
    )
    with pytest.raises(ConnectionError, match="database unavailable"):
        await runner.run(
            task_id="ct_1",
            worker_id="worker-1",
            failure_error_code="worker_retry_exhausted",
        )
    assert runs.fail_calls == []
```

- [ ] **Step 2: Run the new tests to verify RED**

Run:

```bash
.venv/bin/pytest -q -p no:logging --tb=short tests/coding/workers/test_execution.py
```

Expected: collection fails because `neos.coding.workers.execution` does not exist.

- [ ] **Step 3: Implement the outcome, policy, and shared runner**

Create `neos/coding/workers/execution.py`:

```python
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from neos.coding.domain.durability import RunAlreadyLeased, StaleExecutionLease


class CodingTaskOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    LEASE_BUSY = "lease_busy"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class CodingTaskExecutionPolicy:
    retry_backoffs: tuple[float, ...] = (1.0, 2.0, 4.0)

    def __post_init__(self) -> None:
        if any(delay < 0 for delay in self.retry_backoffs):
            raise ValueError("retry_backoffs cannot contain negative values")


class CodingTaskRunner:
    def __init__(
        self,
        *,
        runs: Any,
        policy: CodingTaskExecutionPolicy | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        on_retry: Callable[[str], None] | None = None,
        propagate_exceptions: tuple[type[BaseException], ...] = (),
    ) -> None:
        self._runs = runs
        self._policy = policy or CodingTaskExecutionPolicy()
        self._sleep = sleep
        self._on_retry = on_retry
        self._propagate_exceptions = propagate_exceptions

    async def run(
        self,
        *,
        task_id: str,
        worker_id: str,
        failure_error_code: str,
        keep_running: Callable[[], bool] = lambda: True,
    ) -> CodingTaskOutcome:
        await self._runs.ensure_started(task_id=task_id)
        failures = 0
        while keep_running():
            try:
                event = await self._runs.advance_one_safe_point(
                    task_id=task_id, worker_id=worker_id
                )
            except RunAlreadyLeased:
                return CodingTaskOutcome.LEASE_BUSY
            except StaleExecutionLease:
                return CodingTaskOutcome.STALE
            except asyncio.CancelledError:
                raise
            except BaseException as exc:
                if isinstance(exc, self._propagate_exceptions):
                    raise
                if not isinstance(exc, Exception):
                    raise
                if failures >= len(self._policy.retry_backoffs):
                    try:
                        await self._runs.fail_active_run(
                            task_id=task_id,
                            worker_id=worker_id,
                            error_code=failure_error_code,
                        )
                    except RunAlreadyLeased:
                        return CodingTaskOutcome.LEASE_BUSY
                    return CodingTaskOutcome.FAILED
                delay = self._policy.retry_backoffs[failures]
                failures += 1
                if self._on_retry is not None:
                    self._on_retry("unexpected")
                await self._sleep(delay)
                continue
            failures = 0
            if event is None or event.type == "run.completed":
                return CodingTaskOutcome.COMPLETED
        raise asyncio.CancelledError
```

- [ ] **Step 4: Refactor the development supervisor to delegate task driving**

Construct `CodingTaskRunner` in the supervisor and replace `_run_task` with:

```python
async def _run_task(self, task_id: str) -> None:
    outcome = await self._runner.run(
        task_id=task_id,
        worker_id=self.worker_id,
        failure_error_code="supervisor_retry_exhausted",
        keep_running=lambda: self._accepting,
    )
    if outcome is CodingTaskOutcome.STALE:
        self._record_stale_write()
        return
    self._record_outcome(outcome.value)
```

Pass `on_retry=self._record_retry`, preserve the current queue/idle/graceful-stop behavior, and remove duplicated exception/retry code and unused durability imports.

- [ ] **Step 5: Run shared runner and supervisor GREEN**

Run:

```bash
.venv/bin/pytest -q -p no:logging --tb=short \
  tests/coding/workers/test_execution.py \
  tests/coding/workers/test_development_supervisor.py \
  tests/coding/test_development_supervisor_vertical_slice.py
```

Expected: all tests pass; existing supervisor outcomes and retry delays remain unchanged.

- [ ] **Step 6: Commit the shared execution policy**

```bash
git add neos/coding/workers/execution.py neos/coding/workers/development_supervisor.py tests/coding/workers/test_execution.py tests/coding/workers/test_development_supervisor.py
git commit -m "refactor: share coding task execution policy"
```

---

### Task 2: Add the Dispatcher Port and Celery Adapter

**Files:**
- Create: `neos/coding/workers/dispatcher.py`
- Create: `tests/coding/workers/test_dispatcher.py`
- Modify: `neos/coding/workers/__init__.py`

**Interfaces:**
- Consumes: Celery application's `send_task` API and setting `CODING_CELERY_QUEUE`.
- Produces: `CodingDispatchSource`, `CodingTaskDispatcher.enqueue(task_id, source)`, and `CeleryCodingTaskDispatcher`.

- [ ] **Step 1: Write failing dispatcher tests**

Create `tests/coding/workers/test_dispatcher.py`:

```python
from neos.coding.workers.dispatcher import (
    CeleryCodingTaskDispatcher,
    CodingDispatchSource,
)


class RecordingCeleryApp:
    def __init__(self):
        self.calls = []

    def send_task(self, name, *, args, queue):
        self.calls.append((name, args, queue))
        return type("Result", (), {"id": "delivery-1"})()


def test_dispatcher_publishes_only_task_identity_to_coding_queue():
    app = RecordingCeleryApp()
    dispatcher = CeleryCodingTaskDispatcher(app=app, queue="coding")
    delivery_id = dispatcher.enqueue(
        "ct_1", source=CodingDispatchSource.API
    )
    assert delivery_id == "delivery-1"
    assert app.calls == [
        ("neos.coding.workers.celery_tasks.execute_coding_task", ["ct_1"], "coding")
    ]


def test_dispatch_source_is_a_bounded_enum():
    assert {item.value for item in CodingDispatchSource} == {
        "api", "reconciliation"
    }
```

- [ ] **Step 2: Run RED**

Run:

```bash
.venv/bin/pytest -q -p no:logging --tb=short tests/coding/workers/test_dispatcher.py
```

Expected: import failure because the dispatcher module is absent.

- [ ] **Step 3: Implement the dispatcher boundary**

Create `neos/coding/workers/dispatcher.py`:

```python
from enum import StrEnum
from typing import Any, Protocol


EXECUTE_CODING_TASK = "neos.coding.workers.celery_tasks.execute_coding_task"


class CodingDispatchSource(StrEnum):
    API = "api"
    RECONCILIATION = "reconciliation"


class CodingTaskDispatcher(Protocol):
    def enqueue(self, task_id: str, *, source: CodingDispatchSource) -> str: ...


class CeleryCodingTaskDispatcher:
    def __init__(self, *, app: Any, queue: str, metrics: Any | None = None) -> None:
        if not queue.strip():
            raise ValueError("coding Celery queue cannot be empty")
        self._app = app
        self._queue = queue
        self._metrics = metrics

    def enqueue(self, task_id: str, *, source: CodingDispatchSource) -> str:
        try:
            result = self._app.send_task(
                EXECUTE_CODING_TASK, args=[task_id], queue=self._queue
            )
        except Exception:
            self._record(source, "failed")
            raise
        self._record(source, "enqueued")
        return str(result.id)

    def _record(self, source: CodingDispatchSource, outcome: str) -> None:
        metric = getattr(self._metrics, "coding_dispatch_total", None)
        if metric is not None:
            metric.labels(source=source.value, outcome=outcome).inc()
```

Export the three public dispatcher types from `neos/coding/workers/__init__.py`.

- [ ] **Step 4: Add failure/metric tests and run GREEN**

Add a fake app whose `send_task` raises `ConnectionError("broker down")` and a recording metric. Assert the exception propagates to the post-commit notifier boundary and the only recorded labels are `source="api", outcome="failed"`.

Run:

```bash
.venv/bin/pytest -q -p no:logging --tb=short tests/coding/workers/test_dispatcher.py
```

Expected: all dispatcher tests pass.

- [ ] **Step 5: Commit the dispatcher port**

```bash
git add neos/coding/workers/dispatcher.py neos/coding/workers/__init__.py tests/coding/workers/test_dispatcher.py
git commit -m "feat: add coding celery dispatcher"
```

---

### Task 3: Build a Process-Safe Celery Worker Runtime

**Files:**
- Create: `neos/coding/workers/celery_runtime.py`
- Create: `tests/coding/workers/test_celery_runtime.py`

**Interfaces:**
- Consumes: `DatabaseManager`, `PostgresCodingService`, `CodingTaskRepository`, `PostgresCodingRunRepository`, `FakeDurableCodingLoop`, `CodingTaskRunner`.
- Produces: `run_coding_delivery(task_id, worker_id, database_manager=None) -> CodingTaskOutcome` and `discover_coding_tasks(limit, database_manager=None) -> tuple[str, ...]`.

- [ ] **Step 1: Write failing lifecycle tests with injected database manager**

Create `tests/coding/workers/test_celery_runtime.py` using injected fakes:

```python
async def test_delivery_initializes_and_closes_its_database_manager(monkeypatch):
    manager = RecordingDatabaseManager()
    runner = RecordingRunner(CodingTaskOutcome.COMPLETED)
    monkeypatch.setattr(celery_runtime, "_build_runner", lambda manager: runner)

    outcome = await celery_runtime.run_coding_delivery(
        task_id="ct_1", worker_id="celery-1", database_manager=manager
    )

    assert outcome is CodingTaskOutcome.COMPLETED
    assert manager.calls == ["initialize", "close"]
    assert runner.calls == [
        ("ct_1", "celery-1", "worker_retry_exhausted")
    ]


async def test_discovery_closes_manager_when_repository_raises(monkeypatch):
    manager = RecordingDatabaseManager()
    monkeypatch.setattr(
        celery_runtime,
        "_build_run_repository",
        lambda manager: RaisingDiscoveryRepository(),
    )
    with pytest.raises(ConnectionError, match="database unavailable"):
        await celery_runtime.discover_coding_tasks(
            limit=100, database_manager=manager
        )
    assert manager.calls == ["initialize", "close"]
```

The fake manager implements async `initialize()` and `close()`. The recording
runner captures the exact task, worker, and failure code.

- [ ] **Step 2: Run RED**

Run:

```bash
.venv/bin/pytest -q -p no:logging --tb=short tests/coding/workers/test_celery_runtime.py
```

Expected: import failure because `celery_runtime` does not exist.

- [ ] **Step 3: Implement per-delivery runtime construction**

Create `neos/coding/workers/celery_runtime.py`. Do not import or reuse the API
process global `db_manager` or `coding_runtime`:

```python
from datetime import UTC, datetime

from neos.coding.application.run_service import CodingRunService, InProcessRunInterrupter
from neos.coding.loop.fake import FakeDurableCodingLoop
from neos.coding.persistence.postgres import PostgresCodingService
from neos.coding.repositories.run_repository import PostgresCodingRunRepository
from neos.coding.repositories.task_repository import CodingTaskRepository
from neos.coding.workers.execution import CodingTaskOutcome, CodingTaskRunner
from celery.exceptions import SoftTimeLimitExceeded
from neos.database.connection import DatabaseManager
from neos.observability.metrics import metrics
from sqlalchemy.exc import SQLAlchemyError


def _build_run_repository(manager: DatabaseManager):
    return PostgresCodingRunRepository(manager.get_session)


def _build_runner(manager: DatabaseManager) -> CodingTaskRunner:
    repository = _build_run_repository(manager)
    runs = CodingRunService(
        tasks=CodingTaskRepository(manager),
        runs=repository,
        events=PostgresCodingService(manager.get_session),
        loop=FakeDurableCodingLoop(clock=lambda: datetime.now(UTC)),
        metrics=metrics,
        interrupter=InProcessRunInterrupter(),
    )
    return CodingTaskRunner(
        runs=runs,
        propagate_exceptions=(
            ConnectionError,
            OSError,
            SQLAlchemyError,
            SoftTimeLimitExceeded,
        ),
    )


async def run_coding_delivery(
    *, task_id: str, worker_id: str, database_manager: DatabaseManager | None = None
) -> CodingTaskOutcome:
    manager = database_manager or DatabaseManager()
    await manager.initialize()
    try:
        return await _build_runner(manager).run(
            task_id=task_id,
            worker_id=worker_id,
            failure_error_code="worker_retry_exhausted",
        )
    finally:
        await manager.close()


async def discover_coding_tasks(
    *, limit: int, database_manager: DatabaseManager | None = None
) -> tuple[str, ...]:
    manager = database_manager or DatabaseManager()
    await manager.initialize()
    try:
        return tuple(await _build_run_repository(manager).claimable_task_ids(limit=limit))
    finally:
        await manager.close()
```

- [ ] **Step 4: Run runtime GREEN**

Run:

```bash
.venv/bin/pytest -q -p no:logging --tb=short tests/coding/workers/test_celery_runtime.py
```

Expected: all lifecycle and cleanup tests pass without accessing a real DB.

- [ ] **Step 5: Commit the worker runtime**

```bash
git add neos/coding/workers/celery_runtime.py tests/coding/workers/test_celery_runtime.py
git commit -m "feat: build coding celery worker runtime"
```

---

### Task 4: Add Celery Execution and Reconciliation Tasks

**Files:**
- Create: `neos/coding/workers/celery_tasks.py`
- Create: `tests/coding/workers/test_celery_tasks.py`
- Modify: `neos/workflow/celery_app.py`
- Modify: `neos/config/settings.py`

**Interfaces:**
- Consumes: `run_coding_delivery`, `discover_coding_tasks`, `CeleryCodingTaskDispatcher`, settings, Celery `SoftTimeLimitExceeded`.
- Produces: registered tasks `execute_coding_task(task_id)` and `reconcile_coding_tasks()`.

- [ ] **Step 1: Write failing task-registration and bounded-result tests**

Create `tests/coding/workers/test_celery_tasks.py`:

```python
from neos.coding.workers import celery_tasks
from neos.coding.workers.execution import CodingTaskOutcome


def test_execute_task_is_registered_with_coding_limits():
    assert celery_tasks.execute_coding_task.name == (
        "neos.coding.workers.celery_tasks.execute_coding_task"
    )
    assert celery_tasks.execute_coding_task.acks_late is True
    assert celery_tasks.execute_coding_task.reject_on_worker_lost is True


def test_execute_task_returns_only_bounded_identity_and_outcome(monkeypatch):
    async def run(**kwargs):
        return CodingTaskOutcome.COMPLETED

    monkeypatch.setattr(celery_tasks, "run_coding_delivery", run)
    result = celery_tasks.execute_coding_task.run("ct_1")
    assert result == {"task_id": "ct_1", "outcome": "completed"}
```

- [ ] **Step 2: Write failing infrastructure retry and reconciliation tests**

Use a fake bound request with `id="delivery-1"`, `retries=0`, and monkeypatch
`execute_coding_task.retry` to capture `countdown`. Assert a `ConnectionError`
from `run_coding_delivery` requests retry after 5 seconds. For reconciliation,
monkeypatch `discover_coding_tasks` to return `("ct_1", "ct_2")` and assert the
dispatcher enqueues both with `CodingDispatchSource.RECONCILIATION` and returns
`{"discovered": 2, "enqueued": 2, "failed": 0}`.

- [ ] **Step 3: Run RED**

Run:

```bash
.venv/bin/pytest -q -p no:logging --tb=short tests/coding/workers/test_celery_tasks.py
```

Expected: import failure because the task module does not exist.

- [ ] **Step 4: Add the environment-backed settings consumed by the tasks**

Add to `CONSTANT_SETTINGS` in `neos/config/settings.py`:

```python
"CODING_CELERY_ENABLED": os.getenv("CODING_CELERY_ENABLED", "false").lower()
in {"1", "true", "yes", "on"},
"CODING_CELERY_QUEUE": os.getenv("CODING_CELERY_QUEUE", "coding"),
"CODING_CELERY_RECONCILIATION_SECONDS": float(
    os.getenv("CODING_CELERY_RECONCILIATION_SECONDS", "10")
),
"CODING_CELERY_DISCOVERY_BATCH_SIZE": int(
    os.getenv("CODING_CELERY_DISCOVERY_BATCH_SIZE", "100")
),
"CODING_CELERY_SOFT_TIME_LIMIT_SECONDS": int(
    os.getenv("CODING_CELERY_SOFT_TIME_LIMIT_SECONDS", "300")
),
"CODING_CELERY_HARD_TIME_LIMIT_SECONDS": int(
    os.getenv("CODING_CELERY_HARD_TIME_LIMIT_SECONDS", "360")
),
"CODING_EXECUTION_LEASE_SECONDS": int(
    os.getenv("CODING_EXECUTION_LEASE_SECONDS", "30")
),
```

- [ ] **Step 5: Implement the registered Celery tasks**

Create `neos/coding/workers/celery_tasks.py`:

```python
import asyncio
from uuid import uuid4

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.exc import SQLAlchemyError

from neos.coding.workers.celery_runtime import (
    discover_coding_tasks,
    run_coding_delivery,
)
from neos.coding.workers.dispatcher import (
    CeleryCodingTaskDispatcher,
    CodingDispatchSource,
)
from neos.config.settings import settings
from neos.observability.metrics import metrics
from neos.workflow.celery_app import app


RETRY_DELAYS = (5, 15, 45)


@app.task(
    bind=True,
    name="neos.coding.workers.celery_tasks.execute_coding_task",
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=3,
    soft_time_limit=settings.CODING_CELERY_SOFT_TIME_LIMIT_SECONDS,
    time_limit=settings.CODING_CELERY_HARD_TIME_LIMIT_SECONDS,
    ignore_result=False,
)
def execute_coding_task(self, task_id: str) -> dict[str, str]:
    worker_id = f"celery-{self.request.id or uuid4().hex}"
    try:
        outcome = asyncio.run(
            run_coding_delivery(task_id=task_id, worker_id=worker_id)
        )
    except (ConnectionError, OSError, SQLAlchemyError, SoftTimeLimitExceeded) as exc:
        retry_index = min(self.request.retries, len(RETRY_DELAYS) - 1)
        raise self.retry(exc=exc, countdown=RETRY_DELAYS[retry_index])
    return {"task_id": task_id, "outcome": outcome.value}


@app.task(
    name="neos.coding.workers.celery_tasks.reconcile_coding_tasks",
    ignore_result=True,
)
def reconcile_coding_tasks() -> dict[str, int]:
    task_ids = asyncio.run(
        discover_coding_tasks(limit=settings.CODING_CELERY_DISCOVERY_BATCH_SIZE)
    )
    dispatcher = CeleryCodingTaskDispatcher(
        app=app, queue=settings.CODING_CELERY_QUEUE, metrics=metrics
    )
    enqueued = 0
    failed = 0
    for task_id in task_ids:
        try:
            dispatcher.enqueue(
                task_id, source=CodingDispatchSource.RECONCILIATION
            )
            enqueued += 1
        except Exception:
            failed += 1
    return {"discovered": len(task_ids), "enqueued": enqueued, "failed": failed}
```

Keep exception details in structured logs. Do not add exception strings to the
returned dictionaries.

- [ ] **Step 6: Register the coding route, queue, imports, and Beat entry**

In `neos/workflow/celery_app.py`:

- include `neos.coding.workers.celery_tasks` in the Celery app imports;
- route `execute_coding_task` to `settings.CODING_CELERY_QUEUE`;
- add `Queue(settings.CODING_CELERY_QUEUE, Exchange(...), routing_key=...)`;
- add this Beat entry only when `CODING_CELERY_ENABLED` is true:

```python
if settings.CODING_CELERY_ENABLED:
    app.conf.beat_schedule["reconcile-coding-tasks"] = {
        "task": "neos.coding.workers.celery_tasks.reconcile_coding_tasks",
        "schedule": settings.CODING_CELERY_RECONCILIATION_SECONDS,
    }
```

- [ ] **Step 7: Run Celery task GREEN**

Run:

```bash
.venv/bin/pytest -q -p no:logging --tb=short \
  tests/coding/workers/test_celery_tasks.py \
  tests/workflow/deep_analysis/test_deep_analysis_report_task.py
```

Expected: new task tests pass and the existing Beat schedule regression remains green.

- [ ] **Step 8: Commit Celery entrypoints and settings**

```bash
git add neos/coding/workers/celery_tasks.py neos/workflow/celery_app.py neos/config/settings.py tests/coding/workers/test_celery_tasks.py
git commit -m "feat: execute coding tasks on celery"
```

---

### Task 5: Add Settings and Mutually Exclusive Runtime Activation

**Files:**
- Modify: `neos/coding/runtime.py`
- Modify: `neos/coding/application/run_service.py`
- Modify: `tests/api/test_coding_production_registration.py`
- Modify: `tests/coding/application/test_run_service.py`
- Modify: `tests/coding/application/test_task_service.py`
- Modify: `tests/coding/persistence/test_postgres_service.py`

**Interfaces:**
- Consumes: `CeleryCodingTaskDispatcher`, `CodingDispatchSource.API`, existing `set_task_created_notifier` callbacks.
- Produces: validated coding Celery settings and exactly one configured task-created notifier.

- [ ] **Step 1: Write failing setting and activation tests**

Extend `tests/api/test_coding_production_registration.py`:

```python
def test_runtime_registers_celery_dispatcher_when_enabled(monkeypatch):
    calls = []
    monkeypatch.setattr(settings, "CODING_FAKE_LOOP_ENABLED", False)
    monkeypatch.setattr(settings, "CODING_CELERY_ENABLED", True)
    monkeypatch.setattr(
        runtime_module,
        "create_celery_dispatcher",
        lambda: RecordingDispatcher(calls),
    )
    runtime_module.create_development_coding_runtime()
    notifier = runtime_module.coding_service._task_created_notifier
    notifier("ct_1")
    assert calls == [("ct_1", CodingDispatchSource.API)]


def test_runtime_rejects_local_and_celery_execution_together(monkeypatch):
    monkeypatch.setattr(settings, "CODING_FAKE_LOOP_ENABLED", True)
    monkeypatch.setattr(settings, "CODING_CELERY_ENABLED", True)
    with pytest.raises(RuntimeError, match="cannot be enabled together"):
        runtime_module.create_development_coding_runtime()
```

Add tests that invalid values (zero reconciliation interval, batch size, or
lease; hard time limit not greater than soft) raise `ValueError` from a dedicated
`validate_coding_worker_settings()` function.

Add a run-service test with a recording repository and injected
`execution_lease=timedelta(seconds=75)`. Assert `advance_one_safe_point` passes
`NOW + timedelta(seconds=75)` as `expires_at` to
`acquire_execution_lease`; repeat the assertion for `fail_active_run`. This
prevents the environment setting from becoming dead configuration.

- [ ] **Step 2: Run RED**

Run:

```bash
.venv/bin/pytest -q -p no:logging --tb=short tests/api/test_coding_production_registration.py
```

Expected: failures for missing settings, dispatcher factory, and validation.

- [ ] **Step 3: Validate settings and wire the execution lease**

Implement `validate_coding_worker_settings(settings)` in
`neos/coding/workers/celery_runtime.py`; require positive intervals/limits,
nonempty queue, and `hard > soft`.

Add `execution_lease: timedelta = timedelta(seconds=30)` to
`CodingRunService.__init__`, reject non-positive durations, store it as
`self._execution_lease`, and replace the execution/interrupt lease expiry
expressions with `now + self._execution_lease`. Keep the steering-claim timeout
separate unless the existing domain contract explicitly uses the execution
lease. Pass
`timedelta(seconds=settings.CODING_EXECUTION_LEASE_SECONDS)` from the Celery
worker runtime; development and existing tests retain the 30-second default.

- [ ] **Step 4: Configure exactly one post-commit notifier**

Add a `create_celery_dispatcher()` factory in `neos/coding/runtime.py` that
imports the Celery app lazily and returns `CeleryCodingTaskDispatcher` with the
configured queue and metrics.

At the beginning of `create_development_coding_runtime()`:

```python
if settings.CODING_FAKE_LOOP_ENABLED and settings.CODING_CELERY_ENABLED:
    raise RuntimeError(
        "CODING_FAKE_LOOP_ENABLED and CODING_CELERY_ENABLED cannot be enabled together"
    )
```

After runtime construction, select the notifier:

```python
notifier = None
if supervisor is not None:
    notifier = supervisor.notify
elif settings.CODING_CELERY_ENABLED:
    validate_coding_worker_settings(settings)
    dispatcher = create_celery_dispatcher()
    notifier = lambda task_id: dispatcher.enqueue(
        task_id, source=CodingDispatchSource.API
    )
coding_service.set_task_created_notifier(notifier)
```

Keep notifier exception swallowing in both task services so broker failure after
commit is logged but cannot roll back the task.

- [ ] **Step 5: Run activation and post-commit GREEN**

Run:

```bash
.venv/bin/pytest -q -p no:logging --tb=short \
  tests/api/test_coding_production_registration.py \
  tests/coding/application/test_run_service.py \
  tests/coding/application/test_task_service.py \
  tests/coding/persistence/test_postgres_service.py
```

Expected: all activation, mutual-exclusion, and post-commit tests pass.

- [ ] **Step 6: Commit settings and runtime activation**

```bash
git add neos/coding/runtime.py neos/coding/application/run_service.py neos/coding/workers/celery_runtime.py tests/api/test_coding_production_registration.py tests/coding/application/test_run_service.py tests/coding/application/test_task_service.py tests/coding/persistence/test_postgres_service.py
git commit -m "feat: activate coding celery delivery"
```

---

### Task 6: Add Bounded Worker Observability

**Files:**
- Modify: `neos/observability/metrics.py`
- Modify: `neos/coding/workers/execution.py`
- Modify: `neos/coding/workers/celery_tasks.py`
- Modify: `tests/coding/test_durability_metrics.py`
- Modify: `tests/coding/workers/test_celery_tasks.py`

**Interfaces:**
- Consumes: bounded `CodingTaskOutcome`, dispatch sources, and retry reason `unexpected`/`infrastructure`.
- Produces: worker, dispatch, active-task, and reconciliation metrics specified by the design.

- [ ] **Step 1: Write failing bounded-label tests**

Extend `tests/coding/test_durability_metrics.py`:

```python
def test_celery_worker_metrics_use_only_bounded_labels():
    collector = EnterpriseMetricsCollector(CollectorRegistry())
    assert collector.coding_worker_tasks_total._labelnames == ("outcome",)
    assert collector.coding_worker_retry_total._labelnames == ("reason",)
    assert collector.coding_worker_active_tasks._labelnames == ()
    assert collector.coding_dispatch_total._labelnames == ("source", "outcome")
    assert collector.coding_reconciliation_tasks_total._labelnames == ("outcome",)
```

- [ ] **Step 2: Run RED**

Run:

```bash
.venv/bin/pytest -q -p no:logging --tb=short tests/coding/test_durability_metrics.py
```

Expected: missing metric attributes.

- [ ] **Step 3: Add the Prometheus instruments**

Add exactly these instruments in `EnterpriseMetricsCollector.__init__`:

```python
self.coding_worker_tasks_total = Counter(
    "coding_worker_tasks_total", "Coding Celery worker task outcomes",
    ["outcome"], registry=self.registry,
)
self.coding_worker_retry_total = Counter(
    "coding_worker_retry_total", "Coding Celery worker retries",
    ["reason"], registry=self.registry,
)
self.coding_worker_active_tasks = Gauge(
    "coding_worker_active_tasks", "Active coding Celery worker tasks",
    registry=self.registry,
)
self.coding_dispatch_total = Counter(
    "coding_dispatch_total", "Coding task dispatch attempts",
    ["source", "outcome"], registry=self.registry,
)
self.coding_reconciliation_tasks_total = Counter(
    "coding_reconciliation_tasks_total", "Coding reconciliation task outcomes",
    ["outcome"], registry=self.registry,
)
```

- [ ] **Step 4: Instrument worker execution without identifier labels**

In `execute_coding_task`, increment the active gauge before `asyncio.run` and
decrement it in `finally`. Increment `coding_worker_tasks_total` with the returned
bounded outcome. Increment `coding_worker_retry_total{reason="infrastructure"}`
before requesting Celery retry. In reconciliation, increment outcomes
`discovered`, `enqueued`, and `failed` by counts using `.inc(count)`.

Add recording-metric tests that assert no call contains `task_id`, `run_id`,
`worker_id`, `delivery_id`, or exception text in labels.

- [ ] **Step 5: Run observability GREEN**

Run:

```bash
.venv/bin/pytest -q -p no:logging --tb=short \
  tests/coding/test_durability_metrics.py \
  tests/coding/workers/test_dispatcher.py \
  tests/coding/workers/test_celery_tasks.py
```

Expected: all metric contract and behavior tests pass.

- [ ] **Step 6: Commit observability**

```bash
git add neos/observability/metrics.py neos/coding/workers/execution.py neos/coding/workers/celery_tasks.py tests/coding/test_durability_metrics.py tests/coding/workers/test_celery_tasks.py
git commit -m "feat: observe coding celery workers"
```

---

### Task 7: Prove Eager Delivery, Duplicate Safety, and Recovery

**Files:**
- Create: `tests/coding/test_celery_worker_vertical_slice.py`
- Modify: `tests/coding/integration/test_postgres_durability.py`
- Modify: `docs/NEOS_CODING.md`

**Interfaces:**
- Consumes: dispatcher, Celery execution entrypoint, shared runner, in-memory durable repository, PostgreSQL integration fixture.
- Produces: end-to-end evidence and updated implementation checkpoint.

- [ ] **Step 1: Write an eager-mode automatic execution vertical slice**

Create `tests/coding/test_celery_worker_vertical_slice.py`. Build a harness from
`CodingTaskService`, `InMemoryCodingTaskRepository`,
`InMemoryCodingRunRepository`, `FakeDurableCodingLoop`, and
`create_coding_runtime`. Register a recording/eager dispatcher as the
post-commit notifier and run the shared `CodingTaskRunner` for each dispatched
task ID.

Assert:

```python
async def test_post_commit_delivery_runs_fake_loop_to_completion():
    harness = CeleryWorkerHarness(task_id="ct_eager", prompt="Fix it")
    task = await harness.create_task()
    await harness.drain_deliveries()
    assert harness.repository.active_run.task_id == task.task_id
    assert harness.repository.task_statuses[task.task_id] == "completed"
    assert harness.repository.checkpoints[0].loop_state["current_instruction"] == "Fix it"


async def test_duplicate_delivery_reuses_one_canonical_run():
    harness = CeleryWorkerHarness(task_id="ct_duplicate", prompt="Fix it")
    await harness.create_task()
    harness.duplicate_last_delivery()
    await harness.drain_deliveries()
    assert len(harness.repository.created_runs) == 1
    assert harness.completed_tool_count("tool-understand-1") == 1
```

- [ ] **Step 2: Add checkpoint redelivery proof**

Pause the first runner after the understand checkpoint, expire/release its lease
using the existing fake repository clock controls, and run a second delivery
with another worker ID. Assert understand attempt one is committed once, plan
attempt one is committed once, and the completed tool mutation count remains
one.

- [ ] **Step 3: Run vertical slice GREEN**

Run:

```bash
.venv/bin/pytest -q -p no:logging --tb=short tests/coding/test_celery_worker_vertical_slice.py
```

Expected: automatic execution, duplicate delivery, and checkpoint recovery pass
without a real broker or database.

- [ ] **Step 4: Extend opt-in PostgreSQL concurrency proof**

In `tests/coding/integration/test_postgres_durability.py`, add a test that seeds
one queued task, calls `ensure_run_started` concurrently for two delivery IDs,
and asserts one run plus one `run.started` event. Reuse the existing fixture and
query patterns; do not add Redis requirements to this repository-level test.

Run:

```bash
.venv/bin/pytest -q -p no:logging --tb=short -m integration \
  tests/coding/integration/test_postgres_durability.py
```

Expected: pass with `CODING_TEST_DATABASE_URL`, otherwise explicit skips only.

- [ ] **Step 5: Update the implementation checkpoint**

In `docs/NEOS_CODING.md`, replace the production worker pending line with:

```markdown
- Production Celery coding queue, post-commit dispatch, and DB reconciliation: 구현 완료
- At-least-once delivery with canonical run/lease/checkpoint recovery: 구현 완료
- Real model adapter and sandbox command/file/git execution: 다음 vertical slice로 이관
```

- [ ] **Step 6: Run focused verification**

Run:

```bash
.venv/bin/pytest -q -p no:logging --tb=short \
  tests/coding/workers \
  tests/coding/test_celery_worker_vertical_slice.py \
  tests/coding/test_development_supervisor_vertical_slice.py \
  tests/coding/test_durability_metrics.py \
  tests/api/test_coding_production_registration.py
```

Expected: all focused worker, runtime, metric, and activation tests pass.

- [ ] **Step 7: Run full coding and API/WS regression**

Run:

```bash
.venv/bin/pytest -q -p no:logging --tb=short \
  tests/coding \
  tests/api/handlers/test_coding_handlers.py \
  tests/api/handlers/test_coding_ws_handlers.py \
  tests/api/test_coding_production_registration.py
```

Expected: no failures. PostgreSQL integration tests may skip only when
`CODING_TEST_DATABASE_URL` is absent.

- [ ] **Step 8: Run static checks**

Run:

```bash
.venv/bin/python -m compileall -q neos/coding tests/coding
git diff --check
```

Expected: both commands exit zero.

- [ ] **Step 9: Commit proof and documentation**

```bash
git add tests/coding/test_celery_worker_vertical_slice.py tests/coding/integration/test_postgres_durability.py docs/NEOS_CODING.md
git commit -m "test: verify coding celery delivery"
```

---

## Final Review Checklist

- [ ] `CODING_FAKE_LOOP_ENABLED=true` and `CODING_CELERY_ENABLED=true` fail startup.
- [ ] API commit succeeds even when broker enqueue raises.
- [ ] Beat reconciliation discovers queued/running tasks and uses a bounded batch.
- [ ] Duplicate delivery produces one canonical run and no duplicate completed tool mutation.
- [ ] Worker process/runtime owns and closes its own database manager.
- [ ] Celery results contain only `task_id` and bounded outcome.
- [ ] Metrics contain no task/run/worker/delivery identifier or exception labels.
- [ ] Existing development supervisor behavior remains green through the shared runner.
- [ ] Real model, sandbox, approval, and job outbox work remains out of scope.

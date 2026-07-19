# Coding Development Supervisor Design

**Date:** 2026-07-19  
**Status:** Approved for implementation planning  
**Scope:** Development-only automatic execution for the durable fake coding loop

## 1. Goal

Automatically start and continue coding tasks in development when
`CODING_FAKE_LOOP_ENABLED=true`, while preserving the PostgreSQL durability,
lease, fencing, checkpoint, and steering guarantees already implemented.

This slice makes the existing durable loop usable from the normal task creation
API. It does not introduce a production worker system.

## 2. Non-goals

- Celery coding workers or production queue routing
- Cross-process wake notifications
- Real model or sandbox command execution
- Distributed scheduling fairness or tenant quotas
- A general-purpose workflow engine

## 3. Selected Approach

Use a hybrid development supervisor:

1. An in-process notification queue starts newly created tasks with low latency.
2. Periodic PostgreSQL reconciliation discovers notifications lost during a
   restart and unfinished tasks left by a previous process.
3. Existing execution leases and fencing tokens remain the system-wide
   single-writer mechanism.

Polling-only execution was rejected because it adds avoidable startup latency.
Handler-owned `asyncio.create_task()` execution was rejected because it couples
task lifetime to an API request and has no restart recovery path.

## 4. Components and Boundaries

### 4.1 `CodingDevelopmentSupervisor`

Add `neos/coding/workers/development_supervisor.py`. Its responsibilities are:

- receive task wake notifications;
- reconcile runnable task IDs from PostgreSQL;
- maintain one local runner per task ID;
- provide a stable process-scoped worker identity;
- apply bounded retry and backoff;
- stop accepting work and shut down active runners gracefully.

It does not implement loop phases, write SQL directly, publish WebSocket
events, or infer lease expiry.

### 4.2 Supervisor ports

The supervisor depends on narrow interfaces:

```python
class CodingWorkRepository(Protocol):
    async def claimable_task_ids(self, *, limit: int) -> tuple[str, ...]:
        raise NotImplementedError


class CodingRunDriver(Protocol):
    async def ensure_started(self, *, task_id: str) -> CodingRun:
        raise NotImplementedError

    async def advance_one_safe_point(
        self, *, task_id: str, worker_id: str
    ) -> CodingEvent | None:
        raise NotImplementedError
```

### 4.3 Runtime wiring

`CodingRuntime` gains an optional supervisor. The development runtime creates it
only when `CODING_FAKE_LOOP_ENABLED=true`. Application lifespan starts it after
database and coding transport initialization and stops it before transport and
database shutdown.

Production runtime registration does not activate this supervisor.

### 4.4 Task-created notification

`CodingTaskService` receives an optional task-created notifier. It invokes the
notifier only after the task and `task.created` event commit. Notification
failure does not change a successful task creation response into an error;
periodic reconciliation is the correctness fallback.

## 5. Durable Lifecycle Commands

Automatic execution makes the old split between run creation and lifecycle
event append an unacceptable crash boundary. Add repository business commands.

### 5.1 Start

```python
async def ensure_run_started(
    *, task_id: str, instruction: str, development_mode: bool, now: datetime
) -> CodingRun:
    raise NotImplementedError
```

In one transaction it:

1. locks the task row;
2. returns the current running run when one exists;
3. otherwise calculates the next run attempt;
4. inserts a running run;
5. changes the task state to `running`;
6. inserts `run.started` and its outbox row.

The direct `queued -> running` transition is a development-only fast path that
skips the future sandbox provisioning states. The command requires
`development_mode=True`; it rejects a queued task otherwise. This does not
change the production domain transition table or authorize other callers to
bypass `provisioning -> cloning -> ready`.

Concurrent calls for one task must return one canonical running run and must not
create duplicate attempts or lifecycle events.

### 5.2 Terminal transitions

```python
async def complete_run(
    *, lease: ExecutionLease, now: datetime
) -> CodingEvent:
    raise NotImplementedError


async def fail_run(
    *, lease: ExecutionLease, error_code: str, now: datetime
) -> CodingEvent:
    raise NotImplementedError
```

Each command atomically updates both run and task status and inserts the matching
terminal event and outbox row. Error payloads contain a normalized error code;
exception text and user input are excluded from metric labels.

## 6. Runnable Task Discovery

`claimable_task_ids(limit)` returns oldest-first task IDs that satisfy all of the
following:

- task is not deleted;
- task status is `queued` or `running`;
- no terminal run makes the task ineligible;
- the query result is limited to a configured batch size.

The query is discovery, not ownership. It does not claim rows. Multiple
processes may return the same task ID; execution lease acquisition decides who
may commit.

## 7. Execution Flow

```text
POST /coding/tasks
  -> task and task.created commit
  -> supervisor.notify(task_id)
  -> local task runner
  -> ensure_run_started(task_id)
  -> advance_one_safe_point(task_id, process_worker_id)
  -> repeat until run.completed or terminal failure
```

At process startup and every reconciliation interval:

```text
claimable_task_ids(batch_limit)
  -> notify each ID
  -> ignore IDs already present in the local active map
```

The process-local structures are limited to:

```python
_pending: asyncio.Queue[str]
_active: dict[str, asyncio.Task]
```

They optimize scheduling but are never canonical task state.

## 8. Competition and Retry Semantics

### 8.1 Expected competition

- `RunAlreadyLeased`: another process is the active executor. End the local
  runner without incrementing failure or retry counters.
- `StaleExecutionLease`: the worker lost write authority. End the local runner
  and record the bounded `stale_write` metric outcome.

Multiple development server processes are allowed to discover the same task.
No single-process restriction is imposed.

### 8.2 Failures

Unexpected or infrastructure failures receive at most three retries with
backoffs of 1, 2, and 4 seconds. When the application catches an ordinary
exception in the still-running worker process, it rolls back the active
transaction and releases that worker's current lease before returning the
error. This makes the next bounded retry eligible immediately. An actual process
crash cannot execute that cleanup and therefore leaves the lease to expire.

A runner never guesses lease expiry. If an attempt receives
`RunAlreadyLeased`, it exits and lets reconciliation rediscover the task after
the persisted lease becomes claimable.

After three failed retries, the application service reacquires a lease and
invokes the fenced atomic `fail_run` command. If another process owns the lease,
the local runner exits without writing failure; reconciliation leaves the
canonical owner in control. Once fenced failure succeeds, the run and task
become `failed` with one durable `run.failed` event.

### 8.3 Successful completion

When no phase remains, the durable loop returns without appending a generic
`run.completed` event. The application service uses the fenced atomic
`complete_run` command, and the task, run, terminal event, and outbox commit
together.

## 9. Graceful Shutdown

Shutdown proceeds in this order:

1. reject new notifications;
2. stop the reconciliation loop;
3. request cancellation of task runners;
4. allow the configured grace period for active repository transactions to
   finish or roll back;
5. cancel remaining coroutines;
6. clear local queue and task references.

Cancellation is not persisted as failure. Repository transaction context
managers roll back interrupted writes, so the last committed checkpoint remains
the recovery boundary.

## 10. Metrics and Logging

All labels remain bounded. Suggested supervisor metrics are:

- `coding_supervisor_tasks_total{outcome}` with outcomes `started`, `completed`,
  `failed`, and `lease_busy`;
- `coding_supervisor_active_tasks` gauge;
- `coding_supervisor_retry_total{reason}` with normalized reasons only.

Logs may include task and worker IDs for debugging, but metric labels may not.

## 11. Test Strategy

### 11.1 Unit tests

- duplicate notifications create one local runner;
- `RunAlreadyLeased` is an expected exit, not a retry or failure;
- unexpected errors use 1/2/4 second backoff and stop after three retries;
- notifications are rejected after shutdown begins;
- graceful shutdown drains or cancels all tracked runners.

### 11.2 Application vertical slice

- API task creation automatically creates a run and first checkpoint;
- a replacement supervisor rediscovers queued and running tasks;
- two supervisors discovering one task complete only one phase attempt;
- final phase atomically completes both run and task;
- repeated failures atomically fail both run and task.

### 11.3 PostgreSQL contract and integration tests

- start command atomically commits run, task state, event, and outbox;
- concurrent start calls produce one current run and one attempt;
- terminal status and terminal event roll back together under injected failure.

## 12. Configuration

The development defaults are intentionally bounded:

- reconciliation interval: 2 seconds;
- discovery batch size: 100 tasks;
- retry backoffs: 1, 2, and 4 seconds;
- graceful shutdown timeout: 10 seconds.

The supervisor exists only when the fake coding loop feature is enabled. These
settings are development controls, not production queue policy.

## 13. Completion Criteria

The slice is complete when:

- a task created through the normal API starts without a manual run-service call;
- process restart recovers queued or unfinished running work;
- multi-process discovery produces one fenced writer;
- run/task lifecycle state and events are transactionally consistent;
- bounded retry and graceful shutdown tests pass;
- production registration remains unchanged and the supervisor is disabled by
  default.

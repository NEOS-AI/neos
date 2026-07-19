# Coding Production Celery Worker Design

**Date:** 2026-07-19  
**Status:** Approved  
**Scope:** Production Celery dispatch, execution, redelivery, and PostgreSQL
reconciliation for the durable fake coding loop

## 1. Objective

Move the validated coding execution policy from the development-only in-process
supervisor across a production process boundary. Coding tasks must execute
independently of the API and browser connection, survive duplicate Celery
delivery and worker loss, and recover broker notification gaps from PostgreSQL.

This slice deliberately keeps `FakeDurableCodingLoop` as the loop adapter. A
real model adapter, sandbox tools, and permission execution remain separate
vertical slices built on the worker boundary established here.

## 2. Decisions

- Use a hybrid dispatch model: post-commit Celery enqueue for low latency plus
  periodic PostgreSQL reconciliation for delivery recovery.
- Accept at-least-once task delivery. Canonical run creation, execution leases,
  fencing tokens, checkpoint idempotency, and tool claims enforce safe effects.
- Add a dedicated `coding` Celery queue with prefetch one, late acknowledgement,
  and rejection when a worker process is lost.
- Keep Celery outside the coding application services through a dispatcher port.
- Share one execution/retry engine between the development supervisor and
  production worker so their domain behavior cannot drift.
- Do not add a job transactional outbox in this slice. Reconciliation is the
  explicit recovery mechanism for the DB-commit/enqueue gap.
- Never enable the development supervisor and Celery dispatcher together.

## 3. Architecture

```text
POST /coding/tasks
  -> PostgreSQL task + task.created commit
  -> CodingTaskDispatcher.enqueue(task_id, source="api")
  -> Celery coding queue
  -> execute_coding_task(task_id, delivery_id)
  -> ensure_run_started()
  -> advance_one_safe_point() loop
  -> completed | failed | lease_busy | stale

Celery Beat
  -> reconcile_coding_tasks
  -> claimable_task_ids(limit)
  -> enqueue(task_id, source="reconciliation")
```

### 3.1 Dispatcher port

Add a small application-facing `CodingTaskDispatcher` protocol. It accepts only
a task identifier and a bounded dispatch source. Task creation services keep
their existing post-commit notifier boundary and do not import Celery.

`CeleryCodingTaskDispatcher` is the production adapter. It publishes
`execute_coding_task` to the configured coding queue. Publication failures are
logged and metered after the task transaction has committed; they do not roll
back or delete the durable task. The reconciliation task later republishes it.

An in-memory recording dispatcher supports unit and eager-mode tests without a
broker.

### 3.2 Worker task

`execute_coding_task` is a synchronous Celery entrypoint wrapping one async
execution. It creates worker-safe database/runtime resources after process fork
and invokes the shared coding task runner. It returns only:

```json
{
  "task_id": "ct_...",
  "outcome": "completed | failed | lease_busy | stale"
}
```

Prompts, exception text, tool results, and transcripts are not stored in the
Celery result backend.

### 3.3 Reconciliation task

`reconcile_coding_tasks` queries `claimable_task_ids(limit)` in oldest-first
order and republishes every returned `queued` or `running` task to the coding
queue. Terminal tasks are never returned by the repository query.

Multiple Beat/API processes may publish the same task. This is expected:
`ensure_run_started` returns the canonical running run and the execution lease
allows only one worker to advance it.

## 4. Execution Semantics

The worker calls `ensure_run_started` once and repeatedly invokes
`advance_one_safe_point` until it observes a terminal result.

- An existing running run is reused; duplicate delivery does not increment the
  run attempt.
- `RunAlreadyLeased` produces `lease_busy` and exits successfully.
- `StaleExecutionLease` produces `stale` and exits without retrying a stale
  write.
- A completed event or already-terminal task produces `completed`.
- Domain failure produces `failed` only after a fenced, atomic terminal command.

Extract the bounded retry loop from the development supervisor into a shared
runner. Both adapters use three retry delays: 1, 2, and 4 seconds. Exhaustion
calls `fail_active_run` with normalized error code `worker_retry_exhausted` in
the Celery adapter and the existing supervisor-specific code in development.

## 5. Celery Retry and Time Limits

Internal retries handle short transient errors while the worker process remains
healthy. Celery retry/redelivery is reserved for infrastructure failures:

- database connectivity failure outside a durable domain command;
- Celery soft time limit;
- worker process loss or broker redelivery.

Celery retries at 5, 15, and 45 seconds, at most three times. Domain failure,
lease contention, and stale fencing rejection are returned as bounded outcomes
and do not request Celery retry.

On soft time limit the worker attempts to release its current lease and requests
a Celery retry. A hard kill is assumed to bypass cleanup. Recovery therefore
depends on lease expiry followed by Celery redelivery or Beat reconciliation,
then resumes from the latest committed checkpoint.

## 6. Queue Configuration

Add a dedicated `coding` queue and task routes for the worker and reconciliation
tasks. Coding execution uses:

- `acks_late=True`;
- `reject_on_worker_lost=True`;
- `worker_prefetch_multiplier=1`;
- coding-specific soft and hard time limits;
- a result payload restricted to the bounded outcome envelope.

The global Celery worker may retain its existing defaults for other queues.
Coding-specific task annotations or decorators override defaults without
changing search, analysis, or generation task behavior.

## 7. Configuration and Activation

Add environment-backed settings:

- `CODING_CELERY_ENABLED=false`;
- `CODING_CELERY_QUEUE=coding`;
- `CODING_CELERY_RECONCILIATION_SECONDS=10`;
- `CODING_CELERY_DISCOVERY_BATCH_SIZE=100`;
- `CODING_CELERY_SOFT_TIME_LIMIT_SECONDS`;
- `CODING_CELERY_HARD_TIME_LIMIT_SECONDS`;
- `CODING_EXECUTION_LEASE_SECONDS`.

Values that represent intervals, limits, or batch sizes must be positive. The
hard time limit must exceed the soft time limit, and the execution lease must be
long enough for a safe-point attempt or be renewed during it. Invalid settings
fail startup rather than silently disabling recovery.

When Celery coding is enabled, production runtime registers the Celery
dispatcher as the task-created notifier. When the development fake supervisor
is enabled, it registers the local notifier. Enabling both is a startup error.

## 8. Failure Matrix

| Failure | Durable state | Recovery |
|---|---|---|
| API crashes after task commit before enqueue | queued task in PostgreSQL | Beat reconciliation republishes |
| Broker rejects post-commit enqueue | queued task remains | log/metric, then reconciliation |
| Duplicate API/Beat delivery | one canonical running run | second worker exits `lease_busy` |
| Worker crashes before checkpoint | last committed checkpoint remains | lease expiry and redelivery |
| Worker crashes after checkpoint before ack | checkpoint/event committed | redelivery resumes next safe point |
| Soft time limit | best-effort lease release | Celery retry |
| Hard process kill | lease remains until expiry | redelivery/reconciliation after expiry |
| Stale worker attempts write | transaction rejected by fencing | stale worker exits |
| Retry exhaustion | atomic run/task failure | terminal `worker_retry_exhausted` |

## 9. Observability

Add bounded-label Prometheus instruments:

- `coding_worker_tasks_total{outcome}`;
- `coding_worker_retry_total{reason}`;
- `coding_worker_active_tasks`;
- `coding_dispatch_total{source,outcome}` where source is `api` or
  `reconciliation`, and outcome is `enqueued` or `failed`;
- `coding_reconciliation_tasks_total{outcome}`.

Task, run, delivery, and worker identifiers belong in structured logs and trace
attributes, never metric labels. Exception strings are logged with truncation
and are not Celery result fields or Prometheus labels.

## 10. Test Strategy

### 10.1 Unit tests

- dispatch occurs only after task/event commit;
- the dispatcher selects the coding queue and passes only stable identifiers;
- enqueue failure cannot roll back a created task;
- worker outcomes cover completed, failed, lease busy, and stale execution;
- shared retry delays are bounded and retry exhaustion performs fenced failure;
- soft time limit requests infrastructure retry;
- reconciliation uses a bounded oldest-first batch and excludes terminal tasks;
- metric labels and outcome values remain bounded.

### 10.2 Eager-mode vertical slice

- task creation dispatches to the worker automatically;
- the fake loop commits checkpoints and reaches terminal state;
- duplicate delivery creates one canonical run;
- redelivery resumes from the latest checkpoint without repeating a completed
  tool mutation.

### 10.3 Opt-in integration tests

With prepared PostgreSQL and Redis/Celery infrastructure:

- killing a worker process causes lease-expiry recovery and redelivery;
- tasks committed while the broker is unavailable are discovered by Beat;
- API dispatch and reconciliation races still produce one canonical run.

These tests may skip only when their explicit integration environment variables
are absent. The full existing coding REST/WebSocket regression suite remains a
required local gate.

## 11. Non-Goals

- real model adapter;
- sandbox file, command, Git, PTY, or watcher tools;
- job transactional outbox;
- task pause, cancel, approval, and user-wait workflows;
- Celery autoscaling or Kubernetes deployment;
- cross-region broker failover;
- coordinator or multi-agent execution.

## 12. Completion Criteria

- post-commit API dispatch and periodic DB reconciliation are implemented;
- the dedicated coding queue safely executes the durable fake loop;
- duplicate delivery and worker recovery reuse canonical run/checkpoint state;
- development supervisor and Celery worker share one bounded execution policy;
- eager-mode and coding/API regression suites pass;
- PostgreSQL/Redis process-loss tests pass in a prepared integration environment
  or skip only because the environment is absent;
- `docs/NEOS_CODING.md` records this production worker checkpoint and keeps real
  model/sandbox work as the next vertical slice.

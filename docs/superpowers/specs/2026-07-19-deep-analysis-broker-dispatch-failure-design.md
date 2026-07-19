# Deep Analysis Broker Dispatch Failure Design

**Date:** 2026-07-19  
**Status:** Approved for specification review  
**Scope:** `docs/TODO_260729.md` §5 only

## Goal

When Celery is enabled but the broker rejects a deep-analysis dispatch, fail
loudly and durably. The caller must not receive an accepted response, the run
must not remain orphaned in `running`, and the system must not silently switch
to the less durable inline executor.

## Policy

Celery-enabled deployments promise broker-backed execution. A broker dispatch
failure therefore means the submission failed. The system records the run as
`failed`, appends a terminal `job_failed` event, and returns an explicit error
to the caller. Inline execution remains available only when Celery is disabled
by configuration.

This preserves a clear operational contract:

- `celery.enabled=true`: enqueue successfully or fail the submission;
- `celery.enabled=false`: execute with the existing bounded inline task;
- never change executors implicitly because infrastructure is unavailable.

## Architecture

Convert `submit_deep_analysis_job` from a synchronous function to an async
integration boundary. Both production callers, the FastAPI handlers and the
async graph node, already run in async contexts and will await it.

The submission function keeps the current success paths. If Celery
`apply_async` raises, it calls the existing durable failure helper using a new
database session, then raises `DeepAnalysisDispatchError`. Failure persistence
is centralized here so every caller receives identical run state and event
semantics.

The framework-free `neos.workflow.deep_analysis` package remains unaware of
Celery. Broker handling stays in `neos/tasks/deep_analysis_job_task.py`, the
existing integration layer.

## Failure Data Flow

1. The API or graph node creates and commits the run.
2. It awaits `submit_deep_analysis_job(...)`.
3. With Celery enabled, the function calls `apply_async` on the configured
   analysis queue.
4. If dispatch succeeds, it returns `"celery"` exactly as today.
5. If dispatch raises, the function opens a fresh database session and records:
   - `DARun.status = "failed"`;
   - a terminal `job_failed` event;
   - payload code `E_BROKER_DISPATCH` and a bounded error description.
6. It raises `DeepAnalysisDispatchError` with the original exception chained.
7. The dedicated API maps this error to HTTP 503. The graph node keeps its
   existing user-facing failure response and does not emit a started event.

The failure record is committed before the exception reaches the caller. A
client that already knows the run identifier can therefore replay the terminal
event consistently.

## Error Contract

`DeepAnalysisDispatchError` exposes no broker URL, credentials, task payload,
question, or user content. Its public message identifies broker dispatch
failure and the run identifier only.

The durable event payload is bounded to:

```json
{
  "code": "E_BROKER_DISPATCH",
  "error": "bounded operational description"
}
```

The error description is truncated to the same 500-character boundary used by
job execution failures. Logs may include the exception traceback but must not
log the research question or Celery connection configuration.

If durable failure recording itself fails, the original broker failure remains
the raised cause and a secondary error is logged. This follows the existing
`_record_failure` fail-safe rule: observability failure must not disguise the
primary infrastructure failure.

## API and Graph Behavior

`POST /deep-analysis` and `POST /deep-analysis/{run_id}/resume` catch only
`DeepAnalysisDispatchError` and return HTTP 503 with a stable, non-sensitive
detail. Other exceptions retain existing framework handling.

On initial API submission, the run has already been committed before dispatch;
the compensating failure transition makes that row terminal. On resume, the run
returns to or remains `failed`, so it stays eligible for a later explicit
resume attempt after the broker recovers.

The graph node already has a broad submission failure boundary. It continues
to return `"심층 분석을 시작하지 못했습니다."`, clears the response run ID,
and skips `on_deep_analysis_started`. The newly centralized compensation makes
the committed database run terminal instead of orphaned.

## Non-goals

- Do not add automatic inline fallback.
- Do not add an outbox, reconciliation scheduler, or broker health probe.
- Do not retry `apply_async` inside the web request.
- Do not change Celery worker retry behavior after a task is successfully
  delivered.
- Do not change the inline executor path when Celery is disabled.
- Do not add a database migration or new run status.

## Testing

- Unit-test successful Celery and inline submission after the async conversion.
- Unit-test broker dispatch failure records `failed` plus `job_failed` before
  raising `DeepAnalysisDispatchError`.
- Assert the event uses `E_BROKER_DISPATCH`, bounds its error text, and contains
  no question or broker configuration.
- Assert failure-record persistence errors do not replace the original dispatch
  error.
- API-test initial and resume submission failures return 503 and never return an
  accepted response.
- Graph-test dispatch failure keeps the existing user response and does not emit
  a deep-analysis-started event.
- Run deep-analysis, workflow, and API regression boundaries to verify the
  inline and successful Celery paths remain unchanged.

## Success Criteria

A Celery-enabled broker outage produces no accepted response, no silent inline
execution, and no indefinitely `running` run. Every successfully compensated
failure has a replayable terminal event with a bounded machine-readable code,
and a later explicit resume remains possible after infrastructure recovery.

# Coding Event Outbox Dispatcher Design

## Goal

Eliminate the failure window between committing a durable coding event and
notifying live WebSocket clients. The dispatcher must recover unpublished work
after process restart and remain safe when multiple API instances run at once.

This design covers the Phase 0 PostgreSQL outbox and an API-lifespan dispatcher.
Redis fan-out and the deterministic fake worker consume the resulting publisher
port but are separate implementation increments.

## Delivery Contract

- A coding event and its outbox row are inserted in the same transaction.
- Delivery is at-least-once. Consumers remain idempotent by `(task_id, seq)`.
- An outbox row is complete only after its publisher succeeds and
  `published_at` is stored.
- Process termination never discards unpublished rows.
- Multiple dispatchers may run concurrently without claiming the same row.
- Ordering is strict within a task. A later event for one task cannot be
  published while an earlier event for that task remains unpublished.
- Failure for one task does not block unrelated tasks.

## Schema

Create `coding_event_outbox` with:

- `outbox_id VARCHAR(64) PRIMARY KEY`
- `event_id VARCHAR(64) NOT NULL UNIQUE REFERENCES coding_events(event_id)`
- `task_id VARCHAR(64) NOT NULL REFERENCES coding_tasks(task_id)`
- `seq BIGINT NOT NULL`
- `attempt_count INTEGER NOT NULL DEFAULT 0`
- `next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
- `claimed_at TIMESTAMPTZ NULL`
- `published_at TIMESTAMPTZ NULL`
- `last_error TEXT NULL`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`

Indexes cover eligible unpublished rows and `(task_id, seq)`. A unique
`event_id` makes creation idempotent.

The event payload is not duplicated in the outbox. Claim queries join
`coding_events`, keeping the canonical envelope in one table.

## Components

### Transactional Event Append

`PostgresCodingService._append_in_session` inserts the domain event and its
outbox row before the surrounding transaction commits. It no longer treats a
direct process-local publish as the durable delivery mechanism.

The service may still perform a best-effort wake-up after commit to reduce
latency, but correctness depends only on the outbox dispatcher.

### Outbox Repository

`PostgresCodingOutboxRepository` exposes:

- `claim_batch(limit, now, stale_before) -> list[ClaimedOutboxEvent]`
- `mark_published(outbox_id, published_at)`
- `mark_failed(outbox_id, error, next_attempt_at)`

Claiming uses `FOR UPDATE SKIP LOCKED`. The transaction updates `claimed_at`
before returning rows. A stale claim becomes eligible again after a bounded
lease, allowing crash recovery.

The claim query excludes a row when the same task has an earlier unpublished
sequence. This preserves per-task ordering without globally serializing all
tasks.

### Dispatcher

`CodingOutboxDispatcher` depends on the repository, an `EventPublisher`, a
clock, and configurable batch/poll values. One `run_once` call:

1. claims an eligible batch;
2. publishes each canonical `CodingEvent`;
3. marks successful rows published;
4. records failures with bounded exponential backoff;
5. continues processing unrelated rows after an individual failure.

The continuous `run` loop waits on either a wake-up event or a short poll
timeout. This avoids a busy loop while retaining recovery when a wake-up is
lost.

### API Lifespan Integration

The dispatcher starts after database and cache initialization and stops during
application shutdown. Cancellation waits for the current repository operation
to unwind but does not promise to finish all queued deliveries. Remaining rows
are recovered on the next startup.

If Redis is unavailable, the Phase 0 publisher uses the process-local broker.
Redis publication will be introduced behind the same publisher interface, so
the dispatcher and outbox schema do not change.

## Failure Handling

- Publisher failure: increment attempts, store a truncated error, schedule
  exponential backoff capped at 60 seconds.
- Dispatcher crash after publish but before `mark_published`: the row is
  republished after its claim lease expires. This is the expected at-least-once
  duplicate and is removed by `seq` idempotency.
- Database failure while claiming or marking: log and return to the poll loop;
  no in-memory acknowledgement substitutes for database state.
- Poison row: continue retrying with capped delay and expose attempt/error
  metrics. A dead-letter policy is deferred until operational evidence defines
  a safe threshold.
- Shutdown: cancel the loop; never mark a row published merely because the
  process is stopping.

## Configuration and Observability

Initial defaults:

- batch size: 100
- idle poll: 500 ms
- claim lease: 30 seconds
- retry base: 500 ms
- retry cap: 60 seconds
- stored error limit: 2,000 characters

Metrics and structured logs include claimed, published, failed, retry delay,
oldest unpublished age, `task_id`, `event_id`, and `seq`. Event payloads are not
logged.

## Testing

- Migration contract verifies constraints and indexes.
- Persistence test verifies event and outbox insertion share one transaction.
- Repository contract verifies `SKIP LOCKED`, stale-claim recovery, eligibility,
  and per-task ordering predicates.
- Dispatcher tests cover success, failure backoff, unrelated-task progress,
  duplicate publication after lease expiry, wake-up, and cancellation.
- Vertical slice creates events, dispatches them, reconnects after a sequence,
  and proves replay/live reducer convergence.
- Existing coding API, WebSocket, chat stream, approval, and authorization
  regressions remain green.

## Deferred Scope

- Redis Pub/Sub publisher/subscriber implementation
- Celery or dedicated dispatcher process
- dead-letter administration UI
- transactional Kafka
- sandbox provisioning and real model execution
- deterministic fake coding worker, implemented after this outbox increment

These additions consume the same repository and publisher contracts and do not
alter the event envelope or frontend sequence semantics.

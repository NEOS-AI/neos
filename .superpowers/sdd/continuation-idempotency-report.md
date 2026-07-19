# Celery continuation idempotency report

## Status

Implemented a durable checkpoint-generation token for every production Celery coding delivery.

## Fix

- Celery messages now contain `(task_id, expected_checkpoint_id)`. An explicit `None` means the initial generation expects no durable checkpoint; omitting the Celery argument fails closed at task invocation.
- API dispatch, continuations, and reconciliation all publish an explicit expected checkpoint token.
- Reconciliation discovers the latest durable checkpoint identity together with each claimable task.
- Production advancement carries the token through the worker runner and run service into `acquire_execution_lease`.
- PostgreSQL lease acquisition checks the latest checkpoint token and canonical run status in the same fenced statement that acquires the execution lease. A stale token, terminal run, or busy lease cannot advance.
- A matching delivery advances one safe point. Its continuation is published with the newly durable checkpoint identity.
- Continuation publish exceptions are treated as ambiguous and are not retried by the current delivery. A possibly-published tokenized successor is safe; when publication truly failed, periodic reconciliation republishes the current durable generation.

Internal development-mode calls retain their existing unguarded interface. The production Celery boundary requires an explicit token and all production callers were updated.

## Regression coverage

- Redelivered initial generation cannot advance a second safe point or repeat its tool execution.
- Stale/mismatched deliveries enqueue no successor.
- Reconciliation publishes current durable checkpoint tokens, including explicit no-checkpoint state.
- Broker publish-then-raise executes advancement once and does not invoke Celery retry amplification.
- Repository contract verifies checkpoint validation and running-state validation are integrated into atomic lease acquisition.
- Existing LEASE_BUSY, stale fencing, terminal, recovery, and vertical worker behavior remain covered.

## Verification

- `.venv/bin/pytest -q tests/coding` — **371 passed, 13 skipped**.
- Relevant worker/repository/vertical slice — **75 passed**.
- Scoped Ruff over all changed coding production/test paths — **clean**.
- `git diff --check` — **clean**.
- A broader `ruff check neos/coding tests/coding` reports two pre-existing unrelated unused imports in `neos/coding/sandbox/archive.py` and `tests/coding/persistence/test_postgres_service.py`; neither file was modified.

## Scope preservation

The pre-existing `.env.template` modification and untracked deep-analysis plan/spec files were not changed or staged.

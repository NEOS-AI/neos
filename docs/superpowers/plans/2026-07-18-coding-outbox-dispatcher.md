# Coding Event Outbox Dispatcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist a delivery record with every coding event and reliably publish unpublished events from an API-lifespan dispatcher after crashes or transient publisher failures.

**Architecture:** `PostgresCodingService` inserts `coding_events` and `coding_event_outbox` in one transaction. A focused repository claims eligible rows with `FOR UPDATE SKIP LOCKED`, and `CodingOutboxDispatcher` publishes them through the existing `EventPublisher` port before acknowledging them in PostgreSQL. An API-lifespan task runs the dispatcher; delivery is at-least-once and frontend `seq` handling remains idempotent.

**Tech Stack:** Python 3.12, FastAPI lifespan, SQLAlchemy async sessions and PostgreSQL SQL, pytest/pytest-asyncio.

## Global Constraints

- Event and outbox inserts must share the same PostgreSQL transaction.
- Delivery is at-least-once; never acknowledge before publisher success.
- Preserve strict sequence ordering within each task without blocking unrelated tasks.
- Multiple API instances must claim different rows using `FOR UPDATE SKIP LOCKED`.
- Default batch size is 100, poll interval 500 ms, claim lease 30 seconds, retry base 500 ms, and retry cap 60 seconds.
- Stored publisher errors are limited to 2,000 characters and event payloads are not logged.
- Existing chat SSE, approval, authorization, coding REST, and WebSocket behavior must remain unchanged.

---

### Task 1: Outbox Schema and Atomic Event Append

**Files:**
- Modify: `db/migrations/038_add_coding_phase0.sql`
- Modify: `neos/coding/persistence/postgres.py`
- Modify: `tests/coding/test_migration_contract.py`
- Modify: `tests/coding/persistence/test_postgres_service.py`

**Interfaces:**
- Consumes: existing `PostgresCodingService._append_in_session(...) -> CodingEvent`.
- Produces: one `coding_event_outbox` row per `coding_events` row, keyed by unique `event_id`.

- [ ] **Step 1: Write failing migration and transaction tests**

Add assertions that the migration contains `coding_event_outbox`, unique `event_id`, unpublished eligibility and task-sequence indexes. Extend the fake-session transaction test:

```python
async def test_event_and_outbox_are_inserted_in_same_transaction() -> None:
    session = FakeSession()

    async def session_factory():
        return session

    service = PostgresCodingService(session_factory)
    await service.append(
        task_id="ct_fixed", event_type="text.delta", payload={"delta": "hi"}
    )

    sql = "\n".join(statement for statement, _ in session.statements)
    assert "INSERT INTO coding_events" in sql
    assert "INSERT INTO coding_event_outbox" in sql
    assert sql.index("INSERT INTO coding_events") < sql.index(
        "INSERT INTO coding_event_outbox"
    )
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest -q tests/coding/test_migration_contract.py tests/coding/persistence/test_postgres_service.py`

Expected: FAIL because the migration and append SQL do not contain the outbox.

- [ ] **Step 3: Add the schema and transactional insert**

Add the table and indexes to migration 038:

```sql
CREATE TABLE IF NOT EXISTS coding_event_outbox (
    outbox_id VARCHAR(64) PRIMARY KEY,
    event_id VARCHAR(64) NOT NULL UNIQUE
        REFERENCES coding_events(event_id) ON DELETE CASCADE,
    task_id VARCHAR(64) NOT NULL
        REFERENCES coding_tasks(task_id) ON DELETE CASCADE,
    seq BIGINT NOT NULL CHECK (seq > 0),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    claimed_at TIMESTAMPTZ NULL,
    published_at TIMESTAMPTZ NULL,
    last_error TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coding_outbox_eligible
    ON coding_event_outbox(next_attempt_at, created_at)
    WHERE published_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_coding_outbox_task_seq
    ON coding_event_outbox(task_id, seq);
```

After inserting `coding_events`, insert the outbox row using the same session:

```python
await session.execute(
    text("""
        INSERT INTO coding_event_outbox
            (outbox_id, event_id, task_id, seq, next_attempt_at, created_at)
        VALUES (:outbox_id, :event_id, :task_id, :seq, :now, :now)
        ON CONFLICT (event_id) DO NOTHING
    """),
    {
        "outbox_id": f"co_{uuid4().hex}",
        "event_id": event.event_id,
        "task_id": task_id,
        "seq": seq,
        "now": now,
    },
)
```

- [ ] **Step 4: Run tests and verify GREEN**

Run: `uv run pytest -q tests/coding/test_migration_contract.py tests/coding/persistence/test_postgres_service.py`

Expected: all selected tests PASS.

- [ ] **Step 5: Commit**

```bash
git add db/migrations/038_add_coding_phase0.sql neos/coding/persistence/postgres.py tests/coding/test_migration_contract.py tests/coding/persistence/test_postgres_service.py
git commit -m "feat: persist coding event outbox"
```

### Task 2: PostgreSQL Outbox Claim Repository

**Files:**
- Create: `neos/coding/outbox/__init__.py`
- Create: `neos/coding/outbox/models.py`
- Create: `neos/coding/outbox/repository.py`
- Create: `tests/coding/outbox/test_repository.py`

**Interfaces:**
- Produces: `ClaimedOutboxEvent(outbox_id: str, event: CodingEvent, attempt_count: int)`.
- Produces: `PostgresCodingOutboxRepository.claim_batch(*, limit: int, now: datetime, stale_before: datetime) -> list[ClaimedOutboxEvent]`.
- Produces: `mark_published(outbox_id: str, *, published_at: datetime) -> None` and `mark_failed(outbox_id: str, *, error: str, next_attempt_at: datetime) -> None`.

- [ ] **Step 1: Write fake-session repository contract tests**

```python
async def test_claim_uses_skip_locked_and_preserves_per_task_order() -> None:
    session = FakeSession(rows=[])
    repository = PostgresCodingOutboxRepository(lambda: ready_session(session))

    await repository.claim_batch(
        limit=100,
        now=NOW,
        stale_before=NOW - timedelta(seconds=30),
    )

    sql = "\n".join(statement for statement, _ in session.statements)
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "NOT EXISTS" in sql
    assert "earlier.task_id = candidate.task_id" in sql
    assert "earlier.seq < candidate.seq" in sql
```

Also assert the claim query checks `next_attempt_at`, accepts stale claims, updates `claimed_at`, joins the canonical `coding_events` envelope, and bounds `limit` to 1–500.

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest -q tests/coding/outbox/test_repository.py`

Expected: FAIL because `neos.coding.outbox.repository` does not exist.

- [ ] **Step 3: Implement the model and repository**

Use a frozen dataclass:

```python
@dataclass(frozen=True, slots=True)
class ClaimedOutboxEvent:
    outbox_id: str
    event: CodingEvent
    attempt_count: int
```

The claim SQL must use one transaction and a CTE that selects eligible rows,
excludes earlier unpublished rows for the same task, locks with
`FOR UPDATE SKIP LOCKED`, updates `claimed_at`, and returns the joined event
columns. `mark_failed` increments `attempt_count`, clears `claimed_at`, truncates
`last_error` to 2,000 characters, and stores `next_attempt_at`.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `uv run pytest -q tests/coding/outbox/test_repository.py`

Expected: all repository contract tests PASS.

- [ ] **Step 5: Commit**

```bash
git add neos/coding/outbox tests/coding/outbox
git commit -m "feat: add coding outbox repository"
```

### Task 3: Retry-Safe Outbox Dispatcher

**Files:**
- Create: `neos/coding/outbox/dispatcher.py`
- Create: `tests/coding/outbox/test_dispatcher.py`

**Interfaces:**
- Consumes: the repository methods from Task 2 and `EventPublisher.publish(event)`.
- Produces: `CodingOutboxDispatcher.run_once() -> int`, `run() -> None`, `wake() -> None`.
- Produces: `retry_delay(attempt_count: int, base: float = 0.5, cap: float = 60.0) -> float`.

- [ ] **Step 1: Write failing retry and dispatch tests**

```python
def test_retry_delay_is_exponential_and_capped() -> None:
    assert retry_delay(1) == 0.5
    assert retry_delay(2) == 1.0
    assert retry_delay(20) == 60.0


async def test_run_once_acknowledges_only_after_publish() -> None:
    timeline: list[str] = []
    repository = FakeRepository([claimed_event()], timeline)
    publisher = FakePublisher(timeline)
    dispatcher = CodingOutboxDispatcher(repository, publisher, clock=lambda: NOW)

    assert await dispatcher.run_once() == 1
    assert timeline == ["publish:ce_1", "published:co_1"]
```

Add tests that a publisher failure calls `mark_failed` with the next retry time,
does not call `mark_published`, and does not prevent a later unrelated claimed
event from being published.

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest -q tests/coding/outbox/test_dispatcher.py`

Expected: FAIL because the dispatcher module does not exist.

- [ ] **Step 3: Implement minimal dispatcher behavior**

```python
async def run_once(self) -> int:
    now = self._clock()
    claimed = await self._repository.claim_batch(
        limit=self._batch_size,
        now=now,
        stale_before=now - self._claim_lease,
    )
    published = 0
    for item in claimed:
        try:
            await self._publisher.publish(item.event)
        except Exception as error:
            delay = retry_delay(item.attempt_count + 1)
            await self._repository.mark_failed(
                item.outbox_id,
                error=str(error),
                next_attempt_at=now + timedelta(seconds=delay),
            )
        else:
            await self._repository.mark_published(
                item.outbox_id, published_at=self._clock()
            )
            published += 1
    return published
```

`run` repeatedly calls `run_once` and waits up to 500 ms on an internal
`asyncio.Event`; `wake` sets that event. Propagate `CancelledError` and log
database loop failures without acknowledging rows.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `uv run pytest -q tests/coding/outbox/test_dispatcher.py`

Expected: all dispatcher tests PASS.

- [ ] **Step 5: Commit**

```bash
git add neos/coding/outbox/dispatcher.py tests/coding/outbox/test_dispatcher.py
git commit -m "feat: dispatch coding event outbox"
```

### Task 4: Runtime and API Lifespan Integration

**Files:**
- Modify: `neos/coding/runtime.py`
- Modify: `neos/main.py`
- Create: `tests/coding/outbox/test_runtime.py`
- Modify: `tests/coding/test_phase0_vertical_slice.py`

**Interfaces:**
- Produces: process-wide `coding_outbox_dispatcher` configured with `PostgresCodingOutboxRepository`, `coding_event_broker`, and `db_manager.get_session`.
- Produces: `start_coding_outbox_dispatcher() -> asyncio.Task` and `stop_coding_outbox_dispatcher(task) -> None` helpers used by lifespan.

- [ ] **Step 1: Write failing lifecycle tests**

```python
async def test_start_and_stop_manage_dispatcher_task() -> None:
    dispatcher = BlockingDispatcher()
    task = start_coding_outbox_dispatcher(dispatcher)
    await dispatcher.started.wait()

    await stop_coding_outbox_dispatcher(task)

    assert task.cancelled()
```

Extend the vertical slice with a fake outbox repository and broker to prove
append → dispatch → reconnect replay maintains exact `seq` order.

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest -q tests/coding/outbox/test_runtime.py tests/coding/test_phase0_vertical_slice.py`

Expected: FAIL because lifecycle helpers and dispatcher runtime do not exist.

- [ ] **Step 3: Wire runtime and lifespan**

Construct the repository and dispatcher in `neos/coding/runtime.py`. Add helpers:

```python
def start_coding_outbox_dispatcher(dispatcher=coding_outbox_dispatcher):
    return asyncio.create_task(dispatcher.run(), name="coding-outbox-dispatcher")


async def stop_coding_outbox_dispatcher(task: asyncio.Task) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
```

Start the task after database initialization in the FastAPI lifespan and stop
it before database shutdown. Preserve the current test behavior when database
initialization is unavailable by starting only after successful initialization.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `uv run pytest -q tests/coding/outbox tests/coding/test_phase0_vertical_slice.py`

Expected: all selected tests PASS.

- [ ] **Step 5: Run complete regression verification**

Run:

```bash
GOOGLE_API_KEY=test-key JWT_SECRET_KEY=test-secret-key uv run pytest -q \
  tests/coding \
  tests/api/handlers/test_coding_handlers.py \
  tests/api/handlers/test_coding_ws_handlers.py \
  tests/api/test_stream_adapter_harness_events.py \
  tests/api/handlers/test_approval_authorization.py \
  tests/api/dependencies/test_resource_access.py
```

Expected: zero failures.

Run: `cd web && corepack pnpm test:source && corepack pnpm exec tsc --noEmit`

Expected: frontend source tests and TypeScript checks PASS unchanged.

Run: `git diff --check`

Expected: no whitespace errors.

- [ ] **Step 6: Commit**

```bash
git add neos/coding/runtime.py neos/main.py tests/coding/outbox/test_runtime.py tests/coding/test_phase0_vertical_slice.py
git commit -m "feat: run coding outbox dispatcher"
```

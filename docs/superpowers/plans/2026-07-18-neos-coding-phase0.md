# NEOS Coding Phase 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a durable, authenticated coding-task vertical slice whose state can be reconstructed from an ordered event stream, with a minimal `/code` frontend reducer and shell.

**Architecture:** A framework-free `neos.coding` domain owns task transitions and versioned events. PostgreSQL-shaped repositories persist tasks and append ordered events, while FastAPI exposes authenticated task/snapshot/replay endpoints and a WebSocket protocol. The first frontend slice uses a pure reducer so initial snapshots, replayed events, and live events converge to identical state; no real LLM or sandbox is included in Phase 0.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy/PostgreSQL SQL, pytest/pytest-asyncio, Next.js 16, React 19, TypeScript 5.9, Node test runner.

## Global Constraints

- General chat SSE behavior and history remain unchanged.
- Every task subresource is owner-scoped and cross-user resources return 404.
- Task event `seq` is strictly monotonic per task and event application is idempotent.
- WebSocket disconnect never changes task execution state.
- Phase 0 uses a deterministic fake event producer; LLM and sandbox work begins in later phases.
- Production code follows failing-test-first TDD.

---

### Task 1: Coding Domain and State Transitions

**Files:**
- Create: `neos/coding/__init__.py`
- Create: `neos/coding/domain/__init__.py`
- Create: `neos/coding/domain/models.py`
- Create: `neos/coding/domain/events.py`
- Create: `neos/coding/domain/errors.py`
- Test: `tests/coding/domain/test_task_state.py`
- Test: `tests/coding/domain/test_events.py`

**Interfaces:**
- Produces: `CodingTaskStatus`, `CodingTask`, `CodingEvent`, `transition_task(task, target, now)`, `make_event(...)`.
- Invariant: invalid transitions raise `InvalidTaskTransition`; events reject non-positive `seq` and empty task/type identifiers.

- [ ] **Step 1: Write failing transition tests**

```python
def test_queued_task_can_enter_provisioning():
    task = make_task(CodingTaskStatus.QUEUED)
    changed = transition_task(task, CodingTaskStatus.PROVISIONING, NOW)
    assert changed.status is CodingTaskStatus.PROVISIONING
    assert changed.version == task.version + 1

def test_completed_task_cannot_return_to_running():
    with pytest.raises(InvalidTaskTransition):
        transition_task(make_task(CodingTaskStatus.COMPLETED), CodingTaskStatus.RUNNING, NOW)
```

- [ ] **Step 2: Run tests and verify missing module failure**

Run: `uv run pytest -q tests/coding/domain/test_task_state.py`  
Expected: FAIL because `neos.coding.domain.models` does not exist.

- [ ] **Step 3: Implement immutable domain objects and explicit transition table**

Use frozen dataclasses and `StrEnum`; do not embed database or transport concerns.

- [ ] **Step 4: Add event validation tests, watch them fail, then implement**

Run: `uv run pytest -q tests/coding/domain`  
Expected after implementation: PASS.

### Task 2: Task Repository and Ordered Event Store

**Files:**
- Create: `neos/database/coding_models.py`
- Create: `neos/coding/repositories/__init__.py`
- Create: `neos/coding/repositories/task_repository.py`
- Create: `neos/coding/events/__init__.py`
- Create: `neos/coding/events/store.py`
- Create: `db/migrations/038_add_coding_phase0.sql`
- Test: `tests/coding/repositories/test_task_repository.py`
- Test: `tests/coding/events/test_event_store.py`
- Test: `tests/coding/test_migration_contract.py`

**Interfaces:**
- Consumes: Task 1 domain objects.
- Produces: `CodingTaskRepository.create/get_owned/list_owned/update`, `CodingEventStore.append/list_after/head_seq/snapshot`.
- Transaction rule: `append` locks the task row, computes `last_seq + 1`, inserts the event, and updates `coding_tasks.last_seq` in the same transaction.

- [ ] **Step 1: Write fake-DB repository contract tests**

```python
@pytest.mark.asyncio
async def test_get_owned_scopes_query_to_task_and_owner():
    db = FakeDB(row=None)
    await CodingTaskRepository(db).get_owned("ct_1", "user_1")
    query, params = db.calls[0]
    assert "task_id =" in query and "owner_id =" in query
    assert params == ("ct_1", "user_1")
```

- [ ] **Step 2: Verify RED, implement minimal repository, verify GREEN**

Run: `uv run pytest -q tests/coding/repositories/test_task_repository.py`.

- [ ] **Step 3: Write append/replay tests**

Cover first sequence, increasing sequence, `after_seq` exclusivity, owner scoping, and bounded limit.

- [ ] **Step 4: Implement event store and SQL migration**

Migration creates `coding_tasks`, `coding_events`, indexes, unique `(task_id, seq)`, and owner foreign key. SQL contract tests assert constraints and indexes are present.

- [ ] **Step 5: Run repository/event/migration tests**

Run: `uv run pytest -q tests/coding/repositories tests/coding/events tests/coding/test_migration_contract.py`  
Expected: PASS.

### Task 3: Authenticated Task API, Snapshot, Replay, and WebSocket Protocol

**Files:**
- Create: `neos/coding/application/__init__.py`
- Create: `neos/coding/application/task_service.py`
- Create: `neos/coding/runtime.py`
- Create: `neos/api/models/coding_models.py`
- Create: `neos/api/dependencies/coding_access.py`
- Create: `neos/api/handlers/coding_handlers.py`
- Create: `neos/api/handlers/coding_ws_handlers.py`
- Modify: `neos/main.py`
- Test: `tests/coding/application/test_task_service.py`
- Test: `tests/api/handlers/test_coding_handlers.py`
- Test: `tests/api/handlers/test_coding_ws_handlers.py`

**Interfaces:**
- Consumes: repositories and event store from Task 2.
- Produces: `POST /api/v1/coding/tasks`, `GET /tasks/{id}`, `GET /tasks/{id}/snapshot`, `GET /tasks/{id}/events?after_seq=`, and `/api/v1/coding/ws?task_id=&after_seq=`.
- WebSocket messages: `hello`, ordered replayed domain events, `caught_up`; invalid/missing ownership closes with policy violation without leaking existence.

- [ ] **Step 1: Write task service tests**

```python
@pytest.mark.asyncio
async def test_create_task_persists_created_event_atomically():
    task = await service.create_task(owner_id="u1", prompt="Fix it")
    assert task.status is CodingTaskStatus.QUEUED
    assert event_store.events[0].type == "task.created"
```

- [ ] **Step 2: Verify RED and implement service with injected repositories**

Run: `uv run pytest -q tests/coding/application/test_task_service.py`.

- [ ] **Step 3: Write HTTP authorization and response contract tests**

Cover unauthenticated 401, foreign/missing 404, 202 task creation, snapshot `head_seq`, and exclusive replay.

- [ ] **Step 4: Implement Pydantic models, dependencies, and HTTP router**

Use existing `get_current_user`; handlers delegate to the application service and contain no SQL.

- [ ] **Step 5: Write WebSocket protocol tests, verify RED, implement gateway**

Test `hello → replay → caught_up`, empty replay, malformed `after_seq`, and non-owner rejection. Use an injected in-process event notifier for Phase 0.

- [ ] **Step 6: Register routers and run API tests**

Run: `uv run pytest -q tests/coding tests/api/handlers/test_coding_handlers.py tests/api/handlers/test_coding_ws_handlers.py`  
Expected: PASS.

### Task 4: Pure Frontend Event Reducer and Minimal Code Shell

**Files:**
- Create: `web/features/coding/types/events.ts`
- Create: `web/features/coding/stream/event-reducer.ts`
- Create: `web/features/coding/stream/event-reducer.test.ts`
- Create: `web/features/coding/api/coding-api.ts`
- Create: `web/features/coding/components/coding-shell.tsx`
- Create: `web/app/(code)/code/page.tsx`
- Modify: `web/components/app-sidebar.tsx`
- Modify: `web/package.json`

**Interfaces:**
- Consumes: Task 3 snapshot and event envelopes.
- Produces: `reduceCodingEvent(state, event)` and `/code` navigation/shell.
- Reducer result distinguishes duplicate (`seq <= appliedSeq`) from gap (`seq > appliedSeq + 1`) and never silently applies out-of-order events.

- [ ] **Step 1: Add Node test script coverage and write reducer tests**

```typescript
test("replay and live application converge", () => {
  const replayed = events.reduce(reduceCodingEvent, initialCodingState());
  const reconnected = events.slice(1).reduce(
    reduceCodingEvent,
    snapshotStateAfter(events[0]),
  );
  assert.deepEqual(serialize(replayed), serialize(reconnected));
});
```

- [ ] **Step 2: Run and verify RED**

Run: `pnpm --dir web test:source`  
Expected: FAIL because the reducer module is missing.

- [ ] **Step 3: Implement minimal event types and pure reducer**

Support task lifecycle and text part events only; retain unknown event envelopes for forward-compatible diagnostics.

- [ ] **Step 4: Verify reducer GREEN and add minimal `/code` shell**

The shell creates a task through the API and renders task status plus connection placeholder. No socket hook or workspace UI is added in Phase 0.

- [ ] **Step 5: Run frontend source tests and type/build verification**

Run: `pnpm --dir web test:source` and `pnpm --dir web build`  
Expected: PASS.

### Task 5: Phase 0 Integration and Regression Verification

**Files:**
- Create: `tests/coding/test_phase0_vertical_slice.py`
- Modify: `docs/NEOS_CODING.md` only if implementation decisions diverge from the approved design.

**Interfaces:**
- Consumes all earlier tasks.
- Produces a deterministic vertical slice proving create → append → snapshot → replay convergence.

- [ ] **Step 1: Write failing vertical-slice test using in-memory repositories**

The test creates a task, appends fake `text.delta` events, obtains a snapshot, reconnects after a prior sequence, and asserts exact ordered replay.

- [ ] **Step 2: Implement only missing integration glue and verify**

Run: `uv run pytest -q tests/coding`.

- [ ] **Step 3: Run focused backend regressions**

Run: `uv run pytest -q tests/api/test_stream_adapter_harness_events.py tests/api/handlers/test_approval_authorization.py tests/api/dependencies/test_resource_access.py`  
Expected: 38 passed.

- [ ] **Step 4: Run formatting/diff checks**

Run: `git diff --check` and project-available Python/TypeScript checks. Fix all new warnings attributable to Phase 0.

- [ ] **Step 5: Review scope**

Confirm no LLM, sandbox, terminal, Redis, Celery, approval, or Git mutation implementation leaked into Phase 0; those remain later phases.

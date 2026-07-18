# Coding Production Streaming Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Coding Agent WebSocket authentication, live delivery, replay, and browser reconnect behavior correct across multiple production API workers.

**Architecture:** PostgreSQL remains the durable event source and outbox, while Redis provides atomic single-use tickets and cross-worker Pub/Sub fan-out behind transport protocols. The server pages replay to an exact contiguous cursor before live tail, and the browser classifies terminal versus retryable errors while enforcing heartbeat deadlines.

**Tech Stack:** Python 3.12, FastAPI/Starlette WebSockets, redis-py asyncio, PostgreSQL/SQLAlchemy, pytest, Next.js 16, React 19, TypeScript 5.9, Node test runner.

## Global Constraints

- Production is fail-closed when Redis coding transport initialization fails.
- Development and tests may explicitly use in-memory adapters.
- PostgreSQL `coding_events` and outbox remain the source of truth; Redis Pub/Sub is not durable.
- Tickets expire after 30 seconds, are task-bound, store only a SHA-256 digest key, and are consumed atomically once.
- Replay page size is 500 and one handshake replays at most 20,000 events.
- Local subscriber queues hold 256 events; overflow forces replay reconnect rather than silent loss.
- The dispatcher is the only event publisher; append may only wake it after commit.
- Existing chat SSE, approval, authorization, and unrelated WebSocket production policy remain unchanged.
- Ticket values, access tokens, and event payloads must never be logged.

---

### Task 1: Transport Ports and Bounded In-Memory Adapters

**Files:**
- Create: `neos/coding/transport/__init__.py`
- Create: `neos/coding/transport/base.py`
- Create: `neos/coding/transport/memory.py`
- Modify: `neos/coding/auth/ws_tickets.py`
- Modify: `neos/coding/events/broker.py`
- Create: `tests/coding/transport/test_memory.py`

**Interfaces:**
- Produces: `CodingTicketStore.issue(...)`, `consume(...)`, and `expires_in`.
- Produces: `CodingEventSubscription.get()`, `close()`, and `CodingEventTransport.publish(...)`, `subscribe(...)`, `close()`.
- Preserves compatibility exports `InMemoryWsTicketStore` and `InProcessCodingEventBroker`.

- [ ] **Step 1: Write failing port and cleanup tests**

```python
async def test_wrong_task_consumes_ticket_and_expired_entries_are_swept() -> None:
    now = datetime(2026, 7, 18, tzinfo=UTC)
    current = [now]
    store = InMemoryWsTicketStore(clock=lambda: current[0])
    wrong = await store.issue(owner_id="u1", task_id="ct_1")
    expired = await store.issue(owner_id="u1", task_id="ct_2")

    assert await store.consume(wrong, task_id="ct_other") is None
    assert await store.consume(wrong, task_id="ct_1") is None
    current[0] += timedelta(seconds=31)
    await store.issue(owner_id="u1", task_id="ct_3")

    assert store.pending_count == 1
    assert await store.consume(expired, task_id="ct_2") is None
```

Add a transport test proving two subscriptions receive an event, closing one is
idempotent, and closing the transport releases all subscriptions.

- [ ] **Step 2: Run RED**

Run: `.venv/bin/pytest -q tests/coding/transport/test_memory.py tests/coding/auth/test_ws_tickets.py tests/coding/events/test_broker.py`

Expected: FAIL because transport ports, `pending_count`, and subscription objects do not exist.

- [ ] **Step 3: Implement ports and adapters**

Define protocols in `base.py`:

```python
class CodingEventSubscription(Protocol):
    async def get(self) -> CodingEvent: ...
    async def close(self) -> None: ...


class CodingEventTransport(Protocol):
    async def publish(self, event: CodingEvent) -> None: ...
    async def subscribe(self, task_id: str) -> CodingEventSubscription: ...
    async def close(self) -> None: ...
```

Wrap the existing queues in an idempotent subscription class. Sweep expired
tickets under the ticket lock on both issue and consume. A mismatched task pops
the ticket before returning `None`.

- [ ] **Step 4: Run GREEN**

Run: `.venv/bin/pytest -q tests/coding/transport/test_memory.py tests/coding/auth/test_ws_tickets.py tests/coding/events/test_broker.py`

Expected: all selected tests PASS.

- [ ] **Step 5: Commit**

```bash
git add neos/coding/transport neos/coding/auth/ws_tickets.py neos/coding/events/broker.py tests/coding/transport tests/coding/auth/test_ws_tickets.py tests/coding/events/test_broker.py
git commit -m "refactor: define coding transport ports"
```

### Task 2: Atomic Redis Ticket Store

**Files:**
- Create: `neos/coding/transport/redis_tickets.py`
- Create: `tests/coding/transport/test_redis_tickets.py`

**Interfaces:**
- Consumes: an initialized `redis.asyncio.Redis`-compatible client.
- Produces: `RedisCodingTicketStore(redis_client, ttl_seconds=30, key_prefix="neos:coding:ws-ticket")` implementing `CodingTicketStore`.

- [ ] **Step 1: Write failing cross-instance tests**

Use one fake Redis client shared by two store instances:

```python
async def test_ticket_is_consumed_atomically_across_store_instances() -> None:
    redis = FakeRedis()
    issuer = RedisCodingTicketStore(redis)
    consumer = RedisCodingTicketStore(redis)
    ticket = await issuer.issue(owner_id="u1", task_id="ct_1")

    first, second = await asyncio.gather(
        consumer.consume(ticket, task_id="ct_1"),
        issuer.consume(ticket, task_id="ct_1"),
    )

    assert sorted([first, second], key=lambda value: value is None) == ["u1", None]
```

Also assert Redis keys contain `sha256(ticket)` but never the raw ticket, issuance
uses `nx=True` and `ex=30`, malformed JSON fails closed, and wrong-task consume
invalidates the record.

- [ ] **Step 2: Run RED**

Run: `.venv/bin/pytest -q tests/coding/transport/test_redis_tickets.py`

Expected: FAIL because `RedisCodingTicketStore` does not exist.

- [ ] **Step 3: Implement Redis ticket issuance and Lua consume**

Use compact JSON and this atomic script through `eval`:

```lua
local value = redis.call('GET', KEYS[1])
if value then redis.call('DEL', KEYS[1]) end
return value
```

Generate 256-bit random tickets with `secrets.token_urlsafe(32)`, hash with
SHA-256, and retry the negligible `SET NX` collision up to three times before
raising `RuntimeError`.

- [ ] **Step 4: Run GREEN**

Run: `.venv/bin/pytest -q tests/coding/transport/test_redis_tickets.py`

Expected: all selected tests PASS.

- [ ] **Step 5: Commit**

```bash
git add neos/coding/transport/redis_tickets.py tests/coding/transport/test_redis_tickets.py
git commit -m "feat: add atomic redis coding tickets"
```

### Task 3: Cross-Worker Redis Event Transport

**Files:**
- Create: `neos/coding/transport/redis_events.py`
- Create: `tests/coding/transport/test_redis_events.py`

**Interfaces:**
- Produces: `RedisCodingEventTransport(redis_client, channel_prefix="neos:coding:events", queue_size=256)`.
- Consumes/produces canonical `CodingEvent` envelopes and `CodingEventSubscription`.

- [ ] **Step 1: Write failing shared-bus tests**

```python
async def test_publish_reaches_subscription_owned_by_another_transport() -> None:
    bus = FakeRedisPubSubBus()
    worker_a = RedisCodingEventTransport(bus.client())
    worker_b = RedisCodingEventTransport(bus.client())
    subscription = await worker_b.subscribe("ct_1")
    expected = make_test_event(task_id="ct_1", seq=1)

    await worker_a.publish(expected)

    assert await asyncio.wait_for(subscription.get(), timeout=0.1) == expected
```

Add tests for one Redis listener shared by multiple local subscribers, last-close
unsubscribe, JSON round-trip, publish error propagation, listener failure closing
subscriptions, and queue overflow marking the subscription overloaded.

- [ ] **Step 2: Run RED**

Run: `.venv/bin/pytest -q tests/coding/transport/test_redis_events.py`

Expected: FAIL because the Redis event transport does not exist.

- [ ] **Step 3: Implement registry, listener, and serialization**

Use one registry entry per task containing its Pub/Sub object, listener task, and
local subscription set. `publish()` calls Redis `publish` and raises when it
returns or throws an error. Validate every decoded envelope through `CodingEvent`
construction before enqueueing it. `close()` cancels and awaits every listener.

- [ ] **Step 4: Run GREEN**

Run: `.venv/bin/pytest -q tests/coding/transport/test_redis_events.py`

Expected: all selected tests PASS.

- [ ] **Step 5: Commit**

```bash
git add neos/coding/transport/redis_events.py tests/coding/transport/test_redis_events.py
git commit -m "feat: add redis coding event transport"
```

### Task 4: Runtime Policy, Single Publish Path, and Production Route

**Files:**
- Modify: `neos/coding/persistence/postgres.py`
- Modify: `neos/coding/runtime.py`
- Modify: `neos/api/handlers/coding_handlers.py`
- Modify: `neos/api/handlers/coding_ws_handlers.py`
- Modify: `neos/main.py`
- Modify: `tests/coding/persistence/test_postgres_service.py`
- Modify: `tests/coding/outbox/test_runtime.py`
- Create: `tests/api/test_coding_production_registration.py`

**Interfaces:**
- Produces: `initialize_coding_transport(*, redis_client, production: bool) -> CodingRuntimeTransport`.
- Produces: `close_coding_transport() -> None` and an optional `wake_outbox` callback injected into `PostgresCodingService`.

- [ ] **Step 1: Write failing runtime and registration tests**

```python
async def test_append_wakes_outbox_without_direct_publish() -> None:
    wake_calls = []
    service = PostgresCodingService(session_factory, wake_outbox=lambda: wake_calls.append(1))
    await service.append(task_id="ct_1", event_type="text.delta", payload={})
    assert wake_calls == [1]
    assert publisher.calls == []


def test_production_keeps_authenticated_coding_websocket_registered() -> None:
    paths = production_route_paths()
    assert "/api/v1/coding/ws" in paths.websocket_paths
```

Add tests that production Redis initialization failure raises and development
explicitly selects in-memory adapters.

- [ ] **Step 2: Run RED**

Run: `.venv/bin/pytest -q tests/coding/persistence/test_postgres_service.py tests/coding/outbox/test_runtime.py tests/api/test_coding_production_registration.py`

Expected: FAIL because append directly publishes, runtime policy is absent, and production filters the route.

- [ ] **Step 3: Implement runtime policy and lifecycle**

Remove `broker` from `PostgresCodingService`; add `wake_outbox: Callable[[], None] | None` and call it only after transaction commit. Runtime chooses Redis adapters when production, in-memory when explicitly development/test, injects protocol types into handlers, and closes dispatcher/transport before `cache_manager.close()`.

Register `coding_ws_router` with `app.include_router(...)` directly while leaving
`_include_router_for_runtime` unchanged for every other router.

- [ ] **Step 4: Run GREEN**

Run: `.venv/bin/pytest -q tests/coding/persistence/test_postgres_service.py tests/coding/outbox/test_runtime.py tests/api/test_coding_production_registration.py`

Expected: all selected tests PASS.

- [ ] **Step 5: Commit**

```bash
git add neos/coding/persistence/postgres.py neos/coding/runtime.py neos/api/handlers/coding_handlers.py neos/api/handlers/coding_ws_handlers.py neos/main.py tests/coding/persistence/test_postgres_service.py tests/coding/outbox/test_runtime.py tests/api/test_coding_production_registration.py
git commit -m "fix: harden coding transport runtime"
```

### Task 5: Exact Paged Replay and Resync Protocol

**Files:**
- Modify: `neos/api/handlers/coding_ws_handlers.py`
- Modify: `tests/api/handlers/test_coding_ws_handlers.py`

**Interfaces:**
- Produces: `build_replay_messages(service, task_id, owner_id, after_seq, page_size=500, max_events=20_000) -> ReplayResult | None`.
- `ReplayResult` contains `messages`, `last_contiguous_seq`, and `requires_resync`.

- [ ] **Step 1: Write failing large-replay tests**

```python
async def test_replay_pages_5001_events_before_caught_up() -> None:
    service = FakePagedService(head_seq=5001)
    result = await build_replay_messages(service, "ct_1", "u1", 0)

    assert len([m for m in result.messages if "seq" in m]) == 5001
    assert result.messages[-1] == {
        "v": 1, "type": "caught_up", "task_id": "ct_1", "head_seq": 5001
    }
    assert service.after_seq_calls == [0, 500, 1000, 1500, 2000, 2500,
                                       3000, 3500, 4000, 4500, 5000]
```

Add tests for `resync_required` above 20,000, a missing expected sequence, live
duplicates queued during replay, and a queued live gap forcing resync.

- [ ] **Step 2: Run RED**

Run: `.venv/bin/pytest -q tests/api/handlers/test_coding_ws_handlers.py`

Expected: FAIL because replay is capped at one 5,000-event query.

- [ ] **Step 3: Implement paged replay and exact cursor**

Page from the last contiguous sequence until snapshot head. Require each returned
event sequence to equal `cursor + 1`. Emit `resync_required` and close without
`caught_up` when the maximum or continuity rule is violated. After `caught_up`,
drain the already-subscribed live queue, ignore `seq <= cursor`, send only
`seq == cursor + 1`, and resync on a gap.

- [ ] **Step 4: Run GREEN**

Run: `.venv/bin/pytest -q tests/api/handlers/test_coding_ws_handlers.py`

Expected: all WebSocket protocol tests PASS.

- [ ] **Step 5: Commit**

```bash
git add neos/api/handlers/coding_ws_handlers.py tests/api/handlers/test_coding_ws_handlers.py
git commit -m "fix: page coding websocket replay exactly"
```

### Task 6: Browser Error Policy, Heartbeat, and Cursor Persistence

**Files:**
- Modify: `web/features/coding/api/coding-api.ts`
- Create: `web/features/coding/stream/connection-policy.ts`
- Modify: `web/features/coding/stream/use-coding-stream.ts`
- Modify: `web/features/coding/components/coding-task-workspace.tsx`
- Create: `web/tests/source/coding-connection-policy.test.ts`
- Modify: `web/tests/source/coding-stream-client.test.ts`

**Interfaces:**
- Produces: `CodingAPIError(status: number, message: string)`.
- Produces: `classifyConnectionError(status?: number) -> "terminal" | "retry"`.
- Produces: task cursor helpers `readCursor`, `writeCursor`, `clearCursor`.
- Extends connection state with `unauthorized`, `not_found`, and `protocol_error`.

- [ ] **Step 1: Write failing pure policy tests**

```typescript
test("permanent statuses stop reconnect", () => {
  assert.equal(classifyConnectionError(401), "terminal");
  assert.equal(classifyConnectionError(403), "terminal");
  assert.equal(classifyConnectionError(404), "terminal");
  assert.equal(classifyConnectionError(429), "retry");
  assert.equal(classifyConnectionError(503), "retry");
});

test("cursor storage is task scoped and rejects invalid values", () => {
  const storage = new MemoryStorage();
  writeCursor(storage, "ct_1", 12);
  assert.equal(readCursor(storage, "ct_1"), 12);
  assert.equal(readCursor(storage, "ct_2"), 0);
});
```

Add a deterministic heartbeat controller test proving server-provided cadence,
pong refresh, and timeout after two periods. Add source assertions that
`resync_required` clears the cursor and malformed JSON closes the socket.

- [ ] **Step 2: Run RED**

Run: `cd web && corepack pnpm test:source`

Expected: FAIL because policy, cursor, and heartbeat helpers do not exist.

- [ ] **Step 3: Implement policy and integrate the hook**

Preserve HTTP status in `CodingAPIError`. Initialize `afterSeq` from
`sessionStorage`, update only after contiguous acceptance, and clear on
`resync_required`. Parse `hello.heartbeat_ms`, schedule ping, and close when no
pong arrives within two periods. Terminal ticket errors set a terminal state and
do not schedule `connect`; retryable errors keep the current jittered backoff.

- [ ] **Step 4: Run GREEN and type-check**

Run: `cd web && corepack pnpm test:source`

Expected: all source tests PASS.

Run: `cd web && corepack pnpm exec tsc --noEmit --tsBuildInfoFile /tmp/neos-coding-hardening.tsbuildinfo`

Expected: TypeScript exits zero without changing `web/tsconfig.tsbuildinfo`.

- [ ] **Step 5: Commit**

```bash
git add web/features/coding web/tests/source/coding-connection-policy.test.ts web/tests/source/coding-stream-client.test.ts
git commit -m "fix: harden coding stream reconnect policy"
```

### Task 7: Full Regression and Scope Verification

**Files:**
- Modify only files required to correct regressions attributable to Tasks 1–6.

**Interfaces:**
- Consumes all prior tasks.
- Produces a verified production-streaming hardening increment.

- [ ] **Step 1: Run backend focused regression**

Run:

```bash
GOOGLE_API_KEY=test-key JWT_SECRET_KEY=test-secret-key .venv/bin/pytest -q \
  tests/coding \
  tests/api/handlers/test_coding_handlers.py \
  tests/api/handlers/test_coding_ws_handlers.py \
  tests/api/test_coding_production_registration.py \
  tests/api/test_stream_adapter_harness_events.py \
  tests/api/handlers/test_approval_authorization.py \
  tests/api/dependencies/test_resource_access.py
```

Expected: zero failures.

- [ ] **Step 2: Run frontend regression and type-check**

Run: `cd web && corepack pnpm test:source`

Expected: zero failures.

Run: `cd web && corepack pnpm exec tsc --noEmit --tsBuildInfoFile /tmp/neos-coding-hardening-final.tsbuildinfo`

Expected: exit zero.

- [ ] **Step 3: Check diff and review requirements**

Run: `git diff --check`

Expected: no whitespace errors.

Confirm production route registration, Redis fail-closed policy, cross-instance
ticket/fan-out tests, exact replay, single publish path, terminal browser errors,
heartbeat deadline, and unchanged user-owned working-tree files.

- [ ] **Step 4: Record the verified checkpoint**

Run: `git status --short`

Expected: no uncommitted hardening files. Pre-existing user-owned changes may
remain and must match the baseline status recorded before Task 1.

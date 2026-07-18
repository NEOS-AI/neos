# Coding Production Streaming Hardening Design

## Goal

Make the Coding Agent Phase 0 transport safe for production deployments with
multiple API workers. Remove process affinity from WebSocket tickets and live
event fan-out, make replay bounded without skipping events, and give the browser
an explicit terminal-versus-retry connection policy.

## Scope

This increment addresses the production review findings for:

- production Coding WebSocket registration;
- cross-worker single-use WebSocket tickets;
- cross-worker live event fan-out;
- replay batches larger than 5,000 events;
- the duplicate direct-publish path;
- terminal connection errors and heartbeat timeouts;
- expired in-memory ticket cleanup for the development fallback;
- multi-instance and protocol regression coverage.

Sandbox provisioning, coding model execution, terminal commands, workspace
files, and the deterministic fake coding worker remain separate increments.

## Deployment Policy

Production is fail-closed. If the Redis transport cannot initialize, application
startup fails and no worker serves a partially functional Coding WebSocket.

Development and tests may use the in-memory transport. Fallback must be explicit
from environment/runtime policy; a production Redis error never silently
downgrades to process-local behavior.

## Transport Ports

Introduce focused interfaces instead of exposing concrete broker and ticket
classes through API dependencies:

```python
class CodingTicketStore(Protocol):
    expires_in: int
    async def issue(self, *, owner_id: str, task_id: str) -> str: ...
    async def consume(self, token: str, *, task_id: str) -> str | None: ...


class CodingEventTransport(Protocol):
    async def publish(self, event: CodingEvent) -> None: ...
    async def subscribe(self, task_id: str) -> CodingEventSubscription: ...
    async def close(self) -> None: ...
```

`CodingEventSubscription` owns an async event queue and an idempotent `close()`.
The WebSocket gateway does not know whether the implementation uses Redis or
memory.

The existing in-memory implementations conform to these ports and remain test
fixtures and local-development adapters.

## Redis WebSocket Tickets

Ticket keys use `neos:coding:ws-ticket:{sha256(ticket)}`. The random ticket
value is returned to the browser, but only its digest is stored in Redis. The
record contains `owner_id` and `task_id` as compact JSON and expires after 30
seconds.

Issuance uses `SET key value EX 30 NX`. Consumption is one atomic Redis Lua
operation:

1. read the key;
2. delete it when present;
3. return the stored record.

The application then verifies that the stored `task_id` equals the handshake
task. A mismatched task still consumes the ticket, preventing probing or reuse.
Malformed and expired records fail authentication without leaking task
existence.

The in-memory fallback removes expired entries during issue and consume, keeping
its memory bounded during development.

## Redis Event Fan-Out

The outbox dispatcher publishes each canonical event envelope as JSON to
`neos:coding:events:{task_id}`. Publish errors raise, so the dispatcher records a
failure and retries the durable outbox row.

Each API worker maintains a process-local subscription registry:

- the first local WebSocket for a task creates one Redis Pub/Sub listener;
- additional local sockets share that listener and receive copies through
  bounded local queues;
- closing the last local socket unsubscribes from Redis and releases the task
  listener;
- worker shutdown closes all listeners before the shared Redis client closes.

If a local subscriber queue reaches its bound, that subscription is closed with
WebSocket code `1013`; the client reconnects and recovers through PostgreSQL
replay. Deltas are never silently dropped while leaving the socket open.

Redis Pub/Sub is not treated as durable. PostgreSQL `coding_events` and the
outbox remain the source of truth.

## Single Publish Path

`PostgresCodingService.append` only commits the event and outbox row. It no
longer publishes directly to a process-local broker.

After commit it calls an optional non-blocking outbox wake callback. The wake is
only a latency hint; the 500 ms dispatcher poll remains the recovery mechanism.
The dispatcher is the only component that publishes domain events and marks
outbox rows complete.

## Production WebSocket Registration

The authenticated `coding_ws_router` is registered directly in both development
and production. The existing production filter remains unchanged for unrelated
legacy WebSocket routes.

Registration tests construct the production app policy with `DEBUG=false` and
assert that `/api/v1/coding/ws` remains an `APIWebSocketRoute` while unrelated
filtered routers retain their current behavior.

## Replay Protocol

Replay must never declare a sequence caught up unless every sequence through the
declared head was sent.

At handshake:

1. authorize ownership;
2. subscribe to live transport before reading the snapshot;
3. read snapshot `head_seq`;
4. page PostgreSQL events in ascending batches of 500;
5. send pages until the snapshot head is reached;
6. send `caught_up` with the last contiguous sequence actually sent;
7. drain queued live events, ignoring duplicates and enforcing continuity;
8. continue live tail.

A handshake may replay at most 20,000 events. If the gap exceeds this bound, or
if PostgreSQL does not return the next expected sequence, the server sends:

```json
{
  "v": 1,
  "type": "resync_required",
  "task_id": "ct_...",
  "snapshot_url": "/api/v1/coding/tasks/ct_.../snapshot",
  "head_seq": 25000
}
```

and closes normally. It never sends a misleading `caught_up` message.

## Browser Connection State

The Next.js ticket proxy preserves backend error status. The client classifies:

- terminal: `401`, `403`, `404`;
- retryable: `429`, `500–599`, network failure, abnormal WebSocket close;
- protocol resync: `resync_required`;
- live: `caught_up` followed by a valid heartbeat.

Terminal errors set an explicit `unauthorized` or `not_found` connection state
and stop retrying. Retryable failures use the existing exponential backoff with
jitter.

The client reads `heartbeat_ms` from `hello`, sends ping at that cadence, and
requires pong within two heartbeat periods. Missing pong closes the socket and
starts durable replay reconnect. Hardcoded heartbeat timing is removed.

The last contiguous applied sequence is stored in `sessionStorage` under a
task-specific key. Invalid stored values reset to zero. The persisted cursor is
updated only after a contiguous event is accepted.

On `resync_required`, the client clears the stored cursor and reconnects from
zero. Snapshot hydration remains a later UI enhancement; clearing the cursor is
correct but potentially more expensive.

## Error Handling and Shutdown

- Redis ticket issue/consume errors are authentication-service failures, not
  invalid tickets, and produce a retryable server error before upgrade.
- Redis publish errors propagate to the outbox dispatcher and keep the row
  unpublished.
- Redis subscriber failure closes affected local subscriptions so clients
  replay rather than remaining falsely live.
- JSON decoding and envelope validation failures close the WebSocket with a
  protocol error and trigger replay.
- Shutdown order is dispatcher, event transport subscriptions, Redis/cache, then
  database.
- Logs include task/event identifiers and error class but exclude ticket values,
  event payloads, and access tokens.

## Configuration

Initial configuration:

- ticket TTL: 30 seconds;
- Redis channel prefix: `neos:coding:events`;
- local subscriber queue: 256 events;
- replay page: 500 events;
- maximum handshake replay: 20,000 events;
- default heartbeat: 30 seconds;
- pong deadline: two heartbeat periods.

Production public WebSocket URL continues to use
`CODING_WS_PUBLIC_URL`. Production startup validates that it is configured or
that the derived backend URL is browser-reachable according to deployment
configuration.

## Testing

Backend tests cover:

- two Redis ticket-store instances issuing and atomically consuming one ticket;
- wrong-task consumption invalidating the ticket;
- two transport instances delivering one published event across workers;
- subscriber cleanup and Redis listener failure;
- publisher failure leaving the outbox row retryable;
- exactly one publish path per appended event;
- production Coding WebSocket registration;
- replay of 5,001 events without a gap;
- `resync_required` beyond 20,000 events;
- replay/live boundary duplicate and gap handling;
- production fail-closed and development in-memory fallback.

Frontend tests cover:

- terminal HTTP statuses stopping retries;
- retryable statuses preserving backoff;
- server-provided heartbeat cadence;
- pong deadline reconnect;
- task-specific session cursor restore and update;
- `resync_required` clearing the cursor;
- malformed envelopes causing protocol reconnect.

Existing coding, chat SSE, approval, authorization, source, and TypeScript
regression suites remain green.

## Acceptance Criteria

- Ticket issue and WebSocket upgrade work across different API workers.
- An outbox event published by one worker reaches a socket owned by another.
- Production exposes the authenticated Coding WebSocket and never silently uses
  an in-memory transport.
- No replay size can produce a false `caught_up` sequence.
- Permanent authorization/not-found failures stop browser retries.
- Half-open sockets reconnect after the pong deadline and recover exact state.
- Appending one event produces one transport publish attempt through the outbox
  dispatcher.

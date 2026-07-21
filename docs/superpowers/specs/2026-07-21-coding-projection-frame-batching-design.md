# Coding Projection Frame Batching Design

**Date:** 2026-07-21

**Status:** Approved for written specification review

## 1. Goal

Keep long-running coding tasks responsive when replay or WebSocket delivery produces thousands of events. Projection correctness remains event-synchronous, while React subscriber notification is coalesced to at most one publish per animation frame.

This slice implements the Phase 4 streaming foundation from `docs/NEOS_CODING.md`. Conversation virtualization, terminal buffers, workspace panels, and watcher-driven cache invalidation remain separate follow-up slices.

## 2. Existing Constraint

`createCodingProjectionStore()` currently reduces an event and immediately calls every subscriber. A burst of 10,000 contiguous events therefore creates 10,000 external-store notifications even though intermediate states are not useful to React.

The existing durable rules remain authoritative:

- events with `seq <= appliedSeq` are ignored;
- a sequence gap is represented explicitly and must not apply the out-of-order event;
- snapshot hydration replaces the projection at one consistent `head_seq`;
- snapshot plus replay plus live tail must converge with uninterrupted replay.

## 3. Chosen Architecture

The store owns two state references:

- `workingState`: updated synchronously for every accepted event;
- `publishedState`: returned by `getSnapshot()` and visible to subscribers.

`applyEvent(event)` reduces against `workingState` immediately. If the event is a normal contiguous event, the store schedules one frame publish. Further events in the same frame update `workingState` without scheduling additional callbacks. At the callback, `publishedState` becomes the latest `workingState` and subscribers are notified once.

The store accepts an injectable scheduler:

```ts
export type CodingFrameScheduler = {
  request(callback: () => void): number;
  cancel(handle: number): void;
};
```

The browser default uses `requestAnimationFrame`. If it is unavailable, the scheduler uses a bounded timer fallback. Tests inject a manual scheduler so they do not depend on wall-clock timing or a DOM.

Each scheduled callback also captures a monotonically increasing generation. Cancel, snapshot replacement, immediate gap publish, flush, and dispose advance that generation. A callback whose generation is no longer current returns without publishing, even if the underlying scheduler invokes it after cancellation.

## 4. Immediate Publish Boundaries

Some transitions must not wait for the next frame:

1. `replaceSnapshot()` cancels an outstanding frame, replaces both state references, and publishes immediately. This prevents a stale queued frame from overwriting a newly hydrated snapshot.
2. A newly detected sequence gap publishes immediately so the connection layer can stop rendering the stale stream and initiate durable recovery.
3. `setConnectionBasis()` publishes immediately because `caught_up` is a transport boundary shown directly in the UI.
4. `flush()` publishes the latest working state synchronously when a caller needs a deterministic boundary.
5. `dispose()` cancels the scheduled callback, clears subscribers, and prevents future scheduling or notification.

Duplicate or already-applied events do not schedule or publish because the reducer returns the same state reference.

## 5. Store Interface

```ts
export type CodingProjectionStore = {
  getSnapshot(): CodingProjectionState;
  subscribe(listener: () => void): () => void;
  replaceSnapshot(snapshot: CodingProjectionSnapshot): void;
  applyEvent(event: CodingEvent): void;
  setConnectionBasis(basis: CodingProjectionState["connectionBasis"]): void;
  flush(): void;
  dispose(): void;
};

export function createCodingProjectionStore(
  taskId: string,
  scheduler?: CodingFrameScheduler
): CodingProjectionStore;
```

The public cached store returned by `getCodingProjectionStore(taskId)` uses the browser scheduler. Scheduler injection is limited to directly created stores in tests.

## 6. Data Flow

```text
WebSocket/replay event
  -> reduce workingState immediately
  -> duplicate: stop
  -> gap: cancel frame + immediate publish
  -> contiguous: request one frame if none is pending
  -> more contiguous events update workingState only
  -> frame callback copies latest workingState to publishedState
  -> one subscriber notification
  -> React useSyncExternalStore render
```

This batching changes render cadence, not durable cursor handling. `useCodingStream()` may continue to update `afterSeq` and local storage for every contiguous event.

## 7. Lifecycle and Error Handling

- A scheduler callback is considered single-use. Its handle is cleared before notifying listeners so a listener-triggered event can schedule the next frame safely. A stale callback generation is a no-op.
- Listener exceptions do not prevent other listeners from receiving the publish. The store rethrows the first captured exception after completing notification, matching fail-visible behavior without starving subscribers.
- Calls after `dispose()` are no-ops. `getSnapshot()` continues returning the last published state.
- Snapshot replacement always wins over an older scheduled publish.
- A gap remains published until snapshot hydration or a valid replacement state clears it.

## 8. Performance and Correctness Tests

Deterministic source tests cover:

1. 10,000 contiguous no-op/status events schedule exactly one frame and notify exactly once.
2. Before the manual frame runs, `getSnapshot()` returns the previous published state; after it runs, `appliedSeq` is 10,000.
3. Batched final state deeply equals the state produced by direct reducer replay.
4. Duplicate events do not schedule a frame.
5. A sequence gap publishes immediately and cancels a pending frame.
6. Snapshot replacement cancels a pending frame and cannot be overwritten by invoking an obsolete callback.
7. `dispose()` cancels pending work and prevents later notifications.
8. Existing snapshot/replay/live convergence tests remain unchanged and pass.

The 10,000-event fixture asserts notification count and deterministic state rather than a machine-dependent millisecond threshold. Optional timing may be reported locally but is not a CI gate.

## 9. Rollout and Compatibility

No backend, event schema, REST, or WebSocket protocol changes are required. The change is confined to the browser projection store and its source tests.

Rollback restores immediate notification without changing persisted state. Because `workingState` uses the existing pure reducer, batching can be disabled without data migration or replay incompatibility.

## 10. Acceptance Criteria

- A burst of 10,000 contiguous events produces one scheduled frame and one subscriber notification.
- The published final projection equals uninterrupted reducer replay.
- gap, snapshot, connection-basis, flush, and dispose boundaries are deterministic.
- no scheduled callback can overwrite a newer snapshot.
- the full frontend source suite and `tsc --noEmit` pass.
- backend contracts and user-owned workspace changes are untouched.

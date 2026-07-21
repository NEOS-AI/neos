# Coding Projection Frame Batching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Coalesce coding projection subscriber notifications to one animation-frame publish while preserving synchronous reducer correctness and snapshot/gap recovery boundaries.

**Architecture:** `createCodingProjectionStore()` will keep a synchronous working projection separate from the published projection returned to React. A generation-fenced, injectable scheduler publishes the newest working state once per frame; snapshot, gap, connection, flush, and disposal boundaries cancel pending work and publish deterministically.

**Tech Stack:** TypeScript, React `useSyncExternalStore`, `requestAnimationFrame`, Node test runner via `tsx`.

## Global Constraints

- Do not change backend, REST, WebSocket, or coding event schemas.
- Preserve `seq <= appliedSeq` duplicate suppression and explicit sequence-gap semantics.
- Snapshot replacement must win over every previously scheduled callback.
- CI performance assertions use notification and scheduler counts, not wall-clock thresholds.
- Do not add a new runtime dependency.
- Preserve the user's unrelated `.env.template` and untracked deep-analysis documents.

---

### Task 1: Generation-Fenced Frame Scheduler and Projection Store

**Files:**
- Modify: `web/features/coding/stream/coding-projection-store.ts`
- Create: `web/tests/source/coding-projection-frame-batching.test.ts`

**Interfaces:**
- Consumes: `reduceProjectionEvent()`, `reduceSnapshot()`, `CodingProjectionState`, `CodingProjectionSnapshot`, and `CodingEvent`.
- Produces: `CodingFrameScheduler`, `CodingProjectionStore`, `createCodingProjectionStore(taskId, scheduler?)`, `flush()`, and `dispose()`.

- [ ] **Step 1: Write a manual scheduler and failing batching tests**

Create `web/tests/source/coding-projection-frame-batching.test.ts` with a deterministic scheduler that retains cancelled callbacks so generation fencing can be tested:

```ts
import assert from "node:assert/strict";
import test from "node:test";
import {
  createCodingProjectionStore,
  type CodingFrameScheduler,
} from "../../features/coding/stream/coding-projection-store";
import type { CodingEvent } from "../../features/coding/types/events";

class ManualScheduler implements CodingFrameScheduler {
  callbacks = new Map<number, () => void>();
  cancelled: number[] = [];
  requested = 0;

  request(callback: () => void) {
    const handle = ++this.requested;
    this.callbacks.set(handle, callback);
    return handle;
  }

  cancel(handle: number) {
    this.cancelled.push(handle);
  }

  run(handle = this.requested) {
    this.callbacks.get(handle)?.();
  }
}

const event = (seq: number): CodingEvent => ({
  v: 1,
  task_id: "ct_1",
  seq,
  event_id: `ce_${seq}`,
  type: "task.status.changed",
  ts: "2026-07-21T00:00:00Z",
  payload: { status: seq % 2 ? "running" : "queued" },
});

test("a burst schedules and publishes once", () => {
  const scheduler = new ManualScheduler();
  const store = createCodingProjectionStore("ct_1", scheduler);
  let notifications = 0;
  store.subscribe(() => notifications++);

  for (let seq = 1; seq <= 100; seq++) store.applyEvent(event(seq));

  assert.equal(scheduler.requested, 1);
  assert.equal(store.getSnapshot().appliedSeq, 0);
  scheduler.run();
  assert.equal(notifications, 1);
  assert.equal(store.getSnapshot().appliedSeq, 100);
});
```

Add separate tests for duplicate suppression, immediate gap publish, snapshot replacement with an obsolete callback invocation, `flush()`, and `dispose()`. Add the 10,000-event direct-reducer equivalence test from Task 2 Step 1 at this red-test stage as well, so notification count and final-state convergence fail before the implementation exists.

- [ ] **Step 2: Run the new tests and verify the current immediate store fails**

Run:

```bash
cd web
PATH=/Users/ywsung/.nvm/versions/node/v22.19.0/bin:/Users/ywsung/Library/pnpm:$PATH \
  pnpm exec tsx --test tests/source/coding-projection-frame-batching.test.ts
```

Expected: compilation or assertion failure because scheduler injection, `flush()`, and `dispose()` do not exist and current events notify immediately.

- [ ] **Step 3: Add the scheduler and split working/published state**

Implement these exported contracts in `coding-projection-store.ts`:

```ts
export type CodingFrameScheduler = {
  request(callback: () => void): number;
  cancel(handle: number): void;
};

export type CodingProjectionStore = {
  getSnapshot(): CodingProjectionState;
  subscribe(listener: () => void): () => void;
  replaceSnapshot(snapshot: CodingProjectionSnapshot): void;
  applyEvent(event: CodingEvent): void;
  setConnectionBasis(basis: CodingProjectionState["connectionBasis"]): void;
  flush(): void;
  dispose(): void;
};

const browserFrameScheduler: CodingFrameScheduler = {
  request(callback) {
    if (typeof requestAnimationFrame === "function") {
      return requestAnimationFrame(callback);
    }
    return setTimeout(callback, 16) as unknown as number;
  },
  cancel(handle) {
    if (typeof cancelAnimationFrame === "function") {
      cancelAnimationFrame(handle);
    }
    clearTimeout(handle);
  },
};
```

Inside `createCodingProjectionStore`, maintain `workingState`, `publishedState`, `scheduledHandle`, `generation`, and `disposed`. Implement:

```ts
function cancelScheduled() {
  generation += 1;
  if (scheduledHandle !== null) scheduler.cancel(scheduledHandle);
  scheduledHandle = null;
}

function publishNow() {
  if (disposed || publishedState === workingState) return;
  publishedState = workingState;
  emit();
}

function schedulePublish() {
  if (disposed || scheduledHandle !== null) return;
  const scheduledGeneration = ++generation;
  scheduledHandle = scheduler.request(() => {
    if (disposed || scheduledGeneration !== generation) return;
    scheduledHandle = null;
    publishNow();
  });
}
```

`applyEvent` must reduce synchronously, skip when the same reference is returned, immediately publish a newly introduced gap, and otherwise call `schedulePublish()`. `replaceSnapshot`, `setConnectionBasis`, and `flush` call `cancelScheduled()` before immediate publish. `dispose` cancels, marks disposed, and clears listeners.

When emitting, invoke every subscriber even if one throws; capture and rethrow the first error after the loop.

- [ ] **Step 4: Run focused tests and TypeScript**

Run:

```bash
cd web
PATH=/Users/ywsung/.nvm/versions/node/v22.19.0/bin:/Users/ywsung/Library/pnpm:$PATH \
  pnpm exec tsx --test tests/source/coding-projection-frame-batching.test.ts \
  tests/source/coding-projection-store.test.ts \
  tests/source/coding-approval-projection.test.ts
/Users/ywsung/Library/pnpm/pnpm exec tsc --noEmit
```

Expected: all focused tests and type checking pass. Restore generated `web/tsconfig.tsbuildinfo` afterward.

- [ ] **Step 5: Commit the store boundary**

```bash
git add web/features/coding/stream/coding-projection-store.ts \
  web/tests/source/coding-projection-frame-batching.test.ts
git commit -m "perf(coding): batch projection publishes by frame"
```

### Task 2: Replay Integration and Phase 4 Operations Contract

**Files:**
- Modify: `web/tests/source/coding-projection-frame-batching.test.ts`
- Modify: `web/tests/source/coding-projection-store.test.ts`
- Modify: `docs/NEOS_CODING.md`

**Interfaces:**
- Consumes: `CodingProjectionStore` and the manual scheduler from Task 1.
- Produces: deterministic 10,000-event performance coverage and documented batching/recovery behavior.

- [ ] **Step 1: Complete the 10,000-event equivalence fixture**

Add a test that constructs 10,000 contiguous events, applies them through the store without running the manual frame, and separately reduces them directly:

```ts
test("10k batched events equal uninterrupted reducer replay", () => {
  const scheduler = new ManualScheduler();
  const store = createCodingProjectionStore("ct_1", scheduler);
  let notifications = 0;
  store.subscribe(() => notifications++);
  const events = Array.from({ length: 10_000 }, (_, index) => event(index + 1));
  const direct = events.reduce(reduceProjectionEvent, emptyProjection("ct_1"));

  for (const item of events) store.applyEvent(item);
  assert.equal(scheduler.requested, 1);
  assert.equal(notifications, 0);
  scheduler.run();

  assert.deepEqual(store.getSnapshot(), direct);
  assert.equal(notifications, 1);
});
```

This test was introduced during Task 1's red phase. In this step, review it for exact 10,000-event coverage, direct reducer equivalence, one scheduled callback, and one notification; add any missing assertion before the full regression run.

- [ ] **Step 2: Add snapshot/replay/live regression coverage**

Extend `coding-projection-store.test.ts` so the same tail is applied through a frame-batched store after `replaceSnapshot(snapshotAtSeq4)`. Assert the final store snapshot deeply equals uninterrupted live reducer state after a manual scheduler flush.

- [ ] **Step 3: Document batching and operational boundaries**

Add a Phase 4 implementation checkpoint to `docs/NEOS_CODING.md` containing:

- working versus published projection state;
- one subscriber notification per frame burst;
- immediate snapshot, gap, connection-basis, and explicit flush boundaries;
- generation fencing against stale cancelled callbacks;
- deterministic 10k acceptance test and no wall-clock CI threshold;
- rollback by restoring immediate publish with no protocol or data migration.

- [ ] **Step 4: Run complete frontend verification**

Run:

```bash
cd web
PATH=/Users/ywsung/.nvm/versions/node/v22.19.0/bin:/Users/ywsung/Library/pnpm:$PATH \
  pnpm run test:source
/Users/ywsung/Library/pnpm/pnpm exec tsc --noEmit
```

Expected: the full source suite passes with the new tests included, and TypeScript exits zero. Restore `web/tsconfig.tsbuildinfo` after type checking.

- [ ] **Step 5: Run static and workspace checks**

Run:

```bash
git diff --check
git status --short
```

Expected: only the Task 2 files are modified, plus the pre-existing user-owned `.env.template` and three untracked deep-analysis documents.

- [ ] **Step 6: Commit the performance contract**

```bash
git add web/tests/source/coding-projection-frame-batching.test.ts \
  web/tests/source/coding-projection-store.test.ts docs/NEOS_CODING.md
git commit -m "test(coding): verify 10k projection replay batching"
```

## Final Review Checklist

- [ ] `workingState` advances for every accepted event before a frame runs.
- [ ] `getSnapshot()` changes only at a publish boundary.
- [ ] duplicates neither schedule nor notify.
- [ ] a gap is visible immediately and does not apply the out-of-order event.
- [ ] snapshot replacement and explicit flush invalidate obsolete callbacks.
- [ ] listener failures do not starve other subscribers.
- [ ] disposal prevents callbacks and notifications.
- [ ] 10,000 events schedule once, notify once, and equal direct replay.
- [ ] existing approval, phase, snapshot, and connection source tests pass.
- [ ] no backend or protocol files changed.

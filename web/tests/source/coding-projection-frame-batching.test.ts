import assert from "node:assert/strict";
import test from "node:test";
import {
  createCodingProjectionStore,
  type CodingFrameScheduler,
} from "../../features/coding/stream/coding-projection-store";
import {
  emptyProjection,
  reduceProjectionEvent,
} from "../../features/coding/stream/projection-reducer";
import type { CodingEvent } from "../../features/coding/types/events";
import type { CodingProjectionSnapshot } from "../../features/coding/types/projection";

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

const snapshot = (headSeq: number): CodingProjectionSnapshot => ({
  task: {
    task_id: "ct_1",
    status: "running",
    version: 1,
    last_seq: headSeq,
    created_at: "2026-07-21T00:00:00Z",
    updated_at: "2026-07-21T00:00:00Z",
  },
  active_run: null,
  phases: [],
  tools: [],
  approvals: [],
  todos: [],
  workspace: { revision: `rev_${headSeq}`, git_head: null, changed_files: [] },
  latest_checkpoint: null,
  head_seq: headSeq,
  connection_basis: "checkpoint",
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

test("duplicates neither schedule nor notify", () => {
  const scheduler = new ManualScheduler();
  const store = createCodingProjectionStore("ct_1", scheduler);
  let notifications = 0;
  store.subscribe(() => notifications++);
  store.applyEvent(event(1));
  scheduler.run();

  store.applyEvent(event(1));

  assert.equal(scheduler.requested, 1);
  assert.equal(notifications, 1);
});

test("a gap cancels the frame and publishes immediately", () => {
  const scheduler = new ManualScheduler();
  const store = createCodingProjectionStore("ct_1", scheduler);
  let notifications = 0;
  store.subscribe(() => notifications++);
  store.applyEvent(event(1));

  store.applyEvent(event(3));

  assert.deepEqual(scheduler.cancelled, [1]);
  assert.equal(notifications, 1);
  assert.equal(store.getSnapshot().appliedSeq, 1);
  assert.deepEqual(store.getSnapshot().gap, { expected: 2, received: 3 });
  scheduler.run(1);
  assert.equal(notifications, 1);
});

test("snapshot replacement fences an obsolete callback", () => {
  const scheduler = new ManualScheduler();
  const store = createCodingProjectionStore("ct_1", scheduler);
  let notifications = 0;
  store.subscribe(() => notifications++);
  store.applyEvent(event(1));

  store.replaceSnapshot(snapshot(40));

  assert.deepEqual(scheduler.cancelled, [1]);
  assert.equal(store.getSnapshot().appliedSeq, 40);
  assert.equal(notifications, 1);
  scheduler.run(1);
  assert.equal(store.getSnapshot().appliedSeq, 40);
  assert.equal(notifications, 1);
});

test("flush publishes synchronously and fences its frame", () => {
  const scheduler = new ManualScheduler();
  const store = createCodingProjectionStore("ct_1", scheduler);
  let notifications = 0;
  store.subscribe(() => notifications++);
  store.applyEvent(event(1));

  store.flush();

  assert.equal(store.getSnapshot().appliedSeq, 1);
  assert.equal(notifications, 1);
  scheduler.run(1);
  assert.equal(notifications, 1);
});

test("dispose cancels pending work and ignores later writes", () => {
  const scheduler = new ManualScheduler();
  const store = createCodingProjectionStore("ct_1", scheduler);
  let notifications = 0;
  store.subscribe(() => notifications++);
  store.applyEvent(event(1));

  store.dispose();
  scheduler.run(1);
  store.applyEvent(event(2));
  store.flush();

  assert.deepEqual(scheduler.cancelled, [1]);
  assert.equal(notifications, 0);
  assert.equal(store.getSnapshot().appliedSeq, 0);
});

test("one listener failure does not starve the remaining listeners", () => {
  const scheduler = new ManualScheduler();
  const store = createCodingProjectionStore("ct_1", scheduler);
  let observed = 0;
  store.subscribe(() => {
    throw new Error("listener failed");
  });
  store.subscribe(() => observed++);
  store.applyEvent(event(1));

  assert.throws(() => store.flush(), /listener failed/);
  assert.equal(observed, 1);
  assert.equal(store.getSnapshot().appliedSeq, 1);
});

import assert from "node:assert/strict";
import test from "node:test";
import { emptyProjection, reduceProjectionEvent, reduceSnapshot } from "../../features/coding/stream/projection-reducer";
import { createCodingProjectionStore, type CodingFrameScheduler } from "../../features/coding/stream/coding-projection-store";
import type { CodingEvent } from "../../features/coding/types/events";
import type { CodingProjectionSnapshot } from "../../features/coding/types/projection";

const event = (seq: number, type: string, payload: Record<string, unknown>): CodingEvent => ({
  v: 1, task_id: "ct_1", seq, event_id: `ce_${seq}`, type,
  ts: "2026-07-22T00:00:00Z", payload, run_id: "cr_1", turn_id: "turn_1",
});

class ManualScheduler implements CodingFrameScheduler {
  callback: (() => void) | null = null;
  requests = 0;
  request(callback: () => void) { this.requests += 1; this.callback = callback; return this.requests; }
  cancel() { this.callback = null; }
}

test("text lifecycle concatenates unicode and completes one ordered part", () => {
  const events = [
    event(1, "model.text_part.started", { part_id: "part_1", interrupted_part_ids: [] }),
    event(2, "model.text_delta", { part_id: "part_1", delta: "안" }),
    event(3, "model.text_delta", { part_id: "part_1", delta: "녕" }),
    event(4, "model.text_part.completed", { part_id: "part_1", status: "completed" }),
  ];
  const state = events.reduce(reduceProjectionEvent, emptyProjection("ct_1"));
  assert.equal(state.textPartsById.part_1.content, "안녕");
  assert.equal(state.textPartsById.part_1.status, "completed");
  assert.deepEqual(state.orderedTextPartIds, ["part_1"]);
});

test("unknown part requests resync without advancing cursor", () => {
  const state = reduceProjectionEvent(
    emptyProjection("ct_1"),
    event(1, "model.text_delta", { part_id: "missing", delta: "x" })
  );
  assert.equal(state.appliedSeq, 0);
  assert.deepEqual(state.projectionIssue, { code: "unknown_text_part", eventSeq: 1 });
});

test("snapshot sorts parts and clears projection issue", () => {
  const snapshot = {
    task: { task_id: "ct_1", status: "running", version: 1, last_seq: 5, created_at: "x", updated_at: "x" },
    active_run: null, phases: [], tools: [], approvals: [], todos: [],
    workspace: { revision: "1", git_head: null, changed_files: [] }, latest_checkpoint: null,
    head_seq: 5, connection_basis: "checkpoint",
    parts: [
      { part_id: "b", run_id: "cr_1", turn_id: "t2", status: "streaming", content: "b", first_seq: 4, last_seq: 5 },
      { part_id: "a", run_id: "cr_1", turn_id: "t1", status: "completed", content: "a", first_seq: 1, last_seq: 3 },
    ],
  } satisfies CodingProjectionSnapshot;
  assert.deepEqual(reduceSnapshot(snapshot).orderedTextPartIds, ["a", "b"]);
});

test("unknown part store outcome requests resync without publishing a cursor advance", () => {
  const store = createCodingProjectionStore("ct_1", new ManualScheduler());
  assert.equal(
    store.applyEvent(event(1, "model.text_delta", { part_id: "missing", delta: "x" })),
    "resync_required"
  );
  assert.equal(store.getSnapshot().appliedSeq, 0);
});

test("10k text events remain one frame publication", () => {
  const scheduler = new ManualScheduler();
  const store = createCodingProjectionStore("ct_1", scheduler);
  store.applyEvent(event(1, "model.text_part.started", { part_id: "part_1", interrupted_part_ids: [] }));
  for (let seq = 2; seq <= 10_000; seq += 1) {
    store.applyEvent(event(seq, "model.text_delta", { part_id: "part_1", delta: "x" }));
  }
  assert.equal(scheduler.requests, 1);
  scheduler.callback?.();
  assert.equal(store.getSnapshot().textPartsById.part_1.content.length, 9_999);
});

import assert from "node:assert/strict";
import test from "node:test";
import {
  emptyProjection,
  reduceProjectionEvent,
  reduceSnapshot,
} from "../../features/coding/stream/projection-reducer";
import type { CodingEvent } from "../../features/coding/types/events";
import type { CodingProjectionSnapshot } from "../../features/coding/types/projection";

const REFUSED = { stop_reason: "refusal", stop_category: "cyber" };

const refusedEvent = (seq: number): CodingEvent => ({
  v: 1,
  task_id: "ct_1",
  seq,
  event_id: `ce_${seq}`,
  type: "model.refused",
  ts: "2026-09-23T00:00:00Z",
  payload: REFUSED,
  run_id: "cr_2",
  turn_id: "turn_1",
  tool_call_id: null,
});

const snapshot = (
  overrides: Partial<CodingProjectionSnapshot>
): CodingProjectionSnapshot => ({
  task: {
    task_id: "ct_1",
    status: "failed",
    version: 1,
    last_seq: 9,
    created_at: "2026-09-23T00:00:00Z",
    updated_at: "2026-09-23T00:00:00Z",
  } as CodingProjectionSnapshot["task"],
  active_run: null,
  phases: [],
  tools: [],
  approvals: [],
  parts: [],
  todos: [],
  workspace: { revision: "r1", git_head: null, changed_files: [] },
  latest_checkpoint: null,
  head_seq: 9,
  connection_basis: "checkpoint",
  ...overrides,
});

test("a snapshot refusal reads exactly like the live one", () => {
  // One decoder for both paths; a refresh must not change the banner.
  const live = reduceProjectionEvent(
    { ...emptyProjection("ct_1"), appliedSeq: 6 },
    refusedEvent(7)
  ).refusal;
  const restored = reduceSnapshot(
    snapshot({ refusal: { run_id: "cr_2", seq: 7, payload: REFUSED } })
  ).refusal;
  assert.notEqual(live, null);
  assert.deepEqual(restored, live);
});

test("a snapshot without a refusal restores none", () => {
  assert.equal(reduceSnapshot(snapshot({})).refusal, null);
  assert.equal(reduceSnapshot(snapshot({ refusal: null })).refusal, null);
});

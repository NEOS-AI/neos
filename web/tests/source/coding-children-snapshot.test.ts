import assert from "node:assert/strict";
import test from "node:test";
import {
  emptyProjection,
  reduceProjectionEvent,
  reduceSnapshot,
} from "../../features/coding/stream/projection-reducer";
import type { CodingEvent } from "../../features/coding/types/events";
import type {
  CodingChildEventSnapshot,
  CodingProjectionSnapshot,
} from "../../features/coding/types/projection";

// A reconnect starts from the snapshot. The checkpoint's active_children only
// knows who was running when it was taken; the ledger's subagent.* events know
// how each child ended. These pin that the ledger wins, and that it is read by
// the same decoder as the live stream.

const snapshot = (
  overrides: Partial<CodingProjectionSnapshot>
): CodingProjectionSnapshot => ({
  task: {
    task_id: "ct_1",
    status: "running",
    version: 1,
    last_seq: 20,
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
  head_seq: 20,
  connection_basis: "checkpoint",
  ...overrides,
});

const row = (
  seq: number,
  type: string,
  payload: Record<string, unknown>
): CodingChildEventSnapshot => ({ type, seq, payload });

const live = (row: CodingChildEventSnapshot): CodingEvent => ({
  v: 1,
  task_id: "ct_1",
  seq: row.seq,
  event_id: `ce_${row.seq}`,
  type: row.type,
  ts: "2026-09-23T00:00:00Z",
  payload: row.payload,
  run_id: "cr_1",
  turn_id: "turn_1",
  tool_call_id: "t_spawn",
});

const STARTED = {
  run_id: "sa_1",
  spec: "explore",
  parent_tool_call_id: "t_spawn",
  status: "pending",
  turn_count: 0,
  tool_count: 0,
};

test("a child the checkpoint lists as running but the ledger stalled comes back failed", () => {
  const state = reduceSnapshot(
    snapshot({
      active_children: [{ run_id: "sa_1", status: "running", spec: "explore" }],
      child_events: [
        row(3, "subagent.started", STARTED),
        row(4, "subagent.step", {
          run_id: "sa_1",
          status: "running",
          turn_count: 1,
          tool_count: 1,
        }),
        row(12, "subagent.failed", { run_id: "sa_1", error_code: "stalled" }),
      ],
    })
  );
  const child = state.childrenById.sa_1;
  assert.equal(child?.status, "failed");
  assert.equal(child?.end_reason, "stalled");
  assert.equal(child?.spec, "explore");
});

test("a completed child the checkpoint no longer lists is restored", () => {
  const state = reduceSnapshot(
    snapshot({
      active_children: [],
      child_events: [
        row(3, "subagent.started", STARTED),
        row(9, "subagent.completed", {
          run_id: "sa_1",
          status: "completed",
          turn_count: 4,
          tool_count: 3,
        }),
      ],
    })
  );
  assert.deepEqual(Object.keys(state.childrenById), ["sa_1"]);
  assert.equal(state.childrenById.sa_1?.status, "completed");
  assert.equal(state.childrenById.sa_1?.turn_count, 4);
  assert.equal(state.childrenById.sa_1?.parent_tool_call_id, "t_spawn");
});

test("a restored child is the child the live stream would have built", () => {
  const rows = [
    row(1, "subagent.started", STARTED),
    row(2, "subagent.step", {
      run_id: "sa_1",
      status: "running",
      turn_count: 1,
      tool_count: 2,
    }),
    row(3, "subagent.cancelled", { run_id: "sa_1", reason: "parent_cancelled" }),
  ];
  // Consecutive seqs from an empty basis, or the reducer records a gap.
  const replayed = rows
    .map(live)
    .reduce(reduceProjectionEvent, emptyProjection("ct_1"));
  assert.equal(replayed.gap, null);

  // Handed over out of order: the fold is by seq, not by arrival.
  const restored = reduceSnapshot(
    snapshot({ head_seq: 3, child_events: [rows[2], rows[0], rows[1]] })
  );
  assert.deepEqual(restored.childrenById, replayed.childrenById);
  assert.equal(restored.childrenById.sa_1?.status, "killed");
});

test("spec survives when the latest event forgot it", () => {
  // Terminal rows written before 27674084 carry no spec or counts.
  const state = reduceSnapshot(
    snapshot({
      child_events: [
        row(3, "subagent.started", STARTED),
        row(7, "subagent.failed", { run_id: "sa_1", error_code: "stalled" }),
      ],
    })
  );
  assert.equal(state.childrenById.sa_1?.spec, "explore");
  assert.equal(state.childrenById.sa_1?.status, "failed");
});

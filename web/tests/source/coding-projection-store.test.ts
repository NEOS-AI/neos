import assert from "node:assert/strict";
import test from "node:test";
import {
  emptyProjection,
  reduceProjectionEvent,
  reduceSnapshot,
} from "../../features/coding/stream/projection-reducer";
import type { CodingEvent } from "../../features/coding/types/events";
import type { CodingProjectionSnapshot } from "../../features/coding/types/projection";

const event = (
  seq: number,
  type: string,
  payload: Record<string, unknown>,
  toolCallId?: string
): CodingEvent => ({
  v: 1,
  task_id: "ct_1",
  seq,
  event_id: `ce_${seq}`,
  type,
  ts: "2026-07-19T00:00:00Z",
  payload,
  run_id: "cr_1",
  tool_call_id: toolCallId,
});

const events = [
  event(1, "phase.started", { phase: "understand", attempt: 1 }),
  event(2, "tool.completed", { result: { ok: true } }, "tool_1"),
  event(3, "phase.completed", { phase: "understand", attempt: 1 }),
  event(4, "phase.started", { phase: "plan", attempt: 1 }),
  event(5, "phase.completed", { phase: "plan", attempt: 1 }),
];

const snapshotAtSeq4: CodingProjectionSnapshot = {
  task: {
    task_id: "ct_1",
    status: "running",
    version: 1,
    last_seq: 4,
    created_at: "2026-07-19T00:00:00Z",
    updated_at: "2026-07-19T00:00:00Z",
  },
  active_run: null,
  phases: [
    {
      phase_id: "phase_1",
      run_id: "cr_1",
      kind: "understand",
      attempt: 1,
      status: "completed",
      started_at: "2026-07-19T00:00:00Z",
      completed_at: "2026-07-19T00:00:00Z",
    },
    {
      phase_id: "phase_2",
      run_id: "cr_1",
      kind: "plan",
      attempt: 1,
      status: "active",
      started_at: "2026-07-19T00:00:00Z",
      completed_at: null,
    },
  ],
  tools: [
    {
      tool_call_id: "tool_1",
      run_id: "cr_1",
      status: "completed",
      result: { ok: true },
    },
  ],
  approvals: [],
  todos: [],
  workspace: { revision: "rev_4", git_head: null, changed_files: [] },
  latest_checkpoint: null,
  head_seq: 4,
  connection_basis: "checkpoint",
};

test("snapshot plus replay converges with uninterrupted live projection", () => {
  const live = events.reduce(reduceProjectionEvent, emptyProjection("ct_1"));
  const restored = events
    .slice(4)
    .reduce(reduceProjectionEvent, reduceSnapshot(snapshotAtSeq4));

  assert.deepEqual(restored.phases, live.phases);
  assert.deepEqual(restored.toolsById, live.toolsById);
  assert.equal(restored.appliedSeq, live.appliedSeq);
});

test("phase history appends a second attempt", () => {
  const state = [
    event(1, "phase.started", { phase: "understand", attempt: 1 }),
    event(2, "phase.started", { phase: "plan", attempt: 1 }),
    event(3, "phase.started", { phase: "implement", attempt: 1 }),
    event(4, "phase.started", { phase: "understand", attempt: 2 }),
  ].reduce(reduceProjectionEvent, emptyProjection("ct_1"));

  assert.deepEqual(
    state.phases.map((phase) => [phase.kind, phase.attempt]),
    [
      ["understand", 1],
      ["plan", 1],
      ["implement", 1],
      ["understand", 2],
    ]
  );
});

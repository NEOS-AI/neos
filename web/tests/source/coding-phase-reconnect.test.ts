import assert from "node:assert/strict";
import test from "node:test";
import { createCodingProjectionStore } from "../../features/coding/stream/coding-projection-store";
import type { CodingEvent } from "../../features/coding/types/events";
import type { CodingProjectionSnapshot } from "../../features/coding/types/projection";

const at = "2026-07-19T00:00:00Z";

const event = (seq: number, type: string, phase: string): CodingEvent => ({
  v: 1,
  task_id: "ct_1",
  seq,
  event_id: `ce_${seq}`,
  type,
  ts: at,
  payload: { phase, attempt: 1 },
  run_id: "cr_1",
});

const snapshotAtSeq10: CodingProjectionSnapshot = {
  task: {
    task_id: "ct_1",
    status: "running",
    version: 1,
    last_seq: 10,
    created_at: at,
    updated_at: at,
  },
  active_run: {
    run_id: "cr_1",
    attempt: 1,
    status: "running",
    resume_from_checkpoint_id: null,
  },
  phases: [
    {
      phase_id: "cp_understand_1",
      run_id: "cr_1",
      kind: "understand",
      attempt: 1,
      status: "completed",
      started_at: at,
      completed_at: at,
    },
  ],
  tools: [],
  approvals: [],
  todos: [],
  workspace: { revision: "rev_10", git_head: null, changed_files: [] },
  latest_checkpoint: { checkpoint_id: "cc_10", seq: 10 },
  head_seq: 10,
  connection_basis: "checkpoint",
};

const replay = [
  event(11, "phase.started", "plan"),
  event(12, "phase.completed", "plan"),
  event(13, "phase.started", "implement"),
  event(14, "phase.completed", "implement"),
];

test("restored checkpoint becomes live after replay", () => {
  const restored = createCodingProjectionStore("ct_1");
  restored.replaceSnapshot(snapshotAtSeq10);
  assert.equal(restored.getSnapshot().connectionBasis, "checkpoint");

  for (const next of replay) restored.applyEvent(next);
  restored.setConnectionBasis("live");

  const uninterrupted = createCodingProjectionStore("ct_1");
  uninterrupted.replaceSnapshot(snapshotAtSeq10);
  for (const next of replay) uninterrupted.applyEvent(next);
  uninterrupted.flush();

  assert.equal(restored.getSnapshot().appliedSeq, 14);
  assert.equal(restored.getSnapshot().connectionBasis, "live");
  assert.deepEqual(
    restored.getSnapshot().phases,
    uninterrupted.getSnapshot().phases
  );
});

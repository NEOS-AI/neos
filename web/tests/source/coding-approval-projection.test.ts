import assert from "node:assert/strict";
import test from "node:test";
import {
  emptyProjection,
  reduceProjectionEvent,
  reduceSnapshot,
} from "@/features/coding/stream/projection-reducer";
import type { CodingProjectionSnapshot } from "@/features/coding/types/projection";
import type { CodingEvent } from "@/features/coding/types/events";

const approval = {
  approval_id: "ca_1",
  tool_name: "write_file.v1",
  risk: "workspace_write" as const,
  status: "pending" as const,
  requested_at: "2026-07-21T00:00:00Z",
  expires_at: "2026-07-21T00:15:00Z",
  display_summary: { path: "app.py" },
};

const snapshot = (): CodingProjectionSnapshot => ({
  task: { task_id: "ct_1", status: "waiting_approval", version: 1, last_seq: 1,
    created_at: approval.requested_at, updated_at: approval.requested_at },
  active_run: null, phases: [], tools: [], approvals: [approval], todos: [],
  workspace: { revision: "rev_1", git_head: null, changed_files: [] },
  latest_checkpoint: null, head_seq: 1, connection_basis: "checkpoint",
});

const event = (seq: number, type: string, payload: Record<string, unknown>): CodingEvent => ({
  v: 1, task_id: "ct_1", seq, event_id: `ce_${seq}`, type,
  ts: approval.requested_at, payload,
});

test("snapshot and live approval request converge", () => {
  const fromSnapshot = reduceSnapshot(snapshot()).approvalsById;
  const fromLive = reduceProjectionEvent(
    emptyProjection("ct_1"), event(1, "approval.requested", approval)
  ).approvalsById;
  assert.deepEqual(fromLive, fromSnapshot);
});

test("resolution and task status update durable projection", () => {
  const resolved = reduceProjectionEvent(
    reduceSnapshot(snapshot()), event(2, "approval.denied", { ...approval, status: "denied" })
  );
  const running = reduceProjectionEvent(
    resolved, event(3, "task.status.changed", { status: "running" })
  );
  assert.equal(running.approvalsById.ca_1.status, "denied");
  assert.equal(running.taskStatus, "running");
});

test("snapshot plus live tail equals full approval replay", () => {
  const requested = event(1, "approval.requested", approval);
  const waiting = event(2, "task.status.changed", { status: "waiting_approval" });
  const approved = event(3, "approval.approved", { ...approval, status: "approved" });
  const running = event(4, "task.status.changed", { status: "running" });
  const replayed = [requested, waiting, approved, running].reduce(
    reduceProjectionEvent, emptyProjection("ct_1")
  );
  const restored = [approved, running].reduce(reduceProjectionEvent, {
    ...reduceSnapshot(snapshot()), appliedSeq: 2,
  });
  assert.deepEqual(restored.approvalsById, replayed.approvalsById);
  assert.equal(restored.taskStatus, replayed.taskStatus);
});

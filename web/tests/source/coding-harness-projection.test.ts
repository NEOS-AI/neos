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
  ids: Partial<Pick<CodingEvent, "run_id" | "tool_call_id">> = {}
): CodingEvent => ({
  v: 1,
  task_id: "ct_1",
  seq,
  event_id: `ce_${seq}`,
  type,
  ts: "2026-09-23T00:00:00Z",
  payload,
  run_id: "cr_1",
  turn_id: "turn_1",
  tool_call_id: null,
  ...ids,
});

const SCORED = {
  probability: 0.62,
  band: "middle",
  low_below: 0.3,
  high_at_or_above: 0.8,
  rubric_digest: "f5faf377",
  model: "jev-1.13.0",
  static_outcome: "allow",
  would_be_outcome: "require_approval",
  enforced: false,
  tool: "execute.v1",
  tool_call_id: "t1",
};

test("a verdict that lands before tool.started survives the tool's own events", () => {
  // The gate scores a call before it runs, so the verdict is always first.
  const state = [
    event(1, "jev_risk_scored", SCORED, { tool_call_id: "t1" }),
    event(2, "tool.started", { name: "execute.v1" }, { tool_call_id: "t1" }),
    event(3, "tool.completed", { name: "execute.v1" }, { tool_call_id: "t1" }),
  ].reduce(reduceProjectionEvent, emptyProjection("ct_1"));

  const risk = state.toolRisksById.t1;
  assert.equal(risk?.kind, "scored");
  assert.equal(
    risk.kind === "scored" && risk.would_be_outcome,
    "require_approval"
  );
  assert.equal(risk.enforced, false);
  assert.equal(state.toolsById.t1?.status, "completed");
});

test("the verdict is keyed by the envelope's call, falling back to the payload's", () => {
  const state = reduceProjectionEvent(
    emptyProjection("ct_1"),
    event(1, "jev_risk_scored", { ...SCORED, tool_call_id: "t_payload" })
  );
  assert.deepEqual(Object.keys(state.toolRisksById), ["t_payload"]);
});

test("an unavailable Jev is recorded, not hidden", () => {
  // S12: the fallback to the static policy must not be silent.
  const state = reduceProjectionEvent(
    emptyProjection("ct_1"),
    event(
      1,
      "jev_unavailable",
      { reason: "TimeoutError", static_outcome: "allow", enforced: true },
      { tool_call_id: "t1" }
    )
  );
  const risk = state.toolRisksById.t1;
  assert.equal(risk?.kind, "unavailable");
  assert.equal(risk.kind === "unavailable" && risk.reason, "TimeoutError");
});

test("a verdict without a band is dropped rather than half-drawn", () => {
  const { band: _band, ...noBand } = SCORED;
  const state = reduceProjectionEvent(
    emptyProjection("ct_1"),
    event(1, "jev_risk_scored", noBand, { tool_call_id: "t1" })
  );
  assert.deepEqual(state.toolRisksById, {});
  assert.equal(state.appliedSeq, 1);
});

const snapshot = (
  overrides: Partial<CodingProjectionSnapshot>
): CodingProjectionSnapshot => ({
  task: {
    task_id: "ct_1",
    status: "running",
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

test("a snapshot verdict reads exactly like the live one", () => {
  // One decoder for both paths; if they ever split, this is where it shows.
  const live = reduceProjectionEvent(
    { ...emptyProjection("ct_1"), appliedSeq: 6 },
    event(7, "jev_risk_scored", SCORED, { tool_call_id: "t1" })
  ).toolRisksById.t1;
  const restored = reduceSnapshot(
    snapshot({
      tool_risks: [
        {
          tool_call_id: "t1",
          kind: "jev_risk_scored",
          seq: 7,
          payload: SCORED,
        },
      ],
    })
  ).toolRisksById.t1;
  assert.deepEqual(restored, live);
});

test("a detached child seeded from the snapshot ends when its stall arrives", () => {
  const restored = reduceSnapshot(
    snapshot({
      active_children: [{ run_id: "sa_1", status: "running", spec: "explore" }],
    })
  );
  assert.equal(restored.childrenById.sa_1?.status, "running");

  const after = reduceProjectionEvent(
    restored,
    event(10, "subagent.failed", { run_id: "sa_1", error_code: "stalled" })
  );
  assert.equal(after.childrenById.sa_1?.status, "failed");
  assert.equal(after.childrenById.sa_1?.end_reason, "stalled");
  assert.equal(after.childrenById.sa_1?.spec, "explore");
});

test("a child's step keeps its counts current", () => {
  const state = [
    event(1, "subagent.started", {
      run_id: "sa_1",
      spec: "explore",
      status: "pending",
      turn_count: 0,
      tool_count: 0,
    }),
    event(2, "subagent.step", {
      run_id: "sa_1",
      status: "running",
      turn_count: 1,
      tool_count: 2,
    }),
  ].reduce(reduceProjectionEvent, emptyProjection("ct_1"));
  assert.equal(state.childrenById.sa_1?.status, "running");
  assert.equal(state.childrenById.sa_1?.tool_count, 2);
  assert.equal(state.childrenById.sa_1?.spec, "explore");
});

test("a refusal is shown and clears the running note", () => {
  const state = [
    event(1, "model.thinking", {
      preview: "Considering",
      chars: 11,
      truncated: false,
    }),
    event(2, "model.refused", {
      stop_reason: "refusal",
      stop_category: "cyber",
    }),
  ].reduce(reduceProjectionEvent, emptyProjection("ct_1"));
  assert.equal(state.refusal?.stop_category, "cyber");
  assert.equal(state.thinkingStatus, null);
});

test("a new run clears the previous run's refusal", () => {
  const state = [
    event(1, "model.refused", { stop_reason: "refusal", stop_category: null }),
    event(
      2,
      "run.started",
      { instruction: "try again", attempt: 2 },
      { run_id: "cr_2" }
    ),
  ].reduce(reduceProjectionEvent, emptyProjection("ct_1"));
  assert.equal(state.refusal, null);
  assert.equal(state.activeRun?.run_id, "cr_2");
  assert.equal(state.activeRun?.attempt, 2);
});

test("only the active run's end clears the active run", () => {
  const started = [
    event(
      1,
      "run.started",
      { instruction: "go", attempt: 2 },
      { run_id: "cr_2" }
    ),
  ].reduce(reduceProjectionEvent, emptyProjection("ct_1"));
  const stale = reduceProjectionEvent(
    started,
    event(2, "run.failed", { status: "failed" }, { run_id: "cr_1" })
  );
  assert.equal(stale.activeRun?.run_id, "cr_2");
  const ended = reduceProjectionEvent(
    stale,
    event(3, "run.failed", { status: "failed" }, { run_id: "cr_2" })
  );
  assert.equal(ended.activeRun, null);
});

test("a live user edit reaches the workspace, and its sync updates it in place", () => {
  const state = [
    event(1, "workspace.user_edit.applied", {
      edit_id: "ue_1",
      path: "src/app.py",
      base_revision: "r1",
      resulting_revision: "r2",
      status: "pending_agent_sync",
    }),
    event(2, "workspace.user_edit.synced", {
      edit_id: "ue_1",
      path: "src/app.py",
      resulting_revision: "r2",
      status: "agent_synced",
      applied_checkpoint_id: "cc_3",
    }),
  ].reduce(reduceProjectionEvent, emptyProjection("ct_1"));
  assert.equal(state.workspace.user_edits?.length, 1);
  assert.equal(state.workspace.user_edits?.[0]?.status, "agent_synced");
  assert.equal(state.workspace.user_edits?.[0]?.base_revision, "r1");
  assert.equal(state.workspace.user_edits?.[0]?.applied_checkpoint_id, "cc_3");
});

import assert from "node:assert/strict";
import test from "node:test";
import {
  emptyProjection,
  reduceProjectionEvent,
  reduceSnapshot,
} from "@/features/coding/stream/projection-reducer";
import type { CodingEvent } from "@/features/coding/types/events";
import type { CodingProjectionSnapshot } from "@/features/coding/types/projection";

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
  ts: "2026-07-22T00:00:00Z",
  payload,
  run_id: "cr_1",
  tool_call_id: toolCallId,
});

test("tool.started upserts a running row with name and preview", () => {
  const state = reduceProjectionEvent(
    emptyProjection("ct_1"),
    event(
      1,
      "tool.started",
      { name: "read_file.v1", preview: "src/app.py:1-40" },
      "tool_1"
    )
  );

  assert.equal(state.toolsById.tool_1.status, "running");
  assert.equal(state.toolsById.tool_1.name, "read_file.v1");
  assert.equal(state.toolsById.tool_1.preview, "src/app.py:1-40");
});

test("tool completion keeps name/preview and does not drop them", () => {
  const started = reduceProjectionEvent(
    emptyProjection("ct_1"),
    event(1, "tool.started", { name: "read_file.v1", preview: "app.py" }, "tool_1")
  );
  const completed = reduceProjectionEvent(
    started,
    event(2, "tool.completed", { result: { preview: "app.py:12", status: "ok" } }, "tool_1")
  );

  assert.equal(completed.toolsById.tool_1.status, "completed");
  assert.equal(completed.toolsById.tool_1.name, "read_file.v1");
  assert.equal(completed.toolsById.tool_1.preview, "app.py:12");
});

test("tool.denied keeps name/preview and records denied_by plus reason_code", () => {
  const started = reduceProjectionEvent(
    emptyProjection("ct_1"),
    event(1, "tool.started", { name: "execute.v1", preview: "rm -rf /" }, "tool_1")
  );
  const denied = reduceProjectionEvent(
    started,
    event(
      2,
      "tool.denied",
      {
        reason_code: "approval_denied",
        denied_by: "user",
        result: {
          name: "execute.v1",
          preview: "rm -rf /",
          denied_by: "user",
          reason_code: "approval_denied",
        },
      },
      "tool_1"
    )
  );

  assert.equal(denied.toolsById.tool_1.status, "denied");
  assert.equal(denied.toolsById.tool_1.name, "execute.v1");
  assert.equal(denied.toolsById.tool_1.preview, "rm -rf /");
  assert.equal(denied.toolsById.tool_1.denied_by, "user");
  assert.equal(denied.toolsById.tool_1.reason_code, "approval_denied");
  assert.notEqual(denied.toolsById.tool_1.status, "failed");
  assert.notEqual(denied.toolsById.tool_1.status, "error");
});

test("todo_write.v1 completion updates live todos from payload input", () => {
  const todos = [
    { id: "t1", content: "Read the file", status: "in_progress" },
    { content: "Edit the file", status: "pending" },
  ];
  const state = [
    event(1, "tool.started", { name: "todo_write.v1", preview: "2 todos" }, "tool_todo"),
    event(
      2,
      "tool.completed",
      { name: "todo_write.v1", todos, result: { status: "ok" } },
      "tool_todo"
    ),
  ].reduce(reduceProjectionEvent, emptyProjection("ct_1"));

  assert.deepEqual(state.todos, todos);
});

test("todo_write.v1 completion falls back to result.entries", () => {
  const entries = [{ content: "Run tests", status: "pending" }];
  const state = reduceProjectionEvent(
    emptyProjection("ct_1"),
    event(
      1,
      "tool.completed",
      { result: { name: "todo_write.v1", entries, status: "ok" } },
      "tool_todo"
    )
  );

  assert.deepEqual(state.todos, entries);
});

test("snapshot cost and token fields surface on the projection", () => {
  const snapshot = {
    task: {
      task_id: "ct_1",
      status: "running",
      version: 1,
      last_seq: 4,
      created_at: "2026-07-22T00:00:00Z",
      updated_at: "2026-07-22T00:00:00Z",
    },
    active_run: null,
    phases: [],
    tools: [],
    approvals: [],
    todos: [],
    workspace: { revision: "rev_4", git_head: null, changed_files: [] },
    latest_checkpoint: {
      loop_state: {
        cost_micros: 2_500_000,
        input_tokens: 120,
        output_tokens: 40,
        max_cost_micros: 10_000_000,
      },
    },
    head_seq: 4,
    connection_basis: "checkpoint",
  } satisfies CodingProjectionSnapshot;

  const state = reduceSnapshot(snapshot);
  assert.equal(state.costMicros, 2_500_000);
  assert.equal(state.inputTokens, 120);
  assert.equal(state.outputTokens, 40);
  assert.equal(state.maxCostMicros, 10_000_000);
});

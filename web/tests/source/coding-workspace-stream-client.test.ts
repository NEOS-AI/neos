import assert from "node:assert/strict";
import test from "node:test";
import {
  buildWorkspaceSocketUrl,
  emptyPtyState,
  reducePtyFrame,
} from "../../features/coding/workspace/workspace-stream-client";

const output = (cursor: number, value: string) => ({
  v: 1 as const,
  type: "pty.output" as const,
  cursor,
  data: Buffer.from(value).toString("base64"),
});

test("pty replay advances an independent cursor", () => {
  const state = reducePtyFrame(emptyPtyState(), output(7, "hello"));
  assert.equal(state.afterCursor, 7);
  assert.equal(state.output, "hello");
});

test("duplicate output is ignored and a cursor gap requests resync", () => {
  let state = reducePtyFrame(emptyPtyState(), output(1, "one"));
  state = reducePtyFrame(state, output(1, "duplicate"));
  assert.equal(state.output, "one");

  state = reducePtyFrame(state, output(3, "three"));
  assert.equal(state.connection, "resync_required");
  assert.equal(state.afterCursor, 1);
});

test("terminal output is bounded without affecting connection state", () => {
  let state = emptyPtyState(5);
  state = reducePtyFrame(state, output(1, "1234"));
  state = reducePtyFrame(state, output(2, "5678"));

  assert.equal(state.output, "45678");
  assert.equal(state.connection, "connected");
});

test("terminal failure remains isolated in PTY state", () => {
  const state = reducePtyFrame(emptyPtyState(), {
    v: 1,
    type: "pty.resync_required",
  });
  assert.equal(state.connection, "resync_required");
  assert.equal(state.issue, "pty_resync_required");
});

test("reconnect URL carries only the stream-specific cursor and never a ticket", () => {
  const url = buildWorkspaceSocketUrl({
    websocketUrl: "wss://example.test/api/v1/coding/pty/ws",
    taskId: "ct_1",
    ticket: "ticket_2",
    afterCursor: 17,
    ptyId: "pty_1",
  });
  assert.equal(url.searchParams.get("after_cursor"), "17");
  assert.equal(url.searchParams.get("ticket"), null);
  assert.equal(url.searchParams.get("pty_id"), "pty_1");
  assert.equal(url.searchParams.has("after_seq"), false);
});

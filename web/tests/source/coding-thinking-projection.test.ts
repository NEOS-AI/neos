import assert from "node:assert/strict";
import test from "node:test";
import { emptyProjection, reduceProjectionEvent } from "../../features/coding/stream/projection-reducer";
import type { CodingEvent } from "../../features/coding/types/events";

const event = (seq: number, type: string, payload: Record<string, unknown>): CodingEvent => ({
  v: 1, task_id: "ct_1", seq, event_id: `ce_${seq}`, type,
  ts: "2026-09-19T00:00:00Z", payload, run_id: "cr_1", turn_id: "turn_1",
});

test("a thinking event becomes the current status line", () => {
  const state = reduceProjectionEvent(
    emptyProjection("ct_1"),
    event(1, "model.thinking", { preview: "Reading the config", chars: 18, truncated: false })
  );
  assert.equal(state.thinkingStatus, "Reading the config");
  assert.equal(state.appliedSeq, 1);
});

test("a later thinking event replaces the earlier line", () => {
  const events = [
    event(1, "model.thinking", { preview: "Reading the config", chars: 18, truncated: false }),
    event(2, "model.thinking", { preview: "Editing the parser", chars: 18, truncated: false }),
  ];
  const state = events.reduce(reduceProjectionEvent, emptyProjection("ct_1"));
  assert.equal(state.thinkingStatus, "Editing the parser");
});

test("the status line clears when the model starts speaking", () => {
  const events = [
    event(1, "model.thinking", { preview: "Reading the config", chars: 18, truncated: false }),
    event(2, "model.text_part.started", { part_id: "part_1", interrupted_part_ids: [] }),
  ];
  const state = events.reduce(reduceProjectionEvent, emptyProjection("ct_1"));
  assert.equal(state.thinkingStatus, null);
});

test("a repeated start still clears the line", () => {
  const events = [
    event(1, "model.text_part.started", { part_id: "part_1", interrupted_part_ids: [] }),
    event(2, "model.thinking", { preview: "Still working", chars: 13, truncated: false }),
    event(3, "model.text_part.started", { part_id: "part_1", interrupted_part_ids: [] }),
  ];
  const state = events.reduce(reduceProjectionEvent, emptyProjection("ct_1"));
  assert.equal(state.thinkingStatus, null);
});

// Passes trivially today, since nothing clears yet. It is here to bite later:
// a malformed start is not the model speaking, so it must not wipe the line.
test("a malformed start leaves the line alone", () => {
  const events = [
    event(1, "model.thinking", { preview: "Reading", chars: 7, truncated: false }),
    event(2, "model.text_part.started", { part_id: 42, interrupted_part_ids: [] }),
  ];
  const state = events.reduce(reduceProjectionEvent, emptyProjection("ct_1"));
  assert.equal(state.thinkingStatus, "Reading");
});

test("a malformed preview is ignored rather than rendered as junk", () => {
  const state = reduceProjectionEvent(
    emptyProjection("ct_1"),
    event(1, "model.thinking", { preview: 42, chars: 2, truncated: false })
  );
  assert.equal(state.thinkingStatus, null);
  assert.equal(state.appliedSeq, 1);
});

test("an empty projection has no status line", () => {
  assert.equal(emptyProjection("ct_1").thinkingStatus, null);
});

import assert from "node:assert/strict";
import test from "node:test";
import {
  initialCodingStreamState,
  reduceCodingEvent,
} from "@/features/coding/stream/event-reducer";
import type { CodingEvent } from "@/features/coding/types/events";


const event = (seq: number, type: string, payload = {}): CodingEvent => ({
  v: 1,
  task_id: "ct_1",
  seq,
  event_id: `ce_${seq}`,
  type,
  ts: "2026-07-18T10:00:00Z",
  payload,
});


test("ignores an already applied event", () => {
  const state = reduceCodingEvent(
    initialCodingStreamState(),
    event(1, "task.created", { status: "queued" })
  );

  assert.equal(reduceCodingEvent(state, event(1, "task.created")), state);
});


test("marks a sequence gap without applying the event", () => {
  const state = reduceCodingEvent(
    initialCodingStreamState(),
    event(2, "text.delta", { part_id: "p1", delta: "hello" })
  );

  assert.equal(state.appliedSeq, 0);
  assert.deepEqual(state.gap, { expected: 1, received: 2 });
});


test("replay and continued live application converge", () => {
  const events = [
    event(1, "task.created", { status: "queued" }),
    event(2, "text.delta", { part_id: "p1", delta: "hel" }),
    event(3, "text.delta", { part_id: "p1", delta: "lo" }),
  ];
  const replayed = events.reduce(reduceCodingEvent, initialCodingStreamState());
  const afterSnapshot = events.slice(1).reduce(reduceCodingEvent, {
    ...initialCodingStreamState(),
    appliedSeq: 1,
    taskStatus: "queued",
  });

  assert.deepEqual(replayed, afterSnapshot);
  assert.equal(replayed.partsById.p1, "hello");
});

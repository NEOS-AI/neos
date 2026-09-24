import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import {
  emptyProjection,
  reduceProjectionEvent,
} from "../../features/coding/stream/projection-reducer";
import type { CodingEvent } from "../../features/coding/types/events";
import type { CodingProjectionState } from "../../features/coding/types/projection";

// The coding ledger's vocabulary lives in one file, and the backend test
// (`tests/coding/test_event_kinds.py`) proves that file matches what the
// source actually writes. This side proves each kind is either projected or
// exempted *on purpose*. Before this pairing existed, jev_risk_scored,
// model.refused and subagent.* all fell through `return base` in silence.
const FIXTURE_PATH = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../tests/fixtures/coding_event_kinds.json"
);

type SetupEvent = { type: string; payload: Record<string, unknown> };
type KindCase = {
  kind: string;
  projected: boolean;
  reason?: string;
  sample: Record<string, unknown>;
  setup?: SetupEvent[];
};

const CASES: KindCase[] = JSON.parse(readFileSync(FIXTURE_PATH, "utf8")).kinds;

const envelope = (
  seq: number,
  type: string,
  payload: Record<string, unknown>
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
  tool_call_id: "t1",
});

function prepared(entry: KindCase): {
  before: CodingProjectionState;
  event: CodingEvent;
} {
  const setup = entry.setup ?? [];
  const before = setup
    .map((item, index) => envelope(index + 1, item.type, item.payload))
    .reduce(reduceProjectionEvent, emptyProjection("ct_1"));
  return {
    before,
    event: envelope(setup.length + 1, entry.kind, entry.sample),
  };
}

// What "only the cursor moved" looks like. Anything else is projection.
const cursorOnly = (before: CodingProjectionState, seq: number) => ({
  ...before,
  appliedSeq: seq,
  gap: null,
});

test("the fixture was read", () => {
  // A contrast test can check less than it claims (FE6): an empty read would
  // pass both directions below vacuously.
  assert.ok(CASES.length > 30, "fixture 를 읽지 못했다");
  assert.ok(CASES.some((entry) => entry.projected));
  assert.ok(CASES.some((entry) => !entry.projected));
});

test("every kind the fixture marks projected changes more than the cursor", () => {
  for (const entry of CASES.filter((item) => item.projected)) {
    const { before, event } = prepared(entry);
    const after = reduceProjectionEvent(before, event);
    assert.equal(
      after.appliedSeq,
      event.seq,
      `${entry.kind} did not advance the cursor`
    );
    assert.equal(
      after.projectionIssue,
      null,
      `${entry.kind} raised a projection issue`
    );
    assert.notDeepEqual(
      after,
      cursorOnly(before, event.seq),
      `${entry.kind} 가 커서만 넘겼다 -- projection-reducer.ts 에 처리를 넣거나 fixture 에서 사유와 함께 면제할 것`
    );
  }
});

test("every kind the fixture exempts moves only the cursor", () => {
  for (const entry of CASES.filter((item) => !item.projected)) {
    const { before, event } = prepared(entry);
    const after = reduceProjectionEvent(before, event);
    assert.deepEqual(
      after,
      cursorOnly(before, event.seq),
      `${entry.kind} 가 이제 투영된다 -- fixture 의 projected 를 true 로 바꾸고 reason 을 지울 것`
    );
  }
});

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const PHASE_TIMELINE_PATTERN = /PhaseTimeline/;
const DETAIL_PANEL_PATTERN = /CodingDetailPanel/;
const UNDERSTAND_PATTERN = /Understand/;
const REVIEW_PATTERN = /Review/;
const SAFE_POINT_PATTERN = /safe_point/;
const INTERRUPT_NOW_PATTERN = /interrupt_now/;

test("workspace is phase-oriented and exposes both steering actions", () => {
  const workspace = readFileSync(
    "features/coding/components/coding-task-workspace.tsx",
    "utf8"
  );
  const timeline = readFileSync(
    "features/coding/components/phase-timeline.tsx",
    "utf8"
  );
  const composer = readFileSync(
    "features/coding/components/coding-steer-composer.tsx",
    "utf8"
  );

  assert.match(workspace, PHASE_TIMELINE_PATTERN);
  assert.match(workspace, DETAIL_PANEL_PATTERN);
  assert.match(timeline, UNDERSTAND_PATTERN);
  assert.match(timeline, REVIEW_PATTERN);
  assert.match(composer, SAFE_POINT_PATTERN);
  assert.match(composer, INTERRUPT_NOW_PATTERN);
});

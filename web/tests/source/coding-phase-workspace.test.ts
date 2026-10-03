import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const PHASE_TIMELINE_PATTERN = /PhaseTimeline/;
const DETAIL_PANEL_PATTERN = /CodingDetailPanel/;
const UNDERSTAND_PATTERN = /Understand/;
const REVIEW_PATTERN = /Review/;
const SAFE_POINT_PATTERN = /safe_point/;
const INTERRUPT_NOW_PATTERN = /interrupt_now/;
const WAITING_APPROVAL_PATTERN = /waiting_approval/;

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
  assert.match(workspace, WAITING_APPROVAL_PATTERN);
  assert.match(timeline, /waitingApproval/);
  assert.match(workspace, /costMicros|cost_micros|maxCostMicros/);
  assert.match(workspace, /inputTokens|outputTokens/);
});


test("workspace cancel calls stop, not steer interrupt", () => {
  const workspace = readFileSync(
    "features/coding/components/coding-task-workspace.tsx",
    "utf8"
  );
  const api = readFileSync("features/coding/api/coding-api.ts", "utf8");
  const route = readFileSync(
    "app/(code)/api/coding/tasks/[taskId]/stop/route.ts",
    "utf8"
  );
  const composer = readFileSync(
    "features/coding/components/coding-steer-composer.tsx",
    "utf8"
  );

  assert.match(workspace, /stopCodingTask/);
  assert.match(workspace, /data-testid="coding-stop-button"/);
  assert.match(workspace, />\s*Cancel\s*</);
  assert.doesNotMatch(workspace, /steerCodingTask\([^)]*interrupt_now/);
  assert.match(api, /export async function stopCodingTask/);
  assert.match(api, /\/api\/coding\/tasks\/\$\{encodeURIComponent\(taskId\)\}\/stop/);
  assert.match(route, /\/api\/v1\/coding\/tasks\/\$\{encodeURIComponent\(taskId\)\}\/stop/);
  assert.match(composer, INTERRUPT_NOW_PATTERN);
  assert.doesNotMatch(composer, /stopCodingTask/);
});

test("a paused task shows itself and only a person resumes it (track Q10b)", () => {
  const workspace = readFileSync(
    "features/coding/components/coding-task-workspace.tsx",
    "utf8"
  );
  const api = readFileSync("features/coding/api/coding-api.ts", "utf8");
  const route = readFileSync(
    "app/(code)/api/coding/tasks/[taskId]/resume/route.ts",
    "utf8"
  );
  const composer = readFileSync(
    "features/coding/components/coding-steer-composer.tsx",
    "utf8"
  );

  assert.match(workspace, /projection\.taskStatus === "paused"/);
  assert.match(workspace, /data-testid="coding-paused-badge"/);
  assert.match(workspace, /data-testid="coding-resume-button"/);
  assert.match(workspace, /resumeCodingTask/);
  assert.match(api, /export async function resumeCodingTask/);
  assert.match(api, /\/api\/coding\/tasks\/\$\{encodeURIComponent\(taskId\)\}\/resume/);
  assert.match(route, /\/api\/v1\/coding\/tasks\/\$\{encodeURIComponent\(taskId\)\}\/resume/);
  // 재개는 화면의 버튼 하나다 -- 스티어 입력기가 대신 재개하지 않는다.
  assert.doesNotMatch(composer, /resumeCodingTask/);
});

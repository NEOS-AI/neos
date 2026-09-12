import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("projection tools carry optional name and preview", () => {
  const types = readFileSync("features/coding/types/projection.ts", "utf8");

  assert.match(types, /name\?: string \| null/);
  assert.match(types, /preview\?: string \| null/);
  assert.match(types, /tool_call_id: string/);
});

test("detail panel shows tool name, status, and short preview", () => {
  const panel = readFileSync(
    "features/coding/components/coding-detail-panel.tsx",
    "utf8"
  );

  assert.match(panel, /\bname\b/);
  assert.match(panel, /\bpreview\b/);
  assert.match(panel, /tool\.status/);
  assert.match(panel, /tool_call_id/);
  assert.match(panel, /denied_by/);
  assert.match(panel, /reason_code/);
  assert.match(panel, /status === "denied"/);
  assert.doesNotMatch(panel, /JSON\.stringify/);
  assert.doesNotMatch(panel, /result\.(env|secret|token|password)/);
});

test("workspace renders projection todos with content and status", () => {
  const workspace = readFileSync(
    "features/coding/components/coding-task-workspace.tsx",
    "utf8"
  );

  assert.match(workspace, /projection\.todos/);
  assert.match(workspace, /\.content/);
  assert.match(workspace, /\.status/);
});

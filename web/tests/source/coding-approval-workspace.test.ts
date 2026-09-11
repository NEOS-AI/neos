import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("approval cards precede steering and remain event-driven", () => {
  const workspace = readFileSync(
    "features/coding/components/coding-task-workspace.tsx",
    "utf8"
  );
  const card = readFileSync(
    "features/coding/components/coding-approval-card.tsx",
    "utf8"
  );

  assert.match(workspace, /CodingApprovalCard/);
  assert.match(workspace, /pendingApprovals/);
  assert.match(card, /decideCodingApproval/);
  assert.match(card, /Approve once/);
  assert.match(card, /Approve for this run/);
  assert.match(card, /workspace_write/);
  assert.match(card, /remember/);
});

test("ask_user approval card collects answers instead of echoing questions", () => {
  const card = readFileSync(
    "features/coding/components/coding-approval-card.tsx",
    "utf8"
  );
  const api = readFileSync("features/coding/api/coding-api.ts", "utf8");

  assert.match(card, /ask_user\.v1/);
  assert.match(card, /answers/);
  assert.match(api, /answers/);
});

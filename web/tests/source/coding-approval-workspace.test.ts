import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path: string) => readFileSync(path, "utf8");

test("approval cards precede steering and remain event-driven", () => {
  const workspace = read("features/coding/components/coding-task-workspace.tsx");
  const card = read("features/coding/components/coding-approval-card.tsx");
  assert.ok(workspace.indexOf("CodingApprovalCard") < workspace.indexOf("CodingSteerComposer"));
  assert.match(workspace, /connection === "live"/);
  assert.match(card, /approval\.status !== "pending"/);
  assert.match(card, /decideCodingApproval/);
  assert.doesNotMatch(card, /setApproval|onResolved/);
});

test("approval card exposes bounded summary and accessible decision state", () => {
  const card = read("features/coding/components/coding-approval-card.tsx");
  assert.match(card, /display_summary/);
  assert.match(card, /aria-label="Approve tool request"/);
  assert.match(card, /aria-label="Deny tool request"/);
  assert.match(card, /role="alert"/);
  assert.doesNotMatch(card, /request_hash|requested_by|checkpoint_id|normalized_input/);
});

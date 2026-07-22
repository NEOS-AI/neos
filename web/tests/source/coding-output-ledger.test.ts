import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("output ledger is plain text, lifecycle-labelled, and placed before phases", () => {
  const ledger = readFileSync("features/coding/components/coding-output-ledger.tsx", "utf8");
  const workspace = readFileSync("features/coding/components/coding-task-workspace.tsx", "utf8");

  assert.match(ledger, /whitespace-pre-wrap/);
  assert.match(ledger, /Writing/);
  assert.match(ledger, /Completed/);
  assert.match(ledger, /Interrupted/);
  assert.match(ledger, /aria-live=.*streaming/);
  assert.doesNotMatch(ledger, /dangerouslySetInnerHTML|ReactMarkdown|remark/);
  assert.ok(workspace.indexOf("<CodingOutputLedger") < workspace.indexOf("<PhaseTimeline"));
});

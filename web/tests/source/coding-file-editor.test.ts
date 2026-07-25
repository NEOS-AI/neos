import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { createCodingWorkspaceStore } from "../../features/coding/workspace/workspace-store";

const EDIT_PATTERN = />\s*Edit\s*</;
const SAVE_PATTERN = /Save changes/;
const RELOAD_PATTERN = /Reload latest/;
const COMPARE_PATTERN = /Compare changes/;
const PENDING_PATTERN = /Saved · agent sync pending/;
const SYNCED_PATTERN = /Agent synced at checkpoint/;
const CONFLICT_PATTERN = /File changed since editing began/;
const RAW_HTML_PATTERN = /dangerouslySetInnerHTML/;

test("file viewer is read only until Edit is explicit", () => {
  const store = createCodingWorkspaceStore("ct_1");
  store.hydrateFile({
    path: "src/app.py",
    content: "return 1",
    binary: false,
    size: 8,
    workspace_revision: "12",
  });
  assert.equal(store.getSnapshot().editState, "read_only");

  store.beginEdit("return 1");

  assert.equal(store.getSnapshot().editState, "editing");
  assert.equal(store.getSnapshot().draft?.baseRevision, "12");

  store.cancelEdit();
  assert.equal(store.getSnapshot().editState, "read_only");
  assert.equal(store.getSnapshot().draft, null);
});

test("file viewer exposes explicit conflict recovery and sync labels", () => {
  const source = readFileSync(
    "features/coding/components/workspace/coding-file-viewer.tsx",
    "utf8"
  );
  assert.match(source, EDIT_PATTERN);
  assert.match(source, SAVE_PATTERN);
  assert.match(source, RELOAD_PATTERN);
  assert.match(source, COMPARE_PATTERN);
  assert.match(source, PENDING_PATTERN);
  assert.match(source, SYNCED_PATTERN);
  assert.match(source, CONFLICT_PATTERN);
  assert.doesNotMatch(source, RAW_HTML_PATTERN);
});

test("an empty text file can enter explicit edit mode", () => {
  const store = createCodingWorkspaceStore("ct_1");
  store.hydrateFile({
    path: "empty.txt",
    content: "",
    binary: false,
    size: 0,
    workspace_revision: "4",
  });

  store.beginEdit("");

  assert.equal(store.getSnapshot().editState, "editing");
  assert.equal(store.getSnapshot().draft?.content, "");
});

test("agent sync retains the applied checkpoint label", () => {
  const store = createCodingWorkspaceStore("ct_1");
  store.hydrateFile({
    path: "src/app.py",
    content: "return 1",
    binary: false,
    size: 8,
    workspace_revision: "12",
  });
  store.beginEdit("return 2");
  store.markSaved({
    edit_id: "cwe_1",
    path: "src/app.py",
    base_revision: "12",
    resulting_revision: "13",
    status: "pending_agent_sync",
  });
  store.applyUserEdit({
    edit_id: "cwe_1",
    path: "src/app.py",
    base_revision: "12",
    resulting_revision: "13",
    status: "agent_synced",
    applied_checkpoint_id: "ccp_7",
  });

  assert.equal(store.getSnapshot().syncedCheckpointId, "ccp_7");
});

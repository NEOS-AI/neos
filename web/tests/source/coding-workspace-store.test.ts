import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import type {
  WorkspaceFile,
  WorkspaceTree,
} from "../../features/coding/workspace/types";
import {
  createCodingWorkspaceStore,
  type WorkspaceWatcherFrame,
} from "../../features/coding/workspace/workspace-store";

const ALLOWED_OPERATIONS_PATTERN = /ALLOWED_OPERATIONS/;
const CALL_BACKEND_PATTERN = /callBackendAPI/;
const CONSOLE_PATTERN = /console\.(log|info|debug)/;
const EXTERNAL_STORE_PATTERN = /useSyncExternalStore/;
const GET_FILE_PATTERN = /getCodingWorkspaceFile/;

const tree = (revision: string): WorkspaceTree => ({
  workspace_revision: revision,
  entries: [
    {
      path: "src/app.py",
      kind: "file",
      size: 10,
      modified_at: "2026-07-25T00:00:00Z",
    },
  ],
});

const file = (revision: string): WorkspaceFile => ({
  path: "src/app.py",
  content: "server content",
  binary: false,
  size: 14,
  workspace_revision: revision,
});

const change = (revision: string): WorkspaceWatcherFrame => ({
  v: 1,
  type: "workspace.changed",
  cursor: 4,
  workspace_revision: revision,
  changes: [{ path: "src/app.py", kind: "modified", previous_path: null }],
});

test("watcher invalidates cache but preserves an active draft", () => {
  const store = createCodingWorkspaceStore("ct_1");
  store.hydrateTree(tree("12"));
  store.hydrateFile(file("12"));
  store.beginEdit("local draft");

  store.applyWatcher(change("13"));

  const state = store.getSnapshot();
  assert.equal(state.draft?.content, "local draft");
  assert.equal(state.editState, "revision_conflict");
  assert.equal(state.workspaceRevision, "13");
  assert.equal(state.tree, null);
  assert.equal(state.file, null);
});

test("duplicate watcher cursor is ignored", () => {
  const store = createCodingWorkspaceStore("ct_1");
  store.hydrateTree(tree("12"));
  store.applyWatcher(change("13"));
  store.hydrateTree(tree("13"));

  store.applyWatcher(change("14"));

  assert.equal(store.getSnapshot().workspaceRevision, "13");
  assert.equal(store.getSnapshot().tree?.workspace_revision, "13");
});

test("stale file response cannot replace a newer selection", () => {
  const store = createCodingWorkspaceStore("ct_1");
  const first = store.selectPath("src/old.py");
  const second = store.selectPath("src/app.py");

  assert.equal(store.hydrateFile(file("12"), first), false);
  assert.equal(store.hydrateFile(file("12"), second), true);
  assert.equal(store.getSnapshot().selectedPath, "src/app.py");
});

test("save status remains pending until matching agent sync", () => {
  const store = createCodingWorkspaceStore("ct_1");
  store.hydrateFile(file("12"));
  store.beginEdit("local draft");
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
    applied_checkpoint_id: "ccp_1",
  });

  assert.equal(store.getSnapshot().editState, "agent_synced");
  assert.equal(store.getSnapshot().pendingEditId, null);
});

test("workspace API and BFF expose only the bounded gateway contract", () => {
  const api = readFileSync("features/coding/api/coding-api.ts", "utf8");
  const route = readFileSync(
    "app/(code)/api/coding/tasks/[taskId]/workspace/[...path]/route.ts",
    "utf8"
  );
  const hook = readFileSync(
    "features/coding/workspace/use-coding-workspace.ts",
    "utf8"
  );

  for (const operation of [
    "getCodingWorkspaceTree",
    "getCodingWorkspaceFile",
    "getCodingWorkspaceDiff",
    "saveCodingWorkspaceFile",
    "getCodingWorkspaceWsTicket",
  ]) {
    assert.match(api, new RegExp(operation));
  }
  assert.match(route, ALLOWED_OPERATIONS_PATTERN);
  assert.match(route, CALL_BACKEND_PATTERN);
  assert.doesNotMatch(route, CONSOLE_PATTERN);
  assert.match(hook, EXTERNAL_STORE_PATTERN);
  assert.match(hook, GET_FILE_PATTERN);
});

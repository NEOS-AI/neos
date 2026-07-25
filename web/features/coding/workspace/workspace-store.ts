import type {
  WorkspaceDiff,
  WorkspaceFile,
  WorkspaceFileSaveResult,
  WorkspaceTree,
  WorkspaceUserEditView,
} from "./types";

export type WorkspaceWatcherFrame = {
  v: 1;
  type: "workspace.changed";
  cursor: number;
  workspace_revision: string | number;
  changes: Array<{
    path: string;
    kind: string;
    previous_path: string | null;
  }>;
};

export type CodingWorkspaceState = {
  taskId: string;
  workspaceRevision: string | null;
  tree: WorkspaceTree | null;
  selectedPath: string | null;
  file: WorkspaceFile | null;
  diff: WorkspaceDiff | null;
  draft: { path: string; baseRevision: string; content: string } | null;
  editState:
    | "read_only"
    | "editing"
    | "saving"
    | "saved_pending_agent"
    | "agent_synced"
    | "revision_conflict";
  pendingEditId: string | null;
  syncedCheckpointId: string | null;
  watcherCursor: number;
  issue: string | null;
};

export type CodingWorkspaceStore = ReturnType<
  typeof createCodingWorkspaceStore
>;

export function createCodingWorkspaceStore(taskId: string) {
  let requestGeneration = 0;
  let state: CodingWorkspaceState = {
    taskId,
    workspaceRevision: null,
    tree: null,
    selectedPath: null,
    file: null,
    diff: null,
    draft: null,
    editState: "read_only",
    pendingEditId: null,
    syncedCheckpointId: null,
    watcherCursor: 0,
    issue: null,
  };
  const listeners = new Set<() => void>();
  const commit = (next: CodingWorkspaceState) => {
    state = next;
    for (const listener of listeners) {
      listener();
    }
  };

  return {
    getSnapshot: () => state,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    hydrateTree(tree: WorkspaceTree) {
      commit({ ...state, tree, workspaceRevision: tree.workspace_revision });
    },
    selectPath(path: string) {
      requestGeneration += 1;
      commit({ ...state, selectedPath: path, file: null, issue: null });
      return requestGeneration;
    },
    hydrateFile(file: WorkspaceFile, generation = requestGeneration) {
      if (generation !== requestGeneration) {
        return false;
      }
      commit({
        ...state,
        selectedPath: file.path,
        file,
        workspaceRevision: file.workspace_revision,
        editState: "read_only",
      });
      return true;
    },
    hydrateDiff(diff: WorkspaceDiff) {
      commit({ ...state, diff, workspaceRevision: diff.workspace_revision });
    },
    beginEdit(content: string) {
      if (!state.file || state.file.content === null || state.file.binary) {
        return;
      }
      commit({
        ...state,
        draft: {
          path: state.file.path,
          baseRevision: state.file.workspace_revision,
          content,
        },
        editState: "editing",
      });
    },
    updateDraft(content: string) {
      if (!state.draft) {
        return;
      }
      commit({ ...state, draft: { ...state.draft, content } });
    },
    cancelEdit() {
      commit({ ...state, draft: null, editState: "read_only", issue: null });
    },
    markSaving() {
      commit({ ...state, editState: "saving", issue: null });
    },
    markSaved(result: WorkspaceFileSaveResult) {
      commit({
        ...state,
        workspaceRevision: result.resulting_revision,
        pendingEditId: result.edit_id,
        syncedCheckpointId: null,
        draft: null,
        editState: "saved_pending_agent",
      });
    },
    applyUserEdit(edit: WorkspaceUserEditView) {
      if (edit.edit_id !== state.pendingEditId) {
        return;
      }
      commit({
        ...state,
        pendingEditId: edit.status === "agent_synced" ? null : edit.edit_id,
        syncedCheckpointId:
          edit.status === "agent_synced"
            ? edit.applied_checkpoint_id
            : state.syncedCheckpointId,
        editState:
          edit.status === "agent_synced"
            ? "agent_synced"
            : edit.status === "reconcile_required"
              ? "revision_conflict"
              : "saved_pending_agent",
      });
    },
    applyWatcher(frame: WorkspaceWatcherFrame) {
      if (frame.cursor <= state.watcherCursor) {
        return;
      }
      const changedDraft = state.draft
        ? frame.changes.some(
            (change) =>
              change.path === state.draft?.path ||
              change.previous_path === state.draft?.path
          )
        : false;
      commit({
        ...state,
        workspaceRevision: String(frame.workspace_revision),
        tree: null,
        file: null,
        diff: null,
        watcherCursor: frame.cursor,
        editState: changedDraft ? "revision_conflict" : state.editState,
      });
    },
    setIssue(issue: string) {
      commit({ ...state, issue });
    },
  };
}

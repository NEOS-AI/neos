"use client";

import { useCallback, useEffect, useMemo, useSyncExternalStore } from "react";
import {
  getCodingWorkspaceDiff,
  getCodingWorkspaceFile,
  getCodingWorkspaceTree,
  getCodingWorkspaceWsTicket,
  saveCodingWorkspaceFile,
} from "@/features/coding/api/coding-api";
import {
  createCodingWorkspaceStore,
  type WorkspaceWatcherFrame,
} from "./workspace-store";
import { buildWorkspaceSocketUrl } from "./workspace-stream-client";

export function useCodingWorkspace(taskId: string) {
  const store = useMemo(() => createCodingWorkspaceStore(taskId), [taskId]);
  const workspace = useSyncExternalStore(store.subscribe, store.getSnapshot);

  const refreshTree = useCallback(async () => {
    try {
      store.hydrateTree(await getCodingWorkspaceTree(taskId));
    } catch {
      store.setIssue("workspace_tree_failed");
    }
  }, [store, taskId]);

  const openFile = useCallback(
    async (path: string) => {
      const generation = store.selectPath(path);
      try {
        store.hydrateFile(
          await getCodingWorkspaceFile(taskId, path),
          generation
        );
      } catch {
        store.setIssue("workspace_file_failed");
      }
    },
    [store, taskId]
  );

  const saveDraft = useCallback(async () => {
    const draft = store.getSnapshot().draft;
    if (!draft) {
      return;
    }
    store.markSaving();
    try {
      store.markSaved(
        await saveCodingWorkspaceFile(taskId, {
          edit_id: crypto.randomUUID(),
          path: draft.path,
          base_revision: draft.baseRevision,
          content: draft.content,
        })
      );
    } catch {
      store.setIssue("workspace_save_failed");
    }
  }, [store, taskId]);

  const refreshDiff = useCallback(async () => {
    try {
      store.hydrateDiff(await getCodingWorkspaceDiff(taskId));
    } catch {
      store.setIssue("workspace_diff_failed");
    }
  }, [store, taskId]);

  useEffect(() => {
    let disposed = false;
    let socket: WebSocket | null = null;
    const connect = async () => {
      const ticket = await getCodingWorkspaceWsTicket(taskId, "watcher");
      if (disposed || !ticket.websocket_url) {
        return;
      }
      const url = buildWorkspaceSocketUrl({
        websocketUrl: ticket.websocket_url,
        taskId,
        ticket: ticket.ticket,
        afterCursor: store.getSnapshot().watcherCursor,
      });
      socket = new WebSocket(url, "neos.coding.workspace.v1");
      socket.onmessage = (message) => {
        try {
          const frame = JSON.parse(message.data) as WorkspaceWatcherFrame;
          if (frame.type === "workspace.changed") {
            store.applyWatcher(frame);
          }
        } catch {
          store.setIssue("workspace_protocol_error");
        }
      };
    };
    connect().catch(() => store.setIssue("workspace_stream_failed"));
    return () => {
      disposed = true;
      socket?.close(1000, "Workspace view closed");
    };
  }, [store, taskId]);

  return {
    workspace,
    refreshTree,
    refreshDiff,
    openFile,
    beginEdit: store.beginEdit,
    updateDraft: store.updateDraft,
    cancelEdit: store.cancelEdit,
    applyUserEdit: store.applyUserEdit,
    saveDraft,
  };
}

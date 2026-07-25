export type WorkspaceEntry = {
  path: string;
  kind: string;
  size: number;
  modified_at: string;
};

export type WorkspaceTree = {
  entries: WorkspaceEntry[];
  workspace_revision: string;
};

export type WorkspaceFile = {
  path: string;
  content: string | null;
  binary: boolean;
  size: number;
  workspace_revision: string;
};

export type WorkspaceDiff = {
  content: string;
  truncated: boolean;
  workspace_revision: string;
};

export type WorkspaceFileSaveRequest = {
  edit_id: string;
  path: string;
  base_revision: string;
  content: string;
};

export type WorkspaceFileSaveResult = {
  edit_id: string;
  path: string;
  base_revision: string;
  resulting_revision: string;
  status: "pending_agent_sync";
};

export type WorkspaceUserEditView = {
  edit_id: string;
  path: string;
  base_revision: string;
  resulting_revision: string | null;
  status: "pending_agent_sync" | "agent_synced" | "reconcile_required";
  applied_checkpoint_id: string | null;
};

export type WorkspaceWsTicket = {
  ticket: string;
  expires_in: number;
  kind: "watcher" | "pty";
  websocket_url?: string;
};

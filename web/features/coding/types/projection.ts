import type { CodingTask } from "@/features/coding/api/coding-api";

export type CodingRunView = {
  run_id: string;
  attempt: number;
  status: string;
  resume_from_checkpoint_id: string | null;
};

export type CodingPhaseView = {
  phase_id: string;
  run_id: string;
  kind: string;
  attempt: number;
  status: string;
  started_at: string;
  completed_at: string | null;
};

export type CodingToolView = {
  tool_call_id: string;
  run_id: string;
  status: string;
  result: Record<string, unknown> | null;
};

export type CodingApprovalView = {
  approval_id: string;
  tool_name: string;
  risk: "workspace_write" | "command";
  status: "pending" | "approved" | "denied" | "expired" | "invalidated";
  requested_at: string;
  expires_at: string;
  display_summary: Record<string, unknown>;
};

export type CodingWorkspaceView = {
  revision: string;
  git_head: string | null;
  changed_files: string[];
};

export type CodingProjectionSnapshot = {
  task: CodingTask;
  active_run: CodingRunView | null;
  phases: CodingPhaseView[];
  tools: CodingToolView[];
  approvals: CodingApprovalView[];
  todos: Record<string, unknown>[];
  workspace: CodingWorkspaceView;
  latest_checkpoint: Record<string, unknown> | null;
  head_seq: number;
  connection_basis: "checkpoint";
};

export type CodingProjectionState = {
  taskId: string;
  taskStatus: string | null;
  appliedSeq: number;
  connectionBasis: "empty" | "checkpoint" | "live";
  activeRun: CodingRunView | null;
  phases: CodingPhaseView[];
  toolsById: Record<string, CodingToolView>;
  approvalsById: Record<string, CodingApprovalView>;
  todos: Record<string, unknown>[];
  workspace: CodingWorkspaceView;
  gap: { expected: number; received: number } | null;
};

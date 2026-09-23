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
  name?: string | null;
  preview?: string | null;
  unchanged?: boolean;
  denied_by?: string | null;
  reason_code?: string | null;
};

export type CodingApprovalView = {
  approval_id: string;
  tool_name: string;
  risk: "workspace_write" | "command" | "user_question";
  status: "pending" | "approved" | "denied" | "expired" | "invalidated";
  requested_at: string;
  expires_at: string;
  display_summary: Record<string, unknown>;
};

export type CodingWorkspaceView = {
  revision: string;
  git_head: string | null;
  changed_files: string[];
  user_edits?: import("@/features/coding/workspace/types").WorkspaceUserEditView[];
};

export type CodingTextPartView = {
  part_id: string;
  run_id: string;
  turn_id: string;
  status: "streaming" | "completed" | "interrupted";
  content: string;
  first_seq: number;
  last_seq: number;
};

export type CodingActiveChildView = {
  run_id: string;
  status?: string | null;
  spec?: string | null;
};

// A Jev verdict on one tool call (roadmap §12). Keyed by tool_call_id and kept
// apart from `toolsById`: the verdict lands *before* tool.started, and a call
// parked on approval never gets an execution row at all.
export type CodingToolRiskView =
  | {
      kind: "scored";
      tool_call_id: string;
      seq: number;
      tool: string | null;
      probability: number;
      band: string;
      low_below: number | null;
      high_at_or_above: number | null;
      static_outcome: string | null;
      would_be_outcome: string | null;
      // false = shadow (L2): recorded, not acted on. true = the gate (L3).
      enforced: boolean;
      rubric_digest: string | null;
      model: string | null;
    }
  | {
      kind: "unavailable";
      tool_call_id: string;
      seq: number;
      tool: string | null;
      reason: string | null;
      static_outcome: string | null;
      enforced: boolean;
    };

export type CodingToolRiskSnapshot = {
  tool_call_id: string;
  kind: "jev_risk_scored" | "jev_unavailable";
  seq: number;
  payload: Record<string, unknown>;
};

// A child agent the parent spawned (K3). Seeded from the snapshot's
// active_children and kept current by subagent.* events.
export type CodingChildView = {
  run_id: string;
  spec: string | null;
  status: string | null;
  turn_count: number | null;
  tool_count: number | null;
  parent_tool_call_id: string | null;
  // Short code: `stalled`, `cancelled`, ... Null while the child is healthy.
  end_reason: string | null;
};

export type CodingRefusalView = {
  run_id: string | null;
  stop_category: string | null;
  seq: number;
};

export type CodingProjectionSnapshot = {
  task: CodingTask;
  active_run: CodingRunView | null;
  phases: CodingPhaseView[];
  tools: CodingToolView[];
  approvals: CodingApprovalView[];
  parts?: CodingTextPartView[];
  todos: Record<string, unknown>[];
  workspace: CodingWorkspaceView;
  latest_checkpoint: Record<string, unknown> | null;
  head_seq: number;
  connection_basis: "checkpoint";
  active_children?: CodingActiveChildView[];
  tool_risks?: CodingToolRiskSnapshot[];
  // The `model.refused` event, only while it belongs to the latest run.
  refusal?: {
    run_id: string | null;
    seq: number;
    payload: Record<string, unknown>;
  } | null;
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
  textPartsById: Record<string, CodingTextPartView>;
  orderedTextPartIds: string[];
  todos: Record<string, unknown>[];
  workspace: CodingWorkspaceView;
  costMicros: number | null;
  inputTokens: number | null;
  outputTokens: number | null;
  maxCostMicros: number | null;
  gap: { expected: number; received: number } | null;
  projectionIssue: { code: "unknown_text_part"; eventSeq: number } | null;
  // The model's latest running note, shown while a long tool chain is silent.
  // Cleared once the model starts speaking, so it never competes with prose.
  thinkingStatus: string | null;
  toolRisksById: Record<string, CodingToolRiskView>;
  childrenById: Record<string, CodingChildView>;
  // The model declined the turn (K6). The run ends with model_refused and is
  // never retried, so without this the user sees a run that just stopped.
  refusal: CodingRefusalView | null;
};

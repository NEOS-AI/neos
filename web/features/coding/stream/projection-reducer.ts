import type { CodingEvent } from "@/features/coding/types/events";
import type {
  CodingApprovalView,
  CodingPhaseView,
  CodingProjectionSnapshot,
  CodingProjectionState,
  CodingToolView,
} from "@/features/coding/types/projection";

const phaseId = (kind: string, attempt: number) => `phase:${kind}:${attempt}`;

export const emptyProjection = (taskId: string): CodingProjectionState => ({
  taskId,
  taskStatus: null,
  appliedSeq: 0,
  connectionBasis: "empty",
  activeRun: null,
  phases: [],
  toolsById: {},
  approvalsById: {},
  todos: [],
  workspace: { revision: "uninitialized", git_head: null, changed_files: [] },
  gap: null,
});

export function reduceSnapshot(
  snapshot: CodingProjectionSnapshot
): CodingProjectionState {
  return {
    taskId: snapshot.task.task_id,
    taskStatus: snapshot.task.status,
    appliedSeq: snapshot.head_seq,
    connectionBasis: "checkpoint",
    activeRun: snapshot.active_run,
    phases: snapshot.phases.map((phase) => ({
      ...phase,
      phase_id: phaseId(phase.kind, phase.attempt),
    })),
    toolsById: Object.fromEntries(
      snapshot.tools.map((tool) => [tool.tool_call_id, tool])
    ),
    approvalsById: Object.fromEntries(
      snapshot.approvals.map((approval) => [approval.approval_id, approval])
    ),
    todos: snapshot.todos,
    workspace: snapshot.workspace,
    gap: null,
  };
}

export function reduceProjectionEvent(
  state: CodingProjectionState,
  event: CodingEvent
): CodingProjectionState {
  if (event.seq <= state.appliedSeq) {
    return state;
  }
  const expected = state.appliedSeq + 1;
  if (event.seq !== expected) {
    return { ...state, gap: { expected, received: event.seq } };
  }
  const base = { ...state, appliedSeq: event.seq, gap: null };
  if (event.type === "phase.started") {
    const kind = event.payload.phase;
    const attempt = event.payload.attempt;
    if (typeof kind !== "string" || typeof attempt !== "number") {
      return base;
    }
    const phase: CodingPhaseView = {
      phase_id: phaseId(kind, attempt),
      run_id: event.run_id ?? "",
      kind,
      attempt,
      status: "active",
      started_at: event.ts,
      completed_at: null,
    };
    return { ...base, phases: [...state.phases, phase] };
  }
  if (event.type === "phase.completed" || event.type === "phase.failed") {
    const kind = event.payload.phase;
    const attempt = event.payload.attempt;
    return {
      ...base,
      phases: state.phases.map((phase) =>
        phase.kind === kind && phase.attempt === attempt
          ? {
              ...phase,
              status: event.type === "phase.failed" ? "failed" : "completed",
              completed_at: event.ts,
            }
          : phase
      ),
    };
  }
  if (event.type.startsWith("tool.") && event.tool_call_id) {
    const previous = state.toolsById[event.tool_call_id];
    const tool: CodingToolView = {
      tool_call_id: event.tool_call_id,
      run_id: event.run_id ?? previous?.run_id ?? "",
      status: event.type.slice("tool.".length),
      result:
        event.payload.result && typeof event.payload.result === "object"
          ? (event.payload.result as Record<string, unknown>)
          : (previous?.result ?? null),
    };
    return {
      ...base,
      toolsById: { ...state.toolsById, [tool.tool_call_id]: tool },
    };
  }
  if (event.type.startsWith("approval.")) {
    const approvalId = event.payload.approval_id;
    if (typeof approvalId !== "string") {
      return base;
    }
    const previous = state.approvalsById[approvalId];
    const payload = event.payload as Partial<CodingApprovalView>;
    if (!previous && event.type !== "approval.requested") {
      return base;
    }
    const approval = {
      ...previous,
      ...payload,
      approval_id: approvalId,
      status:
        event.type === "approval.requested"
          ? "pending"
          : event.type.slice("approval.".length),
    } as CodingApprovalView;
    return {
      ...base,
      approvalsById: { ...state.approvalsById, [approvalId]: approval },
    };
  }
  if (
    event.type === "task.status.changed" &&
    typeof event.payload.status === "string"
  ) {
    return { ...base, taskStatus: event.payload.status };
  }
  return base;
}

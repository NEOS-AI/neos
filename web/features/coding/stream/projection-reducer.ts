import type { CodingEvent } from "@/features/coding/types/events";
import type {
  CodingApprovalView,
  CodingPhaseView,
  CodingProjectionSnapshot,
  CodingProjectionState,
  CodingToolView,
  CodingTextPartView,
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
  textPartsById: {},
  orderedTextPartIds: [],
  todos: [],
  workspace: { revision: "uninitialized", git_head: null, changed_files: [] },
  gap: null,
  projectionIssue: null,
});

export function reduceSnapshot(
  snapshot: CodingProjectionSnapshot
): CodingProjectionState {
  const parts = [...(snapshot.parts ?? [])].sort(
    (left, right) => left.first_seq - right.first_seq || left.part_id.localeCompare(right.part_id)
  );
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
    textPartsById: Object.fromEntries(parts.map((part) => [part.part_id, part])),
    orderedTextPartIds: parts.map((part) => part.part_id),
    todos: snapshot.todos,
    workspace: snapshot.workspace,
    gap: null,
    projectionIssue: null,
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
  if (event.type === "model.text_part.started") {
    const partId = event.payload.part_id;
    if (typeof partId !== "string" || !event.run_id || !event.turn_id) return base;
    const interrupted = Array.isArray(event.payload.interrupted_part_ids)
      ? event.payload.interrupted_part_ids.filter((id): id is string => typeof id === "string")
      : [];
    const textPartsById = { ...state.textPartsById };
    for (const id of interrupted) {
      const previous = textPartsById[id];
      if (previous) textPartsById[id] = { ...previous, status: "interrupted", last_seq: event.seq };
    }
    if (textPartsById[partId]) return { ...base, textPartsById };
    const part: CodingTextPartView = {
      part_id: partId,
      run_id: event.run_id,
      turn_id: event.turn_id,
      status: "streaming",
      content: "",
      first_seq: event.seq,
      last_seq: event.seq,
    };
    return {
      ...base,
      textPartsById: { ...textPartsById, [partId]: part },
      orderedTextPartIds: [...state.orderedTextPartIds, partId],
    };
  }
  if (event.type === "model.text_delta" || event.type === "model.text_part.completed") {
    const partId = event.payload.part_id;
    if (typeof partId !== "string") return base;
    const previous = state.textPartsById[partId];
    if (!previous) {
      return {
        ...state,
        projectionIssue: { code: "unknown_text_part", eventSeq: event.seq },
      };
    }
    const delta = event.type === "model.text_delta" ? event.payload.delta : "";
    if (event.type === "model.text_delta" && typeof delta !== "string") return base;
    return {
      ...base,
      projectionIssue: null,
      textPartsById: {
        ...state.textPartsById,
        [partId]: {
          ...previous,
          content: previous.content + delta,
          status: event.type === "model.text_part.completed" ? "completed" : previous.status,
          last_seq: event.seq,
        },
      },
    };
  }
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

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
  costMicros: null,
  inputTokens: null,
  outputTokens: null,
  maxCostMicros: null,
  gap: null,
  projectionIssue: null,
  thinkingStatus: null,
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
      snapshot.tools.map((tool) => [
        tool.tool_call_id,
        {
          ...tool,
          name: tool.name ?? nameFromUnknown(tool.result),
          preview: clippedPreview(tool.preview ?? previewFromUnknown(tool.result)),
          unchanged: tool.unchanged === true || tool.result?.unchanged === true,
          denied_by: tool.denied_by ?? stringField(tool.result, "denied_by"),
          reason_code: tool.reason_code ?? stringField(tool.result, "reason_code"),
        },
      ])
    ),
    approvalsById: Object.fromEntries(
      snapshot.approvals.map((approval) => [approval.approval_id, approval])
    ),
    textPartsById: Object.fromEntries(parts.map((part) => [part.part_id, part])),
    orderedTextPartIds: parts.map((part) => part.part_id),
    todos: snapshot.todos,
    workspace: snapshot.workspace,
    ...usageFromSnapshot(snapshot),
    gap: null,
    projectionIssue: null,
    // A checkpoint is a fresh basis: no thinking is in flight to show.
    thinkingStatus: null,
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
  if (event.type === "model.thinking") {
    const preview = event.payload.preview;
    // A non-string preview is a malformed event, not a status line. Advance
    // the cursor and render nothing rather than stringify junk.
    if (typeof preview !== "string") return base;
    return { ...base, thinkingStatus: preview };
  }
  if (event.type === "model.text_part.started") {
    const partId = event.payload.part_id;
    if (typeof partId !== "string" || !event.run_id || !event.turn_id) return base;
    // Speech has begun, so the running note stops competing with it. Defined
    // once because this branch has two more exits below, and a clear applied
    // to only one of them is the copy that goes stale.
    // The malformed exit above keeps the line: nothing actually started.
    const speaking = { ...base, thinkingStatus: null };
    const interrupted = Array.isArray(event.payload.interrupted_part_ids)
      ? event.payload.interrupted_part_ids.filter((id): id is string => typeof id === "string")
      : [];
    const textPartsById = { ...state.textPartsById };
    for (const id of interrupted) {
      const previous = textPartsById[id];
      if (previous) textPartsById[id] = { ...previous, status: "interrupted", last_seq: event.seq };
    }
    if (textPartsById[partId]) return { ...speaking, textPartsById };
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
      ...speaking,
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
    const result = payloadRecord(event.payload.result) ?? previous?.result ?? null;
    const name = pickToolName(event.payload, result, previous);
    const preview = clippedPreview(
      pickToolPreview(event.payload, result, previous)
    );
    const unchanged =
      event.payload.unchanged === true ||
      result?.unchanged === true ||
      previous?.unchanged === true;
    const deniedBy =
      stringField(event.payload, "denied_by") ??
      stringField(result, "denied_by") ??
      previous?.denied_by ??
      null;
    const reasonCode =
      stringField(event.payload, "reason_code") ??
      stringField(result, "reason_code") ??
      previous?.reason_code ??
      null;
    const status =
      event.type === "tool.started"
        ? "running"
        : event.type.slice("tool.".length);
    const tool: CodingToolView = {
      tool_call_id: event.tool_call_id,
      run_id: event.run_id ?? previous?.run_id ?? "",
      status,
      result,
      name,
      preview,
      unchanged,
      denied_by: status === "denied" ? deniedBy : previous?.denied_by ?? null,
      reason_code: status === "denied" ? reasonCode : previous?.reason_code ?? null,
    };
    const todos =
      event.type === "tool.completed" && name === "todo_write.v1"
        ? todosFromToolEvent(event.payload, result) ?? state.todos
        : state.todos;
    return {
      ...base,
      todos,
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

function asTrimmedString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function payloadRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function stringField(
  source: Record<string, unknown> | null | undefined,
  key: string
): string | null {
  return source ? asTrimmedString(source[key]) : null;
}

function nameFromUnknown(value: unknown): string | null {
  const record = payloadRecord(value);
  return (
    stringField(record, "name") ??
    stringField(record, "tool_name") ??
    stringField(record, "function_id")
  );
}

function previewFromUnknown(value: unknown): string | null {
  return stringField(payloadRecord(value), "preview");
}

function clippedPreview(value: string | null): string | null {
  return value ? value.slice(0, 200) : null;
}

function pickToolName(
  payload: Record<string, unknown>,
  result: Record<string, unknown> | null,
  previous: CodingToolView | undefined
): string | null {
  return (
    stringField(payload, "name") ??
    stringField(payload, "tool_name") ??
    nameFromUnknown(result) ??
    previous?.name ??
    null
  );
}

function pickToolPreview(
  payload: Record<string, unknown>,
  result: Record<string, unknown> | null,
  previous: CodingToolView | undefined
): string | null {
  return (
    stringField(payload, "preview") ??
    previewFromUnknown(result) ??
    previous?.preview ??
    null
  );
}

function asTodoRecords(value: unknown): Record<string, unknown>[] | null {
  if (!Array.isArray(value)) return null;
  const todos = value.filter(
    (item): item is Record<string, unknown> =>
      !!item && typeof item === "object" && !Array.isArray(item)
  );
  return todos;
}

function todosFromToolEvent(
  payload: Record<string, unknown>,
  result: Record<string, unknown> | null
): Record<string, unknown>[] | null {
  return (
    asTodoRecords(payload.todos) ??
    asTodoRecords(result?.todos) ??
    asTodoRecords(result?.entries)
  );
}

function numericField(source: Record<string, unknown>, key: string): number | null {
  const value = source[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function usageFromSnapshot(snapshot: CodingProjectionSnapshot): {
  costMicros: number | null;
  inputTokens: number | null;
  outputTokens: number | null;
  maxCostMicros: number | null;
} {
  const checkpoint = payloadRecord(snapshot.latest_checkpoint);
  const loopState = payloadRecord(checkpoint?.loop_state);
  if (!loopState) {
    return {
      costMicros: null,
      inputTokens: null,
      outputTokens: null,
      maxCostMicros: null,
    };
  }
  return {
    costMicros: numericField(loopState, "cost_micros"),
    inputTokens: numericField(loopState, "input_tokens"),
    outputTokens: numericField(loopState, "output_tokens"),
    maxCostMicros: numericField(loopState, "max_cost_micros"),
  };
}

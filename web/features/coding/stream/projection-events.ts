// Decoders for the coding ledger events that used to fall through
// `reduceProjectionEvent` as `return base` (roadmap §12.8 ①): Jev verdicts,
// subagent lifecycle, refusals, run lifecycle and live user edits.
//
// Each decoder returns null on a malformed payload. The reducer then only
// advances the cursor -- a junk event is not a reason to stall the stream, and
// it is not a reason to render junk either.
import type {
  CodingChildView,
  CodingRefusalView,
  CodingToolRiskView,
} from "@/features/coding/types/projection";
import type { WorkspaceUserEditView } from "@/features/coding/workspace/types";

export const TOOL_RISK_EVENT_TYPES = [
  "jev_risk_scored",
  "jev_unavailable",
] as const;

function str(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

// One decoder for both the live event and the snapshot row -- the snapshot
// carries the event's own type and payload for exactly this reason.
export function toolRiskFromPayload(
  kind: string,
  payload: Record<string, unknown>,
  toolCallId: string | null | undefined,
  seq: number
): CodingToolRiskView | null {
  const id = str(toolCallId) ?? str(payload.tool_call_id);
  if (!id) return null;
  const enforced = payload.enforced === true;
  const unattended = payload.unattended === true;
  if (kind === "jev_unavailable") {
    return {
      kind: "unavailable",
      tool_call_id: id,
      seq,
      tool: str(payload.tool),
      reason: str(payload.reason),
      static_outcome: str(payload.static_outcome),
      enforced,
      unattended,
    };
  }
  if (kind !== "jev_risk_scored") return null;
  const probability = num(payload.probability);
  const band = str(payload.band);
  // Without these two there is nothing to show, and a verdict with no band
  // is not reproducible (S13) -- better absent than half-drawn.
  if (probability === null || band === null) return null;
  return {
    kind: "scored",
    tool_call_id: id,
    seq,
    tool: str(payload.tool),
    probability,
    band,
    low_below: num(payload.low_below),
    high_at_or_above: num(payload.high_at_or_above),
    static_outcome: str(payload.static_outcome),
    would_be_outcome: str(payload.would_be_outcome),
    banded_outcome: str(payload.banded_outcome),
    unattended,
    enforced,
    rubric_digest: str(payload.rubric_digest),
    model: str(payload.model),
  };
}

// `model.refused`, live or from the snapshot row -- one decoder, like the
// verdicts above.
export function refusalFromPayload(
  payload: Record<string, unknown>,
  runId: string | null | undefined,
  seq: number
): CodingRefusalView {
  const category = payload.stop_category;
  return {
    run_id: runId ?? null,
    stop_category: typeof category === "string" && category ? category : null,
    seq,
  };
}

const CHILD_END_STATUS: Record<string, string> = {
  "subagent.completed": "completed",
  "subagent.failed": "failed",
  "subagent.cancelled": "killed",
};

export function childFromEvent(
  type: string,
  payload: Record<string, unknown>,
  previous: CodingChildView | undefined
): CodingChildView | null {
  const runId = str(payload.run_id);
  if (!runId) return null;
  return {
    run_id: runId,
    spec: str(payload.spec) ?? previous?.spec ?? null,
    // A terminal event is terminal even if its payload forgot the status.
    status:
      CHILD_END_STATUS[type] ?? str(payload.status) ?? previous?.status ?? null,
    turn_count: num(payload.turn_count) ?? previous?.turn_count ?? null,
    tool_count: num(payload.tool_count) ?? previous?.tool_count ?? null,
    parent_tool_call_id:
      str(payload.parent_tool_call_id) ?? previous?.parent_tool_call_id ?? null,
    end_reason:
      str(payload.error_code) ??
      str(payload.reason) ??
      previous?.end_reason ??
      null,
  };
}

const USER_EDIT_STATUSES = new Set<WorkspaceUserEditView["status"]>([
  "pending_agent_sync",
  "agent_synced",
  "reconcile_required",
]);

export function upsertUserEdit(
  edits: WorkspaceUserEditView[],
  payload: Record<string, unknown>
): WorkspaceUserEditView[] | null {
  const editId = str(payload.edit_id);
  const status = str(payload.status);
  if (
    !editId ||
    !status ||
    !USER_EDIT_STATUSES.has(status as WorkspaceUserEditView["status"])
  ) {
    return null;
  }
  const previous = edits.find((edit) => edit.edit_id === editId);
  const path = str(payload.path) ?? previous?.path;
  const baseRevision = str(payload.base_revision) ?? previous?.base_revision;
  if (!path || !baseRevision) return null;
  const next: WorkspaceUserEditView = {
    edit_id: editId,
    path,
    base_revision: baseRevision,
    resulting_revision:
      str(payload.resulting_revision) ?? previous?.resulting_revision ?? null,
    status: status as WorkspaceUserEditView["status"],
    applied_checkpoint_id:
      str(payload.applied_checkpoint_id) ??
      previous?.applied_checkpoint_id ??
      null,
  };
  return previous
    ? edits.map((edit) => (edit.edit_id === editId ? next : edit))
    : [...edits, next];
}

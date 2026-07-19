import type { CodingEvent } from "@/features/coding/types/events";


export type CodingStreamState = {
  appliedSeq: number;
  taskStatus: string | null;
  partsById: Record<string, string>;
  gap: { expected: number; received: number } | null;
};


export const initialCodingStreamState = (): CodingStreamState => ({
  appliedSeq: 0,
  taskStatus: null,
  partsById: {},
  gap: null,
});


export function reduceCodingEvent(
  state: CodingStreamState,
  event: CodingEvent
): CodingStreamState {
  if (event.seq <= state.appliedSeq) {
    return state;
  }
  const expected = state.appliedSeq + 1;
  if (event.seq !== expected) {
    return { ...state, gap: { expected, received: event.seq } };
  }

  if (event.type === "task.created" || event.type === "task.status.changed") {
    const status = event.payload.status;
    return {
      ...state,
      appliedSeq: event.seq,
      taskStatus: typeof status === "string" ? status : state.taskStatus,
      gap: null,
    };
  }

  if (event.type === "text.delta") {
    const partId = event.payload.part_id;
    const delta = event.payload.delta;
    if (typeof partId === "string" && typeof delta === "string") {
      return {
        ...state,
        appliedSeq: event.seq,
        partsById: {
          ...state.partsById,
          [partId]: `${state.partsById[partId] ?? ""}${delta}`,
        },
        gap: null,
      };
    }
  }

  return { ...state, appliedSeq: event.seq, gap: null };
}

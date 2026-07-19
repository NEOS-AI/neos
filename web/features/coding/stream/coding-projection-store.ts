import {
  emptyProjection,
  reduceProjectionEvent,
  reduceSnapshot,
} from "@/features/coding/stream/projection-reducer";
import type { CodingEvent } from "@/features/coding/types/events";
import type {
  CodingProjectionSnapshot,
  CodingProjectionState,
} from "@/features/coding/types/projection";

export function createCodingProjectionStore(taskId: string) {
  let state = emptyProjection(taskId);
  const listeners = new Set<() => void>();
  const emit = () => {
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
    replaceSnapshot(snapshot: CodingProjectionSnapshot) {
      state = reduceSnapshot(snapshot);
      emit();
    },
    applyEvent(event: CodingEvent) {
      state = reduceProjectionEvent(state, event);
      emit();
    },
    setConnectionBasis(basis: CodingProjectionState["connectionBasis"]) {
      state = { ...state, connectionBasis: basis };
      emit();
    },
  };
}

const stores = new Map<
  string,
  ReturnType<typeof createCodingProjectionStore>
>();

export function getCodingProjectionStore(taskId: string) {
  const existing = stores.get(taskId);
  if (existing) {
    return existing;
  }
  const store = createCodingProjectionStore(taskId);
  stores.set(taskId, store);
  return store;
}

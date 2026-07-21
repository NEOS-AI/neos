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

export type CodingFrameScheduler = {
  request(callback: () => void): number;
  cancel(handle: number): void;
};

export type CodingProjectionStore = {
  getSnapshot(): CodingProjectionState;
  subscribe(listener: () => void): () => void;
  replaceSnapshot(snapshot: CodingProjectionSnapshot): void;
  applyEvent(event: CodingEvent): void;
  setConnectionBasis(basis: CodingProjectionState["connectionBasis"]): void;
  flush(): void;
  dispose(): void;
};

const browserFrameScheduler: CodingFrameScheduler = {
  request(callback) {
    if (typeof requestAnimationFrame === "function") {
      return requestAnimationFrame(callback);
    }
    return setTimeout(callback, 16) as unknown as number;
  },
  cancel(handle) {
    if (typeof cancelAnimationFrame === "function") {
      cancelAnimationFrame(handle);
    }
    clearTimeout(handle);
  },
};

export function createCodingProjectionStore(
  taskId: string,
  scheduler: CodingFrameScheduler = browserFrameScheduler
): CodingProjectionStore {
  let workingState = emptyProjection(taskId);
  let publishedState = workingState;
  let scheduledHandle: number | null = null;
  let generation = 0;
  let disposed = false;
  const listeners = new Set<() => void>();
  const emit = () => {
    let firstError: unknown;
    let failed = false;
    for (const listener of listeners) {
      try {
        listener();
      } catch (error) {
        if (!failed) {
          failed = true;
          firstError = error;
        }
      }
    }
    if (failed) {
      throw firstError;
    }
  };

  const cancelScheduled = () => {
    generation += 1;
    if (scheduledHandle !== null) {
      scheduler.cancel(scheduledHandle);
    }
    scheduledHandle = null;
  };

  const publishNow = () => {
    if (disposed || publishedState === workingState) {
      return;
    }
    publishedState = workingState;
    emit();
  };

  const schedulePublish = () => {
    if (disposed || scheduledHandle !== null) {
      return;
    }
    const scheduledGeneration = ++generation;
    scheduledHandle = scheduler.request(() => {
      if (disposed || scheduledGeneration !== generation) {
        return;
      }
      scheduledHandle = null;
      publishNow();
    });
  };

  return {
    getSnapshot: () => publishedState,
    subscribe(listener: () => void) {
      if (disposed) {
        return () => undefined;
      }
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    replaceSnapshot(snapshot: CodingProjectionSnapshot) {
      if (disposed) {
        return;
      }
      cancelScheduled();
      workingState = reduceSnapshot(snapshot);
      publishNow();
    },
    applyEvent(event: CodingEvent) {
      if (disposed) {
        return;
      }
      const nextState = reduceProjectionEvent(workingState, event);
      if (nextState === workingState) {
        return;
      }
      workingState = nextState;
      if (nextState.gap !== null) {
        cancelScheduled();
        publishNow();
        return;
      }
      schedulePublish();
    },
    setConnectionBasis(basis: CodingProjectionState["connectionBasis"]) {
      if (disposed || workingState.connectionBasis === basis) {
        return;
      }
      cancelScheduled();
      workingState = { ...workingState, connectionBasis: basis };
      publishNow();
    },
    flush() {
      if (disposed) {
        return;
      }
      cancelScheduled();
      publishNow();
    },
    dispose() {
      if (disposed) {
        return;
      }
      cancelScheduled();
      disposed = true;
      listeners.clear();
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

export type ConnectionErrorPolicy = "terminal" | "retry";

type CursorStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

const CURSOR_PREFIX = "neos:coding:cursor:";

function browserStorage(): CursorStorage | undefined {
  return typeof window === "undefined" ? undefined : window.sessionStorage;
}

export function classifyConnectionError(
  status?: number
): ConnectionErrorPolicy {
  if (status === undefined || status === 429 || status >= 500) {
    return "retry";
  }
  return status >= 400 && status < 500 ? "terminal" : "retry";
}

export function heartbeatDeadlineMs(heartbeatMs: number): number {
  return heartbeatMs * 2;
}

export function readCursor(
  taskId: string,
  storage: CursorStorage | undefined = browserStorage()
): number {
  const value = storage?.getItem(`${CURSOR_PREFIX}${taskId}`);
  if (value === undefined || value === null) {
    return 0;
  }
  const cursor = Number(value);
  return Number.isSafeInteger(cursor) && cursor >= 0 ? cursor : 0;
}

export function writeCursor(
  taskId: string,
  cursor: number,
  storage: CursorStorage | undefined = browserStorage()
): void {
  if (Number.isSafeInteger(cursor) && cursor >= 0) {
    storage?.setItem(`${CURSOR_PREFIX}${taskId}`, String(cursor));
  }
}

export function clearCursor(
  taskId: string,
  storage: CursorStorage | undefined = browserStorage()
): void {
  storage?.removeItem(`${CURSOR_PREFIX}${taskId}`);
}

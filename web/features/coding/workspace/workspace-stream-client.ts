export type PtyState = {
  ptyId: string | null;
  afterCursor: number;
  connection: "disconnected" | "connecting" | "connected" | "resync_required";
  output: string;
  maxOutputCharacters: number;
  rows: number;
  cols: number;
  issue: string | null;
};

type PtyFrame =
  | { v: 1; type: "pty.ready"; pty_id: string }
  | { v: 1; type: "pty.output"; cursor: number; data: string }
  | {
      v: 1;
      type: "pty.closed";
      cursor: number;
      reason: string;
      exit_code: number | null;
    }
  | { v: 1; type: "pty.resync_required" }
  | { v: 1; type: "pong" };

export function workspaceTicketProtocols(
  protocol: string,
  ticket: string
): string[] {
  return [protocol, `neos.ticket.${ticket}`];
}

export function buildWorkspaceSocketUrl(options: {
  websocketUrl: string;
  taskId: string;
  ticket?: string;
  afterCursor: number;
  ptyId?: string | null;
}): URL {
  const { websocketUrl, taskId, afterCursor, ptyId } = options;
  const url = new URL(websocketUrl);
  url.searchParams.set("task_id", taskId);
  url.searchParams.set("after_cursor", String(afterCursor));
  if (ptyId) {
    url.searchParams.set("pty_id", ptyId);
  }
  return url;
}

export function emptyPtyState(maxOutputCharacters = 200_000): PtyState {
  return {
    ptyId: null,
    afterCursor: 0,
    connection: "connected",
    output: "",
    maxOutputCharacters,
    rows: 24,
    cols: 80,
    issue: null,
  };
}

function decodeBase64(value: string): string {
  return new TextDecoder().decode(
    Uint8Array.from(atob(value), (char) => char.charCodeAt(0))
  );
}

export function reducePtyFrame(state: PtyState, frame: PtyFrame): PtyState {
  if (frame.type === "pty.ready") {
    return {
      ...state,
      ptyId: frame.pty_id,
      connection: "connected",
      issue: null,
    };
  }
  if (frame.type === "pty.resync_required") {
    return {
      ...state,
      connection: "resync_required",
      issue: "pty_resync_required",
    };
  }
  if (frame.type === "pty.output" || frame.type === "pty.closed") {
    if (frame.cursor <= state.afterCursor) {
      return state;
    }
    const initialReplay = state.afterCursor === 0 && state.output.length === 0;
    if (!initialReplay && frame.cursor !== state.afterCursor + 1) {
      return {
        ...state,
        connection: "resync_required",
        issue: "pty_cursor_gap",
      };
    }
    if (frame.type === "pty.closed") {
      return {
        ...state,
        afterCursor: frame.cursor,
        connection: "disconnected",
        issue: frame.reason,
      };
    }
    const appended = state.output + decodeBase64(frame.data);
    return {
      ...state,
      afterCursor: frame.cursor,
      output: appended.slice(-state.maxOutputCharacters),
      connection: "connected",
      issue: null,
    };
  }
  return state;
}

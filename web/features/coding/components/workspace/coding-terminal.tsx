"use client";

import { useEffect, useRef, useState } from "react";
import { getCodingWorkspaceWsTicket } from "@/features/coding/api/coding-api";
import {
  buildWorkspaceSocketUrl,
  emptyPtyState,
  reducePtyFrame,
} from "@/features/coding/workspace/workspace-stream-client";

export function CodingTerminal({ taskId }: { taskId: string }) {
  const [terminal, setTerminal] = useState(() => emptyPtyState());
  const [input, setInput] = useState("");
  const surfaceRef = useRef<HTMLPreElement>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const terminalRef = useRef(terminal);

  useEffect(() => {
    terminalRef.current = terminal;
  }, [terminal]);

  useEffect(() => {
    let disposed = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;
    const connect = async () => {
      setTerminal((current) => ({ ...current, connection: "connecting" }));
      const authorization = await getCodingWorkspaceWsTicket(taskId, "pty");
      if (disposed || !authorization.websocket_url) {
        return;
      }
      const reconnectState = terminalRef.current;
      const url = buildWorkspaceSocketUrl({
        websocketUrl: authorization.websocket_url,
        taskId,
        ticket: authorization.ticket,
        afterCursor: reconnectState.afterCursor,
        ptyId: reconnectState.ptyId,
      });
      const socket = new WebSocket(url, "neos.coding.pty.v1");
      socketRef.current = socket;
      socket.onmessage = (message) => {
        try {
          setTerminal((state) =>
            reducePtyFrame(state, JSON.parse(message.data))
          );
        } catch {
          setTerminal((state) => ({
            ...state,
            connection: "resync_required",
            issue: "pty_protocol_error",
          }));
        }
      };
      socket.onopen = () => {
        attempt = 0;
        setTerminal((state) => ({ ...state, connection: "connected" }));
      };
      socket.onclose = () => {
        if (disposed) {
          return;
        }
        setTerminal((state) => ({ ...state, connection: "connecting" }));
        reconnectTimer = setTimeout(
          connect,
          Math.min(8000, 500 * 2 ** attempt++)
        );
      };
    };
    connect().catch(() =>
      setTerminal((state) => ({
        ...state,
        connection: "disconnected",
        issue: "pty_connection_failed",
      }))
    );
    return () => {
      disposed = true;
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
      }
      socketRef.current?.close(1000, "Terminal view closed");
    };
  }, [taskId]);

  useEffect(() => {
    const surface = surfaceRef.current;
    if (!surface) {
      return;
    }
    const observer = new ResizeObserver(([entry]) => {
      const rows = Math.max(
        2,
        Math.min(200, Math.floor(entry.contentRect.height / 18))
      );
      const cols = Math.max(
        20,
        Math.min(300, Math.floor(entry.contentRect.width / 8))
      );
      setTerminal((state) => ({ ...state, rows, cols }));
      if (socketRef.current?.readyState === WebSocket.OPEN) {
        socketRef.current.send(
          JSON.stringify({ type: "pty.resize", rows, cols })
        );
      }
    });
    observer.observe(surface);
    return () => observer.disconnect();
  }, []);

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!input || socketRef.current?.readyState !== WebSocket.OPEN) {
      return;
    }
    socketRef.current.send(
      JSON.stringify({ type: "pty.input", data: btoa(`${input}\n`) })
    );
    setInput("");
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-[#090b0e] text-slate-200">
      <div className="flex items-center justify-between border-white/10 border-b px-3 py-2 font-mono text-[10px] uppercase tracking-wider">
        <span>{terminal.ptyId ?? "New terminal"}</span>
        <span className={terminal.issue ? "text-red-300" : "text-emerald-300"}>
          {terminal.issue ?? terminal.connection}
        </span>
      </div>
      <pre
        aria-live="polite"
        className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap p-3 font-mono text-[12px] leading-[18px]"
        ref={surfaceRef}
      >
        {terminal.output || "Connecting to isolated terminal…"}
      </pre>
      <form className="flex border-white/10 border-t" onSubmit={submit}>
        <span className="px-3 py-2 font-mono text-amber-300 text-xs">$</span>
        <input
          aria-label="Terminal input"
          className="min-w-0 flex-1 bg-transparent py-2 pr-3 font-mono text-xs outline-none"
          onChange={(event) => setInput(event.target.value)}
          value={input}
        />
      </form>
    </div>
  );
}

"use client";

import { useEffect, useReducer, useRef, useState } from "react";
import { getCodingWsTicket } from "@/features/coding/api/coding-api";
import {
  initialCodingStreamState,
  reduceCodingEvent,
} from "@/features/coding/stream/event-reducer";
import {
  nextContiguousSeq,
  reconnectDelayMs,
} from "@/features/coding/stream/socket-client";
import type { CodingEvent } from "@/features/coding/types/events";


export type CodingConnectionState = "connecting" | "live" | "reconnecting" | "closed";

export function useCodingStream(taskId: string) {
  const [state, dispatch] = useReducer(
    reduceCodingEvent,
    undefined,
    initialCodingStreamState
  );
  const [connection, setConnection] = useState<CodingConnectionState>("connecting");
  const afterSeq = useRef(0);

  useEffect(() => {
    let disposed = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
    let attempt = 0;

    async function connect() {
      try {
        const authorization = await getCodingWsTicket(taskId);
        if (disposed) return;
        const url = new URL(authorization.websocket_url);
        url.searchParams.set("task_id", taskId);
        url.searchParams.set("after_seq", String(afterSeq.current));
        url.searchParams.set("ticket", authorization.ticket);
        socket = new WebSocket(url, "neos.coding.v1");
        socket.onmessage = (message) => {
          const envelope = JSON.parse(message.data) as Record<string, unknown>;
          if (envelope.type === "caught_up") {
            setConnection("live");
            attempt = 0;
            return;
          }
          if (typeof envelope.seq === "number") {
            const previousSeq = afterSeq.current;
            afterSeq.current = nextContiguousSeq(previousSeq, envelope.seq);
            dispatch(envelope as CodingEvent);
            if (envelope.seq > previousSeq + 1) {
              socket?.close(1012, "Event gap requires durable replay");
            }
          }
        };
        socket.onopen = () => {
          heartbeatTimer = setInterval(() => {
            if (socket?.readyState === WebSocket.OPEN) {
              socket.send(JSON.stringify({ v: 1, type: "ping" }));
            }
          }, 30_000);
        };
        socket.onclose = () => {
          if (heartbeatTimer) clearInterval(heartbeatTimer);
          if (disposed) return;
          setConnection("reconnecting");
          reconnectTimer = setTimeout(connect, reconnectDelayMs(attempt++));
        };
        socket.onerror = () => socket?.close();
      } catch {
        if (disposed) return;
        setConnection("reconnecting");
        reconnectTimer = setTimeout(connect, reconnectDelayMs(attempt++));
      }
    }

    connect();
    return () => {
      disposed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (heartbeatTimer) clearInterval(heartbeatTimer);
      socket?.close();
      setConnection("closed");
    };
  }, [taskId]);

  return { state, connection };
}

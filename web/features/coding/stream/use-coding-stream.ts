"use client";

import {
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import {
  CodingAPIError,
  getCodingTaskSnapshot,
  getCodingWsTicket,
} from "@/features/coding/api/coding-api";
import { getCodingProjectionStore } from "@/features/coding/stream/coding-projection-store";
import {
  classifyConnectionError,
  heartbeatDeadlineMs,
  readCursor,
  writeCursor,
} from "@/features/coding/stream/connection-policy";
import {
  initialCodingStreamState,
  reduceCodingEvent,
} from "@/features/coding/stream/event-reducer";
import {
  nextContiguousSeq,
  reconnectDelayMs,
} from "@/features/coding/stream/socket-client";
import type { CodingEvent } from "@/features/coding/types/events";

export type CodingConnectionState =
  | "connecting"
  | "live"
  | "reconnecting"
  | "unauthorized"
  | "not_found"
  | "protocol_error"
  | "closed";

function terminalState(status: number): CodingConnectionState {
  if (status === 401 || status === 403) {
    return "unauthorized";
  }
  if (status === 404) {
    return "not_found";
  }
  return "protocol_error";
}

export function useCodingStream(taskId: string) {
  const store = useMemo(() => getCodingProjectionStore(taskId), [taskId]);
  const projection = useSyncExternalStore(store.subscribe, store.getSnapshot);
  const [state, dispatch] = useReducer(
    reduceCodingEvent,
    undefined,
    initialCodingStreamState
  );
  const [connection, setConnection] =
    useState<CodingConnectionState>("connecting");
  const afterSeq = useRef(0);

  useEffect(() => {
    let disposed = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
    let pongDeadline: ReturnType<typeof setTimeout> | null = null;
    let awaitingPong = false;
    let terminal = false;
    let resyncing = false;
    let attempt = 0;
    let hydrationGeneration = 0;
    afterSeq.current = readCursor(taskId);

    async function hydrateFromSnapshot() {
      const generation = ++hydrationGeneration;
      const snapshot = await getCodingTaskSnapshot(taskId);
      if (disposed || generation !== hydrationGeneration) {
        return false;
      }
      store.replaceSnapshot(snapshot);
      afterSeq.current = snapshot.head_seq;
      writeCursor(taskId, snapshot.head_seq);
      return true;
    }

    function clearHeartbeat() {
      if (heartbeatTimer) {
        clearInterval(heartbeatTimer);
      }
      if (pongDeadline) {
        clearTimeout(pongDeadline);
      }
      heartbeatTimer = null;
      pongDeadline = null;
      awaitingPong = false;
    }

    function startHeartbeat(heartbeatMs: number) {
      clearHeartbeat();
      heartbeatTimer = setInterval(() => {
        if (socket?.readyState !== WebSocket.OPEN || awaitingPong) {
          return;
        }
        awaitingPong = true;
        socket.send(JSON.stringify({ v: 1, type: "ping" }));
        pongDeadline = setTimeout(() => {
          socket?.close(1012, "Heartbeat deadline exceeded");
        }, heartbeatDeadlineMs(heartbeatMs));
      }, heartbeatMs);
    }

    function reconnect() {
      if (disposed || terminal) {
        return;
      }
      setConnection("reconnecting");
      reconnectTimer = setTimeout(connect, reconnectDelayMs(attempt++));
    }

    async function connect() {
      try {
        if (!(await hydrateFromSnapshot())) {
          return;
        }
        const authorization = await getCodingWsTicket(taskId);
        if (disposed) {
          return;
        }
        const url = new URL(authorization.websocket_url);
        url.searchParams.set("task_id", taskId);
        url.searchParams.set("after_seq", String(afterSeq.current));
        url.searchParams.set("ticket", authorization.ticket);
        socket = new WebSocket(url, "neos.coding.v1");
        socket.onmessage = (message) => {
          let envelope: Record<string, unknown>;
          try {
            envelope = JSON.parse(message.data) as Record<string, unknown>;
          } catch {
            terminal = true;
            setConnection("protocol_error");
            socket?.close(1002, "Invalid coding event envelope");
            return;
          }
          if (
            envelope.type === "hello" &&
            typeof envelope.heartbeat_ms === "number" &&
            envelope.heartbeat_ms > 0
          ) {
            startHeartbeat(envelope.heartbeat_ms);
            return;
          }
          if (envelope.type === "pong") {
            awaitingPong = false;
            if (pongDeadline) {
              clearTimeout(pongDeadline);
            }
            pongDeadline = null;
            return;
          }
          if (envelope.type === "resync_required") {
            resyncing = true;
            socket?.close(1012, "Refreshing coding snapshot");
            hydrateFromSnapshot()
              .then((hydrated) => {
                if (!hydrated || disposed || terminal) {
                  return;
                }
                resyncing = false;
                return connect();
              })
              .catch(reconnect);
            return;
          }
          if (envelope.type === "caught_up") {
            store.setConnectionBasis("live");
            setConnection("live");
            attempt = 0;
            return;
          }
          if (typeof envelope.seq === "number") {
            const previousSeq = afterSeq.current;
            const nextSeq = nextContiguousSeq(previousSeq, envelope.seq);
            if (envelope.seq > previousSeq + 1) {
              socket?.close(1012, "Event gap requires durable replay");
              return;
            }
            if (nextSeq > previousSeq) {
              afterSeq.current = nextSeq;
              writeCursor(taskId, nextSeq);
              dispatch(envelope as CodingEvent);
              store.applyEvent(envelope as CodingEvent);
            }
          }
        };
        socket.onclose = (event) => {
          clearHeartbeat();
          if (disposed || terminal) {
            return;
          }
          if (resyncing) {
            return;
          }
          if (event.code === 4401 || event.code === 4403) {
            terminal = true;
            setConnection("unauthorized");
            return;
          }
          if (event.code === 4404) {
            terminal = true;
            setConnection("not_found");
            return;
          }
          if (event.code === 4406 || event.code === 1002) {
            terminal = true;
            setConnection("protocol_error");
            return;
          }
          reconnect();
        };
        socket.onerror = () => socket?.close();
      } catch (error) {
        if (disposed) {
          return;
        }
        if (
          error instanceof CodingAPIError &&
          classifyConnectionError(error.status) === "terminal"
        ) {
          terminal = true;
          setConnection(terminalState(error.status));
          return;
        }
        reconnect();
      }
    }

    connect();
    return () => {
      disposed = true;
      terminal = true;
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
      }
      clearHeartbeat();
      socket?.close();
      setConnection("closed");
    };
  }, [store, taskId]);

  return { state, projection, connection };
}

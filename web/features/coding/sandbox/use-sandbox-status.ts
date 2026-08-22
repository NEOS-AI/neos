"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getCodingSandboxStatus } from "@/features/coding/api/coding-api";
import {
  initialSandboxStatus,
  markSandboxStatusStale,
  reduceSandboxStatus,
  type SandboxStatusView,
} from "@/features/coding/sandbox/sandbox-status-store";

/**
 * 샌드박스 상태를 5초마다 읽는다.
 *
 * **소켓 상태에서 provider 건강을 추론하지 않는다.** 스트림이 끊긴 것은
 * 브라우저와 우리 백엔드 사이의 문제이고, provider 가 아픈 것은 백엔드와
 * provider 사이의 문제다. 둘을 엮으면 사용자의 와이파이가 끊겼을 때 멀쩡한
 * 샌드박스가 죽은 것처럼 보인다 -- 그래서 이 훅은 오직 이 엔드포인트의
 * 응답만 믿는다.
 *
 * 종결 상태(`cleaned`)에 도달하면 폴링을 멈춘다. 더 변할 것이 없는데 계속
 * 두드리면 태스크 목록을 열어 둔 브라우저마다 5초짜리 트래픽이 영원히 돈다.
 */

const POLL_INTERVAL_MS = 5000;
const TERMINAL_STATES = new Set(["cleaned"]);

export function useSandboxStatus(taskId: string): SandboxStatusView {
  const [view, setView] = useState<SandboxStatusView>(initialSandboxStatus);
  const viewRef = useRef(view);

  useEffect(() => {
    viewRef.current = view;
  }, [view]);

  const poll = useCallback(async () => {
    try {
      const status = await getCodingSandboxStatus(taskId);
      setView((current) => reduceSandboxStatus(current, status));
    } catch {
      // 실패해도 마지막 상태를 버리지 않는다 -- stale 표시만 올린다.
      setView(markSandboxStatusStale);
    }
  }, [taskId]);

  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const tick = async () => {
      if (disposed) {
        return;
      }
      await poll();
      if (disposed || TERMINAL_STATES.has(viewRef.current.state)) {
        return;
      }
      timer = setTimeout(tick, POLL_INTERVAL_MS);
    };

    void tick();
    return () => {
      disposed = true;
      if (timer) {
        clearTimeout(timer);
      }
    };
  }, [poll]);

  return view;
}

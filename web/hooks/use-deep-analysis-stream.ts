"use client";

/**
 * deep_analysis job 이벤트 구독 훅
 *
 * `neos:deep_analysis_started`로 받은 run_id 하나만 알면 된다. 나머지는
 * `GET /api/deep-analysis/{runId}/events?after=<cursor>` 재구독뿐이다.
 *
 * ## 불변식 (감사 §4.2 재발 방지)
 *
 * 이 훅은 **어떤 경우에도 job을 제출하지 않는다.** 재연결·새로고침·에러 복구
 * 전부 GET 재구독으로만 처리한다. `fetch`의 인자는 언제나
 * `deepAnalysisEventsPath(...)`이며 method는 기본값(GET)이다.
 *
 * ## 정지/이탈이 에러 토스트를 띄우지 않는 이유
 *
 * 언마운트·run 전환 시 `AbortController.abort()`가 `fetch`/`reader.read()`를
 * `AbortError`로 거부시킨다. 이는 정상 종료이므로 `isAbortError`로 걸러
 * 상태를 바꾸지 않는다(감사 §4.1과 동일한 처방).
 */

import { useEffect, useReducer, useRef, useState } from "react";
import {
  type DeepAnalysisJobEvent,
  isTerminalJobKind,
  JOB_COMPLETED,
  JOB_RESUMED,
} from "@/lib/deep-analysis/events";
import {
  type DeepAnalysisProgress,
  initialDeepAnalysisProgress,
  reduceDeepAnalysisEvent,
} from "@/lib/deep-analysis/progress";
import { readDeepAnalysisEventStream } from "@/lib/deep-analysis/reader";
import {
  classifySubscriptionError,
  deepAnalysisEventsPath,
  nextCursor,
  reconnectDelayMs,
  shouldResubscribe,
} from "@/lib/deep-analysis/subscription";
import { isAbortError } from "@/lib/stream-errors";

export type DeepAnalysisConnectionState =
  | "connecting"
  | "live"
  | "reconnecting"
  | "unauthorized"
  | "not_found"
  | "closed";

function terminalConnectionState(
  status: number | undefined
): DeepAnalysisConnectionState {
  if (status === 401 || status === 403) {
    return "unauthorized";
  }
  return "not_found";
}

export type UseDeepAnalysisStreamOptions = {
  runId: string | undefined;
  /** false면 구독하지 않는다 (이미 완료된 run 등). */
  enabled?: boolean;
  /**
   * 바뀌면 처음부터 다시 구독한다. 사람이 누른 재개(`resumeDeepAnalysis`) 뒤에만
   * 올린다 -- 이 훅은 재개를 **부르지 않는다**. 커서를 0 에서 다시 읽어도
   * 리듀서의 `seq <= cursor` 가드가 중복을 버린다.
   */
  subscriptionKey?: number;
  onCompleted?: (reportMarkdown: string | null) => void;
  onFailed?: (error: string) => void;
};

export type UseDeepAnalysisStreamReturn = {
  progress: DeepAnalysisProgress;
  connection: DeepAnalysisConnectionState;
};

export function useDeepAnalysisStream({
  runId,
  enabled = true,
  subscriptionKey = 0,
  onCompleted,
  onFailed,
}: UseDeepAnalysisStreamOptions): UseDeepAnalysisStreamReturn {
  const [progress, dispatch] = useReducer(
    reduceDeepAnalysisEvent,
    undefined,
    () => initialDeepAnalysisProgress()
  );
  const [connection, setConnection] =
    useState<DeepAnalysisConnectionState>("connecting");

  // 콜백을 ref로 고정한다 — 부모가 인라인 함수를 넘겨도 구독이 재시작되지 않는다.
  // (재시작 자체는 재구독이라 안전하지만, 불필요한 전체 이력 재생을 피한다)
  const onCompletedRef = useRef(onCompleted);
  const onFailedRef = useRef(onFailed);
  onCompletedRef.current = onCompleted;
  onFailedRef.current = onFailed;

  // biome-ignore lint/correctness/useExhaustiveDependencies: subscriptionKey is a restart trigger — it is read by React, not by the effect body
  useEffect(() => {
    if (!(runId && enabled)) {
      return;
    }
    const activeRunId = runId;

    let disposed = false;
    let settled = false;
    // 종결 이벤트는 **보류**했다가 스트림이 끝날 때 확정한다. 재개된 run 의
    // 이력은 `job_failed → job_resumed → …` 라서 첫 종결은 끝이 아닐 수 있다.
    // 백엔드는 마지막 종결 뒤에야 스트림을 닫는다(`deep_analysis_handlers.py`).
    // `as` 로 선언한다 -- 콜백 안에서만 대입되므로 제어 흐름이 null 로 좁혀 버린다.
    let pendingTerminal = null as DeepAnalysisJobEvent | null;
    let terminalError = false;
    let attempt = 0;
    let cursor = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    const controller = new AbortController();

    const scheduleResubscribe = () => {
      if (!shouldResubscribe({ settled, disposed, terminalError })) {
        return;
      }
      setConnection("reconnecting");
      reconnectTimer = setTimeout(subscribe, reconnectDelayMs(attempt++));
    };

    async function subscribe(): Promise<void> {
      if (disposed) {
        return;
      }
      try {
        // ⚠️ GET 재구독. 여기에 POST가 들어오면 재과금 사고가 재현된다.
        const response = await fetch(
          deepAnalysisEventsPath(activeRunId, cursor),
          {
            signal: controller.signal,
            headers: { Accept: "text/event-stream" },
          }
        );

        if (!response.ok) {
          if (classifySubscriptionError(response.status) === "terminal") {
            terminalError = true;
            setConnection(terminalConnectionState(response.status));
            return;
          }
          scheduleResubscribe();
          return;
        }

        if (!response.body) {
          scheduleResubscribe();
          return;
        }

        attempt = 0;
        setConnection("live");

        await readDeepAnalysisEventStream(response.body, (event) => {
          cursor = nextCursor(cursor, event.seq);
          dispatch(event);
          if (isTerminalJobKind(event.kind)) {
            pendingTerminal = event;
          } else if (event.kind === JOB_RESUMED) {
            pendingTerminal = null;
          }
          return true;
        });

        if (pendingTerminal) {
          settled = true;
          const terminal = pendingTerminal;
          if (terminal.kind === JOB_COMPLETED) {
            const report = terminal.payload.report_markdown;
            onCompletedRef.current?.(typeof report === "string" ? report : null);
          } else {
            const error = terminal.payload.error;
            onFailedRef.current?.(
              typeof error === "string" ? error : "Deep analysis job failed"
            );
          }
        }

        if (settled) {
          setConnection("closed");
          return;
        }
        // 자연 종료(유휴 타임아웃·프록시 시간 제한·네트워크). run은 아직 살아
        // 있을 수 있으므로 커서를 들고 다시 붙는다 — 재제출이 아니다.
        scheduleResubscribe();
      } catch (error) {
        if (disposed || isAbortError(error)) {
          // 정지/이탈은 에러가 아니다. 상태를 건드리지 않는다.
          return;
        }
        scheduleResubscribe();
      }
    }

    setConnection("connecting");
    subscribe();

    return () => {
      disposed = true;
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
      }
      controller.abort();
    };
  }, [runId, enabled, subscriptionKey]);

  return { progress, connection };
}

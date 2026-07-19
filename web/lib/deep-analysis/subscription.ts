/**
 * deep_analysis 이벤트 스트림 **재구독** 정책 (순수 모듈)
 *
 * ## 이 모듈의 존재 이유: "재개 ≠ 재실행"
 *
 * 감사 §4.2가 기록한 사고 — `use-auto-resume.ts`가 부르던 `resumeStream`이
 * 사실은 `POST /api/chat`을 다시 쳐서 **워크플로우 전체를 재과금 실행**했다.
 * 그 재발을 구조적으로 막기 위해, 이 모듈은 **오직 GET 이벤트 경로만** 만든다.
 * 여기에는 job을 제출하는 함수도, POST 경로 상수도, `/api/chat` 문자열도 없다.
 * 재구독은 언제나 `GET .../events?after=<cursor>` 하나뿐이다.
 * (`web/tests/source/deep-analysis-subscription.test.ts`가 이를 고정한다.)
 *
 * ## 새로고침 후에는 왜 커서를 저장하지 않고 0에서 다시 읽는가
 *
 * `after=0`은 **전체 이력 재생**이다(백엔드 계약). 새로고침하면 리듀서의
 * 카운터가 전부 초기화되므로, 저장된 커서에서 이어받으면 오히려 진행 상황이
 * 비어 보인다. 0에서 전부 다시 읽는 것이 정확하고, 재생은 리듀서가 멱등하게
 * 흡수한다. 저장된 커서는 **같은 마운트 안에서의 재연결**에만 쓴다
 * (그 경우 상태가 메모리에 남아 있으므로 이어받는 것이 맞다).
 * 어느 경우에도 job은 다시 제출되지 않는다.
 */

/** Next.js 라우트 핸들러 프록시 베이스. 백엔드 직접 호출이 아니다(인증 때문). */
export const DEEP_ANALYSIS_EVENTS_PROXY_BASE = "/api/deep-analysis";

/**
 * 이벤트 스트림 재구독 경로.
 *
 * @param runId  구독할 run
 * @param after  마지막으로 적용한 seq. 0이면 전체 이력 재생.
 */
export function deepAnalysisEventsPath(runId: string, after = 0): string {
  const cursor = Number.isSafeInteger(after) && after > 0 ? after : 0;
  return `${DEEP_ANALYSIS_EVENTS_PROXY_BASE}/${encodeURIComponent(runId)}/events?after=${cursor}`;
}

const EVENTS_URL_RUN_ID = /\/deep-analysis\/([^/?#]+)\/events/;

/**
 * 백엔드가 준 `events_url`을 프록시 경로로 환산한다.
 *
 * 챗 SSE가 주는 `events_url`은 **백엔드 절대 경로**
 * (`/api/v1/deep-analysis/{run_id}/events`)라 브라우저에서 직접 부르면
 * 인증 헤더가 붙지 않는다. run_id만 신뢰하고 프록시 경로를 다시 만든다.
 *
 * @returns run_id를 뽑지 못하면 `null`.
 */
export function runIdFromEventsUrl(eventsUrl: string): string | null {
  const match = EVENTS_URL_RUN_ID.exec(eventsUrl);
  if (!match) {
    return null;
  }
  const runId = decodeURIComponent(match[1]);
  return runId.length > 0 ? runId : null;
}

/**
 * 커서 전진 규칙.
 *
 * 단조 최대값만 취한다. `seq`는 단조 증가하지만 연속이 아니므로
 * (`./events.ts` 참조) "직후 값인가"를 따지면 안 된다.
 */
export function nextCursor(current: number, received: number): number {
  if (!Number.isSafeInteger(received) || received <= current) {
    return current;
  }
  return received;
}

export type SubscriptionErrorPolicy = "terminal" | "retry";

/**
 * HTTP 상태로 재시도 여부를 판정한다.
 *
 * 4xx는 재시도해도 같은 답이 온다(401/403 인증, 404 run 없음/소유자 아님).
 * 429·5xx·네트워크 오류(status 없음)만 재시도한다.
 */
export function classifySubscriptionError(
  status?: number
): SubscriptionErrorPolicy {
  if (status === undefined || status === 429 || status >= 500) {
    return "retry";
  }
  return status >= 400 && status < 500 ? "terminal" : "retry";
}

/**
 * 지수 백오프 (`features/coding/stream/socket-client.ts`와 동일한 곡선).
 * 500ms에서 시작해 15s에서 캡, 20% jitter.
 */
export function reconnectDelayMs(
  attempt: number,
  random: () => number = Math.random
): number {
  const base = Math.min(15_000, 500 * 2 ** Math.max(0, attempt));
  return Math.min(15_000, Math.round(base + base * 0.2 * random()));
}

/**
 * 스트림이 끊겼을 때 재연결해야 하는가.
 *
 * run이 종결(completed/failed)됐거나 훅이 정리됐으면 재연결하지 않는다.
 * 그 외(정상 종료·유휴 타임아웃·네트워크 끊김)는 전부 재연결 대상이다 —
 * **재제출이 아니라 재구독이다.**
 */
export function shouldResubscribe(input: {
  settled: boolean;
  disposed: boolean;
  terminalError: boolean;
}): boolean {
  return !(input.settled || input.disposed || input.terminalError);
}

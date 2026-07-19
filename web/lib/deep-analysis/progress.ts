/**
 * deep_analysis job 이벤트 → 챗 인라인 진행 상태 (순수 리듀서)
 *
 * `use-chat-stream.ts`의 `applyHarnessEvent`와 같은 역할·같은 모양이다:
 * 이벤트 이름으로 분기해 불변(immutable) 상태를 갱신한다. 다른 점은
 * **커서(`seq`)를 상태의 일부로 들고 있다**는 것뿐이다 — 그 커서가
 * 재구독 시 "다시 제출"이 아니라 "이어받기"를 가능하게 하는 유일한 장치다.
 *
 * ## 멱등성이 핵심이다
 *
 * `GET /{run_id}/events?after=0`은 **전체 이력을 재생**한다. 즉 재접속하면
 * 이미 처리한 이벤트가 다시 들어온다. `seq <= cursor`인 이벤트를 무시하는
 * 규칙이 이 재생을 무해하게 만든다 — 카운터가 두 배로 뛰지 않는다.
 *
 * ## 연속성(contiguity)을 검사하지 않는 이유
 *
 * `DAEvent.seq`는 테이블 전역 autoincrement PK라 같은 run 안에서도
 * 구멍이 뚫린다(다른 run의 이벤트가 번호를 가져간다). 자세한 근거는
 * `./events.ts` 상단 주석 참조.
 */

import {
  type DeepAnalysisJobEvent,
  JOB_COMPLETED,
  JOB_FAILED,
  JOB_RESUMED,
  JOB_STARTED,
  STREAM_IDLE_TIMEOUT_KIND,
} from "./events";

export type DeepAnalysisPhase = "pending" | "running" | "completed" | "failed";

export type DeepAnalysisProgress = {
  /** 마지막으로 **적용한** 이벤트의 seq. 재구독 시 `?after=` 값이 된다. */
  cursor: number;
  phase: DeepAnalysisPhase;
  /** run이 이전 실행에서 이어진 것인지 (`job_resumed`). */
  resumed: boolean;
  questionsOpened: number;
  splits: number;
  passesCompleted: number;
  claimsVerified: number;
  claimsRejected: number;
  claimsUnverified: number;
  /** 리포트 조립·채점 시도 횟수 (`report_graded`). */
  gradeAttempts: number;
  /** 마지막으로 관측한 이벤트 kind (디버깅·표시용). */
  lastKind: string | null;
  /** 사람이 읽을 수 있는 최근 활동 한 줄. */
  lastActivity: string | null;
  /** `job_completed.payload.report_markdown`. */
  reportMarkdown: string | null;
  /** `job_failed.payload.error`. */
  error: string | null;
  /**
   * 백엔드가 유휴 타임아웃으로 스트림을 닫았다. **run이 끝난 게 아니다.**
   * 구독자는 커서를 들고 재연결해야 한다.
   */
  idleTimedOut: boolean;
};

export function initialDeepAnalysisProgress(cursor = 0): DeepAnalysisProgress {
  return {
    cursor,
    phase: "pending",
    resumed: false,
    questionsOpened: 0,
    splits: 0,
    passesCompleted: 0,
    claimsVerified: 0,
    claimsRejected: 0,
    claimsUnverified: 0,
    gradeAttempts: 0,
    lastKind: null,
    lastActivity: null,
    reportMarkdown: null,
    error: null,
    idleTimedOut: false,
  };
}

const asString = (value: unknown): string | undefined =>
  typeof value === "string" && value.length > 0 ? value : undefined;

const asCount = (value: unknown): number | undefined =>
  typeof value === "number" && Number.isFinite(value) ? value : undefined;

function activityLabel(event: DeepAnalysisJobEvent): string | null {
  const { kind, payload } = event;

  if (kind === "question_opened") {
    const text = asString(payload.text);
    return text ? `질문 열림 · ${text}` : "질문 열림";
  }
  if (kind === "split") {
    const children = Array.isArray(payload.children)
      ? payload.children.length
      : undefined;
    return children === undefined
      ? "질문 분해"
      : `질문 분해 · 하위 ${children}개`;
  }
  if (kind === "pass_completed") {
    const claims = asCount(payload.claims);
    return claims === undefined
      ? "워커 패스 완료"
      : `워커 패스 완료 · 클레임 ${claims}건`;
  }
  if (kind === "claim_verified") {
    return "클레임 검증됨";
  }
  if (kind === "claim_rejected") {
    return "클레임 기각됨";
  }
  if (kind === "claim_unverified") {
    return "클레임 미검증 (재시도 캡 소진)";
  }
  if (kind === "conflict_reinvestigation") {
    return "모순 재조사";
  }
  if (kind === "stall_terminated") {
    return "정체 감지 — 질문 종료";
  }
  if (kind === "dead_end") {
    return "막다른 길 기록";
  }
  if (kind === "abandoned") {
    return "질문 포기";
  }
  if (kind === "recovered") {
    return "중단된 질문 회수";
  }
  if (kind === "synth_pass") {
    return "리포트 조립";
  }
  if (kind === "report_graded") {
    return payload.ok === true ? "리포트 채점 통과" : "리포트 채점 재시도";
  }
  if (kind === JOB_STARTED) {
    return "분석 시작";
  }
  if (kind === JOB_RESUMED) {
    return "분석 재개";
  }
  return null;
}

/**
 * 이벤트 1건을 적용한다.
 *
 * - `seq <= state.cursor`인 이벤트는 **무시**한다(재생 멱등성).
 * - 알 수 없는 kind도 커서는 전진시킨다. 모르는 이벤트 때문에 커서가 멈추면
 *   재구독이 영원히 같은 지점을 다시 읽는다.
 */
export function reduceDeepAnalysisEvent(
  state: DeepAnalysisProgress,
  event: DeepAnalysisJobEvent
): DeepAnalysisProgress {
  // stream_idle_timeout은 백엔드가 만든 **합성** 이벤트이지 로그의 행이 아니다.
  // `seq`는 "여기까지 읽었다"는 에코라 보통 `state.cursor`와 같다. 따라서
  // 아래 재생 가드보다 **먼저** 처리해야 한다 — 아니면 통째로 버려져서
  // 구독자가 스트림이 닫힌 사실을 영영 모른다.
  if (event.kind === STREAM_IDLE_TIMEOUT_KIND) {
    return { ...state, idleTimedOut: true };
  }

  if (event.seq <= state.cursor) {
    return state;
  }

  const next: DeepAnalysisProgress = {
    ...state,
    cursor: event.seq,
    lastKind: event.kind,
    lastActivity: activityLabel(event) ?? state.lastActivity,
    idleTimedOut: false,
  };

  switch (event.kind) {
    case JOB_STARTED:
      return { ...next, phase: "running" };
    case JOB_RESUMED:
      return { ...next, phase: "running", resumed: true };
    case JOB_COMPLETED:
      return {
        ...next,
        phase: "completed",
        reportMarkdown:
          asString(event.payload.report_markdown) ?? next.reportMarkdown,
      };
    case JOB_FAILED:
      return {
        ...next,
        phase: "failed",
        error: asString(event.payload.error) ?? "Deep analysis job failed",
      };
    case "question_opened":
      return { ...next, questionsOpened: next.questionsOpened + 1 };
    case "split":
      return { ...next, splits: next.splits + 1 };
    case "pass_completed":
      return { ...next, passesCompleted: next.passesCompleted + 1 };
    case "claim_verified":
      return { ...next, claimsVerified: next.claimsVerified + 1 };
    case "claim_rejected":
      return { ...next, claimsRejected: next.claimsRejected + 1 };
    case "claim_unverified":
      return { ...next, claimsUnverified: next.claimsUnverified + 1 };
    case "report_graded":
      return { ...next, gradeAttempts: next.gradeAttempts + 1 };
    default:
      return next;
  }
}

/** run이 끝났는가 — 더 구독할 이유가 없는가. */
export function isDeepAnalysisSettled(state: DeepAnalysisProgress): boolean {
  return state.phase === "completed" || state.phase === "failed";
}

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

/** 같은 kind가 여러 번 나면 count로 집계한다 — 3회와 1회는 다른 이야기다. */
export type DegradationEntry = { kind: string; count: number };

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
   * 리포트 품질을 깎은 사건들. `lastActivity`와 달리 덮어써지지 않는다 —
   * 강등은 run이 끝난 뒤에도 남아야 하는 상태이기 때문이다.
   *
   * `kind`는 원장의 어휘 그대로 싣고 사람이 읽는 문구는 렌더 시점에
   * 만든다. 문구를 상태에 넣으면 재생된 옛 이벤트가 옛 문구를 고착시킨다.
   */
  degradations: DegradationEntry[];
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
    degradations: [],
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
    if (payload.ok !== true) {
      return "리포트 채점 재시도";
    }
    // `judge_budget_exhausted`는 이벤트 kind가 아니다 — 판정자가 굶었다는
    // 사실은 이 payload의 `judge` 키로만 남는다 (graders/report.py).
    // 오케스트레이터가 `report_graded`를 `{"ok": ..., "attempt": ...,
    // **verdict.diagnostics}`로 남기면서 diagnostics를 spread하기 때문에
    // `judge`는 `payload.diagnostics.judge`가 아니라 `payload.judge`다.
    // `ok`만 보면 굶은 판정자의 통과와 실제 승인이 같은 문구를 내고,
    // 그것이 이 항목의 실제 결함이었다.
    const judge = asString(payload.judge);
    if (judge === "budget_exhausted") {
      return "리포트 채점 통과 (판정자 예산 소진 — 실제 심사 없음)";
    }
    if (judge === "truncated") {
      return "리포트 채점 통과 (판정자 응답 잘림 — 실제 심사 없음)";
    }
    if (judge === "unparseable") {
      return "리포트 채점 통과 (판정자 응답 해석 실패 — 실제 심사 없음)";
    }
    return "리포트 채점 통과";
  }
  if (kind === "report_assembly_degraded") {
    return "리포트가 템플릿으로 강등됨 (조립 예산 부족)";
  }
  if (kind === "node_reduction_degraded") {
    return "하위 요약 강등 — 자식 답변 이어붙임";
  }
  if (kind === "finalization_prompt_clamped") {
    return payload.exhausted === true
      ? "마무리 프롬프트가 허용량을 넘음 — 내용이 잘림"
      : "마무리 프롬프트 축소됨";
  }
  if (kind === "investigation_stopped_at_floor") {
    return "조사 중단 — 마무리 예산만 남음";
  }
  if (kind === "investigation_stopped_at_input_bound") {
    // floor 정지와 다른 사실이다 — 예산은 남았는데 프롬프트가 그 안에
    // 안 들어갔다. 하나로 묶으면 백엔드가 방금 없앤 구별이 화면에서
    // 다시 사라진다 (로드맵 §7 G10).
    return "조사 중단 — 남은 예산에 프롬프트가 들어가지 않음";
  }
  if (kind === "llm_truncated") {
    const stage = asString(payload.stage);
    return stage ? `응답 잘림 · ${stage}` : "응답 잘림";
  }
  if (kind === "truncation_handled") {
    return payload.action === "retried_ok"
      ? "응답 잘림 — 재시도 성공"
      : "응답 잘림 — 복구 실패";
  }
  if (kind === "entailment_filter_skipped") {
    return "함의 필터 건너뜀";
  }
  if (kind === "claim_discarded") {
    return "클레임 폐기됨";
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
 * 이 이벤트가 리포트를 사용자가 받았어야 할 것보다 못하게 만들었는가 —
 * 만들었다면 어떤 이름으로 셀 것인가.
 *
 * ⚠️ 🟡 **알려진 중복.** 같은 규칙이 백엔드에도 있다:
 * `neos/workflow/deep_analysis/ledger.py`의 `_degradation_kind()`.
 * 이쪽은 라이브 스트림을, 저쪽은 새로고침 후 복원을 담당한다. 어휘를 바꿀 때
 * **반드시 양쪽을 함께** 고칠 것 — 정본 fixture 목록이
 * `web/tests/source/deep-analysis-degradation.test.ts`와
 * `tests/workflow/deep_analysis/test_ledger_degradations.py`에 같은 내용으로
 * 들어 있다. 통합 검토는 로드맵 §7 FE6.
 *
 * 조사 범위나 검증 강도를 깎은 것(`investigation_stopped_at_floor`,
 * `claim_discarded` 등)은 여기 들지 않는다 — 리포트 자체는 주어진 재료로
 * 낼 수 있는 최선이기 때문이다. `llm_truncated`도 마찬가지다: 확장 재시도가
 * 성공하면 산출물에 영향이 없고, 실패한 경우만 가르려면 `truncation_handled`와
 * 상관시켜야 한다. 잘못된 경고보다 과소 보고를 택한다.
 *
 * `report_graded`는 kind가 아니라 **payload가** 강등을 결정하는 유일한 경우다.
 * 굶은/잘린/해석 실패 판정자는 전부 `ok=true`로 재조립 루프를 끝내므로
 * (`graders/report.py`) `judge` 키가 달린 이벤트는 run당 최대 1건이고 항상
 * 최종 판정이다 — 중간 시도가 오탐으로 잡히지 않는다.
 */
function degradationKind(event: DeepAnalysisJobEvent): string | null {
  const { kind, payload } = event;
  if (kind === "report_assembly_degraded") return kind;
  if (kind === "node_reduction_degraded") return kind;
  if (kind === "finalization_prompt_clamped") {
    return payload.exhausted === true ? kind : null;
  }
  if (kind === "report_graded") {
    const judge = asString(payload.judge);
    return judge ? `judge_unreviewed:${judge}` : null;
  }
  return null;
}

/** 최초 발생 순서를 보존하며 같은 kind를 count로 합친다. */
function withDegradation(
  entries: DegradationEntry[],
  kind: string
): DegradationEntry[] {
  const index = entries.findIndex((entry) => entry.kind === kind);
  if (index === -1) {
    return [...entries, { kind, count: 1 }];
  }
  return entries.map((entry, i) =>
    i === index ? { ...entry, count: entry.count + 1 } : entry
  );
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

  const degradation = degradationKind(event);
  const next: DeepAnalysisProgress = {
    ...state,
    cursor: event.seq,
    lastKind: event.kind,
    lastActivity: activityLabel(event) ?? state.lastActivity,
    degradations: degradation
      ? withDegradation(state.degradations, degradation)
      : state.degradations,
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

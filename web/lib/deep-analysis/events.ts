/**
 * deep_analysis job 이벤트 계약 — 런타임 검증 (순수 모듈)
 *
 * 감사 §4.5가 지적한 "백엔드 응답 무검증"을 이 경로에서는 반복하지 않는다.
 * 스트림에서 들어오는 모든 객체는 이 모듈의 파서를 통과해야만
 * 리듀서(`./progress`)에 도달한다. 검증 실패는 **조용히 버린다** —
 * 이벤트 하나가 깨졌다고 진행 중인 run 전체를 죽일 이유가 없다.
 *
 * ## 봉투(envelope) 형태에 관한 주의
 *
 * 공유된 계약 문서는 각 이벤트가 `seq` / `kind` / `payload` / `ts`를 갖는다고
 * 적었으나, 실제로 배포된 백엔드
 * (`neos/api/handlers/deep_analysis_handlers.py`의 `stream_deep_analysis_events`,
 * `neos/workflow/deep_analysis/event_stream.py`의 `read_events_after`)는
 *
 *     data: {"seq": 12, "type": "claim_verified", "qid": "...", "payload": {...}}
 *
 * 를 보낸다 — 필드 이름이 `kind`가 아니라 `type`이고 `ts`가 없다.
 * 어느 쪽이 최종인지 프론트가 임의로 정할 수 없으므로 **둘 다 받는다.**
 * `ts`는 선택 필드로 둔다. (보고서에 불일치로 명시했다.)
 *
 * ## `seq`는 단조 증가하지만 **연속(contiguous)이 아니다**
 *
 * `DAEvent.seq`는 테이블 전역 BigInteger autoincrement PK다
 * (`neos/database/deep_analysis_models.py`). 즉 같은 run의 이벤트 사이에
 * 다른 run의 seq가 끼어들어 **구멍이 생기는 것이 정상**이다.
 * 따라서 `features/coding/stream`의 `nextContiguousSeq`(연속성 검사) 패턴을
 * 여기 그대로 가져오면 안 된다 — 정상 이벤트를 갭으로 오판해 스트림이 멈춘다.
 * 여기서는 "커서보다 큰가"만 본다.
 */

import { z } from "zod";

/** 챗 SSE가 job 제출을 알리는 이벤트 타입. */
export const DEEP_ANALYSIS_STARTED_EVENT_TYPE = "neos:deep_analysis_started";

export const JOB_STARTED = "job_started";
export const JOB_RESUMED = "job_resumed";
export const JOB_COMPLETED = "job_completed";
export const JOB_FAILED = "job_failed";

/**
 * 스트림이 이 kind를 보면 종료한다 (백엔드 `jobs.py`의 `TERMINAL_JOB_KINDS`와 동일).
 * 재구독해도 새 이벤트가 나오지 않으므로 클라이언트도 여기서 멈춰야 한다.
 */
export const TERMINAL_JOB_KINDS: ReadonlySet<string> = new Set([
  JOB_COMPLETED,
  JOB_FAILED,
]);

/**
 * 백엔드가 유휴 타임아웃으로 스트림을 닫을 때 마지막으로 보내는 합성 이벤트
 * (`deep_analysis_handlers.py`의 `stream_idle_timeout`).
 *
 * **종료가 아니다.** run은 아직 돌고 있을 수 있으므로 커서를 들고 재구독해야 한다.
 */
export const STREAM_IDLE_TIMEOUT_KIND = "stream_idle_timeout";

export function isTerminalJobKind(kind: string): boolean {
  return TERMINAL_JOB_KINDS.has(kind);
}

// ---------------------------------------------------------------------------
// 챗 SSE: neos:deep_analysis_started
// ---------------------------------------------------------------------------

const deepAnalysisStartedSchema = z.object({
  run_id: z.string().min(1),
  events_url: z.string().min(1),
  assistant_message_id: z.string().min(1).nullish(),
});

export type DeepAnalysisStarted = {
  runId: string;
  eventsUrl: string;
  assistantMessageId?: string;
};

/**
 * 챗 SSE의 `neos:deep_analysis_started` 페이로드를 검증한다.
 *
 * @returns 검증에 실패하면 `null` — 호출자는 이 이벤트를 무시해야 한다.
 */
export function parseDeepAnalysisStarted(
  raw: unknown
): DeepAnalysisStarted | null {
  const parsed = deepAnalysisStartedSchema.safeParse(raw);
  if (!parsed.success) {
    return null;
  }
  return {
    runId: parsed.data.run_id,
    eventsUrl: parsed.data.events_url,
    assistantMessageId: parsed.data.assistant_message_id ?? undefined,
  };
}

// ---------------------------------------------------------------------------
// job 이벤트 스트림 봉투
// ---------------------------------------------------------------------------

const jobEventEnvelopeSchema = z
  .object({
    seq: z.number().int().nonnegative(),
    // 계약 문서는 `kind`, 배포된 백엔드는 `type` — 둘 다 받는다(위 주석 참조).
    type: z.string().min(1).optional(),
    kind: z.string().min(1).optional(),
    qid: z.string().nullish(),
    ts: z.string().nullish(),
    payload: z.record(z.unknown()).nullish(),
  })
  .refine((value) => Boolean(value.type ?? value.kind), {
    message: "job event must carry `type` or `kind`",
  });

export type DeepAnalysisJobEvent = {
  seq: number;
  kind: string;
  qid?: string;
  ts?: string;
  payload: Record<string, unknown>;
};

/**
 * job 이벤트 봉투를 검증·정규화한다.
 *
 * @returns 계약을 벗어나면 `null`. 절대 예외를 던지지 않는다.
 */
export function parseJobEvent(raw: unknown): DeepAnalysisJobEvent | null {
  const parsed = jobEventEnvelopeSchema.safeParse(raw);
  if (!parsed.success) {
    return null;
  }
  const { seq, type, kind, qid, ts, payload } = parsed.data;
  return {
    seq,
    // refine이 둘 중 하나의 존재를 보장한다.
    kind: (type ?? kind) as string,
    qid: qid ?? undefined,
    ts: ts ?? undefined,
    payload: payload ?? {},
  };
}

/**
 * SSE 텍스트 한 줄에서 job 이벤트를 뽑는다.
 *
 * `: keepalive`, `event:` 라인, `data: [DONE]`, 빈 줄은 모두 `null`이다.
 */
export function parseJobEventLine(line: string): DeepAnalysisJobEvent | null {
  if (!line.startsWith("data: ")) {
    return null;
  }
  const body = line.slice(6).trim();
  if (!body || body === "[DONE]") {
    return null;
  }
  let raw: unknown;
  try {
    raw = JSON.parse(body);
  } catch {
    return null;
  }
  return parseJobEvent(raw);
}

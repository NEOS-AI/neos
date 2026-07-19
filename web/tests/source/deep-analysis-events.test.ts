import assert from "node:assert/strict";
import test from "node:test";
import {
  DEEP_ANALYSIS_STARTED_EVENT_TYPE,
  isTerminalJobKind,
  JOB_COMPLETED,
  JOB_FAILED,
  parseDeepAnalysisStarted,
  parseJobEvent,
  parseJobEventLine,
  STREAM_IDLE_TIMEOUT_KIND,
} from "../../lib/deep-analysis/events";

test("deep_analysis_started 이벤트 타입 상수가 계약과 일치한다", () => {
  assert.equal(DEEP_ANALYSIS_STARTED_EVENT_TYPE, "neos:deep_analysis_started");
});

test("deep_analysis_started 페이로드를 검증해 정규화한다", () => {
  const parsed = parseDeepAnalysisStarted({
    type: "neos:deep_analysis_started",
    run_id: "run-1",
    events_url: "/api/v1/deep-analysis/run-1/events",
    assistant_message_id: "msg-1",
  });

  assert.deepEqual(parsed, {
    runId: "run-1",
    eventsUrl: "/api/v1/deep-analysis/run-1/events",
    assistantMessageId: "msg-1",
  });
});

test("assistant_message_id는 선택 필드다", () => {
  const parsed = parseDeepAnalysisStarted({
    run_id: "run-1",
    events_url: "/x",
  });
  assert.equal(parsed?.assistantMessageId, undefined);
});

test("검증되지 않는 deep_analysis_started 페이로드는 null이다", () => {
  // 감사 §4.5 — 백엔드 응답을 무검증으로 신뢰하지 않는다.
  assert.equal(parseDeepAnalysisStarted(null), null);
  assert.equal(parseDeepAnalysisStarted({}), null);
  assert.equal(
    parseDeepAnalysisStarted({ run_id: "", events_url: "/x" }),
    null
  );
  assert.equal(parseDeepAnalysisStarted({ run_id: 7, events_url: "/x" }), null);
  assert.equal(parseDeepAnalysisStarted({ run_id: "r" }), null);
});

test("job 이벤트 봉투는 `type`과 `kind`를 모두 받는다", () => {
  // 배포된 백엔드는 `type`, 공유 계약 문서는 `kind`라고 적었다.
  const fromType = parseJobEvent({
    seq: 3,
    type: "claim_verified",
    payload: { claim_id: "c1" },
  });
  const fromKind = parseJobEvent({
    seq: 3,
    kind: "claim_verified",
    payload: { claim_id: "c1" },
  });

  assert.equal(fromType?.kind, "claim_verified");
  assert.equal(fromKind?.kind, "claim_verified");
  assert.deepEqual(fromType?.payload, { claim_id: "c1" });
});

test("payload와 ts는 없어도 된다", () => {
  const event = parseJobEvent({ seq: 1, type: "job_started" });
  assert.deepEqual(event, {
    seq: 1,
    kind: "job_started",
    qid: undefined,
    ts: undefined,
    payload: {},
  });
});

test("계약을 벗어난 job 이벤트는 버린다", () => {
  assert.equal(parseJobEvent({ type: "job_started" }), null, "seq 없음");
  assert.equal(parseJobEvent({ seq: -1, type: "x" }), null, "음수 seq");
  assert.equal(parseJobEvent({ seq: 1.5, type: "x" }), null, "정수 아님");
  assert.equal(parseJobEvent({ seq: 1 }), null, "kind/type 둘 다 없음");
  assert.equal(parseJobEvent("nope"), null);
});

test("SSE 라인 파서가 잡음을 걸러낸다", () => {
  assert.equal(parseJobEventLine(": keepalive"), null);
  assert.equal(parseJobEventLine(""), null);
  assert.equal(parseJobEventLine("event: message"), null);
  assert.equal(parseJobEventLine("data: [DONE]"), null);
  assert.equal(parseJobEventLine("data: {broken"), null);

  const event = parseJobEventLine(
    'data: {"seq":9,"type":"split","payload":{}}'
  );
  assert.equal(event?.seq, 9);
  assert.equal(event?.kind, "split");
});

test("종료 kind는 job_completed / job_failed 뿐이다", () => {
  assert.ok(isTerminalJobKind(JOB_COMPLETED));
  assert.ok(isTerminalJobKind(JOB_FAILED));
  assert.equal(isTerminalJobKind("job_started"), false);
  assert.equal(isTerminalJobKind("job_resumed"), false);
  // 유휴 타임아웃은 스트림만 닫는다 — run은 계속된다.
  assert.equal(isTerminalJobKind(STREAM_IDLE_TIMEOUT_KIND), false);
});

import assert from "node:assert/strict";
import test from "node:test";
import type { DeepAnalysisJobEvent } from "../../lib/deep-analysis/events";
import {
  initialDeepAnalysisProgress,
  isDeepAnalysisSettled,
  reduceDeepAnalysisEvent,
} from "../../lib/deep-analysis/progress";

const event = (
  seq: number,
  kind: string,
  payload: Record<string, unknown> = {}
): DeepAnalysisJobEvent => ({ seq, kind, payload });

const applyAll = (events: DeepAnalysisJobEvent[]) =>
  events.reduce(reduceDeepAnalysisEvent, initialDeepAnalysisProgress());

test("job_started가 phase를 running으로 올리고 커서를 전진시킨다", () => {
  const state = applyAll([event(1, "job_started", { profile: "deep" })]);
  assert.equal(state.phase, "running");
  assert.equal(state.cursor, 1);
  assert.equal(state.resumed, false);
});

test("job_resumed는 재개 표식을 남긴다", () => {
  const state = applyAll([event(1, "job_resumed", { resume: true })]);
  assert.equal(state.phase, "running");
  assert.equal(state.resumed, true);
});

test("하네스 내부 이벤트가 진행 카운터를 채운다", () => {
  const state = applyAll([
    event(1, "job_started"),
    event(2, "question_opened", { text: "무엇이 원인인가" }),
    event(3, "question_opened", { text: "하위 질문" }),
    event(4, "split", { children: ["a", "b"] }),
    event(5, "pass_completed", { claims: 4 }),
    event(6, "claim_verified"),
    event(7, "claim_verified"),
    event(8, "claim_rejected"),
    event(9, "claim_unverified"),
    event(10, "report_graded", { ok: false }),
  ]);

  assert.equal(state.questionsOpened, 2);
  assert.equal(state.splits, 1);
  assert.equal(state.passesCompleted, 1);
  assert.equal(state.claimsVerified, 2);
  assert.equal(state.claimsRejected, 1);
  assert.equal(state.claimsUnverified, 1);
  assert.equal(state.gradeAttempts, 1);
  assert.equal(state.cursor, 10);
});

test("job_completed가 리포트를 싣는다", () => {
  const state = applyAll([
    event(1, "job_started"),
    event(2, "job_completed", { report_markdown: "# 리포트\n본문" }),
  ]);

  assert.equal(state.phase, "completed");
  assert.equal(state.reportMarkdown, "# 리포트\n본문");
  assert.ok(isDeepAnalysisSettled(state));
});

test("job_failed가 에러를 표면화한다", () => {
  const state = applyAll([
    event(1, "job_started"),
    event(2, "job_failed", { error: "worker lost" }),
  ]);

  assert.equal(state.phase, "failed");
  assert.equal(state.error, "worker lost");
  assert.ok(isDeepAnalysisSettled(state));
});

test("error 문자열이 없어도 실패는 실패다", () => {
  const state = applyAll([event(1, "job_failed", {})]);
  assert.equal(state.phase, "failed");
  assert.equal(typeof state.error, "string");
});

// ---------------------------------------------------------------------------
// 회귀 고정: 재접속 = 전체 이력 재생. 두 번 세면 안 된다.
// ---------------------------------------------------------------------------

test("이력 재생은 멱등하다 — 커서 이하 이벤트는 무시된다", () => {
  const history = [
    event(1, "job_started"),
    event(2, "question_opened", { text: "q" }),
    event(3, "claim_verified"),
    event(4, "pass_completed", { claims: 2 }),
  ];

  const first = applyAll(history);
  // `after=0`으로 재접속하면 백엔드가 같은 이력을 다시 보낸다.
  const replayed = history.reduce(reduceDeepAnalysisEvent, first);

  assert.deepEqual(replayed, first, "재생이 상태를 바꾸면 안 된다");
  assert.equal(replayed.questionsOpened, 1);
  assert.equal(replayed.claimsVerified, 1);
  assert.equal(replayed.passesCompleted, 1);
  assert.equal(replayed.cursor, 4);
});

test("seq 구멍은 갭이 아니다 — 커서가 그대로 전진한다", () => {
  // DAEvent.seq는 테이블 전역 autoincrement PK라 run 사이에 번호가 비는 것이
  // 정상이다. 연속성 검사를 넣으면 정상 이벤트를 갭으로 오판해 멈춘다.
  const state = applyAll([
    event(10, "job_started"),
    event(37, "question_opened", { text: "q" }),
    event(4001, "claim_verified"),
  ]);

  assert.equal(state.cursor, 4001);
  assert.equal(state.questionsOpened, 1);
  assert.equal(state.claimsVerified, 1);
});

test("알 수 없는 kind도 커서를 전진시킨다", () => {
  // 커서가 멈추면 재구독이 영원히 같은 지점을 다시 읽는다.
  const state = applyAll([
    event(1, "job_started"),
    event(2, "some_future_event_kind"),
  ]);
  assert.equal(state.cursor, 2);
});

test("stream_idle_timeout은 커서를 전진시키지 않고 재연결 신호만 남긴다", () => {
  const running = applyAll([
    event(1, "job_started"),
    event(2, "claim_verified"),
  ]);

  // 백엔드는 지금 커서를 그대로 에코한다 (`{"seq": cursor}`).
  const idle = reduceDeepAnalysisEvent(
    running,
    event(2, "stream_idle_timeout", { run_id: "run-1" })
  );

  assert.equal(idle.idleTimedOut, true, "재연결이 필요함을 알려야 한다");
  assert.equal(idle.cursor, 2, "합성 이벤트가 커서를 소비하면 안 된다");
  assert.equal(idle.phase, "running", "유휴 타임아웃은 종료가 아니다");
  assert.equal(isDeepAnalysisSettled(idle), false);

  // 재연결 후 다음 실제 이벤트가 정상 적용된다.
  const resumed = reduceDeepAnalysisEvent(idle, event(3, "claim_verified"));
  assert.equal(resumed.claimsVerified, 2);
  assert.equal(resumed.idleTimedOut, false);
});

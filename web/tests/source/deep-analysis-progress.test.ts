import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
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

// ---------------------------------------------------------------------------
// degradations: 리포트 품질을 깎은 사건은 lastActivity와 달리 덮어써지지 않는다.
// ---------------------------------------------------------------------------

test("리포트 품질을 깎은 사건은 뒤따르는 이벤트가 덮어쓰지 않는다", () => {
  const state = applyAll([
    event(1, "node_reduction_degraded", { reason: "token_budget_exhausted" }),
    event(2, "node_reduction_degraded", { reason: "token_budget_exhausted" }),
    event(3, "report_assembly_degraded", { reason: "token_budget_exhausted" }),
    event(4, "claim_verified"),
  ]);

  assert.deepEqual(state.degradations, [
    { kind: "node_reduction_degraded", count: 2 },
    { kind: "report_assembly_degraded", count: 1 },
  ]);
  // lastActivity 는 덮어써졌지만 degradations 는 남았다 -- 이 대비가 요점이다.
  assert.equal(state.lastActivity, "클레임 검증됨");
});

test("조사 범위만 깎은 사건은 라벨은 붙되 강등으로 세지 않는다", () => {
  const state = applyAll([
    event(1, "investigation_stopped_at_floor", { floor_tokens: 41_040 }),
    event(2, "claim_discarded"),
    event(3, "llm_truncated", { stage: "worker_analysis" }),
    event(4, "entailment_filter_skipped"),
  ]);

  assert.deepEqual(state.degradations, []);
  assert.notEqual(state.lastActivity, null);
});

test("클램프가 허용량 안에 들어갔으면 강등이 아니다", () => {
  const fitted = applyAll([
    event(1, "finalization_prompt_clamped", {
      exhausted: false,
      stage: "report_assembly",
    }),
  ]);
  assert.deepEqual(fitted.degradations, []);

  const overflowed = applyAll([
    event(1, "finalization_prompt_clamped", {
      exhausted: true,
      stage: "report_assembly",
    }),
  ]);
  assert.deepEqual(overflowed.degradations, [
    { kind: "finalization_prompt_clamped", count: 1 },
  ]);
});

test("굶은 판정자는 강등으로 센다 — 심사 없이 통과한 리포트다", () => {
  const state = applyAll([
    event(1, "report_graded", { ok: true, judge: "budget_exhausted" }),
  ]);

  assert.deepEqual(state.degradations, [
    { kind: "judge_unreviewed:budget_exhausted", count: 1 },
  ]);
});

test("실제로 심사한 판정자의 통과는 강등이 아니다", () => {
  const state = applyAll([
    event(1, "report_graded", { ok: true, uncited_ratio: 0.1 }),
    event(2, "report_graded", { ok: false, code: "E_REPORT_AGENTIC" }),
  ]);

  assert.deepEqual(state.degradations, []);
  assert.equal(state.gradeAttempts, 2);
});

test("판정자 강등 3종이 각각 다른 항목으로 남는다", () => {
  const state = applyAll([
    event(1, "report_graded", { ok: true, judge: "truncated" }),
    event(2, "report_graded", { ok: true, judge: "unparseable" }),
  ]);

  assert.deepEqual(state.degradations, [
    { kind: "judge_unreviewed:truncated", count: 1 },
    { kind: "judge_unreviewed:unparseable", count: 1 },
  ]);
});

test("재생된 이벤트는 강등을 두 번 세지 않는다", () => {
  // `after=0` 재구독은 전체 이력을 다시 흘려보낸다. 커서 가드가 없으면
  // 재연결 한 번에 "3회"가 "6회"가 된다.
  const replayed = [
    event(1, "report_assembly_degraded", {}),
    event(2, "report_graded", { ok: true, judge: "budget_exhausted" }),
  ];
  const state = [...replayed, ...replayed].reduce(
    reduceDeepAnalysisEvent,
    initialDeepAnalysisProgress()
  );

  assert.deepEqual(state.degradations, [
    { kind: "report_assembly_degraded", count: 1 },
    { kind: "judge_unreviewed:budget_exhausted", count: 1 },
  ]);
});

test("굶은 판정자가 통과시킨 리포트는 승인된 리포트와 다르게 말한다", () => {
  const approved = applyAll([event(1, "report_graded", { ok: true })]);
  const starved = applyAll([
    event(1, "report_graded", { ok: true, judge: "budget_exhausted" }),
  ]);

  assert.equal(approved.lastActivity, "리포트 채점 통과");
  assert.notEqual(starved.lastActivity, "리포트 채점 통과");
  assert.ok(starved.lastActivity?.includes("판정자"));
});

// ---------------------------------------------------------------------------
// 라벨 커버리지는 정본 fixture 가 정한다.
//
// 예전에는 kind 9개가 이 파일에 손으로 적혀 있었다. 그 목록은 **백엔드가
// 이벤트를 늘려도 자라지 않으므로**, 막으려던 실패(FE1 -- 8종이 한꺼번에
// 라벨 없이 배포된 것, 로드맵 §5.2)를 그대로 통과시킨다. 실제로 그 상태에서
// 원장 kind 9종이 라벨 없이 쌓여 있었다.
//
// 이제 목록의 출처는 `tests/fixtures/deep_analysis_event_kinds.json` 하나이고,
// 백엔드 테스트(`tests/workflow/deep_analysis/test_event_kinds.py`)가 소스를
// AST 로 훑어 그 파일이 실제 어휘와 일치함을 강제한다. 강등 어휘에 FE6 이
// 붙인 것과 같은 규율이다.

const EVENT_KINDS_FIXTURE_PATH = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../tests/fixtures/deep_analysis_event_kinds.json"
);

type EventKindCase = { kind: string; labeled: boolean; reason?: string };

const CANONICAL_EVENT_KINDS: EventKindCase[] = JSON.parse(
  readFileSync(EVENT_KINDS_FIXTURE_PATH, "utf8")
).kinds;

test("fixture 가 라벨을 약속한 kind 는 전부 문구를 낸다", () => {
  const labeled = CANONICAL_EVENT_KINDS.filter((entry) => entry.labeled);
  // 대조 테스트가 덜 검사할 수 있다(FE6 의 교훈) — fixture 를 잘못 읽어 빈
  // 배열이 되면 아래 루프는 0회 돌고 조용히 통과한다.
  assert.ok(labeled.length > 25, "fixture 를 읽지 못했다");

  for (const { kind } of labeled) {
    const state = applyAll([event(1, kind)]);
    assert.notEqual(
      state.lastActivity,
      null,
      `${kind} 에 라벨이 없다 — activityLabel() 에 추가하거나 fixture 에서 사유와 함께 면제할 것`
    );
  }
});

test("fixture 가 면제한 kind 는 문구를 내지 않는다", () => {
  // 반대 방향도 건다. 한쪽만 걸면 면제 목록이 조용히 낡는다 — 나중에 라벨이
  // 붙어도 fixture 의 `labeled: false` 와 그 사유가 그대로 남아, 다음 사람이
  // 읽는 근거와 코드가 어긋난다.
  const exempt = CANONICAL_EVENT_KINDS.filter((entry) => !entry.labeled);
  assert.ok(exempt.length > 0, "fixture 를 읽지 못했다");

  for (const { kind } of exempt) {
    const state = applyAll([event(1, kind)]);
    assert.equal(
      state.lastActivity,
      null,
      `${kind} 에 라벨이 생겼다 — fixture 의 labeled 를 true 로 바꾸고 사유를 지울 것`
    );
  }
});

test("모르는 kind는 여전히 커서를 전진시킨다", () => {
  const state = applyAll([event(7, "a_kind_from_the_future")]);
  assert.equal(state.cursor, 7);
  assert.equal(state.lastActivity, null);
  assert.deepEqual(state.degradations, []);
});

test("run_manifest에 라벨이 붙는다 (FE1 재발 방지)", () => {
  const state = applyAll([
    event(1, "job_started"),
    event(2, "run_manifest", { profile: "dev" }),
  ]);
  assert.equal(state.lastActivity, "구성 확정 · dev 프로파일");
  assert.equal(state.cursor, 2);
});

test("프로파일이 없어도 run_manifest 라벨은 null이 아니다", () => {
  const state = applyAll([event(1, "run_manifest", {})]);
  assert.equal(state.lastActivity, "구성 확정");
});

test("run_manifest는 강등이 아니다", () => {
  const state = applyAll([event(1, "run_manifest", { profile: "dev" })]);
  assert.deepEqual(state.degradations, []);
});

// ---------------------------------------------------------------------------
// P1 #8: 리포트를 대화에 저장하지 못한 사실이 화면에도 이름을 갖는다.

test("메시지 저장 실패는 라벨을 갖되 강등으로 세지 않는다", () => {
  const state = applyAll([
    event(1, "assistant_message_persist_failed", {
      status: "failed",
      error_type: "ValueError",
      degradations_lost: 2,
    }),
  ]);

  assert.equal(
    state.lastActivity,
    "리포트를 대화에 저장하지 못함 (원장에는 남아 있음)"
  );
  // 강등 어휘에는 들지 않는다 -- 이 실패의 정의상 그 메시지는 저장되지
  // 않았으므로 새로고침 복원 경로에 그릴 것이 없다. 강등으로 세면 셀 수
  // 없는 것을 세게 되고, `degradations` 를 그리는 앰버 블록이 영원히
  // 나타나지 않을 사건을 광고한다.
  assert.deepEqual(state.degradations, []);
});

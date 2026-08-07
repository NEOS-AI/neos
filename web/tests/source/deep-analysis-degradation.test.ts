/**
 * 강등 → 문구. 컴포넌트가 아니라 여기서 테스트하는 이유는 `test:source`가
 * `tsx --test`라 DOM이 없기 때문이다(설계 §2).
 *
 * ⚠️ 🟡 CANONICAL_FIXTURE 는 **정본 fixture 목록**이다. 같은 목록이
 * `tests/workflow/deep_analysis/test_ledger_degradations.py` 에도 있다.
 * 강등 어휘를 바꾸면 **반드시 양쪽을 함께** 고칠 것 — 규칙이 두 언어로
 * 구현돼 있기 때문이다(설계 §3.3, 로드맵 §7 FE6).
 */

import assert from "node:assert/strict";
import test from "node:test";
import {
  degradationLabel,
  degradationNotices,
} from "../../lib/deep-analysis/degradation";
import {
  initialDeepAnalysisProgress,
  reduceDeepAnalysisEvent,
} from "../../lib/deep-analysis/progress";

// [kind, payload, 기대 결과 kind 또는 null]
// test_ledger_degradations.py 의 CANONICAL_FIXTURE 와 같은 내용이어야 한다.
const CANONICAL_FIXTURE: [string, Record<string, unknown>, string | null][] = [
  ["report_assembly_degraded", { reason: "token_budget_exhausted" },
    "report_assembly_degraded"],
  ["node_reduction_degraded", { reason: "token_budget_exhausted" },
    "node_reduction_degraded"],
  ["finalization_prompt_clamped", { exhausted: true, stage: "report_assembly" },
    "finalization_prompt_clamped"],
  ["finalization_prompt_clamped", { exhausted: false, stage: "report_assembly" },
    null],
  ["report_graded", { ok: true, judge: "budget_exhausted" },
    "judge_unreviewed:budget_exhausted"],
  ["report_graded", { ok: true, judge: "truncated" },
    "judge_unreviewed:truncated"],
  ["report_graded", { ok: true, judge: "unparseable" },
    "judge_unreviewed:unparseable"],
  ["report_graded", { ok: true, uncited_ratio: 0.1 }, null],
  ["investigation_stopped_at_floor", { floor_tokens: 41040 }, null],
  ["claim_discarded", {}, null],
  ["llm_truncated", { stage: "worker_analysis" }, null],
];

test("정본 fixture가 백엔드와 같은 kind 집합을 만든다", () => {
  const state = CANONICAL_FIXTURE.reduce(
    (acc, [kind, payload], index) =>
      reduceDeepAnalysisEvent(acc, { seq: index + 1, kind, payload }),
    initialDeepAnalysisProgress()
  );

  const expected: { kind: string; count: number }[] = [];
  for (const [, , resolved] of CANONICAL_FIXTURE) {
    if (resolved === null) continue;
    const existing = expected.find((entry) => entry.kind === resolved);
    if (existing) {
      existing.count += 1;
    } else {
      expected.push({ kind: resolved, count: 1 });
    }
  }

  assert.deepEqual(state.degradations, expected);
});

test("알려진 kind는 저마다 다른 문구를 낸다", () => {
  const kinds = [
    "report_assembly_degraded",
    "node_reduction_degraded",
    "finalization_prompt_clamped",
    "judge_unreviewed:budget_exhausted",
    "judge_unreviewed:truncated",
    "judge_unreviewed:unparseable",
  ];
  const labels = kinds.map(degradationLabel);

  assert.equal(new Set(labels).size, kinds.length);
  for (const label of labels) {
    assert.ok(label.length > 0);
    assert.ok(!label.includes("_"), `원시 kind가 문구에 샜다: ${label}`);
  }
});

test("모르는 kind도 버리지 않고 문구에 싣는다", () => {
  const label = degradationLabel("some_future_degradation");

  assert.ok(label.includes("some_future_degradation"));
});

test("모르는 judge 사유도 문구에 남는다", () => {
  const label = degradationLabel("judge_unreviewed:some_new_mode");

  assert.ok(label.includes("some_new_mode"));
});

test("2회 이상이면 횟수가 문구에 실린다", () => {
  const notices = degradationNotices([
    { kind: "report_assembly_degraded", count: 3 },
    { kind: "judge_unreviewed:truncated", count: 1 },
  ]);

  assert.equal(notices.length, 2);
  assert.ok(notices[0].text.includes("3회"));
  assert.equal(notices[0].kind, "report_assembly_degraded");
  assert.ok(!notices[1].text.includes("회)"));
});

test("빈 입력은 빈 배열을 낸다", () => {
  assert.deepEqual(degradationNotices([]), []);
});

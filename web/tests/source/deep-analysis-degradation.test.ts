/**
 * 강등 → 문구. 컴포넌트가 아니라 여기서 테스트하는 이유는 `test:source`가
 * `tsx --test`라 DOM이 없기 때문이다(설계 §2).
 *
 * 🔍 정본 fixture 는 이 파일에 없다 —
 * `tests/fixtures/deep_analysis_degradation_kinds.json` 하나이고 백엔드
 * 테스트(`tests/workflow/deep_analysis/test_ledger_degradations.py`)도 **같은
 * 파일**을 읽는다. 판정 규칙은 여전히 두 언어에 각각 구현돼 있지만(설계 §3.3,
 * 로드맵 §7 FE6), 어휘가 갈라지면 이제 반대쪽 테스트가 빨개진다.
 *
 * 저장소 밖이 아니라 위쪽을 읽는다 — 테스트 시점의 파일 읽기라 번들에는
 * 들어가지 않는다. `test:source` 가 `tsx --test`(node:test)라 `node:fs` 를 쓸 수 있다.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import {
  degradationLabel,
  degradationNotices,
} from "../../lib/deep-analysis/degradation";
import {
  initialDeepAnalysisProgress,
  reduceDeepAnalysisEvent,
} from "../../lib/deep-analysis/progress";

const FIXTURE_PATH = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../tests/fixtures/deep_analysis_degradation_kinds.json"
);

type FixtureCase = {
  kind: string;
  payload: Record<string, unknown>;
  resolved: string | null;
};

const CANONICAL_FIXTURE: FixtureCase[] = JSON.parse(
  readFileSync(FIXTURE_PATH, "utf8")
).cases;

test("정본 fixture가 백엔드와 같은 kind 집합을 만든다", () => {
  const state = CANONICAL_FIXTURE.reduce(
    (acc, { kind, payload }, index) =>
      reduceDeepAnalysisEvent(acc, { seq: index + 1, kind, payload }),
    initialDeepAnalysisProgress()
  );

  const expected: { kind: string; count: number }[] = [];
  for (const { resolved } of CANONICAL_FIXTURE) {
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

// 대조 테스트 자체가 덜 검사할 수 있다 — 트랙 E 에서 정규식이 마지막 멤버를
// 놓쳐 조용히 6개만 비교한 전례가 있다. 파일을 읽는 방식에서는 같은 사고가
// "파싱은 됐는데 케이스가 줄었다"로 온다. 백엔드의 같은 이름 테스트와 쌍이다.
test("공유 fixture가 줄어들지 않았다", () => {
  const resolved = CANONICAL_FIXTURE.filter((c) => c.resolved !== null);
  const ignored = CANONICAL_FIXTURE.filter((c) => c.resolved === null);

  assert.equal(CANONICAL_FIXTURE.length, 12);
  assert.equal(resolved.length, 6);
  assert.equal(ignored.length, 6);
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

// 회귀 가드: 새로고침 후 복원 경로에서는 `kind`가 와이어 위의 임의
// 문자열이다. 일반 객체 리터럴 테이블을 썼다면 이런 kind가
// `Object.prototype`의 상속 멤버(함수)에 걸려 `degradationLabel`이 문자열이
// 아닌 값을 돌려줬을 것이다 — 컴포넌트가 `{notice.text}`를 그대로 렌더하면
// React가 던진다.
test("Object.prototype 체인에 걸리는 kind도 문자열 문구를 낸다", () => {
  for (const kind of ["constructor", "toString", "hasOwnProperty", "__proto__"]) {
    const label = degradationLabel(kind);
    assert.equal(typeof label, "string");
    assert.ok(label.includes(kind), `원시 kind가 문구에 없다: ${kind}`);
  }
});

test("judge_unreviewed: 뒤에 Object.prototype 체인 이름이 와도 문자열 문구를 낸다", () => {
  const label = degradationLabel("judge_unreviewed:constructor");

  assert.equal(typeof label, "string");
  assert.ok(label.includes("constructor"));
});

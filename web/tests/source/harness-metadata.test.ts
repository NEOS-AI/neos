import assert from "node:assert/strict";
import test from "node:test";
import {
  applyHarnessMetadata,
  harnessFromMessageMetadata,
} from "../../lib/harness/metadata";

/**
 * 백엔드 `harness` 메타데이터의 런타임 검증 (감사 §4.5 · 로드맵 §5.9 FE17).
 *
 * `harnessMetadataSchema` 는 선언돼 있었지만 **타입 소스로만** 쓰였고 파싱은
 * 한 번도 하지 않았다. 아래 다섯 모양은 2026-09-03 에 실제로 렌더를 던지는
 * 것을 확인한 것들이다 -- 여기서 걸러지지 않으면 그 어시스턴트 메시지가
 * `ErrorBoundary` 의 "Something went wrong" 카드로 통째로 대체된다.
 */

const CRASHING_SHAPES: [string, unknown][] = [
  // `?.` 는 보호가 아니다 -- 숫자는 nullish 가 아니라 통과한 뒤 터진다.
  ["verdict 가 숫자", { status: "passed", verdict: 5 }],
  ["checks 가 문자열", { status: "passed", checks: "nope" }],
  ["failed_checks 가 문자열", { status: "failed", failed_checks: "a" }],
  ["repair_actions 가 숫자", { status: "failed", repair_actions: 3 }],
  ["harness 가 null", null],
];

test("렌더를 던지던 모양들이 전부 걸러진다", () => {
  for (const [name, harness] of CRASHING_SHAPES) {
    assert.equal(
      harnessFromMessageMetadata({ harness }),
      undefined,
      `${name} 가 통과했다 -- 이 모양은 렌더에서 TypeError 를 던진다`
    );
  }
});

test("정상 페이로드는 그대로 통과한다", () => {
  const harness = {
    status: "passed",
    mode: "strict",
    verdict: "advisory_pass",
    score: 0.76,
    failed_checks: ["citation_coverage"],
    checks: [{ check: "a", status: "completed", passed: true, score: 0.9 }],
    repair_attempts: 2,
    repair_actions: [{ action_type: "fix", status: "ok" }],
  };

  assert.deepEqual(harnessFromMessageMetadata({ harness }), harness);
});

test("status 만 있어도 통과한다 — 나머지는 선택 필드다", () => {
  assert.deepEqual(harnessFromMessageMetadata({ harness: { status: "x" } }), {
    status: "x",
  });
});

test("harness 키가 없으면 undefined 다", () => {
  assert.equal(harnessFromMessageMetadata({}), undefined);
  assert.equal(harnessFromMessageMetadata(undefined), undefined);
  assert.equal(harnessFromMessageMetadata(null), undefined);
});

// ---------------------------------------------------------------------------
// 삭제가 절반이다.
// ---------------------------------------------------------------------------

test("검증에 실패하면 통과 경로가 남긴 원본을 지운다", () => {
  // `convertBackendMessagesToUI` 의 일반 통과 경로가 먼저 원본을 복사해 둔다.
  // 넣기만 하고 지우지 않으면 **검증하지 않은 값이 그대로 남는다** -- 검증을
  // 붙인 의미가 사라지는 자리다.
  const uiMetadata: Record<string, unknown> = { harness: { verdict: 5 } };

  applyHarnessMetadata(uiMetadata, { harness: { verdict: 5 } });

  assert.equal("harness" in uiMetadata, false);
});

test("검증에 성공하면 검증된 값으로 바꾼다", () => {
  const uiMetadata: Record<string, unknown> = { harness: { status: "raw" } };

  applyHarnessMetadata(uiMetadata, { harness: { status: "passed" } });

  assert.deepEqual(uiMetadata.harness, { status: "passed" });
});

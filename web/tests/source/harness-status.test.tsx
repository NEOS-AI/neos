// DOM 전역을 **먼저** 세운다. 부수효과 임포트라 biome 의 정렬이 건드리지
// 않는다 -- 자세한 근거는 `tests/dom-setup.ts` 상단.
import "../dom-setup";
import assert from "node:assert/strict";
import test from "node:test";
import { HarnessStatus } from "../../components/harness-status";
import type { HarnessMetadata } from "../../lib/types";
import { convertBackendMessagesToUI } from "../../lib/utils";
import { renderComponent } from "../render";

/**
 * 하네스 카드의 **렌더 결과** 회귀 (로드맵 §5.7 FE14).
 *
 * 이 컴포넌트는 심층분석 카드가 "구조를 그대로 따랐다" 고 말하는 원본인데
 * **감사된 적이 없었다.** 그래서 FE11 이 심층분석에서 닫은 것과 같은 종류가
 * 그대로 남아 있었다 -- 특히 실패의 가시성이 그랬다.
 *
 * 이 카드는 챗 SSE 로 상태를 받으므로(`use-chat-stream.ts` 의
 * `applyHarnessEvent`) 네트워크가 필요 없다. 메타데이터를 그대로 넘기면 된다.
 */

const harness = (
  overrides: Partial<HarnessMetadata> = {}
): HarnessMetadata => ({
  status: "passed",
  ...overrides,
});

const renderCard = (metadata: HarnessMetadata) =>
  renderComponent(<HarnessStatus harness={metadata} />);

// ---------------------------------------------------------------------------
// A: 실패는 클릭 없이 보여야 한다 (S6).
// ---------------------------------------------------------------------------

test("실패한 검사가 있으면 카드가 펼쳐진 채 열린다", async () => {
  const host = await renderCard(
    harness({ status: "failed", failed_checks: ["citation_coverage"] })
  );

  assert.ok(
    host.textContent?.includes("citation_coverage"),
    "실패한 검사가 클릭 없이 보여야 한다"
  );
});

test("실패가 없으면 접힌 채 연다 — 대화가 카드로 덮이지 않는다", async () => {
  // 하네스는 거의 모든 응답에 붙는다. 진행마다 펼치면 소음이고, S6 이
  // 요구하는 것은 "실패가 보인다" 이지 "항상 보인다" 가 아니다.
  const host = await renderCard(
    harness({
      status: "validating",
      checks: [{ check: "a", status: "running" }],
    })
  );

  assert.equal(host.querySelector("[data-testid='harness-status']"), null);
  // 헤더는 남으므로 사용자가 열 수 있다.
  assert.ok(host.textContent?.includes("Research harness"));
});

test("펼쳐진 카드는 실패한 검사를 이름과 함께 안내한다", async () => {
  const host = await renderCard(
    harness({ status: "failed", failed_checks: ["a", "b"] })
  );
  const failed = host.querySelector("[aria-label='실패한 검사']");

  assert.ok(failed, "실패 목록에 라이브 영역이 없다");
  assert.equal(failed.getAttribute("aria-live"), "polite");
  // `ul` 이어야 한다. 역할 없는 `div` 는 role=generic 이라 `aria-label` 을
  // 달아도 이름으로 쓰이지 않는다 -- 즉 이 단언이 없으면 위 두 줄이 통과해도
  // 보조기술은 이 블록이 무엇인지 모른다.
  assert.equal(failed.tagName.toLowerCase(), "ul");
  assert.equal(failed.querySelectorAll("li").length, 2);
  assert.ok(failed.textContent?.includes("a"));
  assert.ok(failed.textContent?.includes("b"));
});

// ---------------------------------------------------------------------------
// B: 자르는 것은 유지하되 **말한다**.
// ---------------------------------------------------------------------------

const repairAction = (n: number) => ({ action_type: `fix_${n}`, status: "ok" });

test("생략된 복구 액션의 수를 말한다", async () => {
  const host = await renderCard(
    harness({
      status: "failed",
      failed_checks: ["x"],
      repair_actions: [1, 2, 3, 4, 5, 6, 7].map(repairAction),
    })
  );
  const text = host.textContent ?? "";

  // 마지막 셋은 그린다.
  assert.ok(text.includes("fix_7"));
  assert.ok(text.includes("fix_5"));
  // 나머지 넷은 흔적 없이 사라지지 않는다.
  assert.ok(!text.includes("fix_1"), "네 번째 이전은 그리지 않는다");
  assert.ok(
    text.includes("4") && text.includes("7"),
    "생략된 수와 전체 수를 말해야 한다 -- 7번 시도한 run 과 3번 시도한 run 이 " +
      "화면에서 같아 보이면 안 된다"
  );
});

test("전부 보이면 생략 안내를 붙이지 않는다", async () => {
  const host = await renderCard(
    harness({
      status: "failed",
      failed_checks: ["x"],
      repair_actions: [1, 2].map(repairAction),
    })
  );

  assert.ok(!host.textContent?.includes("표시하지 않음"));
});

// ---------------------------------------------------------------------------
// C·D: 보조기술과 잘림.
// ---------------------------------------------------------------------------

test("상태 줄 자체가 라이브 영역이다", async () => {
  // 심층분석과 달리 `sr-only` 영역을 따로 두지 않는다 -- 이 줄은 조건부가
  // 아니라 항상 그려지므로 여기 직접 걸면 중복 낭독이 없다.
  const host = await renderCard(
    harness({ status: "failed", failed_checks: ["x"], verdict: "fail" })
  );
  const live = host.querySelector(
    "[data-testid='harness-status'] > [aria-live='polite']"
  );

  assert.ok(live, "상태 줄에 aria-live 가 없다");
  assert.ok(live.textContent?.includes("fail"));
});

test("잘린 검사 이름이 전문을 title 로 갖는다", async () => {
  const long = "citation_coverage_with_a_very_long_name";
  const host = await renderCard(
    harness({
      status: "failed",
      failed_checks: ["x"],
      checks: [{ check: long, status: "completed", score: 0.5 }],
    })
  );
  const name = host.querySelector(`span.truncate[title='${long}']`);

  assert.ok(name, "검사 이름에 title 이 없다");
  assert.equal(name.textContent, long);
});

test("점수 막대에 이름이 있다", async () => {
  const host = await renderCard(
    harness({ status: "failed", failed_checks: ["x"], score: 0.76 })
  );
  const bar = host.querySelector("[role='progressbar']");

  assert.ok(bar, "점수 막대가 없다");
  assert.equal(
    bar.getAttribute("aria-label"),
    "하네스 점수",
    "이름이 없으면 'progressbar 76%' 로만 읽힌다"
  );
});

// ---------------------------------------------------------------------------
// FE17: 이력 로드 경로가 실제로 크래시를 막는가 (통합).
// ---------------------------------------------------------------------------

test("잘못된 harness 는 이력 변환에서 걸러져 렌더에 도달하지 않는다", async () => {
  // 프로브가 보여준 다섯 중 하나. 예전에는 통과 경로가 이 값을 그대로 옮겨
  // `verdict?.replaceAll` 에서 던졌고, 그 메시지가 에러 카드로 대체됐다.
  const [message] = convertBackendMessagesToUI([
    {
      message_id: "m1",
      role: "assistant",
      content: "리포트 본문",
      metadata: { harness: { status: "passed", verdict: 5 } },
    },
  ]);

  assert.equal(
    message.metadata?.harness,
    undefined,
    "검증에 실패한 harness 가 메타데이터에 남았다"
  );

  // 그리고 그 메시지는 여전히 렌더된다 -- 본문이 살아 있는 것이 요점이다.
  const host = await renderComponent(
    <div>{message.parts.map((p) => (p as { text?: string }).text)}</div>
  );
  assert.ok(host.textContent?.includes("리포트 본문"));
});

test("정상 harness 는 이력 변환을 거쳐 카드로 그려진다", async () => {
  const [message] = convertBackendMessagesToUI([
    {
      message_id: "m2",
      role: "assistant",
      content: "본문",
      metadata: { harness: { status: "failed", failed_checks: ["citation"] } },
    },
  ]);

  assert.ok(message.metadata?.harness);
  const host = await renderCard(message.metadata.harness);
  assert.ok(host.textContent?.includes("citation"));
});

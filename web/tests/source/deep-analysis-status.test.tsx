// DOM 전역을 **먼저** 세운다. 부수효과 임포트라 biome 의 정렬이
// 건드리지 않는다 -- 이름 있는 임포트로만 두면 정렬이 컴포넌트 뒤로
// 밀어 버리고(실제로 그렇게 됐다) 순서 보장이 우연에 기댄다.
// 실제 렌더 경로의 순서는 `tests/render.tsx` 가 따로 지킨다.
import "../dom-setup";
import assert from "node:assert/strict";
import test from "node:test";
import { DeepAnalysisStatus } from "../../components/deep-analysis-status";
import type { DeepAnalysisMetadata } from "../../lib/types";
import { renderComponent } from "../render";

/**
 * 심층분석 카드의 **렌더 결과** 회귀 (로드맵 §5.5 FE11 · FE12).
 *
 * 여기 있는 단언들은 전부 순수 모듈로는 닿지 못하는 자리다 — 결함이 JSX
 * 배선에 있었고, 그래서 넷이 오래 살아남았다. `degradation.ts` 가 표시 로직을
 * 순수 함수로 들고 있는 것은 그 우회로였지 대체물이 아니었다.
 *
 * ## 스트림을 어떻게 다루는가
 *
 * 이 컴포넌트는 `useDeepAnalysisStream` 으로 fetch 를 건다. 종결된 run
 * (`status: "completed"`/`"failed"`)은 **구독하지 않으므로**(`enabled: false`)
 * 대부분의 테스트가 그 모양을 쓴다 — 네트워크가 아예 없다.
 *
 * 진행 중 run 이 필요한 테스트만 `fetch` 를 세우고, 끝나면 되돌린다.
 * `dom-setup` 이 happy-dom 의 `fetch` 를 전역에 **옮기지 않는** 이유가
 * 이것이다(그 파일 주석 참조).
 */

const originalFetch = globalThis.fetch;

/** 이벤트 몇 건을 흘리고 닫히는 SSE 응답. */
function streamingFetch(lines: string[]) {
  return () =>
    Promise.resolve(
      new Response(
        new ReadableStream<Uint8Array>({
          start(controller) {
            const encoder = new TextEncoder();
            for (const line of lines) {
              controller.enqueue(encoder.encode(`${line}\n`));
            }
            controller.close();
          },
        }),
        { status: 200, headers: { "Content-Type": "text/event-stream" } }
      )
    );
}

const settled = (
  overrides: Partial<DeepAnalysisMetadata> = {}
): DeepAnalysisMetadata => ({
  run_id: "run-1",
  status: "completed",
  ...overrides,
});

const renderCard = (metadata: DeepAnalysisMetadata) =>
  renderComponent(<DeepAnalysisStatus deepAnalysis={metadata} />);

// ---------------------------------------------------------------------------
// FE11-A: 셰브론. 공유 요소 쪽 단언은 `elements-tool.test.tsx` 에 있고,
// 여기서는 이 카드가 실제로 그 요소를 타고 있는지만 본다.
// ---------------------------------------------------------------------------

test("카드가 셰브론이 도는 헤더를 쓴다", async () => {
  const host = await renderCard(settled());
  const trigger = host.querySelector("button");

  assert.ok(trigger?.classList.contains("group"));
});

// ---------------------------------------------------------------------------
// FE11-B: 헤더 배지가 본문과 어긋나지 않는다.
// ---------------------------------------------------------------------------

// 📌 종결된 run 은 강등이 없으면 **접힌 채** 열린다(`defaultOpen`). 접히면
// 본문이 통째로 언마운트되므로(`elements-tool.test.tsx` 가 고정한다) 그때
// 확인할 수 있는 것은 헤더뿐이다 — 그리고 그것이 FE11-B 가 겨눈 자리다.
test("완료된 run 의 헤더는 완료라고 말한다", async () => {
  const host = await renderCard(settled({ status: "completed" }));

  assert.ok(host.textContent?.includes("Completed"));
  assert.ok(!host.textContent?.includes("Running"));
});

test("실패한 run 의 헤더는 실패라고 말한다", async () => {
  const host = await renderCard(settled({ status: "failed" }));

  assert.ok(host.textContent?.includes("Error"));
  assert.ok(!host.textContent?.includes("Running"));
});

test("펼쳐지면 본문 배지가 헤더와 같은 것을 말한다", async () => {
  // 헤더는 영어(공유 요소), 본문은 한국어다. 둘이 **어긋나지 않는지**가
  // 요점이다 -- 예전에는 pending 에서 헤더 "Running" ↔ 본문 "대기 중" 이었다.
  const host = await renderCard(
    settled({
      status: "completed",
      degradations: [{ kind: "report_assembly_degraded", count: 1 }],
    })
  );

  assert.ok(host.textContent?.includes("Completed"));
  assert.ok(host.textContent?.includes("완료"));
});

test("연결이 401 이면 헤더가 진행 중이라고 말하지 않는다", async () => {
  // 이것이 FE11-B 의 본체다. 이 분기가 없을 때 헤더는 **영구히 "Running" 으로
  // 맥동했다** -- 본문에 "접근 권한 없음" 이 떠 있는 동안에도. 접힌 카드에서는
  // 그 거짓말이 유일하게 보이는 정보다.
  globalThis.fetch = (() =>
    Promise.resolve(new Response("no", { status: 401 }))) as typeof fetch;
  try {
    const host = await renderCard({ run_id: "run-1", status: "running" });

    assert.ok(
      host.textContent?.includes("접근 권한 없음"),
      "본문이 인증 실패를 말해야 한다"
    );
    assert.ok(
      !host.textContent?.includes("Running"),
      "헤더가 진행 중이라고 말하면 안 된다"
    );
    assert.ok(host.textContent?.includes("Error"));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

// ---------------------------------------------------------------------------
// FE11-D: 보조기술. 강등이 화면에 그려지는 것과 전달되는 것은 다르다.
// ---------------------------------------------------------------------------

test("펼쳐진 카드에는 라이브 영역이 있다", async () => {
  const host = await renderCard(
    settled({
      status: "completed",
      degradations: [{ kind: "report_assembly_degraded", count: 1 }],
    })
  );
  const live = host.querySelector("output[aria-live='polite']");

  assert.ok(live, "라이브 영역이 없으면 진행이 안내되지 않는다");
  // 활동 줄이 없을 때는 phase 를 싣는다 -- 조건부 렌더에 기대지 않고 **항상**
  // 마운트돼 있어야 안내가 안정적이다.
  assert.equal(live.textContent, "완료");
});

test("접힌 카드는 안내하지 않는다 — 그것이 설계다", async () => {
  // 사용자가 접었다는 뜻이므로 맞는 동작이고, 강등이 있으면 카드가 펼쳐진 채
  // 열리므로 놓치는 경로가 아니다. 이 성질을 적어만 두지 않고 고정한다.
  const host = await renderCard(settled({ status: "completed" }));

  assert.equal(host.querySelector("output[aria-live='polite']"), null);
  assert.ok(host.textContent?.includes("Completed"), "헤더는 남는다");
});

test("강등 목록이 이름과 함께 안내된다", async () => {
  const host = await renderCard(
    settled({ degradations: [{ kind: "report_assembly_degraded", count: 2 }] })
  );
  const list = host.querySelector("[data-testid='deep-analysis-degradations']");

  assert.ok(list, "강등 블록이 없다");
  assert.equal(list.getAttribute("aria-live"), "polite");
  assert.equal(list.getAttribute("aria-label"), "리포트 품질 경고");
  // `role="alert"` 이면 assertive 로 낭독을 끊고 목록 의미론을 덮어쓴다.
  assert.notEqual(list.getAttribute("role"), "alert");
  assert.equal(list.tagName.toLowerCase(), "ul");
  assert.ok(list.textContent?.includes("(2회)"));
});

test("강등이 있으면 카드가 펼쳐진 채 열린다", async () => {
  // 접히면 라이브 영역도 강등 블록도 언마운트된다(`elements-tool.test.tsx`).
  // 즉 이 성질이 깨지면 D 전체가 조용히 무력해진다.
  const host = await renderCard(
    settled({ degradations: [{ kind: "node_reduction_degraded", count: 1 }] })
  );

  assert.ok(host.querySelector("[data-testid='deep-analysis-degradations']"));
});

// ---------------------------------------------------------------------------
// FE11-E + FE12: 활동 줄과 통계는 진행 중 run 에서만 채워진다.
// ---------------------------------------------------------------------------

const LIVE_EVENTS = [
  'data: {"seq":1,"type":"job_started","payload":{}}',
  'data: {"seq":2,"type":"question_opened","payload":{"text":"무엇이 원인인가"}}',
  'data: {"seq":3,"type":"split","payload":{"children":["a","b"]}}',
  'data: {"seq":4,"type":"pass_completed","payload":{"claims":4}}',
  'data: {"seq":5,"type":"claim_verified","payload":{}}',
  'data: {"seq":6,"type":"claim_rejected","payload":{}}',
  'data: {"seq":7,"type":"claim_unverified","payload":{}}',
  'data: {"seq":8,"type":"report_graded","payload":{"ok":false}}',
  'data: {"seq":9,"type":"subq_review_failed","payload":{"proposals":5}}',
];

async function renderLive(): Promise<HTMLElement> {
  globalThis.fetch = streamingFetch(LIVE_EVENTS) as unknown as typeof fetch;
  try {
    return await renderCard({ run_id: "run-live", status: "running" });
  } finally {
    globalThis.fetch = originalFetch;
  }
}

test("잘린 활동 줄이 전문을 title 로 갖는다", async () => {
  const host = await renderLive();
  const line = host.querySelector("div.truncate[title]");

  assert.ok(line, "활동 줄에 title 이 없다 -- 잘리면 전문을 볼 방법이 없다");
  assert.equal(
    line.getAttribute("title"),
    "하위질문 심사 실패 — 제안 5개를 심사 없이 진행"
  );
  // 라이브 영역이 같은 문장을 싣는다. 그래야 `aria-hidden` 이 잃는 것이 없다.
  assert.equal(line.getAttribute("aria-hidden"), "true");
  assert.equal(
    host.querySelector("output[aria-live='polite']")?.textContent,
    line.getAttribute("title")
  );
});

test("리듀서가 센 카운터가 전부 화면에 도달한다", async () => {
  // FE12. 예전에는 일곱을 세고 넷만 그렸다 -- 특히 `claimsUnverified` 는
  // 기각과 형제인 품질 신호인데 기각만 보여줬다.
  const host = await renderLive();
  const text = host.textContent ?? "";

  for (const label of [
    "질문",
    "질문 분해",
    "패스",
    "검증 클레임",
    "기각 클레임",
    "미검증 클레임",
    "채점 시도",
  ]) {
    assert.ok(text.includes(label), `${label} 이 화면에 없다`);
  }
});

test("이름으로 갈리지 않는 통계에는 툴팁이 있다", async () => {
  const host = await renderLive();
  const tiles = [...host.querySelectorAll("div[title]")].filter((tile) =>
    tile.textContent?.includes("미검증 클레임")
  );

  assert.equal(tiles.length, 1);
  assert.ok(
    tiles[0].getAttribute("title")?.includes("재시도 캡"),
    "기각과 미검증은 이름만으로 구별되지 않는다"
  );
});

test("값이 0 인 카운터는 그리지 않는다", async () => {
  // 표가 일곱으로 길어져도 조용한 run 은 조용해야 한다.
  globalThis.fetch = streamingFetch([
    'data: {"seq":1,"type":"job_started","payload":{}}',
    'data: {"seq":2,"type":"question_opened","payload":{"text":"q"}}',
  ]) as unknown as typeof fetch;
  try {
    const host = await renderCard({ run_id: "run-quiet", status: "running" });
    const text = host.textContent ?? "";

    assert.ok(text.includes("질문"));
    assert.ok(!text.includes("미검증 클레임"));
    assert.ok(!text.includes("채점 시도"));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

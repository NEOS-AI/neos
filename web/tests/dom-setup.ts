/**
 * `tsx --test` 를 위한 DOM 전역 설치 (컴포넌트 테스트 전용)
 *
 * ## 왜 필요했나
 *
 * 이 저장소의 프론트 테스트는 `tsx --test`(node:test)로 돈다. 러너에 DOM 이
 * 없어서 **컴포넌트 테스트가 0개였고**, 그래서 표시 로직이 순수 모듈로
 * 빠져 나가 있다(`lib/deep-analysis/degradation.ts` 의 상단 주석이 그 이유를
 * 적는다). 그 우회로가 닿지 못하는 곳 — JSX 배선 자체 — 에서 결함 넷이
 * 오래 살아남았다(로드맵 §5.5 FE11): 셰브론이 한 번도 회전하지 않았고,
 * 헤더 배지가 오류 상태에서 거짓말했고, 라이브 영역이 없었고, 잘린 줄에
 * 툴팁이 없었다. **넷 다 렌더 결과를 보면 즉시 드러난다.**
 *
 * ## 왜 Vitest 도 Testing Library 도 아닌가
 *
 * 러너를 하나 더 들이면 CI 도 둘, 설정도 둘, 사람이 외울 것도 둘이 된다.
 * 필요한 것은 러너가 아니라 **DOM 하나**였다. 그래서 의존성은 `happy-dom`
 * 하나뿐이고 렌더는 React 가 이미 주는 것(`act` + `createRoot`)으로 한다.
 * 쿼리 편의가 아쉬워지면 그때 Testing Library 를 얹으면 되고, 그 결정은
 * 이 파일을 바꾸지 않는다.
 *
 * ## 쓰는 법
 *
 * 컴포넌트 테스트 파일의 **첫 줄**에서 부수효과로 임포트한다:
 *
 *     import "../dom-setup";
 *
 * 첫 줄이어야 하는 이유: `react-dom/client` 는 로드 시점에 전역을 본다.
 * 나중에 임포트하면 이미 늦다. esbuild 가 CJS 로 바꿔도 임포트 실행
 * 순서는 보존되므로 이 규칙만 지키면 된다.
 *
 * ⚠️ **이 파일은 `*.test.ts` 가 아니다.** 테스트가 없으므로 러너가 직접
 * 집으면 "테스트 0건" 으로 실패한다. `tests/` 바로 아래 두어 `test:source`
 * 글롭(`tests/source/**`)에서 벗어나 있다.
 */

import { Window } from "happy-dom";

const win = new Window({ url: "http://localhost" });

/**
 * React 와 Radix 가 실제로 만지는 전역만 옮긴다.
 *
 * 통째로 복사하지 않는 이유: happy-dom 의 `Window` 에는 `fetch` 도 들어 있고,
 * 그것을 전역에 덮으면 **테스트가 심는 fetch 스텁을 조용히 이긴다.**
 * 이 카드의 훅은 fetch 로 이벤트 스트림을 읽으므로 정확히 그 자리에서
 * 어긋난다 — 목록을 명시하는 편이 그 사고를 원천 차단한다.
 */
const GLOBALS = [
  "window",
  "document",
  "navigator",
  "location",
  "history",
  "Node",
  "Element",
  "HTMLElement",
  "HTMLButtonElement",
  "HTMLInputElement",
  "SVGElement",
  "DocumentFragment",
  "Event",
  "CustomEvent",
  "KeyboardEvent",
  "MouseEvent",
  "PointerEvent",
  "getComputedStyle",
  "requestAnimationFrame",
  "cancelAnimationFrame",
  "MutationObserver",
  "ResizeObserver",
  "DOMRect",
] as const;

for (const key of GLOBALS) {
  const value = (win as unknown as Record<string, unknown>)[key];
  if (value === undefined) {
    continue;
  }
  // 단순 대입이 아니라 `defineProperty` 다. Node 22 의 `globalThis.navigator`
  // 는 **접근자만 있는 속성**이라 `globalThis.navigator = ...` 가
  // `TypeError: Cannot set property navigator of #<Object> which has only a
  // getter` 로 죽는다. `location` 도 같은 부류다.
  Object.defineProperty(globalThis, key, {
    value,
    configurable: true,
    writable: true,
  });
}

// React 19 의 `act` 가 이 플래그를 보고 업데이트를 동기적으로 비운다.
// 없으면 `act` 안의 렌더가 커밋되기 전에 단언이 돌아 간헐 실패가 된다.
(globalThis as unknown as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT =
  true;

/** 마운트한 루트를 테스트가 정리할 수 있게 하는 최소 도우미. */
export function mountPoint(): HTMLElement {
  const host = document.createElement("div");
  document.body.appendChild(host);
  return host;
}

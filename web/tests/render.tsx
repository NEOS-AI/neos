// DOM 전역이 **먼저** 서야 한다 -- 아래 `react-dom/client` 가 로드 시점에
// 전역을 본다. esbuild 가 CJS 로 바꿔도 임포트 실행 순서는 보존된다.
import "./dom-setup";

import { afterEach } from "node:test";
import type { ReactElement } from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { mountPoint } from "./dom-setup";

/**
 * 컴포넌트를 붙였다 떼는 최소 헬퍼.
 *
 * ## `afterEach` 정리가 선택이 아닌 이유
 *
 * 처음에는 정리 없이 마운트만 했고 **테스트 실행이 멈췄다**(2분 타임아웃).
 * `useDeepAnalysisStream` 은 스트림이 종결 이벤트 없이 닫히면 커서를 들고
 * **다시 붙는다** -- 그것이 이 훅의 설계이고(유휴 타임아웃은 종료가 아니다),
 * 따라서 언마운트하지 않으면 백오프 타이머가 영원히 이벤트 루프를 붙든다.
 *
 * 즉 여기서의 정리는 위생이 아니라 **동작의 일부**다. 언마운트가 훅의 정리
 * 함수를 불러 `disposed = true` 를 세우고 타이머를 지운다.
 */

const roots: Root[] = [];

export async function renderComponent(
  node: ReactElement
): Promise<HTMLElement> {
  const host = mountPoint();
  const root = createRoot(host);
  roots.push(root);
  // React 의 act 는 콜백이 thenable 을 돌려줄 때만 **비동기 경로**를 타고,
  // 그 경로만이 이펙트가 시작한 promise 사슬(여기서는 이벤트 스트림 fetch)을
  // 비운다. 동기 콜백으로 바꾸면 라이브 이벤트가 하나도 적용되지 않은 채
  // 단언이 돈다. 즉 `async` 는 잉여가 아니라 이 호출의 목적이다.
  // biome-ignore lint/suspicious/useAwait: 위 문단 -- act 의 비동기 경로를 고른다
  await act(async () => {
    root.render(node);
  });
  return host;
}

afterEach(async () => {
  // React 의 act 는 콜백이 thenable 을 돌려줄 때만 **비동기 경로**를 타고,
  // 그 경로만이 이펙트가 시작한 promise 사슬(여기서는 이벤트 스트림 fetch)을
  // 비운다. 동기 콜백으로 바꾸면 라이브 이벤트가 하나도 적용되지 않은 채
  // 단언이 돈다. 즉 `async` 는 잉여가 아니라 이 호출의 목적이다.
  // biome-ignore lint/suspicious/useAwait: 위 문단 -- act 의 비동기 경로를 고른다
  await act(async () => {
    for (const root of roots) {
      root.unmount();
    }
  });
  roots.length = 0;
  document.body.innerHTML = "";
});

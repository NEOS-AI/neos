import { strict as assert } from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";
import { fileURLToPath } from "node:url";

import {
  isAbortError,
  shouldSurfaceStreamError,
} from "../../lib/stream-errors";

/**
 * 회귀 테스트: 정지(Stop) 버튼이 에러 토스트를 띄우던 문제
 * (FE_AUDIT_260717 §4.1)
 */
describe("스트림 에러 분류", () => {
  test("AbortController가 만든 실제 AbortError를 인식한다", async () => {
    const controller = new AbortController();
    controller.abort();

    // 실제 런타임이 던지는 오류로 검증한다 (수제 객체가 아니라)
    const error = await fetch("http://127.0.0.1:1/", {
      signal: controller.signal,
    }).catch((e) => e);

    assert.equal(error.name, "AbortError");
    assert.equal(isAbortError(error), true);
    assert.equal(
      shouldSurfaceStreamError(error),
      false,
      "정지는 사용자 의도된 정상 종료 — 에러 토스트를 띄우면 안 된다"
    );
  });

  test("일반 에러는 그대로 표면화한다", () => {
    assert.equal(isAbortError(new Error("backend exploded")), false);
    assert.equal(shouldSurfaceStreamError(new Error("backend exploded")), true);
  });

  test("DOMException 형태의 AbortError도 인식한다 (instanceof Error에 의존하지 않는다)", () => {
    const domError = new DOMException("aborted", "AbortError");
    assert.equal(isAbortError(domError), true);
  });

  test("null/undefined/문자열에 안전하다", () => {
    assert.equal(isAbortError(null), false);
    assert.equal(isAbortError(undefined), false);
    assert.equal(isAbortError("AbortError"), false);
  });
});

const read = (relativePath: string) =>
  readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), "utf8");

/**
 * 구조적 회귀 테스트: 재개가 재실행이 되어 재과금되던 문제
 * (FE_AUDIT_260717 §4.2)
 *
 * 훅 자체는 React 렌더러가 없어 단위 테스트가 불가하므로(이 프로젝트는
 * vitest/jest/testing-library가 없다) 소스 수준에서 불변식을 고정한다.
 */
describe("재개(resume)는 재실행을 트리거하지 않는다", () => {
  test("resumeStream이 sendMessage를 호출하지 않는다", () => {
    const source = read("../../hooks/use-chat-stream.ts");

    const start = source.indexOf("const resumeStream");
    assert.ok(start > -1, "resumeStream을 찾지 못했다");

    // resumeStream 정의부터 return 문(훅 반환)까지를 본문으로 본다
    const body = source.slice(start, source.indexOf("return {", start));

    assert.ok(
      !body.includes("sendMessage("),
      "resumeStream이 sendMessage를 호출한다 — 워크플로우가 재실행되어 재과금된다. " +
        "진짜 재개는 백엔드 이벤트 재생(Phase 3) 위에서 구현해야 한다."
    );
  });

  test("채팅 페이지가 autoResume을 켜지 않는다", () => {
    const source = read("../../app/(chat)/chat/[id]/page.tsx");

    assert.ok(
      !source.includes("autoResume={true}"),
      "autoResume이 다시 켜졌다 — 중단된 대화를 새로고침하면 재과금된다"
    );
  });
});

/**
 * 구조적 회귀 테스트: 정지 후에도 백엔드가 계속 과금하던 문제
 * (FE_AUDIT_260717 §4.3)
 */
describe("클라이언트 abort가 백엔드로 전파된다", () => {
  test("채팅 스트림 호출이 request.signal을 전달한다", () => {
    const source = read("../../app/(chat)/api/chat/route.ts");

    assert.ok(
      source.includes("signal: request.signal"),
      "백엔드 스트림 호출에 signal이 없다 — 정지해도 백엔드가 계속 생성하고 계속 과금된다"
    );
  });
});

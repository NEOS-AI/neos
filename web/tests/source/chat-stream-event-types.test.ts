import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

/**
 * 챗 SSE 이벤트 어휘의 프론트 쪽 짝 (`tests/fixtures/chat_stream_event_types.json`).
 *
 * 백엔드 테스트(`tests/api/test_chat_stream_event_types.py`)가 fixture 를
 * **발행되는 집합과 정확히** 맞춘다. 여기서는 `handled` 를 양방향으로 본다:
 *
 * - true  → `open-responses-types.ts` 에 그 type 의 가드가 있고, 훅
 *           (`hooks/use-chat-stream.ts`)이 그 가드를 **부른다**.
 * - false → 훅이 그 가드를 부르지 **않는다**. 나중에 처리가 붙었는데 false 가
 *           남아 있으면 면제가 조용히 낡는다.
 *
 * 이 훅은 거대한 스트리밍 루프라 이벤트별 동작을 단위로 떼어 볼 수 없다. 그래서
 * 가드 호출을 **소스로** 본다 -- 코딩·DA fixture 가 리듀서를 직접 부르는 것보다
 * 약한 단언이고, 그 약함은 여기 적어 둔다. 처리 내용 자체는 순수 모듈로 뗀
 * 것(`reasoning-parts.ts` 등)의 테스트가 본다.
 */

type Entry = { type: string; handled: boolean; reason?: string };

const fixture: { types: Entry[] } = JSON.parse(
  readFileSync("../tests/fixtures/chat_stream_event_types.json", "utf8")
);
const guards = readFileSync("lib/open-responses-types.ts", "utf8");
const hook = readFileSync("hooks/use-chat-stream.ts", "utf8");

/** `export function isX(...) { ... .type === "<type>" ... }` → type 별 가드 이름. */
function guardFor(type: string): string | null {
  const pattern = /export function (\w+)\([^)]*\)[^{]*\{([\s\S]*?)\n\}/g;
  for (const match of guards.matchAll(pattern)) {
    if (match[2].includes(`=== "${type}"`)) {
      return match[1];
    }
  }
  return null;
}

const calls = (name: string) => new RegExp(`\\b${name}\\(`).test(hook);

test("every handled type has a guard the chat hook calls", () => {
  const missing = fixture.types
    .filter((entry) => entry.handled)
    .filter((entry) => {
      const guard = guardFor(entry.type);
      return !(guard && calls(guard));
    })
    .map((entry) => entry.type);
  assert.deepEqual(missing, []);
});

test("every exempt type is really left alone by the chat hook", () => {
  const stale = fixture.types
    .filter((entry) => !entry.handled)
    .filter((entry) => {
      const guard = guardFor(entry.type);
      return guard !== null && calls(guard);
    })
    .map((entry) => entry.type);
  assert.deepEqual(stale, []);
});

test("an exemption says why", () => {
  for (const entry of fixture.types) {
    if (!entry.handled) {
      assert.ok(entry.reason?.trim(), entry.type);
    }
  }
});

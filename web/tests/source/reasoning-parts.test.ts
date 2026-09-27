import assert from "node:assert/strict";
import test from "node:test";
import {
  applyReasoningDelta,
  applyReasoningDone,
  textPartOf,
} from "@/lib/reasoning-parts";
import type { ChatMessage } from "@/lib/types";

/**
 * 챗 SSE 의 `response.reasoning.*` 가 메시지 파트로 쌓이는 규칙.
 *
 * 백엔드는 사고 과정을 스트리밍했고 `message.tsx` 는 `reasoning` 파트를 그릴
 * 준비가 돼 있었는데, 그 사이의 훅이 이벤트를 받지 않아 **조용히 버려졌다**
 * (`tests/fixtures/chat_stream_event_types.json` 이 드러낸 구멍).
 */

type Parts = ChatMessage["parts"];

const fresh = (): Parts => [{ type: "text", text: "" }];

test("the first delta opens a reasoning part ahead of the answer", () => {
  const parts = applyReasoningDelta(fresh(), "Checking the ");
  assert.deepEqual(
    parts.map((part) => part.type),
    ["reasoning", "text"]
  );
  assert.equal((parts[0] as { text: string }).text, "Checking the ");
});

test("later deltas append to the same part", () => {
  const parts = applyReasoningDelta(applyReasoningDelta(fresh(), "a"), "b");
  assert.equal(parts.filter((part) => part.type === "reasoning").length, 1);
  assert.equal((parts[0] as { text: string }).text, "ab");
});

test("done replaces the streamed text with the authoritative one", () => {
  const parts = applyReasoningDone(applyReasoningDelta(fresh(), "partial"), "full text");
  assert.equal((parts[0] as { text: string }).text, "full text");
});

test("done without deltas still records the reasoning", () => {
  const parts = applyReasoningDone(fresh(), "only done");
  assert.equal((parts[0] as { text: string }).text, "only done");
});

test("the answer text part stays reachable after reasoning is inserted", () => {
  const parts = applyReasoningDelta(fresh(), "thinking");
  const text = textPartOf(parts);
  assert.ok(text);
  text.text += "answer";
  assert.equal((parts[1] as { text: string }).text, "answer");
});

import type { ChatMessage } from "@/lib/types";

/**
 * 챗 SSE `response.reasoning.delta` / `.done` → 메시지의 `reasoning` 파트.
 *
 * `message.tsx` 는 `reasoning` 파트를 `MessageReasoning` 으로 그린다. 사고
 * 과정은 답보다 먼저 오므로 파트를 **텍스트 파트 앞**에 끼운다 -- 그래서 훅은
 * 더 이상 `parts[0]` 을 텍스트라고 가정하면 안 되고 `textPartOf()` 를 쓴다.
 *
 * 파트 배열을 제자리에서 고친다(훅이 들고 있는 스트리밍 중 메시지를 그대로
 * 다루는 기존 방식과 같다). 반환값은 같은 배열이다.
 */

type Parts = ChatMessage["parts"];
type TextLikePart = Extract<Parts[number], { type: "text" | "reasoning" }>;

function reasoningPartOf(parts: Parts): TextLikePart {
  const existing = parts.find((part) => part.type === "reasoning");
  if (existing) {
    return existing as TextLikePart;
  }
  const created = { type: "reasoning", text: "" } as TextLikePart;
  const textIndex = parts.findIndex((part) => part.type === "text");
  parts.splice(textIndex === -1 ? parts.length : textIndex, 0, created);
  return created;
}

export function applyReasoningDelta(parts: Parts, delta: string): Parts {
  reasoningPartOf(parts).text += delta;
  return parts;
}

export function applyReasoningDone(parts: Parts, text: string): Parts {
  reasoningPartOf(parts).text = text;
  return parts;
}

export function textPartOf(parts: Parts): { type: "text"; text: string } | undefined {
  return parts.find((part) => part.type === "text") as
    | { type: "text"; text: string }
    | undefined;
}

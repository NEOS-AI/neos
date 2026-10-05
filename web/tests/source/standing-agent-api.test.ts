import assert from "node:assert/strict";
import test from "node:test";
import { openAgentConversation } from "@/lib/standing-agent-api";

// 트랙 Q8d -- 사이드바 "Agent" 가 부르는 클라이언트 함수.

function respond(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

test("returns the agent conversation id from the BFF route", async () => {
  const calls: Array<[RequestInfo | URL, RequestInit | undefined]> = [];
  globalThis.fetch = async (input, init) => {
    calls.push([input, init]);
    return respond(200, { conversationId: "conv_agent", created: false });
  };

  assert.equal(await openAgentConversation(), "conv_agent");
  assert.equal(calls[0][0], "/api/standing-agent/conversation");
  assert.equal(calls[0][1]?.method, "POST");
});

test("no agent (or the feature off) is null, not an error", async () => {
  globalThis.fetch = async () =>
    respond(404, { error: "No standing agent", code: "no_standing_agent" });

  assert.equal(await openAgentConversation(), null);
});

test("other failures throw a readable message", async () => {
  globalThis.fetch = async () =>
    respond(500, { error: "Could not open the agent conversation" });

  await assert.rejects(openAgentConversation, (error: unknown) => {
    assert.ok(error instanceof Error);
    assert.equal(error.message, "Could not open the agent conversation");
    return true;
  });
});

test("a success without an id is not treated as an id", async () => {
  globalThis.fetch = async () => respond(200, { created: true });

  await assert.rejects(openAgentConversation);
});

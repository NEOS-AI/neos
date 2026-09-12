import assert from "node:assert/strict";
import test from "node:test";
import { decideCodingApproval } from "@/features/coding/api/coding-api";

test("approval decision uses the task-scoped route", async () => {
  const calls: Array<[RequestInfo | URL, RequestInit | undefined]> = [];
  globalThis.fetch = async (input, init) => {
    calls.push([input, init]);
    return new Response(JSON.stringify({ status: "approved" }), {
      status: 200, headers: { "Content-Type": "application/json" },
    });
  };
  await decideCodingApproval("ct/1", "ca/1", "approve");
  assert.equal(calls[0][0], "/api/coding/tasks/ct%2F1/approvals/ca%2F1");
  assert.equal(
    calls[0][1]?.body,
    JSON.stringify({ decision: "approve", answers: [], remember: false })
  );
});

test("approval remember flag is forwarded for this-run writes", async () => {
  const calls: Array<[RequestInfo | URL, RequestInit | undefined]> = [];
  globalThis.fetch = async (input, init) => {
    calls.push([input, init]);
    return new Response(JSON.stringify({ status: "approved" }), {
      status: 200, headers: { "Content-Type": "application/json" },
    });
  };
  await decideCodingApproval("ct/1", "ca/1", "approve", [], true);
  assert.equal(
    calls[0][1]?.body,
    JSON.stringify({ decision: "approve", answers: [], remember: true })
  );
});

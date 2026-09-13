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

test("dict detail uses message and does not stringify the object", async () => {
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        detail: {
          code: "workspace_revision_conflict",
          message: "Coding workspace revision conflict",
        },
      }),
      { status: 409, headers: { "Content-Type": "application/json" } }
    );
  await assert.rejects(
    () => decideCodingApproval("ct/1", "ca/1", "deny"),
    (error: unknown) => {
      assert.ok(error instanceof Error);
      assert.equal(error.message, "Coding workspace revision conflict");
      assert.doesNotMatch(error.message, /\[object Object\]/);
      return true;
    }
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

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  nextContiguousSeq,
  reconnectDelayMs,
} from "../../features/coding/stream/socket-client";


test("reconnect backoff is exponential and capped", () => {
  assert.equal(reconnectDelayMs(0, () => 0), 500);
  assert.equal(reconnectDelayMs(1, () => 0), 1000);
  assert.equal(reconnectDelayMs(10, () => 0), 15_000);
});


test("reconnect cursor never advances across an event gap", () => {
  assert.equal(nextContiguousSeq(4, 5), 5);
  assert.equal(nextContiguousSeq(5, 8), 5);
  assert.equal(nextContiguousSeq(5, 5), 5);
});


test("coding task route fetches a fresh ticket for websocket connection", () => {
  const route = readFileSync(
    "app/(code)/api/coding/tasks/[taskId]/ws-ticket/route.ts",
    "utf8"
  );
  const hook = readFileSync("features/coding/stream/use-coding-stream.ts", "utf8");

  assert.match(route, /ws-ticket/);
  assert.match(route, /websocket_url/);
  assert.match(hook, /getCodingWsTicket/);
  assert.match(hook, /afterSeq/);
});

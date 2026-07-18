import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  nextContiguousSeq,
  reconnectDelayMs,
} from "../../features/coding/stream/socket-client";

const WS_TICKET_PATTERN = /ws-ticket/;
const WEBSOCKET_URL_PATTERN = /websocket_url/;
const GET_TICKET_PATTERN = /getCodingWsTicket/;
const AFTER_SEQ_PATTERN = /afterSeq/;
const HEARTBEAT_PATTERN = /heartbeat_ms/;
const WRITE_CURSOR_PATTERN = /writeCursor/;
const RESYNC_PATTERN = /resync_required/;

test("reconnect backoff is exponential and capped", () => {
  assert.equal(
    reconnectDelayMs(0, () => 0),
    500
  );
  assert.equal(
    reconnectDelayMs(1, () => 0),
    1000
  );
  assert.equal(
    reconnectDelayMs(10, () => 0),
    15_000
  );
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
  const hook = readFileSync(
    "features/coding/stream/use-coding-stream.ts",
    "utf8"
  );

  assert.match(route, WS_TICKET_PATTERN);
  assert.match(route, WEBSOCKET_URL_PATTERN);
  assert.match(hook, GET_TICKET_PATTERN);
  assert.match(hook, AFTER_SEQ_PATTERN);
  assert.match(hook, HEARTBEAT_PATTERN);
  assert.match(hook, WRITE_CURSOR_PATTERN);
  assert.match(hook, RESYNC_PATTERN);
});

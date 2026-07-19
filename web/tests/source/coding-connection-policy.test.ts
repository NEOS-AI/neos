import assert from "node:assert/strict";
import test from "node:test";
import {
  classifyConnectionError,
  clearCursor,
  heartbeatDeadlineMs,
  readCursor,
  writeCursor,
} from "../../features/coding/stream/connection-policy";

class MemoryStorage {
  private readonly values = new Map<string, string>();

  getItem(key: string) {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string) {
    this.values.set(key, value);
  }

  removeItem(key: string) {
    this.values.delete(key);
  }
}

test("permanent statuses stop reconnect", () => {
  assert.equal(classifyConnectionError(401), "terminal");
  assert.equal(classifyConnectionError(403), "terminal");
  assert.equal(classifyConnectionError(404), "terminal");
});

test("rate limits, server failures, and network errors retry", () => {
  assert.equal(classifyConnectionError(429), "retry");
  assert.equal(classifyConnectionError(503), "retry");
  assert.equal(classifyConnectionError(), "retry");
});

test("cursor is task scoped, validated, and clearable", () => {
  const storage = new MemoryStorage();

  writeCursor("ct_1", 12, storage);
  writeCursor("ct_2", 3, storage);
  assert.equal(readCursor("ct_1", storage), 12);
  assert.equal(readCursor("ct_2", storage), 3);
  clearCursor("ct_1", storage);
  assert.equal(readCursor("ct_1", storage), 0);
});

test("pong deadline is two server heartbeat periods", () => {
  assert.equal(heartbeatDeadlineMs(30_000), 60_000);
});

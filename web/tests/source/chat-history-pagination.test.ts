import { strict as assert } from "node:assert/strict";
import { describe, test } from "node:test";

import {
  type ChatHistory,
  getChatHistoryPaginationKey,
  PAGE_SIZE,
} from "../../lib/chat-history-pagination";

const page = (over: Partial<ChatHistory> = {}): ChatHistory => ({
  chats: [],
  hasMore: true,
  nextCursor: "CURSOR_A",
  ...over,
});

describe("getChatHistoryPaginationKey", () => {
  test("first page requests limit only, no cursor", () => {
    assert.equal(
      getChatHistoryPaginationKey(0, null),
      `/api/history?limit=${PAGE_SIZE}`
    );
  });

  test("subsequent page forwards the opaque cursor, url-encoded", () => {
    const prev = page({ nextCursor: "a+b/c=" });
    assert.equal(
      getChatHistoryPaginationKey(1, prev),
      `/api/history?cursor=${encodeURIComponent("a+b/c=")}&limit=${PAGE_SIZE}`
    );
  });

  test("stops when previous page has no more", () => {
    assert.equal(getChatHistoryPaginationKey(1, page({ hasMore: false })), null);
  });

  test("stops when previous page has a null cursor", () => {
    assert.equal(
      getChatHistoryPaginationKey(1, page({ nextCursor: null })),
      null
    );
  });

  test("never emits the legacy offset/ending_before params", () => {
    const key = getChatHistoryPaginationKey(1, page());
    assert.ok(key && !key.includes("offset="));
    assert.ok(key && !key.includes("ending_before="));
  });
});

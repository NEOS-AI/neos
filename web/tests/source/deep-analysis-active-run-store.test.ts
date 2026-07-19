import assert from "node:assert/strict";
import test from "node:test";
import {
  forgetActiveRun,
  readActiveRun,
  rememberActiveRun,
} from "../../lib/deep-analysis/active-run-store";

function memoryStorage() {
  const map = new Map<string, string>();
  return {
    getItem: (key: string) => map.get(key) ?? null,
    setItem: (key: string, value: string) => {
      map.set(key, value);
    },
    removeItem: (key: string) => {
      map.delete(key);
    },
    size: () => map.size,
  };
}

test("run 포인터를 저장하고 읽는다", () => {
  const storage = memoryStorage();
  rememberActiveRun(
    "chat-1",
    { runId: "run-1", assistantMessageId: "m1" },
    storage
  );

  assert.deepEqual(readActiveRun("chat-1", storage), {
    runId: "run-1",
    assistantMessageId: "m1",
  });
});

test("포인터는 대화별로 분리된다", () => {
  const storage = memoryStorage();
  rememberActiveRun("chat-1", { runId: "run-1" }, storage);
  rememberActiveRun("chat-2", { runId: "run-2" }, storage);

  assert.equal(readActiveRun("chat-1", storage)?.runId, "run-1");
  assert.equal(readActiveRun("chat-2", storage)?.runId, "run-2");
});

test("종결된 run 포인터를 지우면 다시 붙지 않는다", () => {
  const storage = memoryStorage();
  rememberActiveRun("chat-1", { runId: "run-1" }, storage);
  forgetActiveRun("chat-1", storage);

  assert.equal(readActiveRun("chat-1", storage), null);
});

test("손상된 저장값은 null로 떨어진다", () => {
  const storage = memoryStorage();
  storage.setItem("neos:deep-analysis:run:chat-1", "{not json");
  assert.equal(readActiveRun("chat-1", storage), null);

  storage.setItem("neos:deep-analysis:run:chat-1", '{"runId":123}');
  assert.equal(readActiveRun("chat-1", storage), null);

  storage.setItem("neos:deep-analysis:run:chat-1", '{"runId":""}');
  assert.equal(readActiveRun("chat-1", storage), null);
});

test("스토리지가 없어도 던지지 않는다 (SSR)", () => {
  assert.doesNotThrow(() => rememberActiveRun("c", { runId: "r" }, undefined));
  assert.equal(readActiveRun("c", undefined), null);
  assert.doesNotThrow(() => forgetActiveRun("c", undefined));
});

test("빈 값은 저장하지 않는다", () => {
  const storage = memoryStorage();
  rememberActiveRun("", { runId: "run-1" }, storage);
  rememberActiveRun("chat-1", { runId: "" }, storage);
  assert.equal(storage.size(), 0);
});

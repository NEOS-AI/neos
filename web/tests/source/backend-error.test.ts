import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import {
  backendErrorCode,
  backendErrorMessage,
} from "@/lib/backend-error";
import { bffErrorResponse } from "@/lib/bff-error";

/**
 * 백엔드는 `detail` 을 세 모양으로 보낸다. 셋 다 사람이 읽을 문장이 되어야
 * 하고, 어느 것도 `[object Object]` 가 되면 안 된다.
 *
 * 1. 문자열                    -- 일반 `HTTPException`
 * 2. `{code, message}`         -- 코딩 핸들러 `_error_detail()`
 * 3. `[{loc, msg, type}, ...]` -- FastAPI 422 검증 오류
 */

test("a string detail is the message", () => {
  assert.equal(backendErrorMessage({ detail: "Task not found" }, "x"), "Task not found");
});

test("an object detail yields its message and its code", () => {
  const body = {
    detail: { code: "unknown_coding_command", message: "Unknown command /nope" },
  };
  assert.equal(backendErrorMessage(body, "x"), "Unknown command /nope");
  assert.equal(backendErrorCode(body), "unknown_coding_command");
});

test("a validation error list yields the field messages", () => {
  const body = {
    detail: [
      { loc: ["body", "text"], msg: "Field required", type: "missing" },
      { loc: ["body", "mode"], msg: "Input should be 'safe_point'", type: "literal_error" },
    ],
  };
  assert.equal(
    backendErrorMessage(body, "x"),
    "text: Field required; mode: Input should be 'safe_point'"
  );
});

test("a BFF error body is understood too", () => {
  assert.equal(backendErrorMessage({ error: "Could not steer" }, "x"), "Could not steer");
});

test("an unreadable body falls back and never stringifies an object", () => {
  for (const body of [undefined, null, {}, { detail: {} }, { detail: [{}] }, "oops", 42]) {
    const message = backendErrorMessage(body, "Fallback");
    assert.equal(message, "Fallback", JSON.stringify(body));
    assert.doesNotMatch(message, /\[object Object\]/);
  }
});

test("the BFF error response carries message, code, and status", async () => {
  const error = Object.assign(new Error("Unknown command /nope"), {
    status: 400,
    code: "unknown_coding_command",
  });
  const response = bffErrorResponse(error, "Could not run coding command");
  assert.equal(response.status, 400);
  assert.deepEqual(await response.json(), {
    error: "Unknown command /nope",
    code: "unknown_coding_command",
  });
});

test("a non-backend failure becomes a 500 with the fallback", async () => {
  const response = bffErrorResponse(new TypeError("fetch failed"), "Could not stop");
  assert.equal(response.status, 500);
  assert.deepEqual(await response.json(), { error: "Could not stop" });
});

test("no BFF route hand-rolls the backend error body any more", () => {
  // 11개 라우트가 같은 catch 블록을 복사해 들고 있었고, 그래서 한 곳의
  // 고침이 나머지에 닿지 않았다. 새 라우트가 옛 모양을 다시 들여오면 여기서 멈춘다.
  const offenders: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const full = path.join(dir, name);
      if (statSync(full).isDirectory()) {
        walk(full);
      } else if (name === "route.ts") {
        const source = readFileSync(full, "utf8");
        if (/cause\.message\s*\?\?|error\?\.message\s*\|\|/.test(source)) {
          offenders.push(full);
        }
      }
    }
  };
  walk("app");
  assert.deepEqual(offenders, []);
});

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  invokeCodingCommand,
  listCodingCommands,
} from "@/features/coding/api/coding-api";
import {
  buildCommandTokens,
  routeComposerInput,
} from "@/features/coding/commands/route-input";
import type { CodingCommandListing } from "@/features/coding/commands/types";

/**
 * 이 스위트가 지키는 것: **카탈로그에 있는 이름만 커맨드로 간다.**
 *
 * 입력기는 하나이고 목적지는 둘이다(steer / commands). `/` 로 시작한다고
 * 전부 커맨드로 보내면 `/src/app.py 고쳐줘` 같은 경로 입력이 백엔드에서
 * `unknown_coding_command` 400 이 되어 지시가 에이전트에 닿지 않는다.
 * 반대로 카탈로그를 무시하면 `/plan` 이 에이전트에게 평문으로 새어
 * 백엔드 커맨드 해석을 건너뛴다.
 *
 * 토큰화는 백엔드 `neos/coding/commands/parse.py` 와 같은 규칙이어야 한다 --
 * 규칙이 어긋나면 프론트가 커맨드라고 보낸 것을 백엔드가 모른다고 한다.
 */

function listing(
  name: string,
  aliases: string[] = [],
  enabled = true
): CodingCommandListing {
  return {
    name,
    aliases,
    family: "prompt",
    description: `${name} command`,
    usage: `/${name}`,
    enabled,
    requires_task: true,
  };
}

const CATALOG = buildCommandTokens([
  listing("plan"),
  listing("review"),
  listing("new", ["reset"]),
  listing("code", ["!code"]),
  listing("loop", [], false),
]);

test("tokens carry names and aliases without their prefix, lowercased", () => {
  const tokens = buildCommandTokens([listing("New", ["/Reset", "!code"])]);
  assert.deepEqual([...tokens].sort(), ["code", "new", "reset"]);
});

test("a catalog name goes to the command endpoint with the text intact", () => {
  assert.deepEqual(routeComposerInput("/plan tighten the parser", CATALOG), {
    kind: "command",
    text: "/plan tighten the parser",
  });
});

test("matching is case-insensitive like the backend tokenizer", () => {
  assert.equal(routeComposerInput("/PLAN", CATALOG).kind, "command");
});

test("aliases and the bang prefix are catalog names too", () => {
  assert.equal(routeComposerInput("/reset", CATALOG).kind, "command");
  assert.equal(routeComposerInput("!code start over", CATALOG).kind, "command");
});

test("a bot suffix on the token is ignored like the backend does", () => {
  assert.equal(routeComposerInput("/review@neosbot", CATALOG).kind, "command");
});

test("leading whitespace does not hide a command", () => {
  assert.equal(routeComposerInput("   /review focus on tests", CATALOG).kind, "command");
});

test("a disabled catalog command still goes to the endpoint", () => {
  // 백엔드가 '이 배포에선 꺼져 있다'고 답해야 한다. steer 로 보내면
  // 에이전트가 `/loop` 을 평문 지시로 받는다.
  assert.equal(routeComposerInput("/loop 5m check", CATALOG).kind, "command");
});

test("a path that starts with a slash is steered, not rejected", () => {
  assert.deepEqual(routeComposerInput("/src/app.py 고쳐줘", CATALOG), {
    kind: "steer",
    instruction: "/src/app.py 고쳐줘",
  });
});

test("an unknown slash word is steered", () => {
  assert.equal(routeComposerInput("/deploy now", CATALOG).kind, "steer");
});

test("plain text and a bare slash are steered", () => {
  assert.equal(routeComposerInput("use pytest", CATALOG).kind, "steer");
  assert.equal(routeComposerInput("/", CATALOG).kind, "steer");
});

test("the catalog list uses the BFF route", async () => {
  const calls: Array<RequestInfo | URL> = [];
  globalThis.fetch = async (input) => {
    calls.push(input);
    return Response.json({ commands: [listing("plan")] });
  };
  const commands = await listCodingCommands();
  assert.equal(calls[0], "/api/coding/commands");
  assert.equal(commands[0].name, "plan");
});

test("invoking a command posts the raw text to the task-scoped route", async () => {
  const calls: Array<[RequestInfo | URL, RequestInit | undefined]> = [];
  globalThis.fetch = async (input, init) => {
    calls.push([input, init]);
    return Response.json({
      name: "plan",
      status: "queued",
      message: "Plan mode queued.",
      args: "",
      payload: {},
    });
  };
  const result = await invokeCodingCommand("ct/1", "/plan");
  assert.equal(calls[0][0], "/api/coding/tasks/ct%2F1/commands");
  assert.equal(calls[0][1]?.method, "POST");
  assert.equal(calls[0][1]?.body, JSON.stringify({ text: "/plan" }));
  assert.equal(result.status, "queued");
});

test("a rejected command surfaces the backend message", async () => {
  globalThis.fetch = async () =>
    Response.json(
      {
        detail: {
          code: "unknown_coding_command",
          message: "Unknown command /nope",
        },
      },
      { status: 400 }
    );
  await assert.rejects(
    () => invokeCodingCommand("ct_1", "/nope"),
    /Unknown command \/nope/
  );
});

test("the BFF routes proxy exactly the backend routes that exist", () => {
  const backend = readFileSync("../neos/api/handlers/coding_handlers.py", "utf8");
  const list = readFileSync("app/(code)/api/coding/commands/route.ts", "utf8");
  const invoke = readFileSync(
    "app/(code)/api/coding/tasks/[taskId]/commands/route.ts",
    "utf8"
  );

  assert.match(list, /\/api\/v1\/coding\/commands/);
  assert.match(backend, /@router\.get\("\/commands"/);
  assert.match(invoke, /\/api\/v1\/coding\/tasks\/\$\{[^}]+\}\/commands/);
  assert.match(backend, /"\/tasks\/\{task_id\}\/commands"/);
});

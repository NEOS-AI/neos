import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";


test("sidebar exposes separate Chat and Code product navigation", () => {
  const sidebar = readFileSync("components/app-sidebar.tsx", "utf8");

  assert.match(sidebar, /href="\/code"/);
  assert.match(sidebar, />\s*Code\s*</);
});


test("code entry page renders the coding task shell", () => {
  const page = readFileSync("app/(code)/code/page.tsx", "utf8");
  const shell = readFileSync(
    "features/coding/components/coding-shell.tsx",
    "utf8"
  );

  assert.match(page, /CodingShell/);
  assert.match(shell, /Start task/);
  assert.match(shell, /What should NEOS change/);
});


test("coding shell creates a task through the authenticated proxy", () => {
  const shell = readFileSync(
    "features/coding/components/coding-shell.tsx",
    "utf8"
  );
  const api = readFileSync("features/coding/api/coding-api.ts", "utf8");
  const route = readFileSync("app/(code)/api/coding/tasks/route.ts", "utf8");

  assert.match(shell, /createCodingTask/);
  assert.match(shell, /onSubmit/);
  assert.match(api, /fetch\("\/api\/coding\/tasks"/);
  assert.match(route, /\/api\/v1\/coding\/tasks/);
  assert.match(shell, /router\.push/);
});


test("task workspace renders durable stream state and connection status", () => {
  const page = readFileSync("app/(code)/code/tasks/[taskId]/page.tsx", "utf8");
  const workspace = readFileSync(
    "features/coding/components/coding-task-workspace.tsx",
    "utf8"
  );

  assert.match(page, /CodingTaskWorkspace/);
  assert.match(workspace, /useCodingStream/);
  assert.match(workspace, /connection/);
  assert.match(workspace, /partsById/);
});

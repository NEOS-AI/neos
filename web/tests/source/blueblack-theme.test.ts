import { readFile } from "node:fs/promises";
import { describe, test } from "node:test";

const readSource = (path: string) => readFile(path, "utf8");

const assertIncludes = (source: string, expected: string) => {
  if (!source.includes(expected)) {
    throw new Error(`Expected source to include: ${expected}`);
  }
};

const assertNotIncludes = (source: string, unexpected: string) => {
  if (source.includes(unexpected)) {
    throw new Error(`Expected source not to include: ${unexpected}`);
  }
};

describe("Blue-black dark theme", () => {
  test("defines the approved dark theme tokens and utilities", async () => {
    const globals = await readSource("app/globals.css");

    for (const token of [
      "--background: hsl(225 38% 3%);",
      "--card: hsl(222 39% 7%);",
      "--popover: hsl(222 39% 7%);",
      "--primary: hsl(214 100% 58%);",
      "--ring: hsl(214 100% 62%);",
      "--sidebar-background: hsl(225 38% 5%);",
    ]) {
      assertIncludes(globals, token);
    }

    assertIncludes(globals, ".neos-blueblack-workspace");
    assertIncludes(globals, ".neos-blueblack-empty");
    assertIncludes(globals, ".neos-blueblack-panel");
    assertIncludes(globals, ".dark .neos-blueblack-workspace");
    assertIncludes(globals, ".dark .neos-blueblack-empty");
    assertIncludes(globals, ".dark .neos-blueblack-panel");
    assertIncludes(globals, "radial-gradient(");
    assertIncludes(globals, "dark:bg-card!");
    assertNotIncludes(globals, "dark:bg-zinc-800!");
  });

  test("wires the workspace and composer hooks into chat UI", async () => {
    const chat = await readSource("components/chat.tsx");
    const input = await readSource("components/multimodal-input.tsx");
    const sidebar = await readSource("components/app-sidebar.tsx");
    const messages = await readSource("components/messages.tsx");
    const header = await readSource("components/chat-header.tsx");
    const greeting = await readSource("components/greeting.tsx");

    assertIncludes(chat, "neos-blueblack-workspace");
    assertIncludes(chat, 'data-testid="blueblack-workspace"');
    assertIncludes(chat, "bg-transparent px-2 pb-3");

    assertIncludes(input, "neos-blueblack-panel");
    assertIncludes(input, "bg-background");
    assertIncludes(input, "shadow-xs");
    assertIncludes(input, 'data-testid="prompt-composer"');
    assertIncludes(input, 'data-testid="compact-model-selector"');
    assertIncludes(input, "w-[156px]");
    assertIncludes(input, "sm:w-[200px]");

    assertIncludes(sidebar, "border-sidebar-border/70");
    assertIncludes(sidebar, "NEOS");
    assertIncludes(messages, "dark:border-blue-300/20");
    assertIncludes(messages, "dark:shadow-[0_10px_35px_rgba(2,8,30,0.4)]");
    assertIncludes(header, "dark:border-blue-300/10");
    assertIncludes(greeting, 'lang="ko"');
  });

  test("keeps blue-black accent styling scoped to dark mode", async () => {
    const input = await readSource("components/multimodal-input.tsx");

    for (const className of [
      "dark:focus-within:border-blue-300/45",
      "dark:focus-within:ring-blue-300/35",
      "dark:hover:border-blue-300/30",
      "dark:shadow-[0_0_24px_rgba(59,130,246,0.28)]",
      "dark:disabled:shadow-none",
    ]) {
      assertIncludes(input, className);
    }

    assertNotIncludes(input, " focus-within:border-blue-300/45");
    assertNotIncludes(input, " focus-within:ring-blue-300/35");
    assertNotIncludes(input, " hover:border-blue-300/30");
    assertNotIncludes(
      input,
      " text-primary-foreground shadow-[0_0_24px_rgba(59,130,246,0.28)]"
    );
  });
});

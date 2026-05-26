import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";

const readSource = (path: string) => readFile(path, "utf8");

test.describe("Blue-black dark theme", () => {
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
      expect(globals).toContain(token);
    }

    expect(globals).toContain(".neos-blueblack-workspace");
    expect(globals).toContain(".neos-blueblack-empty");
    expect(globals).toContain(".neos-blueblack-panel");
    expect(globals).toContain(".dark .neos-blueblack-workspace");
    expect(globals).toContain(".dark .neos-blueblack-empty");
    expect(globals).toContain(".dark .neos-blueblack-panel");
    expect(globals).toContain("radial-gradient(");
    expect(globals).toContain("dark:bg-card!");
    expect(globals).not.toContain("dark:bg-zinc-800!");
  });

  test("wires the workspace and composer hooks into chat UI", async () => {
    const chat = await readSource("components/chat.tsx");
    const input = await readSource("components/multimodal-input.tsx");
    const sidebar = await readSource("components/app-sidebar.tsx");
    const messages = await readSource("components/messages.tsx");
    const header = await readSource("components/chat-header.tsx");
    const greeting = await readSource("components/greeting.tsx");

    expect(chat).toContain("neos-blueblack-workspace");
    expect(chat).toContain('data-testid="blueblack-workspace"');
    expect(chat).toContain("bg-transparent px-2 pb-3");

    expect(input).toContain("neos-blueblack-panel");
    expect(input).toContain("bg-background");
    expect(input).toContain("shadow-xs");
    expect(input).toContain('data-testid="prompt-composer"');
    expect(input).toContain('data-testid="compact-model-selector"');
    expect(input).toContain("w-[156px]");
    expect(input).toContain("sm:w-[200px]");

    expect(sidebar).toContain("border-sidebar-border/70");
    expect(sidebar).toContain("NEOS");
    expect(messages).toContain("dark:border-blue-300/20");
    expect(messages).toContain("dark:shadow-[0_10px_35px_rgba(2,8,30,0.4)]");
    expect(header).toContain("dark:border-blue-300/10");
    expect(greeting).toContain('lang="ko"');
  });

  test("keeps blue-black accent styling scoped to dark mode", async () => {
    const input = await readSource("components/multimodal-input.tsx");

    for (const className of [
      "dark:focus-within:border-blue-300/45",
      "dark:focus-within:ring-blue-300/35",
      "dark:hover:border-blue-300/30",
      "dark:shadow-[0_0_24px_rgba(59,130,246,0.28)]",
    ]) {
      expect(input).toContain(className);
    }

    expect(input).not.toContain(" focus-within:border-blue-300/45");
    expect(input).not.toContain(" focus-within:ring-blue-300/35");
    expect(input).not.toContain(" hover:border-blue-300/30");
    expect(input).not.toContain(
      " text-primary-foreground shadow-[0_0_24px_rgba(59,130,246,0.28)]"
    );
  });
});

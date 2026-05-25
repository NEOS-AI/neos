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
  });
});

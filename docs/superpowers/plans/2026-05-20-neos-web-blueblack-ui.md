# neos-web Blue-Black Dark UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update the `neos-web` chat workspace to a cohesive black and deep-blue dark theme inspired by the approved reference direction.

**Architecture:** Keep the redesign token-first. Global CSS variables define the blue-black system, reusable CSS utilities provide the workspace glow, and component edits only remove gray hard-coding where it blocks the new theme. No chat, upload, auth, model selection, or history behavior changes.

**Tech Stack:** Next.js 16, React 19, Tailwind CSS v4, TypeScript, Playwright.

---

## File Structure

- Create: `web/tests/e2e/blueblack-theme.test.ts`
  - Verifies that the dark CSS tokens, branded sidebar label, and blue-black workspace hooks exist.
- Modify: `web/app/globals.css`
  - Owns global theme tokens, scrollbars, CodeMirror dark surface, and reusable blue-black workspace utilities.
- Modify: `web/app/layout.tsx`
  - Updates the browser dark theme color to match the new near-black base.
- Modify: `web/components/chat.tsx`
  - Applies the workspace background and exposes a stable test id.
- Modify: `web/components/messages.tsx`
  - Applies the stronger empty-state glow behind the greeting and keeps active chats calmer.
- Modify: `web/components/greeting.tsx`
  - Updates empty-state typography and copy to match the reference mood.
- Modify: `web/components/multimodal-input.tsx`
  - Restyles the composer, model selector trigger, attachment button, send button, and stop button.
- Modify: `web/components/chat-header.tsx`
  - Makes the header translucent over the new workspace.
- Modify: `web/components/app-sidebar.tsx`
  - Rebrands the label from `Chatbot` to `NEOS` and aligns the sidebar header controls with the token system.

---

### Task 1: Add Theme Regression Coverage

**Files:**
- Create: `web/tests/e2e/blueblack-theme.test.ts`

- [ ] **Step 1: Write the failing Playwright test**

Create `web/tests/e2e/blueblack-theme.test.ts` with this complete content:

```ts
import { expect, test } from "@playwright/test";

test.describe("Blue-black dark theme", () => {
  test("exposes approved dark theme tokens", async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() => {
      document.documentElement.classList.add("dark");
    });

    const tokens = await page.evaluate(() => {
      const styles = getComputedStyle(document.documentElement);
      const read = (name: string) => styles.getPropertyValue(name).trim();

      return {
        background: read("--background"),
        card: read("--card"),
        popover: read("--popover"),
        primary: read("--primary"),
        ring: read("--ring"),
        sidebar: read("--sidebar-background"),
      };
    });

    expect(tokens).toEqual({
      background: "hsl(225 38% 3%)",
      card: "hsl(222 39% 7%)",
      popover: "hsl(222 39% 7%)",
      primary: "hsl(214 100% 58%)",
      ring: "hsl(214 100% 62%)",
      sidebar: "hsl(225 38% 5%)",
    });
  });

  test("renders the blue-black workspace shell", async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() => {
      document.documentElement.classList.add("dark");
    });

    await expect(page.getByTestId("blueblack-workspace")).toBeVisible();
    await expect(page.getByTestId("prompt-composer")).toBeVisible();
    await expect(page.getByText("NEOS").first()).toBeVisible();
  });
});
```

- [ ] **Step 2: Run the new test and confirm it fails before implementation**

Run:

```bash
pnpm --dir web exec playwright test tests/e2e/blueblack-theme.test.ts --project=e2e
```

Expected: FAIL. The current app still exposes the old gray dark tokens, lacks `data-testid="blueblack-workspace"`, lacks `data-testid="prompt-composer"`, and shows `Chatbot` instead of `NEOS`.

- [ ] **Step 3: Commit the failing test**

Run:

```bash
git add web/tests/e2e/blueblack-theme.test.ts
git commit -m "test: add blue-black theme coverage"
```

Expected: Commit succeeds with only the new Playwright test staged.

---

### Task 2: Update Global Dark Theme Tokens And Utilities

**Files:**
- Modify: `web/app/globals.css`

- [ ] **Step 1: Replace the `.dark` token block**

In `web/app/globals.css`, replace the existing `.dark { ... }` block with:

```css
.dark {
  --background: hsl(225 38% 3%);
  --foreground: hsl(220 32% 96%);
  --card: hsl(222 39% 7%);
  --card-foreground: hsl(220 32% 96%);
  --popover: hsl(222 39% 7%);
  --popover-foreground: hsl(220 32% 96%);
  --primary: hsl(214 100% 58%);
  --primary-foreground: hsl(220 40% 98%);
  --secondary: hsl(222 31% 11%);
  --secondary-foreground: hsl(218 33% 92%);
  --muted: hsl(222 24% 13%);
  --muted-foreground: hsl(220 16% 68%);
  --accent: hsl(219 43% 15%);
  --accent-foreground: hsl(216 50% 92%);
  --destructive: hsl(0 70% 44%);
  --destructive-foreground: hsl(0 0% 98%);
  --border: hsl(220 31% 16%);
  --input: hsl(220 31% 16%);
  --ring: hsl(214 100% 62%);
  --chart-1: hsl(214 100% 58%);
  --chart-2: hsl(190 92% 58%);
  --chart-3: hsl(252 92% 70%);
  --chart-4: hsl(158 68% 52%);
  --chart-5: hsl(38 96% 62%);
  --sidebar-background: hsl(225 38% 5%);
  --sidebar-foreground: hsl(220 28% 91%);
  --sidebar-primary: hsl(214 100% 58%);
  --sidebar-primary-foreground: hsl(220 40% 98%);
  --sidebar-accent: hsl(220 44% 13%);
  --sidebar-accent-foreground: hsl(216 50% 92%);
  --sidebar-border: hsl(220 33% 14%);
  --sidebar-ring: hsl(214 100% 62%);
  --sidebar: hsl(225 38% 5%);
}
```

- [ ] **Step 2: Add blue-black workspace utility classes**

In `web/app/globals.css`, add this block after the existing `@layer base` blocks and before `.skeleton`:

```css
@layer utilities {
  .neos-blueblack-workspace {
    background:
      radial-gradient(
        ellipse 110% 72% at 56% 36%,
        hsl(224 82% 29% / 0.2),
        hsl(224 70% 14% / 0.1) 42%,
        transparent 72%
      ),
      linear-gradient(180deg, hsl(225 38% 3%) 0%, hsl(220 38% 2%) 100%);
  }

  .neos-blueblack-empty {
    background:
      radial-gradient(
        ellipse 76% 50% at 50% 45%,
        hsl(224 84% 34% / 0.38),
        hsl(225 58% 13% / 0.26) 42%,
        transparent 74%
      );
  }

  .neos-blueblack-panel {
    background: hsl(222 42% 7% / 0.92);
    border-color: hsl(218 48% 24% / 0.72);
    box-shadow:
      0 18px 70px rgb(2 8 30 / 0.48),
      inset 0 1px 0 rgb(255 255 255 / 0.04);
  }
}
```

- [ ] **Step 3: Update CodeMirror dark surfaces**

In `web/app/globals.css`, replace:

```css
.cm-editor,
.cm-gutters {
  @apply bg-background! dark:bg-zinc-800! outline-hidden! selection:bg-zinc-900!;
}
```

with:

```css
.cm-editor,
.cm-gutters {
  @apply bg-background! dark:bg-card! outline-hidden! selection:bg-blue-950!;
}
```

- [ ] **Step 4: Run the token test**

Run:

```bash
pnpm --dir web exec playwright test tests/e2e/blueblack-theme.test.ts --project=e2e
```

Expected: Still FAIL. The token assertion now passes, while the workspace shell assertions still fail until component hooks are added.

- [ ] **Step 5: Commit global theme changes**

Run:

```bash
git add web/app/globals.css
git commit -m "style: add blue-black dark theme tokens"
```

Expected: Commit succeeds with only `web/app/globals.css` staged.

---

### Task 3: Apply Workspace Background To The Chat Shell

**Files:**
- Modify: `web/components/chat.tsx`

- [ ] **Step 1: Update the root chat shell**

In `web/components/chat.tsx`, replace:

```tsx
<div className="overscroll-behavior-contain flex h-dvh min-w-0 touch-pan-y flex-col bg-background">
```

with:

```tsx
<div
  className="neos-blueblack-workspace overscroll-behavior-contain flex h-dvh min-w-0 touch-pan-y flex-col bg-background"
  data-testid="blueblack-workspace"
>
```

- [ ] **Step 2: Make the composer dock blend into the workspace**

In `web/components/chat.tsx`, replace:

```tsx
<div className="sticky bottom-0 z-1 mx-auto flex w-full max-w-4xl gap-2 border-t-0 bg-background px-2 pb-3 md:px-4 md:pb-4">
```

with:

```tsx
<div className="sticky bottom-0 z-1 mx-auto flex w-full max-w-4xl gap-2 border-t-0 bg-transparent px-2 pb-3 md:px-4 md:pb-4">
```

- [ ] **Step 3: Run the blue-black test**

Run:

```bash
pnpm --dir web exec playwright test tests/e2e/blueblack-theme.test.ts --project=e2e
```

Expected: Still FAIL. `blueblack-workspace` is visible, while `prompt-composer` and `NEOS` still fail.

- [ ] **Step 4: Commit the chat shell change**

Run:

```bash
git add web/components/chat.tsx
git commit -m "style: apply blue-black chat workspace"
```

Expected: Commit succeeds with only `web/components/chat.tsx` staged.

---

### Task 4: Refresh Empty-State Message Area And Greeting

**Files:**
- Modify: `web/components/messages.tsx`
- Modify: `web/components/greeting.tsx`

- [ ] **Step 1: Import `cn` in the messages component**

In `web/components/messages.tsx`, add this import with the existing imports:

```ts
import { cn } from "@/lib/utils";
```

- [ ] **Step 2: Apply the empty-state glow behind the greeting**

In `web/components/messages.tsx`, replace:

```tsx
<div className="relative flex-1">
```

with:

```tsx
<div
  className={cn(
    "relative flex-1 overflow-hidden",
    messages.length === 0 && "neos-blueblack-empty"
  )}
>
```

- [ ] **Step 3: Restyle the scroll-to-bottom button**

In `web/components/messages.tsx`, replace the scroll button `className` template with:

```tsx
className={`-translate-x-1/2 absolute bottom-4 left-1/2 z-10 rounded-full border border-blue-300/20 bg-card/90 p-2 text-foreground shadow-[0_10px_35px_rgba(2,8,30,0.4)] backdrop-blur-xl transition-all hover:bg-accent hover:text-accent-foreground ${
  isAtBottom
    ? "pointer-events-none scale-0 opacity-0"
    : "pointer-events-auto scale-100 opacity-100"
}`}
```

- [ ] **Step 4: Replace the greeting content**

In `web/components/greeting.tsx`, replace the returned JSX with:

```tsx
return (
  <div
    className="mx-auto mt-4 flex size-full max-w-3xl flex-col justify-center px-4 text-center md:mt-16 md:px-8"
    key="overview"
  >
    <motion.div
      animate={{ opacity: 1, y: 0 }}
      className="font-light text-2xl text-foreground/90 md:text-3xl"
      exit={{ opacity: 0, y: 10 }}
      initial={{ opacity: 0, y: 10 }}
      transition={{ delay: 0.5 }}
    >
      안녕하세요.
    </motion.div>
    <motion.div
      animate={{ opacity: 1, y: 0 }}
      className="mt-2 text-2xl text-muted-foreground md:text-3xl"
      exit={{ opacity: 0, y: 10 }}
      initial={{ opacity: 0, y: 10 }}
      transition={{ delay: 0.6 }}
    >
      무엇을 도와드릴까요?
    </motion.div>
  </div>
);
```

- [ ] **Step 5: Run the existing chat smoke tests**

Run:

```bash
pnpm --dir web exec playwright test tests/e2e/chat.test.ts --project=e2e
```

Expected: PASS. The input, submit button, and suggested actions remain visible.

- [ ] **Step 6: Commit the empty-state update**

Run:

```bash
git add web/components/messages.tsx web/components/greeting.tsx
git commit -m "style: refresh blue-black empty chat state"
```

Expected: Commit succeeds with only the two message-area files staged.

---

### Task 5: Restyle The Composer And Compact Model Selector

**Files:**
- Modify: `web/components/multimodal-input.tsx`

- [ ] **Step 1: Add a stable test id and blue-black panel styling to `PromptInput`**

In `web/components/multimodal-input.tsx`, replace the `PromptInput` opening tag:

```tsx
<PromptInput
  className="rounded-xl border border-border bg-background p-3 shadow-xs transition-all duration-200 focus-within:border-border hover:border-muted-foreground/50"
```

with:

```tsx
<PromptInput
  className="neos-blueblack-panel rounded-[28px] border p-3 backdrop-blur-xl transition-all duration-200 focus-within:border-blue-300/45 focus-within:ring-1 focus-within:ring-blue-300/35 hover:border-blue-300/30"
  data-testid="prompt-composer"
```

- [ ] **Step 2: Restyle the textarea**

In `web/components/multimodal-input.tsx`, replace the textarea class:

```tsx
className="grow resize-none border-0! border-none! bg-transparent p-2 text-sm outline-none ring-0 [-ms-overflow-style:none] [scrollbar-width:none] placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-0 focus-visible:ring-offset-0 [&::-webkit-scrollbar]:hidden"
```

with:

```tsx
className="grow resize-none border-0! border-none! bg-transparent p-2 text-sm text-foreground outline-none ring-0 [-ms-overflow-style:none] [scrollbar-width:none] placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-0 focus-visible:ring-offset-0 [&::-webkit-scrollbar]:hidden"
```

- [ ] **Step 3: Restyle the send button**

In `web/components/multimodal-input.tsx`, replace the `PromptInputSubmit` class:

```tsx
className="size-8 rounded-full bg-primary text-primary-foreground transition-colors duration-200 hover:bg-primary/90 disabled:bg-muted disabled:text-muted-foreground"
```

with:

```tsx
className="size-8 rounded-full bg-blue-500 text-white shadow-[0_0_24px_rgba(59,130,246,0.28)] transition-colors duration-200 hover:bg-blue-400 disabled:bg-muted disabled:text-muted-foreground disabled:shadow-none"
```

- [ ] **Step 4: Restyle the attachment button**

In `web/components/multimodal-input.tsx`, replace the attachment button class:

```tsx
className="aspect-square h-8 rounded-lg p-1 transition-colors hover:bg-accent"
```

with:

```tsx
className="aspect-square h-8 rounded-full p-1 text-muted-foreground transition-colors hover:bg-blue-400/10 hover:text-blue-100"
```

- [ ] **Step 5: Restyle the compact model selector trigger**

In `web/components/multimodal-input.tsx`, replace:

```tsx
<Button className="h-8 w-[200px] justify-between px-2" variant="ghost">
```

with:

```tsx
<Button
  className="h-8 w-[156px] justify-between rounded-full px-2 text-muted-foreground hover:bg-blue-400/10 hover:text-blue-100 sm:w-[200px]"
  variant="ghost"
>
```

- [ ] **Step 6: Restyle the stop button**

In `web/components/multimodal-input.tsx`, replace the stop button class:

```tsx
className="size-7 rounded-full bg-foreground p-1 text-background transition-colors duration-200 hover:bg-foreground/90 disabled:bg-muted disabled:text-muted-foreground"
```

with:

```tsx
className="size-7 rounded-full bg-blue-100 p-1 text-background transition-colors duration-200 hover:bg-white disabled:bg-muted disabled:text-muted-foreground"
```

- [ ] **Step 7: Run focused theme and chat tests**

Run:

```bash
pnpm --dir web exec playwright test tests/e2e/blueblack-theme.test.ts tests/e2e/chat.test.ts --project=e2e
```

Expected: The `prompt-composer` assertion now passes. The theme test still fails only if the sidebar label has not been updated yet.

- [ ] **Step 8: Commit composer changes**

Run:

```bash
git add web/components/multimodal-input.tsx
git commit -m "style: restyle chat composer for blue-black theme"
```

Expected: Commit succeeds with only `web/components/multimodal-input.tsx` staged.

---

### Task 6: Refresh Header, Sidebar, And Browser Theme Color

**Files:**
- Modify: `web/app/layout.tsx`
- Modify: `web/components/chat-header.tsx`
- Modify: `web/components/app-sidebar.tsx`

- [ ] **Step 1: Update the browser dark theme color**

In `web/app/layout.tsx`, replace:

```ts
const DARK_THEME_COLOR = "hsl(240deg 10% 3.92%)";
```

with:

```ts
const DARK_THEME_COLOR = "hsl(225 38% 3%)";
```

- [ ] **Step 2: Make the chat header translucent**

In `web/components/chat-header.tsx`, replace:

```tsx
<header className="sticky top-0 flex items-center gap-2 bg-background px-2 py-1.5 md:px-2">
```

with:

```tsx
<header className="sticky top-0 z-20 flex items-center gap-2 border-blue-300/10 border-b bg-background/65 px-2 py-1.5 backdrop-blur-xl md:px-2">
```

- [ ] **Step 3: Update the sidebar component class and label**

In `web/components/app-sidebar.tsx`, replace:

```tsx
<Sidebar className="group-data-[side=left]:border-r-0">
```

with:

```tsx
<Sidebar className="group-data-[side=left]:border-sidebar-border/70 group-data-[side=left]:border-r">
```

In the same file, replace:

```tsx
<span className="cursor-pointer rounded-md px-2 font-semibold text-lg hover:bg-muted">
  Chatbot
</span>
```

with:

```tsx
<span className="cursor-pointer rounded-md px-2 font-semibold text-lg text-sidebar-foreground tracking-normal hover:bg-sidebar-accent hover:text-sidebar-accent-foreground">
  NEOS
</span>
```

- [ ] **Step 4: Restyle sidebar icon buttons**

In `web/components/app-sidebar.tsx`, replace each sidebar header icon button class:

```tsx
className="h-8 p-1 md:h-fit md:p-2"
```

with:

```tsx
className="h-8 p-1 text-sidebar-foreground/75 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground md:h-fit md:p-2"
```

There are two matching header buttons: delete-all and new-chat.

- [ ] **Step 5: Run the blue-black theme test**

Run:

```bash
pnpm --dir web exec playwright test tests/e2e/blueblack-theme.test.ts --project=e2e
```

Expected: PASS. Tokens, workspace test id, prompt composer test id, and `NEOS` brand label are all present.

- [ ] **Step 6: Commit header and sidebar changes**

Run:

```bash
git add web/app/layout.tsx web/components/chat-header.tsx web/components/app-sidebar.tsx
git commit -m "style: align header and sidebar with blue-black theme"
```

Expected: Commit succeeds with only the three chrome files staged.

---

### Task 7: Final Verification And Visual Inspection

**Files:**
- Read: all modified files

- [ ] **Step 1: Run the production build**

Run:

```bash
pnpm --dir web build
```

Expected: PASS. Next.js completes the production build without TypeScript or CSS errors.

- [ ] **Step 2: Run the focused Playwright suite**

Run:

```bash
pnpm --dir web exec playwright test tests/e2e/blueblack-theme.test.ts tests/e2e/chat.test.ts --project=e2e
```

Expected: PASS. Theme regression and existing chat smoke coverage both pass.

- [ ] **Step 3: Start the local dev server for visual QA**

Run:

```bash
pnpm --filter @neos-work/desktop dev
```

Expected: The local app starts and prints a localhost URL.

- [ ] **Step 4: Inspect desktop empty chat in the browser**

Open the local app URL and inspect `/`.

Expected:

- The workspace reads black and deep blue rather than dark gray.
- The central empty-state glow is visible behind the greeting.
- The greeting text is centered and does not overlap the composer.
- The composer has a dark blue-black pill surface with a blue focus ring.
- The sidebar label reads `NEOS`.

- [ ] **Step 5: Inspect desktop chat after typing**

Type a short message into the composer.

Expected:

- The input remains legible.
- The send button is enabled and blue.
- Existing send behavior is unchanged.
- The background remains calmer than the empty-state glow once messages appear.

- [ ] **Step 6: Inspect mobile width**

Use the browser device toolbar at a mobile width near 390px.

Expected:

- Header controls do not overlap.
- The compact model selector fits inside the composer toolbar.
- The composer remains usable without horizontal page scroll.
- Text stays within its containers.

- [ ] **Step 7: Commit final verification notes only if a tracked doc is updated**

Run:

```bash
git status --short
```

Expected: Only intentional source and test changes are present. Do not stage `.superpowers/` mockup files.

---

## Self-Review

Spec coverage:

- Global tokens are covered by Task 2.
- Browser theme color is covered by Task 6.
- Chat shell and bottom composer area are covered by Tasks 3 and 5.
- Empty and populated message areas are covered by Task 4.
- Greeting is covered by Task 4.
- Header and sidebar are covered by Task 6.
- Verification is covered by Task 7.

Placeholder scan:

- The plan contains no placeholder markers, no incomplete file paths, and no unspecified code steps.

Type and selector consistency:

- The new Playwright test expects `data-testid="blueblack-workspace"`, which Task 3 adds to `web/components/chat.tsx`.
- The new Playwright test expects `data-testid="prompt-composer"`, which Task 5 adds to `web/components/multimodal-input.tsx`.
- The new Playwright test expects `NEOS`, which Task 6 adds to `web/components/app-sidebar.tsx`.

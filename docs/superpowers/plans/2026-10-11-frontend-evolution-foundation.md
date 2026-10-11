# 프론트엔드 진화 1단계(기반) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 시맨틱 토큰 · 한글 서체 · 공통 셸 · 활동 인박스 · 작업 흔적 프리미티브 6종 · FE 표면 인벤토리를 세워, 2~5단계 표면 작업이 올라설 기반을 만든다.

**Architecture:** 디자인 언어는 `web/app/globals.css` 의 토큰 층으로 정하고 소스 테스트로 원시 팔레트를 금지한다. 화면은 "출처 → 순수 어댑터 → 표시 모델 → 프리미티브" 경계로 나눈다 — 프리미티브(`web/components/trace/`)는 표시 모델만 받고, 코딩 어댑터(`web/features/coding/trace.ts`)가 기존 투영을 그 모델로 바꾼다. 셸·인박스는 기존 BE 목록 API 두 개만 읽는 BFF 팬아웃이다.

**Tech Stack:** Next.js 16 · React 19 · Tailwind v4(`@theme`) · shadcn/Radix · SWR · `tsx --test`(node:test + happy-dom) · Playwright · FastAPI(AST 스캔 테스트만) · pytest

**Spec:** [docs/superpowers/specs/2026-10-11-frontend-evolution-foundation-design.md](../specs/2026-10-11-frontend-evolution-foundation-design.md) — 계획은 spec 을 근거로 한다. 실행자는 둘 다 읽는다.

## Global Constraints

- 작업 디렉터리: FE 명령은 `web/` 에서(`pnpm …`), BE 명령은 저장소 루트에서(`uv run --frozen …`)
- FE 테스트 러너는 `pnpm test:source`(= `tsx --tsconfig tsconfig.test.json --test tests/source/**/*.test.ts tests/source/**/*.test.tsx`). 한 파일만: `pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/<name>.test.ts`
- 컴포넌트 테스트 파일은 **첫 줄**이 `import "../dom-setup";` 이고 렌더는 `tests/render.tsx` 의 `renderComponent` 를 쓴다
- 새 런타임 의존성은 `pretendard@1.3.9`(정확 버전, OFL-1.1) **하나뿐**이다
- 사용자에게 보이는 새 문구는 `web/lib/copy/*.ts` 의 `as const` 사전에서 온다. 값은 한국어. **예외:** 이식하는 코딩 승인 카드 · Jev 배지 문구는 사전으로 옮기되 값은 지금의 영문 그대로(spec §3.4)
- `app/` · `components/` · `features/` · `hooks/` · `lib/` 의 `.ts(x)` 에서 원시 팔레트 색 클래스 금지(spec §3.1). 예외는 `components/ui/`, `components/icons.tsx`, blue-black 허용 목록(Task 4)
- 코딩 소스 테스트(`web/tests/source/coding-*.test.ts(x)`)는 고치지 않는다. **유일한 예외:** `coding-shell.test.ts` 의 사이드바 라벨 단언(`>\s*Code\s*<`) — Task 10 이 고치고 커밋 메시지에 "같은 의미로 남은 것" 을 적는다
- `web/tests/source/blueblack-theme.test.ts` 가 고정하는 문자열(`neos-blueblack-*`, `dark:border-blue-300/*`, 사이드바의 `NEOS`·`border-sidebar-border/70`, 인사말의 `lang="ko"` 등)은 지운다면 그 테스트가 빨개진다 — 남긴다
- 커밋 메시지에 `Co-Authored-By` 트레일러를 넣지 않는다(저장소 규칙)
- 각 작업 끝에 `pnpm typecheck` 와 그 작업의 테스트를 돌린다. 마지막 작업에서 CI 명령 전체를 돌린다

## Review Focus

1. **BE 가 꺼졌거나 토큰이 만료된 인박스** — 두 출처가 모두 401 이면 "할 일 없음(0)" 이 아니라 401 이어야 하고, 한 출처만 실패하면 나머지 항목과 함께 `degraded` 로 보여야 한다 → Task 11 `collectInbox` 테스트
2. **지금 모르는 Jev band 값**(예: 새 band `"extreme"`) — 배지 문자열은 원문 그대로 보이고 색은 중립(`unavailable`)이어야 한다. 크래시나 "low" 로 보이는 것은 안 된다 → Task 8 어댑터 테스트
3. **경로 접두어 충돌** — `/codex`·`/reports-old` 같은 경로가 코드·리포트 공간으로 판정되면 안 된다 → Task 10 `spaceForPath` 테스트
4. **빈 프롬프트 · 아주 긴 프롬프트의 인박스 제목** — 빈 제목이나 줄바꿈 범벅이 아니라 잘린 한 줄 또는 작업 id 대체여야 한다 → Task 11 `inboxItemsFromTasks` 테스트
5. **`cn(...)`·삼항·템플릿 문자열 안의 원시 팔레트 클래스** — 금지 테스트가 className 리터럴만이 아니라 소스 어디의 문자열이든 잡아야 한다 → Task 4 정규식 자체 테스트

---

## 파일 구조

| 파일 | 책임 | 작업 |
|---|---|---|
| `web/app/globals.css` | 라이트 토큰 재정의 · 시맨틱 토큰 · 모션 · 타입 스케일 · `@theme` 별칭 | 1, 2 |
| `web/components/motion-provider.tsx` | framer-motion 의 `reducedMotion="user"` | 1 |
| `web/app/layout.tsx` | Pretendard 로드 · 라이트 theme-color · MotionProvider | 1, 2 |
| `web/lib/copy/{common,code,chat,inbox}.ts` | 문구 사전 | 5, 8, 10~12 |
| `web/components/trace/types.ts` | 표시 모델(spec §5.2 그대로) | 5 |
| `web/components/trace/status.ts` | `TraceStatus` → 토큰 클래스 | 5 |
| `web/components/trace/{run-status,verdict-badge,tool-activity}.tsx` | 프리미티브 ① | 6 |
| `web/components/trace/{claim-evidence,approval-card,step-timeline}.tsx` | 프리미티브 ② | 7 |
| `web/features/coding/trace.ts` | 코딩 투영 → 표시 모델 | 8 |
| `web/features/coding/components/coding-approval-card.tsx` | `ApprovalCard` 위의 래퍼로 | 8 |
| `web/features/coding/components/coding-detail-panel.tsx` | `ToolRiskLine` 이 `VerdictBadge` 를 쓴다 | 8 |
| `tests/fixtures/fe_surface_inventory.json` | 태그별 표면/이유 정본 | 9 |
| `tests/api/test_fe_surface_inventory.py` | BE: AST 태그 집합 = 인벤토리 | 9 |
| `web/tests/source/fe-surface-inventory.test.ts` | FE: 표면 경로 실존 | 9 |
| `web/components/shell/{app-shell.tsx,spaces.ts,space-placeholder.tsx}` | 공통 셸 · 공간 판정 · 자리 화면 | 10 |
| `web/components/app-sidebar.tsx` | 공간 내비 · 최근 항목 · 활동 배지 · 새 작업 | 10~12 |
| `web/app/(chat)/{reports,agents,settings,inbox}/page.tsx` | 공간 페이지 | 10, 11 |
| `web/lib/inbox/{normalize,collect,client}.ts` · `web/hooks/use-inbox.ts` · `web/app/(chat)/api/inbox/route.ts` | 인박스 | 11 |
| `web/components/shell/{task-modes.ts,new-task-dialog.tsx}` | 새 작업 컴포저 | 12 |
| `web/app/(dev)/…` · `web/tests/fixtures/trace/*.ts` · `web/tests/e2e/trace-gallery.test.ts` · `web/proxy.ts` | 갤러리 | 13 |

---

### Task 1: 시맨틱 토큰 · 라이트 테마 · 모션

**Files:**
- Modify: `web/app/globals.css` (`:root` 블록 전체, `.dark` 블록 끝, `@theme` 블록 끝, 파일 끝)
- Modify: `web/app/layout.tsx` (`LIGHT_THEME_COLOR`, `<body>` 안쪽)
- Create: `web/components/motion-provider.tsx`
- Create: `web/tests/css-tokens.ts` (테스트 헬퍼 — 테스트 파일끼리 import 하면 node:test 가 그 파일의 테스트를 한 번 더 등록하므로 헬퍼를 따로 둔다)
- Test: `web/tests/source/semantic-tokens.test.ts`, `web/tests/source/light-theme.test.ts`

**Interfaces:**
- Produces: `tests/css-tokens.ts` 의 `STATUS_TOKENS` · `cssBlock(source, ":root" | ".dark"): string`
- Produces: CSS 변수 `--status-{running,waiting,paused,success,warning,danger,idle}`(`:root`·`.dark` 양쪽), `--evidence-{verified,unverified,rejected}` · `--risk-{low,mid,high,blocked}` · `--surface-{1,2,3}` · `--motion-{fast,base,slow}` · `--motion-ease`(`:root`), Tailwind 유틸리티 `text-status-*`·`bg-status-*`·`border-status-*`·`text-evidence-*`·`text-risk-*`·`bg-surface-*` 등(`@theme` `--color-*` 별칭)

- [ ] **Step 1: 헬퍼와 실패하는 테스트를 쓴다**

`web/tests/css-tokens.ts`:

```ts
import assert from "node:assert/strict";

export const STATUS_TOKENS = [
  "running",
  "waiting",
  "paused",
  "success",
  "warning",
  "danger",
  "idle",
] as const;

/** `globals.css` 에서 `:root { … }` 또는 `.dark { … }` 블록의 본문. 줄머리의 닫는 `}` 까지다. */
export function cssBlock(source: string, selector: ":root" | ".dark"): string {
  const escaped = selector.replace(".", "\\.");
  const match = source.match(new RegExp(`^${escaped}\\s*\\{([\\s\\S]*?)^\\}`, "m"));
  assert.ok(match, `${selector} block not found`);
  return match[1];
}
```

`web/tests/source/semantic-tokens.test.ts`:

```ts
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { cssBlock, STATUS_TOKENS } from "../css-tokens";

const globals = () => readFileSync("app/globals.css", "utf8");

test("every status token is defined for light and dark", () => {
  const source = globals();
  for (const selector of [":root", ".dark"] as const) {
    const block = cssBlock(source, selector);
    for (const token of STATUS_TOKENS) {
      assert.match(block, new RegExp(`--status-${token}:\\s*hsl\\(`), `${selector} --status-${token}`);
    }
  }
});

test("evidence, risk and surface tokens point at the status and base tokens", () => {
  const root = cssBlock(globals(), ":root");
  for (const [token, target] of [
    ["--evidence-verified", "--status-success"],
    ["--evidence-unverified", "--status-waiting"],
    ["--evidence-rejected", "--status-danger"],
    ["--risk-low", "--status-success"],
    ["--risk-mid", "--status-waiting"],
    ["--risk-high", "--status-danger"],
    ["--risk-blocked", "--status-paused"],
    ["--surface-1", "--card"],
    ["--surface-2", "--muted"],
    ["--surface-3", "--secondary"],
  ]) {
    assert.match(root, new RegExp(`${token}:\\s*var\\(${target}\\);`), token);
  }
});

test("theme aliases expose the tokens as Tailwind colors", () => {
  const source = globals();
  const theme = source.match(/@theme\s*\{([\s\S]*?)^\}/m)?.[1] ?? "";
  const names = [
    ...STATUS_TOKENS.map((t) => `status-${t}`),
    "evidence-verified",
    "evidence-unverified",
    "evidence-rejected",
    "risk-low",
    "risk-mid",
    "risk-high",
    "risk-blocked",
    "surface-1",
    "surface-2",
    "surface-3",
  ];
  for (const name of names) {
    assert.ok(theme.includes(`--color-${name}: var(--${name});`), name);
  }
});

test("motion tokens exist and reduced motion is honored", () => {
  const source = globals();
  const root = cssBlock(source, ":root");
  for (const token of ["--motion-fast: 120ms", "--motion-base: 200ms", "--motion-slow: 320ms"]) {
    assert.ok(root.includes(token), token);
  }
  assert.match(source, /@media \(prefers-reduced-motion: reduce\)/);
  const layout = readFileSync("app/layout.tsx", "utf8");
  assert.match(layout, /<MotionProvider>/);
  const provider = readFileSync("components/motion-provider.tsx", "utf8");
  assert.match(provider, /reducedMotion="user"/);
});
```

`web/tests/source/light-theme.test.ts`:

```ts
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { cssBlock, STATUS_TOKENS } from "../css-tokens";

type Hsl = [number, number, number];

function readHsl(block: string, name: string): Hsl {
  const match = block.match(new RegExp(`${name}:\\s*hsl\\(([\\d.]+)\\s+([\\d.]+)%\\s+([\\d.]+)%\\)`));
  assert.ok(match, `${name} is not an hsl() literal`);
  return [Number(match[1]), Number(match[2]) / 100, Number(match[3]) / 100];
}

function luminance([h, s, l]: Hsl): number {
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = l - c / 2;
  const [r, g, b] =
    h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x]
    : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  const lin = (v: number) => {
    const u = v + m;
    return u <= 0.04045 ? u / 12.92 : ((u + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

function contrast(a: Hsl, b: Hsl): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (hi + 0.05) / (lo + 0.05);
}

const source = readFileSync("app/globals.css", "utf8");

test("the light theme shares the dark theme's 214° primary", () => {
  const root = cssBlock(source, ":root");
  assert.equal(readHsl(root, "--primary")[0], 214);
  assert.equal(readHsl(root, "--ring")[0], 214);
  // 순백(shadcn 기본)이 아니다 — 두 모드를 한 브랜드로 묶는다(spec §3.2).
  assert.doesNotMatch(root, /--background:\s*hsl\(0 0% 100%\)/);
});

for (const selector of [":root", ".dark"] as const) {
  test(`${selector}: body text, muted text, primary and every status pass WCAG AA on the background`, () => {
    const block = cssBlock(source, selector);
    const background = readHsl(block, "--background");
    const pairs: Array<[string, Hsl, Hsl]> = [
      ["--foreground", readHsl(block, "--foreground"), background],
      ["--muted-foreground", readHsl(block, "--muted-foreground"), background],
      ["--primary", readHsl(block, "--primary"), background],
      ...STATUS_TOKENS.map((t): [string, Hsl, Hsl] => [`--status-${t}`, readHsl(block, `--status-${t}`), background]),
    ];
    // 버튼 글자 대비는 라이트만 본다. 승인된 다크 쌍(primary 214 100% 58% 위의 220 40% 98%)은
    // 약 3.4:1 이고 blueblack-theme.test.ts 가 그 값을 고정한다 — 바꾸려면 그 테마 결정을 다시 해야 한다.
    if (selector === ":root") {
      pairs.push(["--primary-foreground on --primary", readHsl(block, "--primary-foreground"), readHsl(block, "--primary")]);
    }
    for (const [name, fg, bg] of pairs) {
      assert.ok(contrast(fg, bg) >= 4.5, `${selector} ${name}: ${contrast(fg, bg).toFixed(2)} < 4.5`);
    }
  });
}
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd web && pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/semantic-tokens.test.ts tests/source/light-theme.test.ts`
Expected: FAIL — `:root --status-running` 단언 실패, `--primary` hue 240

- [ ] **Step 3: `globals.css` 의 `:root` 블록을 통째로 바꾼다** (`/* define design tokens (light mode) */` 아래 `:root { … }`)

```css
:root {
  --background: hsl(220 33% 99%);
  --foreground: hsl(224 40% 8%);
  --card: hsl(0 0% 100%);
  --card-foreground: hsl(224 40% 8%);
  --popover: hsl(0 0% 100%);
  --popover-foreground: hsl(224 40% 8%);
  --primary: hsl(214 90% 44%);
  --primary-foreground: hsl(220 40% 98%);
  --secondary: hsl(218 33% 95%);
  --secondary-foreground: hsl(224 40% 12%);
  --muted: hsl(218 33% 95%);
  --muted-foreground: hsl(220 14% 38%);
  --accent: hsl(216 60% 94%);
  --accent-foreground: hsl(224 40% 12%);
  --destructive: hsl(0 72% 46%);
  --destructive-foreground: hsl(0 0% 98%);
  --border: hsl(220 25% 89%);
  --input: hsl(220 25% 89%);
  --ring: hsl(214 90% 44%);
  --chart-1: hsl(214 90% 44%);
  --chart-2: hsl(190 80% 38%);
  --chart-3: hsl(252 70% 56%);
  --chart-4: hsl(158 60% 36%);
  --chart-5: hsl(38 92% 44%);
  --sidebar-background: hsl(220 33% 97%);
  --sidebar-foreground: hsl(224 25% 24%);
  --sidebar-primary: hsl(214 90% 44%);
  --sidebar-primary-foreground: hsl(220 40% 98%);
  --sidebar-accent: hsl(216 50% 93%);
  --sidebar-accent-foreground: hsl(224 40% 12%);
  --sidebar-border: hsl(220 25% 89%);
  --sidebar-ring: hsl(214 90% 44%);
  /* border radius unit */
  --radius: 0.5rem;
  --sidebar: hsl(220 33% 97%);

  /* 작업 상태 (spec §3.1) — 라이트 값은 배경 대비 4.5:1 이상 */
  --status-running: hsl(214 90% 44%);
  --status-waiting: hsl(36 90% 32%);
  --status-paused: hsl(262 55% 48%);
  --status-success: hsl(152 65% 28%);
  --status-warning: hsl(24 90% 38%);
  --status-danger: hsl(0 72% 44%);
  --status-idle: hsl(220 12% 42%);

  /* 근거 · 위험 · 표면 — 상태 토큰을 가리키므로 .dark 에서 다시 정의하지 않는다 */
  --evidence-verified: var(--status-success);
  --evidence-unverified: var(--status-waiting);
  --evidence-rejected: var(--status-danger);
  --risk-low: var(--status-success);
  --risk-mid: var(--status-waiting);
  --risk-high: var(--status-danger);
  --risk-blocked: var(--status-paused);
  --surface-1: var(--card);
  --surface-2: var(--muted);
  --surface-3: var(--secondary);

  /* 모션 (spec §3.6) */
  --motion-fast: 120ms;
  --motion-base: 200ms;
  --motion-slow: 320ms;
  --motion-ease: cubic-bezier(0.2, 0, 0, 1);
}
```

- [ ] **Step 4: `.dark` 블록의 닫는 `}` 바로 앞(`--sidebar: hsl(225 38% 5%);` 다음 줄)에 더한다**

```css

  --status-running: hsl(214 100% 62%);
  --status-waiting: hsl(38 96% 62%);
  --status-paused: hsl(262 85% 74%);
  --status-success: hsl(152 60% 52%);
  --status-warning: hsl(28 95% 62%);
  --status-danger: hsl(0 85% 66%);
  --status-idle: hsl(220 14% 62%);
```

- [ ] **Step 5: `@theme` 블록의 닫는 `}` 바로 앞에 더한다**

```css

  --color-status-running: var(--status-running);
  --color-status-waiting: var(--status-waiting);
  --color-status-paused: var(--status-paused);
  --color-status-success: var(--status-success);
  --color-status-warning: var(--status-warning);
  --color-status-danger: var(--status-danger);
  --color-status-idle: var(--status-idle);
  --color-evidence-verified: var(--evidence-verified);
  --color-evidence-unverified: var(--evidence-unverified);
  --color-evidence-rejected: var(--evidence-rejected);
  --color-risk-low: var(--risk-low);
  --color-risk-mid: var(--risk-mid);
  --color-risk-high: var(--risk-high);
  --color-risk-blocked: var(--risk-blocked);
  --color-surface-1: var(--surface-1);
  --color-surface-2: var(--surface-2);
  --color-surface-3: var(--surface-3);
```

- [ ] **Step 6: 파일 끝에 reduced-motion 규칙을 더한다**

```css

/* spec §3.6 — 이동·맥동은 끄고 불투명도 전환만 남긴다 */
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    scroll-behavior: auto !important;
    transition-property: opacity !important;
  }
}
```

- [ ] **Step 7: `web/components/motion-provider.tsx` 를 만든다**

```tsx
"use client";

import { MotionConfig } from "framer-motion";
import type { ReactNode } from "react";

// framer-motion 은 인라인 스타일로 움직여 CSS 의 reduced-motion 규칙이 닿지 않는다.
// "user" 는 OS 설정을 따라 이동을 끄고 불투명도만 남긴다(spec §3.6).
export function MotionProvider({ children }: { children: ReactNode }) {
  return <MotionConfig reducedMotion="user">{children}</MotionConfig>;
}
```

- [ ] **Step 8: `web/app/layout.tsx` 를 고친다**

`const LIGHT_THEME_COLOR = "hsl(0 0% 100%)";` → `const LIGHT_THEME_COLOR = "hsl(220 33% 99%)";`

import 에 `import { MotionProvider } from "@/components/motion-provider";` 를 더하고, `<ThemeProvider …>` 의 자식 전체를 `<MotionProvider>…</MotionProvider>` 로 감싼다(ThemeProvider 바로 안쪽).

- [ ] **Step 9: 테스트 통과를 확인한다**

Run: `cd web && pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/semantic-tokens.test.ts tests/source/light-theme.test.ts tests/source/blueblack-theme.test.ts`
Expected: PASS (blue-black 테스트는 다크 값만 고정하므로 그대로 초록)

- [ ] **Step 10: 타입체크 후 커밋한다**

```bash
cd web && pnpm typecheck
git add app/globals.css app/layout.tsx components/motion-provider.tsx tests/css-tokens.ts tests/source/semantic-tokens.test.ts tests/source/light-theme.test.ts
git commit -m "feat(web): semantic status/evidence/risk tokens and a 214° light theme"
```

---

### Task 2: 한글 서체(Pretendard)와 타입 스케일

**Files:**
- Modify: `web/package.json`, `web/pnpm-lock.yaml` (pnpm 이 쓴다)
- Modify: `web/app/layout.tsx` (폰트 선언, `<html>` className)
- Modify: `web/app/globals.css` (`@theme` 의 `--font-sans`, 타입 스케일)
- Test: `web/tests/source/typography.test.ts`

**Interfaces:**
- Produces: CSS 변수 `--font-pretendard`, Tailwind 유틸리티 `text-caption` · `text-body-sm` · `text-body` · `text-title-sm` · `text-title` · `text-display`

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `web/tests/source/typography.test.ts`

```ts
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const WEIGHTS = ["Regular", "Medium", "SemiBold", "Bold"] as const;
const SUBSET_DIR = "node_modules/pretendard/dist/web/static/woff2-subset";

test("pretendard is pinned to an exact version", () => {
  const pkg = JSON.parse(readFileSync("package.json", "utf8"));
  assert.equal(pkg.dependencies.pretendard, "1.3.9");
});

test("the four KS X 1001 subset weights exist where next/font reads them", () => {
  for (const weight of WEIGHTS) {
    assert.ok(existsSync(`${SUBSET_DIR}/Pretendard-${weight}.subset.woff2`), weight);
  }
});

test("the root layout loads pretendard locally and exposes its variable", () => {
  const layout = readFileSync("app/layout.tsx", "utf8");
  assert.match(layout, /from "next\/font\/local"/);
  for (const weight of WEIGHTS) {
    assert.ok(layout.includes(`woff2-subset/Pretendard-${weight}.subset.woff2`), weight);
  }
  assert.match(layout, /variable: "--font-pretendard"/);
  assert.match(layout, /\$\{pretendard\.variable\}/);
});

test("sans falls back from Geist to Pretendard, and the type scale is tokenized", () => {
  const css = readFileSync("app/globals.css", "utf8");
  assert.match(css, /--font-sans: var\(--font-geist\), var\(--font-pretendard\), system-ui, sans-serif;/);
  for (const step of ["caption", "body-sm", "body", "title-sm", "title", "display"]) {
    assert.match(css, new RegExp(`--text-${step}:\\s*[\\d.]+rem;`), step);
    assert.match(css, new RegExp(`--text-${step}--line-height:\\s*[\\d.]+;`), `${step} line height`);
  }
  // 한글 본문 가독성(spec §3.3)
  const body = Number(css.match(/--text-body--line-height:\s*([\d.]+);/)?.[1]);
  assert.ok(body >= 1.65, `body line height ${body}`);
});
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd web && pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/typography.test.ts`
Expected: FAIL — `pkg.dependencies.pretendard` undefined

- [ ] **Step 3: 패키지를 정확 버전으로 더한다**

Run: `cd web && pnpm add pretendard@1.3.9 --save-exact`
그 뒤 `cat package.json | grep pretendard` 가 `"pretendard": "1.3.9"` 인지 확인한다(캐럿 없이).

- [ ] **Step 4: `web/app/layout.tsx` 에 폰트를 선언한다** — `const geistMono = …;` 블록 바로 아래

```tsx
// 한글 글꼴(spec §3.3). Geist 에는 한글 글리프가 없어 OS 시스템 폰트로 떨어지고 있었다.
// KS X 1001 서브셋 정적 네 굵기 — 단일 가변 파일은 약 2MB 라 쓰지 않는다.
// preload 를 끄는 이유: 네 파일을 모두 미리 받으면 첫 페인트 전에 약 1MB 가 된다.
const pretendard = localFont({
  src: [
    { path: "../node_modules/pretendard/dist/web/static/woff2-subset/Pretendard-Regular.subset.woff2", weight: "400", style: "normal" },
    { path: "../node_modules/pretendard/dist/web/static/woff2-subset/Pretendard-Medium.subset.woff2", weight: "500", style: "normal" },
    { path: "../node_modules/pretendard/dist/web/static/woff2-subset/Pretendard-SemiBold.subset.woff2", weight: "600", style: "normal" },
    { path: "../node_modules/pretendard/dist/web/static/woff2-subset/Pretendard-Bold.subset.woff2", weight: "700", style: "normal" },
  ],
  variable: "--font-pretendard",
  display: "swap",
  preload: false,
});
```

import 에 `import localFont from "next/font/local";` 를 더한다. `<html>` 의 `` className={`${geist.variable} ${geistMono.variable}`} `` 를 `` className={`${geist.variable} ${geistMono.variable} ${pretendard.variable}`} `` 로 바꾼다.

- [ ] **Step 5: `globals.css` 의 `@theme` 을 고친다**

`--font-sans: var(--font-geist);` → `--font-sans: var(--font-geist), var(--font-pretendard), system-ui, sans-serif;`

`--breakpoint-toast-mobile: 600px;` 다음 줄에 더한다:

```css

  /* 타입 스케일 (spec §3.3) */
  --text-caption: 0.75rem;
  --text-caption--line-height: 1.5;
  --text-body-sm: 0.8125rem;
  --text-body-sm--line-height: 1.6;
  --text-body: 0.9375rem;
  --text-body--line-height: 1.7;
  --text-title-sm: 1.0625rem;
  --text-title-sm--line-height: 1.5;
  --text-title: 1.375rem;
  --text-title--line-height: 1.4;
  --text-display: 2rem;
  --text-display--line-height: 1.25;
```

- [ ] **Step 6: 테스트와 빌드를 확인한다**

Run: `cd web && pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/typography.test.ts && pnpm typecheck && pnpm build`
Expected: PASS · 빌드 성공(`next/font/local` 이 경로를 못 찾으면 빌드가 경로를 찍으며 실패한다)

- [ ] **Step 7: 커밋한다**

```bash
git add package.json pnpm-lock.yaml app/layout.tsx app/globals.css tests/source/typography.test.ts
git commit -m "feat(web): load Pretendard for Korean text and tokenize the type scale"
```

---

### Task 3: 템플릿 도구 제거

**Files:**
- Delete: `web/lib/ai/tools/get-weather.ts`, `web/lib/ai/tools/request-suggestions.ts`, `web/components/weather.tsx`
- Modify: `web/lib/types.ts` (import 2줄, `weatherTool`·`requestSuggestionsTool` 타입, `ChatTools` 의 두 키)
- Modify: `web/components/message.tsx` (`import { Weather }`, `tool-getWeather`·`tool-requestSuggestions` 분기)
- Test: `web/tests/source/template-tools-removed.test.ts`

**Interfaces:**
- Produces: `ChatTools = { createDocument; updateDocument }` (두 키만)

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `web/tests/source/template-tools-removed.test.ts`

```ts
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import test from "node:test";

// spec §3.5 — 두 도구는 BFF 챗 라우트가 등록하지 않는 죽은 코드였다(2026-10-11).
const REMOVED_FILES = [
  "lib/ai/tools/get-weather.ts",
  "lib/ai/tools/request-suggestions.ts",
  "components/weather.tsx",
];
const REMOVED_NAMES = ["getWeather", "requestSuggestions", "tool-getWeather", "tool-requestSuggestions"];

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) return sources(full);
    return /\.tsx?$/.test(entry) ? [full] : [];
  });
}

test("the template tool files are gone", () => {
  for (const file of REMOVED_FILES) {
    assert.equal(existsSync(file), false, file);
  }
});

test("nothing names the template tools", () => {
  const offenders = ["app", "components", "features", "hooks", "lib"]
    .flatMap(sources)
    .filter((file) => {
      const text = readFileSync(file, "utf8");
      return REMOVED_NAMES.some((name) => text.includes(name));
    });
  assert.deepEqual(offenders, []);
});
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd web && pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/template-tools-removed.test.ts`
Expected: FAIL — `lib/ai/tools/get-weather.ts` 가 있다

- [ ] **Step 3: 파일을 지운다**

```bash
cd web && git rm lib/ai/tools/get-weather.ts lib/ai/tools/request-suggestions.ts components/weather.tsx
```

- [ ] **Step 4: `web/lib/types.ts` 를 고친다**

`getWeather` · `requestSuggestions` 를 들여오는 import 두 줄을 지운다(`grep -n "get-weather\|request-suggestions" lib/types.ts` 로 찾는다). 아래 두 타입을 지운다:

```ts
type weatherTool = InferUITool<typeof getWeather>;
type requestSuggestionsTool = InferUITool<
  ReturnType<typeof requestSuggestions>
>;
```

`ChatTools` 를 이렇게 바꾼다:

```ts
export type ChatTools = {
  createDocument: createDocumentTool;
  updateDocument: updateDocumentTool;
};
```

- [ ] **Step 5: `web/components/message.tsx` 를 고친다**

`import { Weather } from "./weather";` 를 지운다. `if (type === "tool-getWeather") { … }` 블록 전체와 `if (type === "tool-requestSuggestions") { … }` 블록 전체를 지운다(각 블록은 `return ( <Tool … </Tool> ); }` 로 끝난다). `tool-createDocument` · `tool-updateDocument` 분기는 남긴다.

- [ ] **Step 6: 남은 참조가 없는지 보고 테스트·타입체크를 돌린다**

Run: `cd web && grep -rn "getWeather\|requestSuggestions\|weather\"" app components features hooks lib; pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/template-tools-removed.test.ts && pnpm typecheck`
Expected: grep 출력 없음 · PASS · 타입 오류 없음. `components/document.tsx` 의 `type: "request-suggestions"` 문자열 유니언은 도구 이름이 아니라 문서 결과 종류이므로 남는다 — 테스트의 금지 이름(`requestSuggestions`)과 다르다.

- [ ] **Step 7: 커밋한다**

```bash
git add -A lib/types.ts components/message.tsx tests/source/template-tools-removed.test.ts
git commit -m "chore(web): remove the template weather and suggestions tools (never registered)"
```

---

### Task 4: 원시 팔레트 색을 시맨틱 토큰으로 바꾸고 금지한다

**Files:**
- Modify: 원시 팔레트 클래스를 가진 파일 전부(2026-10-11 기준 32개 — Step 2 출력이 정본). 대표: `components/deep-analysis-status.tsx` · `components/message.tsx` · `components/harness-status.tsx` · `features/coding/components/{coding-task-workspace,phase-card,coding-detail-panel,coding-approval-card,phase-timeline,…}.tsx`
- Test: `web/tests/source/raw-palette-ban.test.ts`

**Interfaces:**
- Consumes: Task 1 의 `text-status-*` · `bg-status-*` · `border-status-*` · `text-primary` 유틸리티

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `web/tests/source/raw-palette-ban.test.ts`

```ts
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const ROOTS = ["app", "components", "features", "hooks", "lib"];
// shadcn 원자와 아이콘 SVG 는 대상이 아니다(spec §3.1). 이름으로 고정한다.
const EXCLUDED_DIRS = ["components/ui"];
const EXCLUDED_FILES = ["components/icons.tsx"];
// 승인된 blue-black 다크 장식 — blueblack-theme.test.ts 가 같은 값을 고정한다.
const ALLOWED: Record<string, string[]> = {
  "components/chat-header.tsx": ["dark:border-blue-300/10"],
  "components/messages.tsx": ["dark:border-blue-300/20"],
  "components/multimodal-input.tsx": [
    "dark:hover:border-blue-300/30",
    "dark:focus-within:border-blue-300/45",
    "dark:focus-within:ring-blue-300/35",
  ],
};

const HUES = "red|green|amber|yellow|blue|purple|emerald|orange|rose|sky|indigo";
const RAW_PALETTE = new RegExp(
  `(?<![\\w-])((?:[\\w-]+:)*)((?:text|bg|border(?:-[trblxy])?|ring|from|via|to|fill|stroke|outline|divide|decoration)-(?:${HUES})-\\d{2,3}(?:\\/[\\d.]+)?)(?![\\w-])`,
  "g"
);

function rawPaletteClasses(text: string): string[] {
  return [...text.matchAll(RAW_PALETTE)].map((m) => `${m[1]}${m[2]}`);
}

function sources(dir: string): string[] {
  if (EXCLUDED_DIRS.includes(dir)) return [];
  return readdirSync(dir).flatMap((entry) => {
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) return sources(full);
    return /\.tsx?$/.test(entry) && !EXCLUDED_FILES.includes(full) ? [full] : [];
  });
}

test("the matcher sees classes inside cn(), ternaries and template strings (review focus 5)", () => {
  assert.deepEqual(rawPaletteClasses('cn("p-2", ok ? "text-green-600" : "text-red-500")'), [
    "text-green-600",
    "text-red-500",
  ]);
  assert.deepEqual(rawPaletteClasses("`border-l-2 ${x ? \"border-l-rose-400\" : \"\"}`"), ["border-l-rose-400"]);
  // 임의값 불투명도(`/[0.06]`)도 잡힌다 — 색 이름 다음 문자 `/` 에서 경계가 선다.
  assert.deepEqual(rawPaletteClasses('"dark:hover:bg-amber-400/[0.06] from-amber-400/60"'), [
    "dark:hover:bg-amber-400",
    "from-amber-400/60",
  ]);
  assert.deepEqual(rawPaletteClasses('"text-status-danger bg-primary/10 text-red"'), []);
});

test("no source file uses a raw palette class outside the allowlist", () => {
  const offenders: string[] = [];
  for (const file of ROOTS.flatMap(sources)) {
    const allowed = new Set(ALLOWED[file] ?? []);
    for (const cls of rawPaletteClasses(readFileSync(file, "utf8"))) {
      if (!allowed.has(cls)) offenders.push(`${file}: ${cls}`);
    }
  }
  assert.deepEqual(offenders, []);
});

test("every allowlist entry is still used (a stale exemption hides nothing)", () => {
  for (const [file, classes] of Object.entries(ALLOWED)) {
    const found = new Set(rawPaletteClasses(readFileSync(file, "utf8")));
    for (const cls of classes) assert.ok(found.has(cls), `${file}: ${cls} no longer present`);
  }
});
```

- [ ] **Step 2: 실패를 확인하고 목록을 받는다**

Run: `cd web && pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/raw-palette-ban.test.ts 2>&1 | tail -80`
Expected: 첫 테스트 PASS, 둘째 FAIL — `offenders` 에 `파일: 클래스` 목록(약 180줄). 임의값 불투명도(`bg-amber-400/[0.06]`)는
목록에 `bg-amber-400` 으로 나온다 — 치환할 때 뒤의 `/[0.06]` 는 남기고 색 이름만 바꾼다(`bg-status-running/[0.06]`).

- [ ] **Step 3: 의미에 따라 치환한다** — 색이 아니라 **그 자리의 뜻**을 보고 고른다

| 원래 쓰임 | 바꿀 토큰 | 예 |
|---|---|---|
| 오류 · 실패 · 거절 · 명령 위험(red · rose) | `status-danger` | `text-red-600` → `text-status-danger`, `border-l-rose-400` → `border-l-status-danger`, `bg-rose-500/10` → `bg-status-danger/10` |
| 완료 · 통과(green · emerald) | `status-success` | `text-emerald-400` → `text-status-success` |
| 승인 대기 · 사용자 응답 대기(amber · yellow) | `status-waiting` | 승인 카드 `border-l-amber-400` → `border-l-status-waiting` |
| 경고 · 저하 · 막힘(amber · orange) | `status-warning` | phase `blocked` 톤, DA 저하 알림 |
| 진행 중(amber 스피너 · blue · purple · sky) | `status-running` | phase `active` 톤, DA `running` 아이콘 |
| 대기(진행 전) | `status-idle` | DA `pending` 아이콘 |
| **상태가 아닌 장식 강조**(타임라인 그라데이션, 섹션 eyebrow, 강조 아이콘) | `primary` | `from-amber-400/60` → `from-primary/60`, eyebrow `text-amber-400` → `text-primary` |
| diff 추가 / 삭제 줄 | `status-success` / `status-danger` | `components/diffview.tsx` |

판단이 갈리면 **상태 의미를 먼저** 고른다. `/code` 의 amber 장식이 블루가 되는 것은 의도된 변화다(spec §3.1).

- [ ] **Step 4: 테스트와 기존 테마 테스트를 함께 돌린다**

Run: `cd web && pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/raw-palette-ban.test.ts tests/source/blueblack-theme.test.ts && pnpm test:source`
Expected: PASS 전체. 실패한 기존 테스트가 있으면 그 테스트가 **클래스 문자열**을 고정한 것인지 본다 — 2026-10-11 grep 에서 `blueblack-theme.test.ts` 외에는 없었다. 있다면 치환이 아니라 그 클래스를 허용 목록에 넣을지 멈추고 묻는다.

- [ ] **Step 5: 커밋한다**

```bash
git add -A app components features hooks lib tests/source/raw-palette-ban.test.ts
git commit -m "refactor(web): replace raw palette classes with semantic status tokens, and ban them

/code amber accents become --primary on purpose (one brand, spec §3.1)."
```

---

### Task 5: 문구 사전 · 표시 모델 · 상태 매핑

**Files:**
- Create: `web/lib/copy/common.ts`, `web/components/trace/types.ts`, `web/components/trace/status.ts`
- Test: `web/tests/source/trace-status.test.ts`

**Interfaces:**
- Produces:
  - `commonCopy` — `status: Record<TraceStatus, string>`, `verdictMode: { shadow: "shadow"; enforced: "enforced" }`, `evidence: Record<ClaimView["status"], string>`, `question: Record<QuestionView["status"], string>`, `trace: { timelineLabel; sources; noSources; duration(seconds) }`
  - `components/trace/types.ts` 의 `TraceStatus` · `TraceStep` · `TraceItem` · `ToolActivityView` · `ApprovalView` · `VerdictView` · `ClaimView` · `QuestionView`(spec §5.2 와 글자 그대로)
  - `TRACE_STATUSES: readonly TraceStatus[]`, `StatusToken`, `STATUS_TOKEN: Record<TraceStatus, StatusToken>`, `statusClasses(status: TraceStatus): { text: string; bg: string; border: string }`

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `web/tests/source/trace-status.test.ts`

```ts
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { STATUS_TOKEN, statusClasses, TRACE_STATUSES } from "@/components/trace/status";
import { commonCopy } from "@/lib/copy/common";
import { cssBlock } from "../css-tokens";

test("every trace status maps to a token that light and dark both define", () => {
  const css = readFileSync("app/globals.css", "utf8");
  for (const status of TRACE_STATUSES) {
    const token = STATUS_TOKEN[status];
    for (const selector of [":root", ".dark"] as const) {
      assert.match(cssBlock(css, selector), new RegExp(`--status-${token}:`), `${status} → ${token} in ${selector}`);
    }
  }
});

test("the mapping is the one spec §3.1 names", () => {
  assert.deepEqual(STATUS_TOKEN, {
    queued: "idle",
    running: "running",
    waiting: "waiting",
    paused: "paused",
    succeeded: "success",
    failed: "danger",
    cancelled: "idle",
  });
});

test("classes are literal Tailwind names (the compiler only sees literals)", () => {
  assert.deepEqual(statusClasses("failed"), {
    text: "text-status-danger",
    bg: "bg-status-danger/10",
    border: "border-status-danger/40",
  });
});

test("every status has a Korean label", () => {
  for (const status of TRACE_STATUSES) {
    assert.ok(commonCopy.status[status].length > 0, status);
  }
});
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd web && pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/trace-status.test.ts`
Expected: FAIL — `Cannot find module '@/components/trace/status'`

- [ ] **Step 3: `web/components/trace/types.ts` 를 만든다** (spec §5.2 그대로 — 1단계가 고정하는 계약)

```ts
// 작업 흔적 표시 모델 (spec §5.2). 출처와 무관하다 — 코딩 · 챗 · DA · 상시 에이전트
// 어댑터가 이 모양을 만들고 components/trace/* 가 그린다. 필드를 빼거나 뜻을
// 바꾸려면 그 단계 spec 이 이유를 적는다.

export type TraceStatus =
  | "queued"
  | "running"
  | "waiting"
  | "paused"
  | "succeeded"
  | "failed"
  | "cancelled";

export type TraceStep = {
  id: string;
  label: string;
  status: TraceStatus;
  startedAt?: string;
  endedAt?: string;
  items: TraceItem[];
  /** depth-1 만. 서브에이전트 런타임의 depth-1 제약을 따른다. */
  children?: TraceStep[];
};

export type TraceItem =
  | { kind: "tool"; call: ToolActivityView }
  | { kind: "approval"; approval: ApprovalView }
  | { kind: "verdict"; verdict: VerdictView }
  | { kind: "evidence"; claim: ClaimView }
  | { kind: "question"; question: QuestionView }
  | { kind: "note"; text: string };

export type ToolActivityView = {
  id: string;
  name: string;
  status: TraceStatus;
  /** 어댑터가 지은 한 줄 */
  summary?: string;
  /** 결과 미리보기 */
  preview?: string;
  deniedReason?: string;
};

export type ApprovalView = {
  id: string;
  toolName: string;
  risk: "workspace_write" | "command" | "user_question";
  status: "pending" | "approved" | "denied" | "expired" | "invalidated";
  summary: { label: string; value: string }[];
  expiresAt?: string;
  verdict?: VerdictView;
};

export type VerdictView = {
  band: "low" | "mid" | "high" | "blocked" | "unavailable";
  probability?: number;
  mode: "shadow" | "enforced";
  /** 고정부 — 늘 보인다 */
  badge: string;
  /** 의미 문장 — 어댑터의 문장 함수가 짓는다 */
  sentence: string | null;
};

export type ClaimView = {
  id: string;
  text: string;
  status: "verified" | "unverified" | "rejected";
  sources: { url: string; title?: string; excerpt?: string }[];
  /** L6 판정자 */
  verdict?: VerdictView;
};

export type QuestionView = {
  id: string;
  prompt: string;
  status: "open" | "answered" | "expired";
};
```

- [ ] **Step 4: `web/components/trace/status.ts` 를 만든다**

```ts
import type { TraceStatus } from "./types";

export const TRACE_STATUSES = [
  "queued",
  "running",
  "waiting",
  "paused",
  "succeeded",
  "failed",
  "cancelled",
] as const satisfies readonly TraceStatus[];

// 목록이 유니언을 다 덮는지 컴파일러가 본다 — 새 상태를 더하고 여기를 잊으면 타입 오류다.
type Missing = Exclude<TraceStatus, (typeof TRACE_STATUSES)[number]>;
const _exhaustive: Missing extends never ? true : never = true;
void _exhaustive;

export type StatusToken = "running" | "waiting" | "paused" | "success" | "warning" | "danger" | "idle";

export const STATUS_TOKEN: Record<TraceStatus, StatusToken> = {
  queued: "idle",
  running: "running",
  waiting: "waiting",
  paused: "paused",
  succeeded: "success",
  failed: "danger",
  cancelled: "idle",
};

// Tailwind 는 소스의 리터럴만 본다 — 문자열을 조립하지 않는다.
const TEXT: Record<StatusToken, string> = {
  running: "text-status-running",
  waiting: "text-status-waiting",
  paused: "text-status-paused",
  success: "text-status-success",
  warning: "text-status-warning",
  danger: "text-status-danger",
  idle: "text-status-idle",
};
const BG: Record<StatusToken, string> = {
  running: "bg-status-running/10",
  waiting: "bg-status-waiting/10",
  paused: "bg-status-paused/10",
  success: "bg-status-success/10",
  warning: "bg-status-warning/10",
  danger: "bg-status-danger/10",
  idle: "bg-status-idle/10",
};
const BORDER: Record<StatusToken, string> = {
  running: "border-status-running/40",
  waiting: "border-status-waiting/40",
  paused: "border-status-paused/40",
  success: "border-status-success/40",
  warning: "border-status-warning/40",
  danger: "border-status-danger/40",
  idle: "border-status-idle/40",
};

export function statusClasses(status: TraceStatus): { text: string; bg: string; border: string } {
  const token = STATUS_TOKEN[status];
  return { text: TEXT[token], bg: BG[token], border: BORDER[token] };
}
```

- [ ] **Step 5: `web/lib/copy/common.ts` 를 만든다**

```ts
// 표면 공통 문구 사전 (spec §3.4). 값은 한국어다.
// 예외 — verdictMode 는 코딩 소스 테스트가 "shadow" 를 고정해 5단계에서 번역한다.
export const commonCopy = {
  status: {
    queued: "대기열",
    running: "진행 중",
    waiting: "응답 대기",
    paused: "멈춤",
    succeeded: "완료",
    failed: "실패",
    cancelled: "취소됨",
  },
  verdictMode: { shadow: "shadow", enforced: "enforced" },
  evidence: { verified: "검증됨", unverified: "미검증", rejected: "기각" },
  question: { open: "답을 기다림", answered: "답함", expired: "만료됨" },
  trace: {
    timelineLabel: "작업 단계",
    sources: "출처",
    noSources: "출처 없음",
    duration: (seconds: number) =>
      seconds < 60 ? `${seconds}초` : `${Math.floor(seconds / 60)}분 ${seconds % 60}초`,
  },
} as const;
```

- [ ] **Step 6: 통과를 확인하고 커밋한다**

Run: `cd web && pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/trace-status.test.ts && pnpm typecheck`
Expected: PASS

```bash
git add components/trace/types.ts components/trace/status.ts lib/copy/common.ts tests/source/trace-status.test.ts
git commit -m "feat(web): trace display model, status-to-token mapping and the common copy dictionary"
```

---

### Task 6: 프리미티브 ① — RunStatus · VerdictBadge · ToolActivity

**Files:**
- Create: `web/components/trace/run-status.tsx`, `web/components/trace/verdict-badge.tsx`, `web/components/trace/tool-activity.tsx`
- Test: `web/tests/source/trace-primitives.test.tsx`

**Interfaces:**
- Consumes: Task 5 의 `statusClasses`, `commonCopy`, 표시 모델 타입
- Produces:
  - `RunStatus({ status: TraceStatus; label?: string; actions?: RunStatusAction[]; className?: string })`, `type RunStatusAction = { id: string; label: string; onSelect: () => void; disabled?: boolean }` — 루트 `data-testid="run-status"` `data-status`
  - `VerdictBadge({ verdict: VerdictView })` — 루트 `data-testid="verdict-badge"` `data-band` `data-mode`
  - `ToolActivity({ call: ToolActivityView; children?: ReactNode })` — 루트 `data-testid="tool-activity"` `data-status`

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `web/tests/source/trace-primitives.test.tsx`

```tsx
import "../dom-setup";
import assert from "node:assert/strict";
import test from "node:test";
import { act } from "react";
import { RunStatus } from "@/components/trace/run-status";
import { ToolActivity } from "@/components/trace/tool-activity";
import type { VerdictView } from "@/components/trace/types";
import { VerdictBadge } from "@/components/trace/verdict-badge";
import { renderComponent } from "../render";

const verdict = (overrides: Partial<VerdictView> = {}): VerdictView => ({
  band: "mid",
  probability: 0.62,
  mode: "shadow",
  badge: "jev 0.62 · mid",
  sentence: "Shadow: with the gate on, this call would have required approval.",
  ...overrides,
});

test("RunStatus speaks the Korean label and colors by token", async () => {
  const host = await renderComponent(<RunStatus status="failed" />);
  const root = host.querySelector('[data-testid="run-status"]');
  assert.equal(root?.getAttribute("data-status"), "failed");
  assert.match(root?.textContent ?? "", /실패/);
  assert.ok(root?.innerHTML.includes("text-status-danger"));
});

test("RunStatus actions are buttons that fire", async () => {
  let resumed = 0;
  const host = await renderComponent(
    <RunStatus actions={[{ id: "resume", label: "재개", onSelect: () => resumed++ }]} status="paused" />
  );
  const button = host.querySelector("button") as HTMLButtonElement;
  assert.equal(button.textContent, "재개");
  await act(async () => button.click());
  assert.equal(resumed, 1);
});

test("VerdictBadge always shows the badge and the mode", async () => {
  const host = await renderComponent(<VerdictBadge verdict={verdict()} />);
  const root = host.querySelector('[data-testid="verdict-badge"]');
  assert.equal(root?.getAttribute("data-band"), "mid");
  assert.match(root?.textContent ?? "", /jev 0\.62 · mid/);
  assert.match(root?.textContent ?? "", /shadow/);
  assert.match(root?.textContent ?? "", /would have required approval/);
});

test("VerdictBadge with no sentence renders the badge alone", async () => {
  const host = await renderComponent(<VerdictBadge verdict={verdict({ sentence: null })} />);
  assert.equal(host.querySelectorAll('[data-testid="verdict-badge"] p').length, 1);
});

test("ToolActivity names the call, its summary, preview and denial", async () => {
  const host = await renderComponent(
    <ToolActivity
      call={{
        id: "t1",
        name: "execute.v1",
        status: "failed",
        summary: "pytest -q",
        preview: "1 failed",
        deniedReason: "denied by gate",
      }}
    />
  );
  const root = host.querySelector('[data-testid="tool-activity"]');
  assert.equal(root?.getAttribute("data-status"), "failed");
  assert.match(root?.textContent ?? "", /execute\.v1 · pytest -q/);
  assert.match(root?.textContent ?? "", /1 failed/);
  assert.match(root?.textContent ?? "", /denied by gate/);
});
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd web && pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/trace-primitives.test.tsx`
Expected: FAIL — 모듈 없음

- [ ] **Step 3: `web/components/trace/run-status.tsx`**

```tsx
"use client";

import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  Clock3,
  Loader2,
  type LucideIcon,
  PauseCircle,
  XCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { commonCopy } from "@/lib/copy/common";
import { cn } from "@/lib/utils";
import { statusClasses } from "./status";
import type { TraceStatus } from "./types";

const ICONS: Record<TraceStatus, LucideIcon> = {
  queued: CircleDashed,
  running: Loader2,
  waiting: Clock3,
  paused: PauseCircle,
  succeeded: CheckCircle2,
  failed: AlertTriangle,
  cancelled: XCircle,
};

export type RunStatusAction = {
  id: string;
  label: string;
  onSelect: () => void;
  disabled?: boolean;
};

export function RunStatus({
  status,
  label,
  actions = [],
  className,
}: {
  status: TraceStatus;
  label?: string;
  actions?: RunStatusAction[];
  className?: string;
}) {
  const Icon = ICONS[status];
  const tone = statusClasses(status);
  return (
    <span
      className={cn("inline-flex items-center gap-2", className)}
      data-status={status}
      data-testid="run-status"
    >
      <span
        className={cn(
          "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-medium text-caption",
          tone.text,
          tone.bg,
          tone.border
        )}
      >
        <Icon
          aria-hidden
          className={cn("size-3.5", status === "running" && "animate-spin motion-reduce:animate-none")}
        />
        {label ?? commonCopy.status[status]}
      </span>
      {actions.map((action) => (
        <Button
          className="h-7 px-2 text-caption"
          disabled={action.disabled}
          key={action.id}
          onClick={action.onSelect}
          size="sm"
          type="button"
          variant="ghost"
        >
          {action.label}
        </Button>
      ))}
    </span>
  );
}
```

- [ ] **Step 4: `web/components/trace/verdict-badge.tsx`**

```tsx
import { commonCopy } from "@/lib/copy/common";
import type { VerdictView } from "./types";

const BAND_TEXT: Record<VerdictView["band"], string> = {
  low: "text-risk-low",
  mid: "text-risk-mid",
  high: "text-risk-high",
  blocked: "text-risk-blocked",
  unavailable: "text-muted-foreground",
};

// 문장을 짓지 않는다 — badge 와 sentence 는 출처의 문장 함수가 채운다(spec §5.1).
export function VerdictBadge({ verdict }: { verdict: VerdictView }) {
  return (
    <div data-band={verdict.band} data-mode={verdict.mode} data-testid="verdict-badge">
      <p className="flex items-center gap-2 font-mono text-[11px]">
        <span className={BAND_TEXT[verdict.band]}>{verdict.badge}</span>
        <span className="rounded-sm border border-border/70 px-1 py-px text-[9px] text-muted-foreground uppercase tracking-wider">
          {commonCopy.verdictMode[verdict.mode]}
        </span>
      </p>
      {verdict.sentence ? (
        <p className="mt-0.5 text-[11px] text-muted-foreground">{verdict.sentence}</p>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 5: `web/components/trace/tool-activity.tsx`**

```tsx
import { Wrench } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { RunStatus } from "./run-status";
import { statusClasses } from "./status";
import type { ToolActivityView } from "./types";

export function ToolActivity({ call, children }: { call: ToolActivityView; children?: ReactNode }) {
  return (
    <div
      className="rounded-md border border-border/70 bg-surface-1 px-3 py-2"
      data-status={call.status}
      data-testid="tool-activity"
    >
      <div className="flex items-center justify-between gap-3">
        <span className="flex min-w-0 items-center gap-2 font-mono text-xs">
          <Wrench aria-hidden className={cn("size-3 shrink-0", statusClasses(call.status).text)} />
          <span className="truncate" title={call.summary ? `${call.name} · ${call.summary}` : call.name}>
            {call.name}
            {call.summary ? ` · ${call.summary}` : ""}
          </span>
        </span>
        <RunStatus status={call.status} />
      </div>
      {call.preview ? (
        <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-sm bg-surface-2 px-2 py-1 font-mono text-[11px]">
          {call.preview}
        </pre>
      ) : null}
      {call.deniedReason ? (
        <p className="mt-1 text-[11px] text-status-danger">{call.deniedReason}</p>
      ) : null}
      {children}
    </div>
  );
}
```

- [ ] **Step 6: 통과를 확인하고 커밋한다**

Run: `cd web && pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/trace-primitives.test.tsx && pnpm typecheck`
Expected: PASS

```bash
git add components/trace/run-status.tsx components/trace/verdict-badge.tsx components/trace/tool-activity.tsx tests/source/trace-primitives.test.tsx
git commit -m "feat(web): RunStatus, VerdictBadge and ToolActivity trace primitives"
```

---

### Task 7: 프리미티브 ② — ClaimEvidence · ApprovalCard · StepTimeline

**Files:**
- Create: `web/components/trace/claim-evidence.tsx`, `web/components/trace/approval-card.tsx`, `web/components/trace/step-timeline.tsx`
- Modify: `web/tests/source/trace-primitives.test.tsx` (테스트 추가)

**Interfaces:**
- Consumes: Task 6 의 세 프리미티브, `components/elements/inline-citation.tsx` 의 `InlineCitation` · `InlineCitationText` · `InlineCitationCard` · `InlineCitationCardTrigger` · `InlineCitationCardBody` · `InlineCitationSource` · `InlineCitationQuote`
- Produces:
  - `ClaimEvidence({ claim: ClaimView })` — 루트 `data-testid="claim-evidence"` `data-status`
  - `ApprovalCard({ approval: ApprovalView; eyebrow: string; hint: string; warnings?: string[]; actions: ApprovalAction[]; busyActionId?: string | null; error?: string | null; body?: ReactNode; details?: ReactNode })`, `type ApprovalAction = { id: string; label: string; busyLabel: string; ariaLabel: string; variant: "default" | "outline"; disabled: boolean; onSelect: () => void }` — `body` 가 있으면 summary 목록 대신 그린다. `details` 는 summary/body 다음에 붙는다
  - `StepTimeline({ steps: TraceStep[] })`, `TraceItemView({ item: TraceItem })`

- [ ] **Step 1: 실패하는 테스트를 `trace-primitives.test.tsx` 끝에 더한다** (import 도 파일 위에 더한다)

```tsx
import { ApprovalCard } from "@/components/trace/approval-card";
import { ClaimEvidence } from "@/components/trace/claim-evidence";
import { StepTimeline } from "@/components/trace/step-timeline";
import type { ApprovalView, TraceItem, TraceStep } from "@/components/trace/types";

const approvalView = (overrides: Partial<ApprovalView> = {}): ApprovalView => ({
  id: "ca_1",
  toolName: "execute.v1",
  risk: "command",
  status: "pending",
  summary: [{ label: "command", value: "pytest -q" }],
  expiresAt: "2026-10-11T00:15:00Z",
  ...overrides,
});

test("ClaimEvidence shows the claim, its status and every source excerpt", async () => {
  const host = await renderComponent(
    <ClaimEvidence
      claim={{
        id: "c1",
        text: "출하량이 12% 늘었다",
        status: "verified",
        sources: [{ url: "https://example.com/report", title: "분기 보고서", excerpt: "shipments rose 12%" }],
      }}
    />
  );
  const root = host.querySelector('[data-testid="claim-evidence"]');
  assert.equal(root?.getAttribute("data-status"), "verified");
  assert.match(root?.textContent ?? "", /출하량이 12% 늘었다/);
  assert.match(root?.textContent ?? "", /검증됨/);
  assert.match(root?.textContent ?? "", /example\.com/);
});

test("ClaimEvidence with no sources says so instead of throwing on new URL()", async () => {
  const host = await renderComponent(
    <ClaimEvidence claim={{ id: "c2", text: "근거 없는 단정", status: "unverified", sources: [] }} />
  );
  assert.match(host.textContent ?? "", /출처 없음/);
});

test("ApprovalCard renders the summary and the given actions with their aria labels", async () => {
  let approved = 0;
  const host = await renderComponent(
    <ApprovalCard
      actions={[
        { id: "deny", label: "Deny", busyLabel: "Denying…", ariaLabel: "Deny tool request", variant: "outline", disabled: false, onSelect: () => {} },
        { id: "approve", label: "Approve once", busyLabel: "Approving…", ariaLabel: "Approve tool request", variant: "default", disabled: false, onSelect: () => approved++ },
      ]}
      approval={approvalView()}
      eyebrow="Command permission"
      hint="Review this exact request before continuing."
    />
  );
  assert.match(host.textContent ?? "", /pytest -q/);
  const approve = host.querySelector('[aria-label="Approve tool request"]') as HTMLButtonElement;
  await act(async () => approve.click());
  assert.equal(approved, 1);
  assert.equal(host.querySelector('[data-testid="approval-card"]')?.getAttribute("data-risk"), "command");
});

test("ApprovalCard body replaces the summary; details follow it; busy action shows its busy label", async () => {
  const host = await renderComponent(
    <ApprovalCard
      actions={[{ id: "approve", label: "Approve once", busyLabel: "Approving…", ariaLabel: "Approve tool request", variant: "default", disabled: true, onSelect: () => {} }]}
      approval={approvalView()}
      body={<p>질문 본문</p>}
      busyActionId="approve"
      details={<p>계획 본문</p>}
      error="실패했다"
      eyebrow="Workspace permission"
      hint=""
    />
  );
  const text = host.textContent ?? "";
  assert.doesNotMatch(text, /pytest -q/);
  assert.ok(text.indexOf("질문 본문") < text.indexOf("계획 본문"));
  assert.match(text, /Approving…/);
  assert.equal(host.querySelector('[role="alert"]')?.textContent, "실패했다");
});

test("StepTimeline renders steps, their items and depth-1 children only", async () => {
  const grandchild: TraceStep = { id: "g", label: "손주", status: "running", items: [] };
  const steps: TraceStep[] = [
    {
      id: "s1",
      label: "구현",
      status: "running",
      startedAt: "2026-10-11T00:00:00Z",
      endedAt: "2026-10-11T00:01:05Z",
      items: [
        { kind: "tool", call: { id: "t1", name: "read_file.v1", status: "succeeded" } },
        { kind: "note", text: "파서를 읽는 중" },
        { kind: "question", question: { id: "q1", prompt: "어느 러너?", status: "open" } },
      ],
      children: [{ id: "c1", label: "explore", status: "succeeded", items: [], children: [grandchild] }],
    },
  ];
  const host = await renderComponent(<StepTimeline steps={steps} />);
  const text = host.textContent ?? "";
  assert.match(text, /구현/);
  assert.match(text, /1분 5초/);
  assert.match(text, /read_file\.v1/);
  assert.match(text, /파서를 읽는 중/);
  assert.match(text, /어느 러너\?/);
  assert.match(text, /explore/);
  assert.doesNotMatch(text, /손주/);
  assert.equal(host.querySelector("ol")?.getAttribute("aria-label"), "작업 단계");
});

test("StepTimeline ignores an item kind it does not know", async () => {
  const unknown = { kind: "hologram", payload: 1 } as unknown as TraceItem;
  const host = await renderComponent(
    <StepTimeline steps={[{ id: "s", label: "단계", status: "queued", items: [unknown] }]} />
  );
  assert.match(host.textContent ?? "", /단계/);
});
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd web && pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/trace-primitives.test.tsx`
Expected: 새 테스트 FAIL — 모듈 없음

- [ ] **Step 3: `web/components/trace/claim-evidence.tsx`**

```tsx
"use client";

import {
  InlineCitation,
  InlineCitationCard,
  InlineCitationCardBody,
  InlineCitationCardTrigger,
  InlineCitationQuote,
  InlineCitationSource,
  InlineCitationText,
} from "@/components/elements/inline-citation";
import { commonCopy } from "@/lib/copy/common";
import { cn } from "@/lib/utils";
import type { ClaimView } from "./types";
import { VerdictBadge } from "./verdict-badge";

const STATUS_TEXT: Record<ClaimView["status"], string> = {
  verified: "text-evidence-verified",
  unverified: "text-evidence-unverified",
  rejected: "text-evidence-rejected",
};

function validUrls(claim: ClaimView): string[] {
  // InlineCitationCardTrigger 는 new URL() 을 부른다 — 깨진 URL 하나가 카드 전체를 죽이지 않게 거른다.
  return claim.sources.flatMap((source) => {
    try {
      return [new URL(source.url).toString()];
    } catch {
      return [];
    }
  });
}

export function ClaimEvidence({ claim }: { claim: ClaimView }) {
  const urls = validUrls(claim);
  return (
    <div className="space-y-1" data-status={claim.status} data-testid="claim-evidence">
      <InlineCitation>
        <InlineCitationText>{claim.text}</InlineCitationText>
        {urls.length ? (
          <InlineCitationCard>
            <InlineCitationCardTrigger sources={urls} />
            <InlineCitationCardBody>
              <div className="space-y-3 p-4">
                {claim.sources.map((source) => (
                  <InlineCitationSource key={source.url} title={source.title} url={source.url}>
                    {source.excerpt ? <InlineCitationQuote>{source.excerpt}</InlineCitationQuote> : null}
                  </InlineCitationSource>
                ))}
              </div>
            </InlineCitationCardBody>
          </InlineCitationCard>
        ) : (
          <span className="ml-1 text-caption text-muted-foreground">{commonCopy.trace.noSources}</span>
        )}
      </InlineCitation>
      <p className={cn("text-caption", STATUS_TEXT[claim.status])}>{commonCopy.evidence[claim.status]}</p>
      {/* 호버 카드는 닫혀 있으면 DOM 에 없다 — 발췌를 접근 가능한 목록으로도 둔다 */}
      {claim.sources.length ? (
        <ul aria-label={commonCopy.trace.sources} className="sr-only">
          {claim.sources.map((source) => (
            <li key={source.url}>
              {source.title ?? source.url} {new URL(source.url, "https://invalid.local").hostname}
              {source.excerpt ? ` — ${source.excerpt}` : ""}
            </li>
          ))}
        </ul>
      ) : null}
      {claim.verdict ? <VerdictBadge verdict={claim.verdict} /> : null}
    </div>
  );
}
```

- [ ] **Step 4: `web/components/trace/approval-card.tsx`**

```tsx
"use client";

import { Clock3, ShieldAlert, Terminal } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { ApprovalView } from "./types";
import { VerdictBadge } from "./verdict-badge";

export type ApprovalAction = {
  id: string;
  label: string;
  busyLabel: string;
  ariaLabel: string;
  variant: "default" | "outline";
  disabled: boolean;
  onSelect: () => void;
};

// 승인 요청의 틀. 행동(무엇을 보낼지)과 문구는 호출자가 쥔다 — 코딩 래퍼가
// 승인 API · 질문 답 · 계획 본문을 body/details 로 넣는다(spec §5.4).
export function ApprovalCard({
  approval,
  eyebrow,
  hint,
  warnings = [],
  actions,
  busyActionId = null,
  error = null,
  body,
  details,
}: {
  approval: ApprovalView;
  eyebrow: string;
  hint: string;
  warnings?: string[];
  actions: ApprovalAction[];
  busyActionId?: string | null;
  error?: string | null;
  body?: ReactNode;
  details?: ReactNode;
}) {
  const command = approval.risk === "command";
  return (
    <article
      className={cn(
        "border-l-2 bg-card/55 p-4",
        command ? "border-l-status-danger" : "border-l-status-waiting"
      )}
      data-risk={approval.risk}
      data-status={approval.status}
      data-testid="approval-card"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 gap-3">
          <span className="mt-0.5 border border-border/80 bg-background/70 p-2">
            {command ? (
              <Terminal className="size-4 text-status-danger" />
            ) : (
              <ShieldAlert className="size-4 text-status-waiting" />
            )}
          </span>
          <div className="min-w-0">
            <p className="font-mono text-[10px] text-muted-foreground uppercase tracking-[0.18em]">{eyebrow}</p>
            <h2 className="mt-1 truncate font-mono text-sm">{approval.toolName}</h2>
          </div>
        </div>
        {approval.expiresAt ? (
          <span className="flex shrink-0 items-center gap-1 font-mono text-[10px] text-muted-foreground">
            <Clock3 className="size-3" />
            {new Date(approval.expiresAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </span>
        ) : null}
      </div>

      {warnings.length > 0 ? (
        <ul className="mt-3 space-y-1 border border-status-danger/40 bg-status-danger/10 px-3 py-2">
          {warnings.map((warning) => (
            <li className="font-mono text-[11px] text-status-danger" key={warning}>
              {warning.replaceAll("_", " ")}
            </li>
          ))}
        </ul>
      ) : null}

      {body ??
        (approval.summary.length ? (
          <dl className="mt-4 grid gap-px border border-border/60 bg-border/60 sm:grid-cols-2">
            {approval.summary.map(({ label, value }) => (
              <div className="bg-background/90 px-3 py-2" key={label}>
                <dt className="font-mono text-[9px] text-muted-foreground uppercase tracking-wider">{label}</dt>
                <dd className="mt-1 truncate font-mono text-xs" title={value}>
                  {value}
                </dd>
              </div>
            ))}
          </dl>
        ) : null)}

      {details}

      {approval.verdict ? (
        <div className="mt-3">
          <VerdictBadge verdict={approval.verdict} />
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-[11px] text-muted-foreground">{hint}</p>
        <div className="flex gap-2">
          {actions.map((action) => (
            <Button
              aria-label={action.ariaLabel}
              disabled={action.disabled}
              key={action.id}
              onClick={action.onSelect}
              size="sm"
              type="button"
              variant={action.variant}
            >
              {busyActionId === action.id ? action.busyLabel : action.label}
            </Button>
          ))}
        </div>
      </div>
      {error ? (
        <p className="mt-3 text-destructive text-xs" role="alert">
          {error}
        </p>
      ) : null}
    </article>
  );
}
```

- [ ] **Step 5: `web/components/trace/step-timeline.tsx`**

```tsx
"use client";

import { MessageCircleQuestion } from "lucide-react";
import { commonCopy } from "@/lib/copy/common";
import { ApprovalCard } from "./approval-card";
import { ClaimEvidence } from "./claim-evidence";
import { RunStatus } from "./run-status";
import { ToolActivity } from "./tool-activity";
import type { TraceItem, TraceStep } from "./types";
import { VerdictBadge } from "./verdict-badge";

function durationSeconds(step: TraceStep): number | null {
  if (!step.startedAt || !step.endedAt) return null;
  const ms = Date.parse(step.endedAt) - Date.parse(step.startedAt);
  return Number.isFinite(ms) && ms >= 0 ? Math.round(ms / 1000) : null;
}

function warnInDevelopment(message: string, value: unknown) {
  if (process.env.NODE_ENV === "development") console.warn(message, value);
}

export function TraceItemView({ item }: { item: TraceItem }) {
  switch (item.kind) {
    case "tool":
      return <ToolActivity call={item.call} />;
    case "verdict":
      return <VerdictBadge verdict={item.verdict} />;
    case "evidence":
      return <ClaimEvidence claim={item.claim} />;
    case "approval":
      // 타임라인 안에서는 읽기 전용이다 — 결정은 작업 화면의 래퍼가 한다.
      return <ApprovalCard actions={[]} approval={item.approval} eyebrow={item.approval.risk} hint="" />;
    case "question":
      return (
        <p className="flex items-center gap-2 text-body-sm">
          <MessageCircleQuestion aria-hidden className="size-4 text-status-waiting" />
          <span>{item.question.prompt}</span>
          <span className="text-caption text-muted-foreground">{commonCopy.question[item.question.status]}</span>
        </p>
      );
    case "note":
      return <p className="text-body-sm text-muted-foreground">{item.text}</p>;
    default:
      warnInDevelopment("StepTimeline: unknown trace item kind", item);
      return null;
  }
}

function StepRow({ step, depth }: { step: TraceStep; depth: 0 | 1 }) {
  const seconds = durationSeconds(step);
  if (depth === 1 && step.children?.length) {
    warnInDevelopment("StepTimeline: children deeper than depth-1 are not drawn", step.id);
  }
  return (
    <li className="space-y-2" data-status={step.status} data-testid="trace-step">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-body">{step.label}</span>
        <RunStatus status={step.status} />
        {seconds !== null ? (
          <span className="text-caption text-muted-foreground">{commonCopy.trace.duration(seconds)}</span>
        ) : null}
      </div>
      {step.items.length ? (
        <div className="space-y-2">
          {step.items.map((item, index) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: 항목은 단계 안에서 순서로만 구별된다
            <TraceItemView item={item} key={`${step.id}:${index}`} />
          ))}
        </div>
      ) : null}
      {depth === 0 && step.children?.length ? (
        <ol className="ml-3 space-y-3 border-border/70 border-l pl-4">
          {step.children.map((child) => (
            <StepRow depth={1} key={child.id} step={child} />
          ))}
        </ol>
      ) : null}
    </li>
  );
}

export function StepTimeline({ steps }: { steps: TraceStep[] }) {
  return (
    <ol aria-label={commonCopy.trace.timelineLabel} className="space-y-4">
      {steps.map((step) => (
        <StepRow depth={0} key={step.id} step={step} />
      ))}
    </ol>
  );
}
```

> `ClaimEvidence` 의 `sr-only` 목록이 `new URL(source.url, "https://invalid.local")` 를 쓰는 이유: 상대 · 깨진 URL 에서도 던지지 않는다.
> `pnpm lint` 가 `biome-ignore` 주석의 규칙 이름을 다르게 원하면 그 출력이 정본이다 — 이름만 맞춘다.

- [ ] **Step 6: 통과를 확인하고 커밋한다**

Run: `cd web && pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/trace-primitives.test.tsx && pnpm typecheck && pnpm lint`
Expected: PASS

```bash
git add components/trace/claim-evidence.tsx components/trace/approval-card.tsx components/trace/step-timeline.tsx tests/source/trace-primitives.test.tsx
git commit -m "feat(web): ClaimEvidence, ApprovalCard and StepTimeline trace primitives"
```

---

### Task 8: 코딩 어댑터와 승인 카드 · Jev 배지 이식

**Files:**
- Create: `web/features/coding/trace.ts`, `web/lib/copy/code.ts`
- Modify: `web/features/coding/components/coding-approval-card.tsx` (컴포넌트 본문 — 헬퍼 함수들은 그대로)
- Modify: `web/features/coding/components/coding-detail-panel.tsx` (`ToolRiskLine`)
- Test: `web/tests/source/coding-trace-adapter.test.ts`

**Interfaces:**
- Consumes: Task 5~7 의 타입 · 프리미티브, `tool-risk.ts` 의 `toolRiskBadge` · `toolRiskMode` · `describeToolRisk`(바꾸지 않는다), `projection.ts` 타입
- Produces:
  - `verdictFromToolRisk(risk: CodingToolRiskView): VerdictView`
  - `approvalFromCoding(approval: CodingApprovalView, options?: { hiddenKeys?: ReadonlySet<string>; risk?: CodingToolRiskView }): ApprovalView`
  - `toolActivityFromCoding(tool: CodingToolView): ToolActivityView`
  - `stepsFromCoding(state: CodingProjectionState): TraceStep[]`
  - `codeCopy.approval` — 지금 영문 값 그대로

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `web/tests/source/coding-trace-adapter.test.ts`

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { describeToolRisk, toolRiskBadge } from "@/features/coding/components/tool-risk";
import { emptyProjection } from "@/features/coding/stream/projection-reducer";
import {
  approvalFromCoding,
  stepsFromCoding,
  toolActivityFromCoding,
  verdictFromToolRisk,
} from "@/features/coding/trace";
import type { CodingApprovalView, CodingToolRiskView } from "@/features/coding/types/projection";

type Scored = Extract<CodingToolRiskView, { kind: "scored" }>;
const scored = (overrides: Partial<Scored> = {}): Scored => ({
  kind: "scored",
  tool_call_id: "t1",
  seq: 3,
  tool: "execute.v1",
  probability: 0.623,
  band: "mid",
  low_below: 0.3,
  high_at_or_above: 0.8,
  static_outcome: "allow",
  would_be_outcome: "require_approval",
  banded_outcome: "require_approval",
  unattended: false,
  enforced: false,
  rubric_digest: "f5faf377",
  model: "jev-1.13.0",
  driver: null,
  questions: [],
  ...overrides,
});

test("the verdict's badge and sentence are the tool-risk functions' own output", () => {
  const risk = scored();
  const verdict = verdictFromToolRisk(risk);
  assert.equal(verdict.badge, toolRiskBadge(risk));
  assert.equal(verdict.sentence, describeToolRisk(risk));
  assert.equal(verdict.mode, "shadow");
  assert.equal(verdict.band, "mid");
  assert.equal(verdict.probability, 0.623);
});

test("a band Jev has not shipped yet stays visible but neutral (review focus 2)", () => {
  const verdict = verdictFromToolRisk(scored({ band: "extreme" }));
  assert.equal(verdict.band, "unavailable");
  assert.match(verdict.badge, /extreme/);
});

test("a WAF block is its own band; other unavailability is neutral", () => {
  const unavailable = (blocked: boolean): CodingToolRiskView => ({
    kind: "unavailable",
    tool_call_id: "t1",
    seq: 1,
    tool: "execute.v1",
    reason: "timeout",
    static_outcome: "allow",
    enforced: true,
    unattended: false,
    blocked,
    would_be_outcome: "deny",
  });
  assert.equal(verdictFromToolRisk(unavailable(true)).band, "blocked");
  assert.equal(verdictFromToolRisk(unavailable(false)).band, "unavailable");
  assert.equal(verdictFromToolRisk(unavailable(true)).mode, "enforced");
});

test("approval summary hides the given keys and humanizes labels", () => {
  const approval: CodingApprovalView = {
    approval_id: "ca_1",
    tool_name: "write_file.v1",
    risk: "workspace_write",
    status: "pending",
    requested_at: "2026-10-11T00:00:00Z",
    expires_at: "2026-10-11T00:15:00Z",
    display_summary: { file_path: "app.py", warnings: ["protected_file"], bytes: 12 },
  };
  const view = approvalFromCoding(approval, { hiddenKeys: new Set(["warnings"]) });
  assert.deepEqual(view.summary, [
    { label: "file path", value: "app.py" },
    { label: "bytes", value: "12" },
  ]);
  assert.equal(view.expiresAt, "2026-10-11T00:15:00Z");
  assert.equal(view.verdict, undefined);
});

test("tool status maps to trace status; a denial carries its reason", () => {
  const base = { tool_call_id: "t1", run_id: "cr_1", result: null, name: "execute.v1" };
  assert.equal(toolActivityFromCoding({ ...base, status: "running" }).status, "running");
  assert.equal(toolActivityFromCoding({ ...base, status: "completed" }).status, "succeeded");
  const denied = toolActivityFromCoding({ ...base, status: "denied", reason_code: "jev_gate" });
  assert.equal(denied.status, "failed");
  assert.equal(denied.deniedReason, "jev_gate");
  assert.equal(toolActivityFromCoding({ ...base, status: "mystery" }).status, "queued");
  assert.equal(toolActivityFromCoding({ ...base, name: null, status: "running" }).name, "t1");
});

test("phases become steps holding their run's tools, verdicts and children", () => {
  const state = {
    ...emptyProjection("ct_1"),
    phases: [
      {
        phase_id: "phase:implement:2",
        run_id: "cr_1",
        kind: "implement",
        attempt: 2,
        status: "active",
        started_at: "2026-10-11T00:00:00Z",
        completed_at: null,
      },
    ],
    toolsById: {
      t1: { tool_call_id: "t1", run_id: "cr_1", status: "completed", result: null, name: "execute.v1" },
      t9: { tool_call_id: "t9", run_id: "other", status: "completed", result: null, name: "x" },
    },
    toolRisksById: { t1: scored() },
    childrenById: {
      sa_1: {
        run_id: "sa_1",
        spec: "explore",
        status: "completed",
        turn_count: 2,
        tool_count: 3,
        parent_tool_call_id: "t1",
        end_reason: null,
      },
    },
  };
  const [step] = stepsFromCoding(state);
  assert.equal(step.label, "implement #2");
  assert.equal(step.status, "running");
  assert.deepEqual(
    step.items.map((item) => item.kind),
    ["tool", "verdict"]
  );
  assert.equal(step.children?.[0]?.label, "explore");
  assert.equal(step.children?.[0]?.status, "succeeded");
});
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd web && pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/coding-trace-adapter.test.ts`
Expected: FAIL — `Cannot find module '@/features/coding/trace'`

- [ ] **Step 3: `web/features/coding/trace.ts`**

```ts
// 코딩 투영 → 작업 흔적 표시 모델 (spec §5.4). 순수 함수이고 새 상태를 만들지 않는다.
// 판정 문장의 정본은 계속 tool-risk.ts 다 — 여기는 그 출력을 옮겨 담기만 한다.
import type {
  ApprovalView,
  ToolActivityView,
  TraceItem,
  TraceStatus,
  TraceStep,
  VerdictView,
} from "@/components/trace/types";
import { describeToolRisk, toolRiskBadge, toolRiskMode } from "@/features/coding/components/tool-risk";
import type {
  CodingApprovalView,
  CodingChildView,
  CodingProjectionState,
  CodingToolRiskView,
  CodingToolView,
} from "@/features/coding/types/projection";

const KNOWN_BANDS: ReadonlySet<string> = new Set(["low", "mid", "high"]);

export function verdictFromToolRisk(risk: CodingToolRiskView): VerdictView {
  const band: VerdictView["band"] =
    risk.kind === "unavailable"
      ? risk.blocked
        ? "blocked"
        : "unavailable"
      : KNOWN_BANDS.has(risk.band)
        ? (risk.band as "low" | "mid" | "high")
        : // 모르는 band 는 원문 배지로 보이고 색만 중립이다 — "low" 로 읽히면 안 된다.
          "unavailable";
  return {
    band,
    probability: risk.kind === "scored" ? risk.probability : undefined,
    mode: toolRiskMode(risk),
    badge: toolRiskBadge(risk),
    sentence: describeToolRisk(risk),
  };
}

export function approvalFromCoding(
  approval: CodingApprovalView,
  options: { hiddenKeys?: ReadonlySet<string>; risk?: CodingToolRiskView } = {}
): ApprovalView {
  const hidden = options.hiddenKeys ?? new Set<string>();
  return {
    id: approval.approval_id,
    toolName: approval.tool_name,
    risk: approval.risk,
    status: approval.status,
    summary: Object.entries(approval.display_summary)
      .filter(([key]) => !hidden.has(key))
      .map(([key, value]) => ({ label: key.replaceAll("_", " "), value: String(value) })),
    expiresAt: approval.expires_at,
    verdict: options.risk ? verdictFromToolRisk(options.risk) : undefined,
  };
}

// 리듀서가 쓰는 도구 상태: started→running, 그 밖은 tool.<x> 의 x (completed · denied …).
const TOOL_STATUS: Record<string, TraceStatus> = {
  running: "running",
  completed: "succeeded",
  denied: "failed",
  failed: "failed",
};

export function toolActivityFromCoding(tool: CodingToolView): ToolActivityView {
  return {
    id: tool.tool_call_id,
    name: tool.name ?? tool.tool_call_id,
    status: TOOL_STATUS[tool.status] ?? "queued",
    preview: tool.preview ?? undefined,
    deniedReason: tool.status === "denied" ? (tool.reason_code ?? tool.denied_by ?? tool.status) : undefined,
  };
}

const PHASE_STATUS: Record<string, TraceStatus> = {
  active: "running",
  completed: "succeeded",
  failed: "failed",
  blocked: "waiting",
};

const CHILD_STATUS: Record<string, TraceStatus> = {
  started: "running",
  running: "running",
  active: "running",
  completed: "succeeded",
  failed: "failed",
  cancelled: "cancelled",
};

function childStep(child: CodingChildView): TraceStep {
  return {
    id: child.run_id,
    label: child.spec ?? child.run_id,
    status: (child.status && CHILD_STATUS[child.status]) || "queued",
    items: child.end_reason ? [{ kind: "note", text: child.end_reason }] : [],
  };
}

export function stepsFromCoding(state: CodingProjectionState): TraceStep[] {
  const tools = Object.values(state.toolsById);
  const children = Object.values(state.childrenById);
  return state.phases.map((phase) => {
    const phaseTools = tools.filter((tool) => tool.run_id === phase.run_id);
    const toolIds = new Set(phaseTools.map((tool) => tool.tool_call_id));
    const items: TraceItem[] = phaseTools.flatMap((tool): TraceItem[] => {
      const risk = state.toolRisksById[tool.tool_call_id];
      const call: TraceItem = { kind: "tool", call: toolActivityFromCoding(tool) };
      return risk ? [call, { kind: "verdict", verdict: verdictFromToolRisk(risk) }] : [call];
    });
    const phaseChildren = children
      .filter((child) => child.parent_tool_call_id !== null && toolIds.has(child.parent_tool_call_id))
      .map(childStep);
    return {
      id: phase.phase_id,
      label: phase.attempt > 1 ? `${phase.kind} #${phase.attempt}` : phase.kind,
      status: PHASE_STATUS[phase.status] ?? "queued",
      startedAt: phase.started_at,
      endedAt: phase.completed_at ?? undefined,
      items,
      children: phaseChildren.length ? phaseChildren : undefined,
    };
  });
}
```

- [ ] **Step 4: 어댑터 테스트 통과를 확인한다**

Run: `cd web && pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/coding-trace-adapter.test.ts`
Expected: PASS

- [ ] **Step 5: `web/lib/copy/code.ts`** — 지금의 영문 값을 옮긴다(spec §3.4: 번역은 5단계)

```ts
// /code 문구 사전 (spec §3.4). 1단계는 이식한 승인 카드 문구만 옮기고 값은 영문 그대로다 —
// 코딩 소스 테스트가 aria-label 을 고정한다. 번역은 5단계에서 테스트와 함께.
export const codeCopy = {
  approval: {
    eyebrowCommand: "Command permission",
    eyebrowWorkspace: "Workspace permission",
    hintLive: "Review this exact request before continuing.",
    hintOffline: "Reconnect to decide.",
    deny: { label: "Deny", busy: "Denying…", aria: "Deny tool request" },
    approveForRun: { label: "Approve for this run", busy: "Approving…", aria: "Approve tool for this run" },
    approveOnce: { label: "Approve once", busy: "Approving…", aria: "Approve tool request" },
    failed: "승인 요청을 처리하지 못했습니다.",
  },
} as const;
```

- [ ] **Step 6: `CodingApprovalCard` 를 `ApprovalCard` 위로 옮긴다**

`coding-approval-card.tsx` 의 import 를 바꾼다:

```tsx
import { useState } from "react";
import { type ApprovalAction, ApprovalCard } from "@/components/trace/approval-card";
import { decideCodingApproval } from "@/features/coding/api/coding-api";
import { approvalFromCoding } from "@/features/coding/trace";
import type { CodingApprovalView } from "@/features/coding/types/projection";
import { codeCopy } from "@/lib/copy/code";
```

(`Clock3, ShieldAlert, Terminal` 와 `Button` import 는 지운다.) `CodingApprovalCard` 함수에서 `decide` 정의까지는 그대로 두고, `catch` 의 기본 문구를 `codeCopy.approval.failed` 로 바꾼다. `return ( <article …> … </article> );` 전체를 아래로 바꾼다. 질문 입력 마크업(`questions.map(...)` 블록)과 계획 본문 마크업(`planBody ? … : null`)은 **원래 JSX 를 그대로** `questionBody`·`planDetails` 로 옮긴다:

```tsx
  const copy = codeCopy.approval;
  const actions: ApprovalAction[] = [
    {
      id: "deny",
      label: copy.deny.label,
      busyLabel: copy.deny.busy,
      ariaLabel: copy.deny.aria,
      variant: "outline",
      disabled,
      onSelect: () => decide("deny"),
    },
    ...(workspaceWrite
      ? [
          {
            id: "remember",
            label: copy.approveForRun.label,
            busyLabel: copy.approveForRun.busy,
            ariaLabel: copy.approveForRun.aria,
            variant: "outline" as const,
            disabled: approveDisabled,
            onSelect: () => decide("approve", true),
          },
        ]
      : []),
    {
      id: "approve",
      label: copy.approveOnce.label,
      busyLabel: copy.approveOnce.busy,
      ariaLabel: copy.approveOnce.aria,
      variant: "default",
      disabled: approveDisabled,
      onSelect: () => decide("approve"),
    },
  ];

  // 원래 `asking ? ( <div className="mt-4 space-y-2"> {questions.map(...)} </div> )` 의 div 를 그대로 둔다.
  const questionBody = asking ? (
    <div className="mt-4 space-y-2">{/* ← 원래 questions.map((question, index) => { … }) 블록을 글자 그대로 옮긴다 */}</div>
  ) : undefined;

  // 원래 `{planBody ? ( <div className="mt-4 space-y-2"> … </div> ) : null}` 를 그대로 둔다.
  const planDetails = planBody ? (
    <div className="mt-4 space-y-2">{/* ← 원래 preview · plan · criticalFiles 세 블록을 글자 그대로 옮긴다 */}</div>
  ) : null;

  return (
    <ApprovalCard
      actions={actions}
      approval={approvalFromCoding(approval, { hiddenKeys: hiddenSummaryKeys(planBody) })}
      body={questionBody}
      busyActionId={submitting}
      details={planDetails}
      error={error}
      eyebrow={command ? copy.eyebrowCommand : copy.eyebrowWorkspace}
      hint={live ? copy.hintLive : copy.hintOffline}
      warnings={warnings}
    />
  );
```

> 이 단계는 **옮기기만** 한다. 질문 · 계획 블록 안의 클래스는 Task 4 에서 이미 토큰으로 바뀌어 있다. `submitting` 의 값(`"approve" | "deny" | "remember"`)이 action id 와 같아 `busyActionId` 로 그대로 쓴다.

- [ ] **Step 7: `ToolRiskLine` 이 `VerdictBadge` 를 쓰게 한다** — `coding-detail-panel.tsx`

import 의 `describeToolRisk, toolRiskBadge, toolRiskMode` 를 지우고 더한다:

```tsx
import { VerdictBadge } from "@/components/trace/verdict-badge";
import { verdictFromToolRisk } from "@/features/coding/trace";
```

`function ToolRiskLine(…) { … }` 전체를 바꾼다:

```tsx
function ToolRiskLine({ risk }: { risk: CodingToolRiskView }) {
  return (
    <div className="mt-1" data-testid="coding-tool-risk">
      <VerdictBadge verdict={verdictFromToolRisk(risk)} />
    </div>
  );
}
```

- [ ] **Step 8: 코딩 소스 테스트 전부를 돌린다 — 고치지 않고 초록이어야 한다**

Run: `cd web && pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/coding-*.test.ts tests/source/coding-*.test.tsx tests/source/coding-trace-adapter.test.ts && pnpm typecheck && pnpm lint`
Expected: PASS 전체(`coding-approval-card.test.tsx` 의 aria-label · 문구, `coding-run-signals.test.tsx` 의 `jev 0.62 · mid` · `shadow`, `coding-tool-risk.test.ts` 가 그대로 초록). 하나라도 빨개지면 테스트가 아니라 이식을 고친다.

- [ ] **Step 9: 커밋한다**

```bash
git add features/coding/trace.ts lib/copy/code.ts features/coding/components/coding-approval-card.tsx features/coding/components/coding-detail-panel.tsx tests/source/coding-trace-adapter.test.ts
git commit -m "refactor(coding): draw the approval card and Jev line with the shared trace primitives

Coding source tests pass unchanged; tool-risk.ts stays the verdict sentence's source."
```

---

### Task 9: FE 표면 인벤토리

**Files:**
- Create: `tests/fixtures/fe_surface_inventory.json`
- Create: `tests/api/test_fe_surface_inventory.py`
- Create: `web/tests/source/fe-surface-inventory.test.ts`

**Interfaces:**
- Produces: 인벤토리 형식 `{ "$comment": string[], "tags": Array<{ "tag": string } & ({ "surface": { "routes": string[], "files": string[] } } | { "reason": string })> }` — `routes` 는 Next 라우트(`/chat/[id]`), `files` 는 `web/` 기준 경로

- [ ] **Step 1: BE 테스트를 먼저 쓴다** — `tests/api/test_fe_surface_inventory.py`

```python
"""FE 표면 인벤토리가 BE 의 라우터 태그 집합과 정확히 일치하는가.

## 왜 이 테스트가 생겼나

트랙 Q 설계 문서들이 각자 "FE 작업 불필요" 를 그 자리에 맞게 내렸고, 쌓여서
엔드포인트 약 30개가 웹에서 보이지 않게 됐다(2026-10-11 진단,
docs/superpowers/specs/2026-10-11-frontend-evolution-foundation-design.md §1.3).
이벤트 fixture 는 "처리하는가" 만 묻는다 -- 이것은 "보이는가, 아니면 왜 안 보이는가" 를 묻는다.

## 왜 런타임 순회가 아니라 AST 스캔인가

마운트가 설정에 따라 달라진다. 2026-10-11 실측에서 `Coding Approval Rules` 는
마운트되지 않았고 상시 에이전트 태그는 개발 프로파일이 켜서 보였다. 런타임으로
읽으면 이 테스트의 답이 프로파일마다 바뀐다. `test_chat_stream_event_types.py` 와
같은 방식으로 리터럴 `tags` 를 모은다.
"""

from __future__ import annotations

import ast
import json
import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
FIXTURE_PATH = _REPO_ROOT / "tests" / "fixtures" / "fe_surface_inventory.json"
_CALLS = {"APIRouter", "include_router", "_include_router_for_runtime"}


def _scanned_files() -> list[pathlib.Path]:
    return [_REPO_ROOT / "neos" / "main.py", *sorted((_REPO_ROOT / "neos" / "api").rglob("*.py"))]


def _backend_tags() -> set[str]:
    tags: set[str] = set()
    for path in _scanned_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name not in _CALLS:
                continue
            for keyword in node.keywords:
                if keyword.arg != "tags":
                    continue
                assert isinstance(keyword.value, (ast.List, ast.Tuple)), (
                    f"{path}:{node.lineno} tags 가 리터럴 목록이 아니다 -- 이 스캔이 못 읽는다"
                )
                for element in keyword.value.elts:
                    assert isinstance(element, ast.Constant) and isinstance(element.value, str), (
                        f"{path}:{node.lineno} 리터럴 문자열이 아닌 태그"
                    )
                    tags.add(element.value)
    return tags


def _inventory() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text())["tags"]


def test_scan_sees_included_and_websocket_routers():
    # 스캔이 공허하지 않은지 먼저 본다 -- 이웃 태그가 보여야 나머지 비교가 의미 있다.
    tags = _backend_tags()
    assert "Coding Agent" in tags
    assert "Coding Agent WebSocket" in tags
    assert "Chat & Conversations" in tags  # main.py 의 _include_router_for_runtime 에서만 온다


def test_inventory_matches_backend_tags_exactly():
    listed = [entry["tag"] for entry in _inventory()]
    assert len(listed) == len(set(listed)), "인벤토리에 같은 태그가 두 번 있다"
    backend = _backend_tags()
    assert sorted(backend - set(listed)) == [], "인벤토리에 없는 BE 태그 -- surface 나 reason 을 적는다"
    assert sorted(set(listed) - backend) == [], "BE 에 없는 인벤토리 태그 -- 지운다"


def test_every_entry_has_exactly_one_of_surface_or_reason():
    for entry in _inventory():
        has_surface = "surface" in entry
        has_reason = "reason" in entry
        assert has_surface != has_reason, entry["tag"]
        if has_reason:
            assert entry["reason"].strip(), entry["tag"]
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run --frozen pytest tests/api/test_fe_surface_inventory.py -q -p no:randomly`
Expected: FAIL — `FileNotFoundError: …fe_surface_inventory.json`. (수집이 DB · 키 문제로 먼저 죽으면 저장소 메모리 "로컬 통합 테스트는 부트스트랩된 DB가 필요하다" 의 조건을 갖춘 뒤 다시 돌린다 — 이 테스트 자체는 DB 를 쓰지 않는다.)

- [ ] **Step 3: 인벤토리를 쓴다** — `tests/fixtures/fe_surface_inventory.json` (2026-10-11 정적 태그 31개)

```json
{
  "$comment": [
    "FE 표면 인벤토리 정본 (spec 2026-10-11-frontend-evolution-foundation-design.md §6.1).",
    "BE 라우터 태그마다 surface(보이는 화면 · 쓰는 BFF 파일) 또는 reason(보이지 않는 이유) 중 정확히 하나.",
    "reason 에 단계가 적힌 항목은 그 단계 spec 이 surface 로 바꿀 책임을 진다.",
    "읽는 곳: tests/api/test_fe_surface_inventory.py (BE 태그 AST 스캔과 정확히 일치)",
    "        web/tests/source/fe-surface-inventory.test.ts (surface 의 라우트 · 파일 실존)"
  ],
  "tags": [
    { "tag": "A2UI", "surface": { "routes": ["/chat/[id]"], "files": ["app/(chat)/api/ui-submit/route.ts"] } },
    { "tag": "Agent Autonomy", "surface": { "routes": ["/chat/[id]"], "files": ["app/(chat)/api/autonomy-preference/route.ts"] } },
    { "tag": "Artifacts & Documents", "surface": { "routes": ["/chat/[id]"], "files": ["app/(chat)/api/document/route.ts"] } },
    { "tag": "artifacts", "surface": { "routes": ["/chat/[id]"], "files": ["app/(chat)/api/document/route.ts"] } },
    { "tag": "Authentication", "reason": "BFF 내부 사용(NextAuth 가 토큰을 받는다) — 사용자 표면이 아니다" },
    { "tag": "Chat & Conversations", "surface": { "routes": ["/", "/chat/[id]"], "files": ["app/(chat)/api/chat/route.ts", "app/(chat)/api/history/route.ts"] } },
    { "tag": "Coding Agent", "surface": { "routes": ["/code", "/code/tasks/[taskId]"], "files": ["app/(code)/api/coding/tasks/route.ts"] } },
    { "tag": "Coding Agent Admin", "reason": "운영자 API(할당 복구 승인) — 사용자 표면이 아니다" },
    { "tag": "Coding Agent WebSocket", "surface": { "routes": ["/code/tasks/[taskId]"], "files": ["app/(code)/api/coding/tasks/[taskId]/ws-ticket/route.ts"] } },
    { "tag": "Coding Approval Rules", "reason": "4단계(에이전트 · 설정) 예정 — API 만 있다" },
    { "tag": "Coding Device Bridge", "reason": "기기 쪽 브리지 프로세스가 붙는 소켓 — 사용자 표면이 아니다" },
    { "tag": "Coding Device Bridges", "reason": "4단계(설정 · 기기) 예정 — API 만 있다" },
    { "tag": "Coding Secrets", "reason": "4단계(설정 · 비밀) 예정 — API 만 있다" },
    { "tag": "Coding Workspace WebSocket", "surface": { "routes": ["/code/tasks/[taskId]"], "files": ["app/(code)/api/coding/tasks/[taskId]/workspace/[...path]/route.ts"] } },
    { "tag": "Deep Analysis Analytics", "reason": "운영 분석 — 사용자 표면이 아니다" },
    { "tag": "Deep Analysis Harness", "surface": { "routes": ["/chat/[id]"], "files": ["app/(chat)/api/deep-analysis/[runId]/events/route.ts", "app/(chat)/api/deep-analysis/[runId]/resume/route.ts"] } },
    { "tag": "Document Management", "surface": { "routes": ["/chat/[id]"], "files": ["app/(chat)/api/files/upload/route.ts"] } },
    { "tag": "documents", "surface": { "routes": ["/chat/[id]"], "files": ["app/(chat)/api/document/route.ts", "app/(chat)/api/files/upload/route.ts"] } },
    { "tag": "Execution Approval", "surface": { "routes": ["/chat/[id]"], "files": ["app/(chat)/api/approval/respond/route.ts", "app/(chat)/api/approval/stream/[sessionId]/route.ts"] } },
    { "tag": "Model Preferences", "surface": { "routes": ["/chat/[id]"], "files": ["app/(chat)/api/model-preferences/route.ts"] } },
    { "tag": "Models", "surface": { "routes": ["/", "/chat/[id]"], "files": ["lib/ai/catalog.ts"] } },
    { "tag": "Multi-Agent AI", "reason": "헬스 · 디버그 전용 라우트 — 비디버그에서 WS 가 제거된다(main.py _include_router_for_runtime)" },
    { "tag": "Scheduled Tasks", "reason": "4단계 후보 — 상시 에이전트 트리거와 합칠지 4단계 spec 이 정한다" },
    { "tag": "Skills Management", "reason": "사용자 노출 여부 미정 — 4단계 spec 이 정한다" },
    { "tag": "Standing Agent Questions", "reason": "4단계(에이전트) 예정 — 사용자가 등록하는 cron 상시 질문(Q3). 에이전트가 사람에게 묻는 질문(Q9)이 아니다" },
    { "tag": "Standing Agent Threads", "surface": { "routes": ["/chat/[id]"], "files": ["app/(chat)/api/standing-agent/conversation/route.ts"] } },
    { "tag": "Standing Agent Triggers", "reason": "4단계(에이전트) 예정 — API 만 있다" },
    { "tag": "Standing Agents", "reason": "4단계(에이전트) 예정 — 관리 화면이 없다. 1단계는 대화 BFF 의 /me 와 인박스의 목록 읽기만 쓴다" },
    { "tag": "Votes & Feedback", "surface": { "routes": ["/chat/[id]"], "files": ["app/(chat)/api/vote/route.ts"] } },
    { "tag": "votes", "surface": { "routes": ["/chat/[id]"], "files": ["app/(chat)/api/vote/route.ts"] } },
    { "tag": "Web Search Analytics", "reason": "운영 분석 — 사용자 표면이 아니다" }
  ]
}
```

- [ ] **Step 4: BE 테스트 통과를 확인한다**

Run: `uv run --frozen pytest tests/api/test_fe_surface_inventory.py -q -p no:randomly && uv run --frozen ruff check tests/api/test_fe_surface_inventory.py`
Expected: 3 passed · ruff 경고 0. `test_inventory_matches_backend_tags_exactly` 가 차이를 찍으면, 그 사이 BE 에 태그가 생기거나 사라진 것이다 — 차이를 인벤토리에 반영한다(이름을 지어내지 않는다).

- [ ] **Step 5: FE 테스트를 쓴다** — `web/tests/source/fe-surface-inventory.test.ts`

```ts
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import test from "node:test";

type Entry = { tag: string; surface?: { routes: string[]; files: string[] }; reason?: string };
const inventory: Entry[] = JSON.parse(readFileSync("../tests/fixtures/fe_surface_inventory.json", "utf8")).tags;

function pageRoutes(dir = "app"): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) return pageRoutes(full);
    if (entry !== "page.tsx") return [];
    // 라우트 그룹 "(chat)" 은 URL 에 없다.
    const segments = path.dirname(full).split(path.sep).slice(1).filter((s) => !/^\(.*\)$/.test(s));
    return [`/${segments.join("/")}`];
  });
}

test("every surface route is a real page", () => {
  const routes = new Set(pageRoutes());
  for (const entry of inventory) {
    for (const route of entry.surface?.routes ?? []) {
      assert.ok(routes.has(route), `${entry.tag}: ${route} has no page.tsx (known: ${[...routes].join(", ")})`);
    }
  }
});

test("every surface file exists", () => {
  for (const entry of inventory) {
    for (const file of entry.surface?.files ?? []) {
      assert.ok(existsSync(file), `${entry.tag}: ${file}`);
    }
  }
});

test("each entry has a surface with at least one route, or a reason — never both", () => {
  for (const entry of inventory) {
    assert.notEqual(Boolean(entry.surface), Boolean(entry.reason), entry.tag);
    if (entry.surface) assert.ok(entry.surface.routes.length > 0, entry.tag);
  }
});
```

- [ ] **Step 6: 통과를 확인하고 커밋한다**

Run: `cd web && pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/fe-surface-inventory.test.ts`
Expected: PASS

```bash
git add tests/fixtures/fe_surface_inventory.json tests/api/test_fe_surface_inventory.py web/tests/source/fe-surface-inventory.test.ts
git commit -m "test: pin an FE surface inventory against the backend's router tags"
```

---

### Task 10: 공통 셸 · 공간 내비게이션 · 자리 페이지

**Files:**
- Create: `web/components/shell/app-shell.tsx`, `web/components/shell/spaces.ts`, `web/components/shell/space-placeholder.tsx`, `web/components/shell/open-agent-button.tsx`
- Create: `web/app/(chat)/reports/page.tsx`, `web/app/(chat)/agents/page.tsx`, `web/app/(chat)/settings/page.tsx`
- Modify: `web/app/(chat)/layout.tsx`, `web/app/(code)/layout.tsx`, `web/components/app-sidebar.tsx`
- Modify: `web/lib/copy/common.ts` (`shell` 절 추가)
- Modify: `web/tests/source/coding-shell.test.ts` (라벨 단언 한 줄)
- Test: `web/tests/source/shell.test.ts`

**Interfaces:**
- Consumes: `openAgentConversation()`(`lib/standing-agent-api.ts`), `CodingTaskList`, `SidebarHistory`
- Produces:
  - `type SpaceId = "chat" | "reports" | "code" | "agents" | "settings" | "inbox"`, `SPACES: readonly { id: Exclude<SpaceId, "settings" | "inbox">; href: string }[]`, `spaceForPath(pathname: string): SpaceId`
  - `AppShell({ children })` (서버 컴포넌트), `SpacePlaceholder({ space: "reports" | "agents" | "settings" })`, `OpenAgentButton()`
  - `commonCopy.shell` — `newTask` · `inbox` · `spaces` · `recent` · `settings` · `placeholder` · `agent`

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `web/tests/source/shell.test.ts`

```ts
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { SPACES, spaceForPath } from "@/components/shell/spaces";

test("space detection matches whole segments, not prefixes (review focus 3)", () => {
  assert.equal(spaceForPath("/"), "chat");
  assert.equal(spaceForPath("/chat/abc"), "chat");
  assert.equal(spaceForPath("/code"), "code");
  assert.equal(spaceForPath("/code/tasks/ct_1"), "code");
  assert.equal(spaceForPath("/codex"), "chat");
  assert.equal(spaceForPath("/reports"), "reports");
  assert.equal(spaceForPath("/reports-old"), "chat");
  assert.equal(spaceForPath("/agents/sa_1"), "agents");
  assert.equal(spaceForPath("/settings"), "settings");
  assert.equal(spaceForPath("/inbox"), "inbox");
  assert.equal(spaceForPath(""), "chat");
});

test("the four spaces are navigable in spec order", () => {
  assert.deepEqual(
    SPACES.map((s) => [s.id, s.href]),
    [
      ["chat", "/"],
      ["reports", "/reports"],
      ["code", "/code"],
      ["agents", "/agents"],
    ]
  );
});

test("both route groups share one shell and own no sidebar wiring", () => {
  for (const layout of ["app/(chat)/layout.tsx", "app/(code)/layout.tsx"]) {
    const source = readFileSync(layout, "utf8");
    assert.match(source, /<AppShell>/, layout);
    assert.doesNotMatch(source, /SidebarProvider/, layout);
  }
});

test("placeholder spaces have pages that say when they fill", () => {
  for (const page of ["app/(chat)/reports/page.tsx", "app/(chat)/agents/page.tsx", "app/(chat)/settings/page.tsx"]) {
    assert.match(readFileSync(page, "utf8"), /SpacePlaceholder/, page);
  }
  const copy = readFileSync("lib/copy/common.ts", "utf8");
  assert.match(copy, /3단계/);
  assert.match(copy, /4단계/);
});

test("the sidebar navigates spaces from SPACES and keeps the blue-black hooks", () => {
  const sidebar = readFileSync("components/app-sidebar.tsx", "utf8");
  assert.match(sidebar, /SPACES\.map/);
  assert.match(sidebar, /spaceForPath\(pathname\)/);
  assert.match(sidebar, /href=\{item\.href\}/);
  assert.match(sidebar, /aria-label=\{commonCopy\.shell\.navLabel\}/);
  assert.match(sidebar, /border-sidebar-border\/70/);
  assert.match(sidebar, /NEOS/);
});
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd web && pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/shell.test.ts`
Expected: FAIL — 모듈 없음

- [ ] **Step 3: `web/lib/copy/common.ts` 의 `commonCopy` 객체 안, `trace` 다음에 `shell` 을 더한다**

```ts
  shell: {
    navLabel: "작업 공간",
    newTask: "새 작업",
    inbox: "활동",
    recent: "최근 항목",
    settings: "설정",
    spaces: { chat: "대화", reports: "리포트", code: "코드", agents: "에이전트" },
    placeholder: {
      reports: {
        title: "리포트는 3단계에서 열립니다",
        body: "지금은 대화에서 시작한 심층분석이 그 대화 안에서 진행 상황과 리포트를 보여 줍니다.",
      },
      agents: {
        title: "에이전트 관리는 4단계에서 열립니다",
        body: "트리거 · 예산 · 멈춤 · 활동을 여기서 다루게 됩니다. 지금은 에이전트와의 대화를 열 수 있습니다.",
      },
      settings: {
        title: "설정은 4단계에서 열립니다",
        body: "승인 규칙 · 비밀 · 기기 브리지 · 알림 대상을 여기서 다루게 됩니다.",
      },
    },
    agent: {
      open: "에이전트 대화 열기",
      opening: "여는 중…",
      none: "아직 상시 에이전트가 없습니다.",
      failed: "에이전트 대화를 열지 못했습니다.",
    },
  },
```

- [ ] **Step 4: `web/components/shell/spaces.ts`**

```ts
export type SpaceId = "chat" | "reports" | "code" | "agents" | "settings" | "inbox";

export const SPACES = [
  { id: "chat", href: "/" },
  { id: "reports", href: "/reports" },
  { id: "code", href: "/code" },
  { id: "agents", href: "/agents" },
] as const satisfies readonly { id: Exclude<SpaceId, "settings" | "inbox">; href: string }[];

const FIRST_SEGMENT: Record<string, SpaceId> = {
  code: "code",
  reports: "reports",
  agents: "agents",
  settings: "settings",
  inbox: "inbox",
};

// 첫 세그먼트 전체로 판정한다 — "/codex" 가 코드 공간이 되면 안 된다.
export function spaceForPath(pathname: string): SpaceId {
  const first = pathname.split("/").filter(Boolean)[0] ?? "";
  return FIRST_SEGMENT[first] ?? "chat";
}
```

- [ ] **Step 5: `web/components/shell/app-shell.tsx`**

```tsx
import { cookies } from "next/headers";
import type { ReactNode } from "react";
import { auth } from "@/app/(auth)/auth";
import { AppSidebar } from "@/components/app-sidebar";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";

// 두 라우트 그룹이 같은 셸을 쓴다(spec §4.1). 셸은 사이드바만 소유한다 —
// 본문(코드 독 크기 등)에는 관여하지 않는다.
export async function AppShell({ children }: { children: ReactNode }) {
  const [session, cookieStore] = await Promise.all([auth(), cookies()]);
  const isCollapsed = cookieStore.get("sidebar_state")?.value !== "true";
  return (
    <SidebarProvider defaultOpen={!isCollapsed}>
      <AppSidebar user={session?.user} />
      <SidebarInset>{children}</SidebarInset>
    </SidebarProvider>
  );
}
```

- [ ] **Step 6: 두 레이아웃을 셸 위로 올린다**

`web/app/(chat)/layout.tsx` 전체:

```tsx
import { Suspense } from "react";
import { DataStreamProvider } from "@/components/data-stream-provider";
import { AppShell } from "@/components/shell/app-shell";

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <DataStreamProvider>
      <Suspense fallback={<div className="flex h-dvh" />}>
        <AppShell>{children}</AppShell>
      </Suspense>
    </DataStreamProvider>
  );
}
```

`web/app/(code)/layout.tsx` 전체:

```tsx
import { Suspense } from "react";
import { AppShell } from "@/components/shell/app-shell";

export default function CodeLayout({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={<div className="flex h-dvh" />}>
      <AppShell>{children}</AppShell>
    </Suspense>
  );
}
```

- [ ] **Step 7: 에이전트 열기를 컴포넌트로 뺀다** — `web/components/shell/open-agent-button.tsx` (사이드바의 `handleOpenAgent` 를 옮긴 것)

```tsx
"use client";

import { BotIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { commonCopy } from "@/lib/copy/common";
import { openAgentConversation } from "@/lib/standing-agent-api";

// 트랙 Q8d -- 상시 에이전트와의 웹 대화. 채널(Slack 등) DM 과 같은 맥락을 쓴다.
export function useOpenAgent() {
  const router = useRouter();
  const [opening, setOpening] = useState(false);
  const open = async () => {
    setOpening(true);
    try {
      const conversationId = await openAgentConversation();
      if (conversationId === null) {
        toast.info(commonCopy.shell.agent.none);
        return;
      }
      router.push(`/chat/${conversationId}`);
    } catch (error: unknown) {
      toast.error(error instanceof Error ? error.message : commonCopy.shell.agent.failed);
    } finally {
      setOpening(false);
    }
  };
  return { open, opening };
}

export function OpenAgentButton() {
  const { open, opening } = useOpenAgent();
  return (
    <Button disabled={opening} onClick={open} type="button">
      <BotIcon className="size-4" />
      {opening ? commonCopy.shell.agent.opening : commonCopy.shell.agent.open}
    </Button>
  );
}
```

- [ ] **Step 8: `web/components/shell/space-placeholder.tsx` 와 세 페이지**

```tsx
import type { ReactNode } from "react";
import { commonCopy } from "@/lib/copy/common";

export function SpacePlaceholder({
  space,
  action,
}: {
  space: keyof typeof commonCopy.shell.placeholder;
  action?: ReactNode;
}) {
  const copy = commonCopy.shell.placeholder[space];
  return (
    <main className="mx-auto flex min-h-dvh max-w-2xl flex-col justify-center gap-3 px-6" lang="ko">
      <h1 className="font-semibold text-title">{copy.title}</h1>
      <p className="text-body text-muted-foreground">{copy.body}</p>
      {action ? <div className="pt-2">{action}</div> : null}
    </main>
  );
}
```

`web/app/(chat)/reports/page.tsx`:

```tsx
import { SpacePlaceholder } from "@/components/shell/space-placeholder";

export default function ReportsPage() {
  return <SpacePlaceholder space="reports" />;
}
```

`web/app/(chat)/agents/page.tsx`:

```tsx
import { OpenAgentButton } from "@/components/shell/open-agent-button";
import { SpacePlaceholder } from "@/components/shell/space-placeholder";

export default function AgentsPage() {
  return <SpacePlaceholder action={<OpenAgentButton />} space="agents" />;
}
```

`web/app/(chat)/settings/page.tsx`:

```tsx
import { SpacePlaceholder } from "@/components/shell/space-placeholder";

export default function SettingsPage() {
  return <SpacePlaceholder space="settings" />;
}
```

- [ ] **Step 9: 사이드바를 공간 내비게이션으로 바꾼다** — `web/components/app-sidebar.tsx`

import 를 고친다: `BotIcon, Code2Icon, MessageCircleIcon` → `Code2Icon, FileTextIcon, MessageCircleIcon, BotIcon, SettingsIcon` (lucide-react), `openAgentConversation` import 와 `openingAgent` 상태 · `handleOpenAgent` 함수를 지운다. 더한다:

```tsx
import { SPACES, type SpaceId, spaceForPath } from "@/components/shell/spaces";
import { commonCopy } from "@/lib/copy/common";
import { cn } from "@/lib/utils";

const SPACE_ICONS: Record<(typeof SPACES)[number]["id"], typeof MessageCircleIcon> = {
  chat: MessageCircleIcon,
  reports: FileTextIcon,
  code: Code2Icon,
  agents: BotIcon,
};
```

`const isCode = pathname.startsWith("/code");` → `const space: SpaceId = spaceForPath(pathname);`

`<nav … aria-label="Products">…</nav>` 전체를 바꾼다:

```tsx
          <nav aria-label={commonCopy.shell.navLabel} className="grid gap-1 px-2 pb-3">
            {SPACES.map((item) => {
              const Icon = SPACE_ICONS[item.id];
              return (
                <Link
                  aria-current={space === item.id ? "page" : undefined}
                  className={cn(
                    "flex items-center gap-3 rounded-md px-2 py-2 text-sidebar-foreground text-sm hover:bg-sidebar-accent",
                    space === item.id && "bg-sidebar-accent font-medium"
                  )}
                  href={item.href}
                  key={item.id}
                  onClick={() => setOpenMobile(false)}
                >
                  <Icon className="size-4" />
                  {commonCopy.shell.spaces[item.id]}
                </Link>
              );
            })}
          </nav>
```

그 아래의 `{isCode ? ( … ) : ( <SidebarHistory user={user} /> )}` 를 바꾼다:

```tsx
          {space === "code" ? (
            <div className="px-1 pb-3">
              <p className="px-2 pb-1 font-mono text-[10px] text-primary uppercase tracking-[0.18em]">
                {commonCopy.shell.recent}
              </p>
              <CodingTaskList compact />
            </div>
          ) : space === "chat" ? (
            <SidebarHistory user={user} />
          ) : null}
```

`<SidebarFooter>` 안, `SidebarUserNav` 앞에 설정 링크를 더한다:

```tsx
          <Link
            className="flex items-center gap-3 rounded-md px-2 py-2 text-sidebar-foreground text-sm hover:bg-sidebar-accent"
            href="/settings"
            onClick={() => setOpenMobile(false)}
          >
            <SettingsIcon className="size-4" />
            {commonCopy.shell.settings}
          </Link>
```

(리포트 · 에이전트 · 설정 공간의 "최근 항목" 은 3·4단계가 채운다 — 그 전에는 아무것도 그리지 않는다.)

- [ ] **Step 10: `coding-shell.test.ts` 의 라벨 단언을 고친다**

```ts
test("sidebar exposes separate Chat and Code product navigation", () => {
  const sidebar = readFileSync("components/app-sidebar.tsx", "utf8");
  const spaces = readFileSync("components/shell/spaces.ts", "utf8");
  const copy = readFileSync("lib/copy/common.ts", "utf8");

  // 같은 의미: 사이드바에 /code 로 가는 별도 진입이 있다. 라벨은 사전으로 옮겼다.
  assert.match(spaces, /href: "\/code"/);
  assert.match(sidebar, /SPACES\.map/);
  assert.match(copy, /code: "코드"/);
});
```

- [ ] **Step 11: 테스트 · 타입체크 · 린트를 돌린다**

Run: `cd web && pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/shell.test.ts tests/source/coding-shell.test.ts tests/source/blueblack-theme.test.ts tests/source/fe-surface-inventory.test.ts && pnpm typecheck && pnpm lint`
Expected: PASS

- [ ] **Step 12: 커밋한다**

```bash
git add components/shell app/\(chat\)/layout.tsx app/\(code\)/layout.tsx app/\(chat\)/reports app/\(chat\)/agents app/\(chat\)/settings components/app-sidebar.tsx lib/copy/common.ts tests/source/shell.test.ts tests/source/coding-shell.test.ts
git commit -m "feat(web): one shell with chat, reports, code and agents spaces

coding-shell.test: the sidebar still has its own /code entry; the label moved to the copy dictionary."
```

---

### Task 11: 활동 인박스

**Files:**
- Create: `web/lib/copy/inbox.ts`, `web/lib/inbox/normalize.ts`, `web/lib/inbox/collect.ts`, `web/lib/inbox/client.ts`, `web/hooks/use-inbox.ts`
- Create: `web/app/(chat)/api/inbox/route.ts`, `web/app/(chat)/inbox/page.tsx`
- Modify: `web/components/app-sidebar.tsx` (활동 링크 + 배지)
- Modify: `web/components/shell/spaces.ts` 는 이미 `inbox` 를 안다(Task 10)
- Test: `web/tests/source/inbox.test.ts`

**Interfaces:**
- Consumes: `RunStatus`, `TraceStatus`, `callBackendAPIWithJSON`, `BackendAPIError`
- Produces:
  - `type InboxItem = { id: string; source: "task_waiting" | "task_paused" | "task_failed" | "agent_paused"; title: string; status: TraceStatus; href: string; createdAt: string }` (spec §4.2)
  - `type InboxTask = { task_id: string; status: string; prompt: string; updated_at: string }`, `type InboxAgent = { agent_id: string; name: string; status: string; updated_at: string }`
  - `inboxItemsFromTasks(tasks: InboxTask[]): InboxItem[]`, `inboxItemsFromAgents(agents: InboxAgent[]): InboxItem[]`
  - `type InboxSource = "tasks" | "agents"`, `type InboxResult = { items: InboxItem[]; degraded: InboxSource[]; unauthorized: boolean }`
  - `collectInbox(fetchers: { tasks: () => Promise<{ tasks: InboxTask[] }>; agents: () => Promise<InboxAgent[]> }, classify: (error: unknown) => "absent" | "unauthorized" | "failed", timeoutMs?: number): Promise<InboxResult>`
  - `fetchInbox(): Promise<InboxResult>`, `useInbox(): { data?: InboxResult; count: number }`

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `web/tests/source/inbox.test.ts`

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { collectInbox } from "@/lib/inbox/collect";
import { inboxItemsFromAgents, inboxItemsFromTasks } from "@/lib/inbox/normalize";

const task = (status: string, prompt = "로그인 버그 고치기") => ({
  task_id: `ct_${status}`,
  status,
  prompt,
  updated_at: "2026-10-11T01:00:00Z",
});

test("only tasks that need a person become items, with their trace status", () => {
  const items = inboxItemsFromTasks(
    ["running", "waiting_approval", "waiting_user", "paused", "failed", "completed"].map((s) => task(s))
  );
  assert.deepEqual(
    items.map((i) => [i.source, i.status, i.href]),
    [
      ["task_waiting", "waiting", "/code/tasks/ct_waiting_approval"],
      ["task_waiting", "waiting", "/code/tasks/ct_waiting_user"],
      ["task_paused", "paused", "/code/tasks/ct_paused"],
      ["task_failed", "failed", "/code/tasks/ct_failed"],
    ]
  );
});

test("titles are one clipped line, or the task id when the prompt is empty (review focus 4)", () => {
  const [long] = inboxItemsFromTasks([task("failed", `첫 줄\n${"가".repeat(200)}`)]);
  assert.ok(!long.title.includes("\n"));
  assert.ok(long.title.length <= 90, long.title);
  assert.ok(long.title.endsWith("…"));
  const [empty] = inboxItemsFromTasks([task("failed", "   ")]);
  assert.match(empty.title, /ct_failed/);
});

test("only paused agents become items", () => {
  const items = inboxItemsFromAgents([
    { agent_id: "sa_1", name: "연구 비서", status: "paused", updated_at: "2026-10-11T00:00:00Z" },
    { agent_id: "sa_2", name: "다른 비서", status: "active", updated_at: "2026-10-11T00:00:00Z" },
  ]);
  assert.deepEqual(items.map((i) => [i.id, i.status, i.href]), [["agent_paused:sa_1", "paused", "/agents"]]);
  assert.match(items[0].title, /연구 비서/);
});

const classify = (error: unknown): "absent" | "unauthorized" | "failed" =>
  error === 404 ? "absent" : error === 401 ? "unauthorized" : "failed";

test("both sources answer: items are merged newest first, nothing degraded", async () => {
  const result = await collectInbox(
    {
      tasks: async () => ({ tasks: [{ ...task("failed"), updated_at: "2026-10-11T00:00:00Z" }] }),
      agents: async () => [{ agent_id: "sa_1", name: "비서", status: "paused", updated_at: "2026-10-11T02:00:00Z" }],
    },
    classify
  );
  assert.deepEqual(result.items.map((i) => i.source), ["agent_paused", "task_failed"]);
  assert.deepEqual(result.degraded, []);
  assert.equal(result.unauthorized, false);
});

test("a feature that is off (404) is absence, not failure", async () => {
  const result = await collectInbox(
    { tasks: async () => ({ tasks: [task("failed")] }), agents: async () => Promise.reject(404) },
    classify
  );
  assert.equal(result.items.length, 1);
  assert.deepEqual(result.degraded, []);
});

test("one failing source degrades instead of hiding the other (review focus 1)", async () => {
  const result = await collectInbox(
    { tasks: async () => Promise.reject(new Error("boom")), agents: async () => [] },
    classify
  );
  assert.deepEqual(result.degraded, ["tasks"]);
  assert.equal(result.unauthorized, false);
});

test("both sources unauthorized means unauthorized, not an empty inbox (review focus 1)", async () => {
  const result = await collectInbox(
    { tasks: async () => Promise.reject(401), agents: async () => Promise.reject(401) },
    classify
  );
  assert.equal(result.unauthorized, true);
});

test("a source slower than the timeout degrades", async () => {
  const result = await collectInbox(
    { tasks: () => new Promise(() => {}), agents: async () => [] },
    classify,
    20
  );
  assert.deepEqual(result.degraded, ["tasks"]);
});
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd web && pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/inbox.test.ts`
Expected: FAIL — 모듈 없음

- [ ] **Step 3: `web/lib/copy/inbox.ts`**

```ts
export const inboxCopy = {
  title: "활동",
  empty: "지금 나설 일이 없습니다.",
  degraded: (sources: string) => `일부 출처를 읽지 못했습니다: ${sources}. 목록이 완전하지 않을 수 있습니다.`,
  sourceNames: { tasks: "작업", agents: "에이전트" },
  task: {
    waiting_approval: "승인 대기",
    waiting_user: "답을 기다림",
    paused: "멈춤",
    failed: "실패",
  },
  agentPaused: (name: string) => `${name} 멈춤`,
  untitledTask: (taskId: string) => `작업 ${taskId}`,
  unauthorized: "로그인이 만료됐습니다. 다시 로그인하면 활동이 보입니다.",
} as const;
```

- [ ] **Step 4: `web/lib/inbox/normalize.ts`**

```ts
// BE 상태 문자열을 해석하는 유일한 곳(spec §4.2).
import type { TraceStatus } from "@/components/trace/types";
import { inboxCopy } from "@/lib/copy/inbox";

export type InboxItem = {
  /** `${source}:${sourceId}` */
  id: string;
  source: "task_waiting" | "task_paused" | "task_failed" | "agent_paused";
  title: string;
  status: TraceStatus;
  href: string;
  /** 그 상태에 들어선 시각의 근사 — BE 의 updated_at */
  createdAt: string;
};

export type InboxTask = { task_id: string; status: string; prompt: string; updated_at: string };
export type InboxAgent = { agent_id: string; name: string; status: string; updated_at: string };

const TASK_STATES = {
  waiting_approval: { source: "task_waiting", status: "waiting" },
  waiting_user: { source: "task_waiting", status: "waiting" },
  paused: { source: "task_paused", status: "paused" },
  failed: { source: "task_failed", status: "failed" },
} as const satisfies Record<string, { source: InboxItem["source"]; status: TraceStatus }>;

const TITLE_MAX = 80;

function oneLine(text: string): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > TITLE_MAX ? `${flat.slice(0, TITLE_MAX - 1)}…` : flat;
}

export function inboxItemsFromTasks(tasks: InboxTask[]): InboxItem[] {
  return tasks.flatMap((task): InboxItem[] => {
    if (!(task.status in TASK_STATES)) return [];
    const status = task.status as keyof typeof TASK_STATES;
    const state = TASK_STATES[status];
    const subject = oneLine(task.prompt) || inboxCopy.untitledTask(task.task_id);
    return [
      {
        id: `${state.source}:${task.task_id}`,
        source: state.source,
        title: `${inboxCopy.task[status]} · ${subject}`,
        status: state.status,
        href: `/code/tasks/${encodeURIComponent(task.task_id)}`,
        createdAt: task.updated_at,
      },
    ];
  });
}

export function inboxItemsFromAgents(agents: InboxAgent[]): InboxItem[] {
  return agents
    .filter((agent) => agent.status === "paused")
    .map((agent) => ({
      id: `agent_paused:${agent.agent_id}`,
      source: "agent_paused" as const,
      title: inboxCopy.agentPaused(oneLine(agent.name) || agent.agent_id),
      status: "paused" as const,
      // 에이전트 상세는 4단계 — 그 전에는 에이전트 공간으로 간다.
      href: "/agents",
      createdAt: agent.updated_at,
    }));
}
```

- [ ] **Step 5: `web/lib/inbox/collect.ts`**

```ts
import { type InboxAgent, type InboxItem, type InboxTask, inboxItemsFromAgents, inboxItemsFromTasks } from "./normalize";

export type InboxSource = "tasks" | "agents";
export type InboxResult = { items: InboxItem[]; degraded: InboxSource[]; unauthorized: boolean };
type Classification = "absent" | "unauthorized" | "failed";

const TIMEOUT = Symbol("timeout");

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(TIMEOUT), ms);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

// 출처 하나가 실패해도 나머지를 돌려준다. 실패는 degraded 로 싣는다 — 빈 목록으로 숨기지 않는다.
export async function collectInbox(
  fetchers: { tasks: () => Promise<{ tasks: InboxTask[] }>; agents: () => Promise<InboxAgent[]> },
  classify: (error: unknown) => Classification,
  timeoutMs = 5000
): Promise<InboxResult> {
  const [tasks, agents] = await Promise.allSettled([
    withTimeout(fetchers.tasks(), timeoutMs),
    withTimeout(fetchers.agents(), timeoutMs),
  ]);
  const items: InboxItem[] = [];
  const degraded: InboxSource[] = [];
  const failures: Classification[] = [];

  const settle = <T>(source: InboxSource, result: PromiseSettledResult<T>, toItems: (value: T) => InboxItem[]) => {
    if (result.status === "fulfilled") {
      items.push(...toItems(result.value));
      return;
    }
    const kind = result.reason === TIMEOUT ? "failed" : classify(result.reason);
    failures.push(kind);
    if (kind !== "absent") degraded.push(source);
  };
  settle("tasks", tasks, (value) => inboxItemsFromTasks(value.tasks ?? []));
  settle("agents", agents, (value) => inboxItemsFromAgents(value ?? []));

  items.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  const unauthorized = failures.length === 2 && failures.every((kind) => kind === "unauthorized");
  return { items, degraded, unauthorized };
}
```

- [ ] **Step 6: 테스트 통과를 확인한다**

Run: `cd web && pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/inbox.test.ts`
Expected: PASS

- [ ] **Step 7: BFF 라우트** — `web/app/(chat)/api/inbox/route.ts`

```ts
import { NextResponse } from "next/server";
import { BackendAPIError, callBackendAPIWithJSON } from "@/lib/backend-api";
import { collectInbox } from "@/lib/inbox/collect";
import type { InboxAgent, InboxTask } from "@/lib/inbox/normalize";

// spec §4.2 — 기존 목록 API 두 개의 팬아웃. 새 BE 엔드포인트는 없다.
// /coding/tasks 는 최근 활동 순 최대 50건이다(clamp_task_list_limit) — 그보다 오래된 대기 작업은 보이지 않는다.
export async function GET() {
  const result = await collectInbox(
    {
      tasks: () => callBackendAPIWithJSON<{ tasks: InboxTask[] }>("/api/v1/coding/tasks?limit=50"),
      agents: () => callBackendAPIWithJSON<InboxAgent[]>("/api/v1/standing-agents"),
    },
    (error) => {
      if (error instanceof BackendAPIError && error.status === 404) return "absent";
      if (error instanceof BackendAPIError && error.status === 401) return "unauthorized";
      return "failed";
    }
  );
  if (result.unauthorized) {
    return NextResponse.json({ error: "Unauthorized", code: "unauthorized" }, { status: 401 });
  }
  return NextResponse.json(result);
}
```

- [ ] **Step 8: 클라이언트와 훅**

`web/lib/inbox/client.ts`:

```ts
import { backendErrorMessage } from "@/lib/backend-error";
import type { InboxResult } from "./collect";

export class InboxUnauthorizedError extends Error {}

export async function fetchInbox(): Promise<InboxResult> {
  const response = await fetch("/api/inbox");
  if (response.status === 401) throw new InboxUnauthorizedError("unauthorized");
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(backendErrorMessage(body, "Could not load the inbox"));
  return body as InboxResult;
}
```

`web/hooks/use-inbox.ts`:

```ts
"use client";

import useSWR from "swr";
import type { InboxResult } from "@/lib/inbox/collect";
import { fetchInbox } from "@/lib/inbox/client";

// spec §4.2 — 30초 폴링 + 창 포커스 시 즉시 갱신. 실시간 푸시는 이후 단계.
export function useInbox() {
  const { data, error, isLoading } = useSWR<InboxResult>("/api/inbox", fetchInbox, {
    refreshInterval: 30_000,
    revalidateOnFocus: true,
  });
  return { data, error, isLoading, count: data?.items.length ?? 0 };
}
```

- [ ] **Step 9: 인박스 페이지** — `web/app/(chat)/inbox/page.tsx`

```tsx
"use client";

import Link from "next/link";
import { RunStatus } from "@/components/trace/run-status";
import { useInbox } from "@/hooks/use-inbox";
import { inboxCopy } from "@/lib/copy/inbox";
import { InboxUnauthorizedError } from "@/lib/inbox/client";

export default function InboxPage() {
  const { data, error, isLoading } = useInbox();
  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-10 md:px-6" lang="ko">
      <h1 className="font-semibold text-title">{inboxCopy.title}</h1>
      {error instanceof InboxUnauthorizedError ? (
        <p className="mt-6 text-body text-status-danger" role="alert">
          {inboxCopy.unauthorized}
        </p>
      ) : null}
      {data?.degraded.length ? (
        <p className="mt-4 rounded-md border border-status-warning/40 bg-status-warning/10 px-3 py-2 text-body-sm text-status-warning" role="status">
          {inboxCopy.degraded(data.degraded.map((s) => inboxCopy.sourceNames[s]).join(", "))}
        </p>
      ) : null}
      {!isLoading && data && data.items.length === 0 ? (
        <p className="mt-6 text-body text-muted-foreground">{inboxCopy.empty}</p>
      ) : null}
      <ul className="mt-6 divide-y divide-border rounded-md border border-border">
        {data?.items.map((item) => (
          <li key={item.id}>
            <Link className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-surface-2" href={item.href}>
              <span className="min-w-0 truncate text-body" title={item.title}>
                {item.title}
              </span>
              <RunStatus status={item.status} />
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
```

- [ ] **Step 10: 사이드바에 활동 항목과 배지를 더한다** — `web/components/app-sidebar.tsx`

import 에 `import { InboxIcon } from "lucide-react";`(기존 lucide import 목록에 더한다) 와 `import { useInbox } from "@/hooks/use-inbox";` 를 더하고, 컴포넌트 본문 위쪽에 `const { count: inboxCount } = useInbox();` 를 둔다. `<nav …>` 바로 앞에:

```tsx
          <div className="px-2 pb-2">
            <Link
              aria-current={space === "inbox" ? "page" : undefined}
              className={cn(
                "flex items-center gap-3 rounded-md px-2 py-2 text-sidebar-foreground text-sm hover:bg-sidebar-accent",
                space === "inbox" && "bg-sidebar-accent font-medium"
              )}
              data-testid="sidebar-inbox"
              href="/inbox"
              onClick={() => setOpenMobile(false)}
            >
              <InboxIcon className="size-4" />
              {commonCopy.shell.inbox}
              {inboxCount > 0 ? (
                <span className="ml-auto rounded-full bg-status-waiting/15 px-2 py-0.5 font-medium text-caption text-status-waiting">
                  {inboxCount}
                </span>
              ) : null}
            </Link>
          </div>
```

- [ ] **Step 11: 배선 테스트를 `inbox.test.ts` 끝에 더한다** — 파일 맨 위 import 목록에 `import { readFileSync } from "node:fs";` 를 더하고, 끝에:

```ts
test("the BFF fans out to the two list APIs and the sidebar shows the count", () => {
  const route = readFileSync("app/(chat)/api/inbox/route.ts", "utf8");
  assert.match(route, /\/api\/v1\/coding\/tasks\?limit=50/);
  assert.match(route, /\/api\/v1\/standing-agents"/);
  assert.match(route, /status: 401/);
  const sidebar = readFileSync("components/app-sidebar.tsx", "utf8");
  assert.match(sidebar, /useInbox\(\)/);
  assert.match(sidebar, /href="\/inbox"/);
  const hook = readFileSync("hooks/use-inbox.ts", "utf8");
  assert.match(hook, /refreshInterval: 30_000/);
  assert.match(hook, /revalidateOnFocus: true/);
});
```

- [ ] **Step 12: 통과를 확인하고 커밋한다**

Run: `cd web && pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/inbox.test.ts tests/source/shell.test.ts && pnpm typecheck && pnpm lint`
Expected: PASS

```bash
git add lib/copy/inbox.ts lib/inbox hooks/use-inbox.ts app/\(chat\)/api/inbox app/\(chat\)/inbox components/app-sidebar.tsx tests/source/inbox.test.ts
git commit -m "feat(web): activity inbox from the coding task and standing agent lists"
```

---

### Task 12: 새 작업 컴포저 · 빈 상태 · NEOS 마크 · 자율성 선택기 이동

**Files:**
- Create: `web/components/shell/task-modes.ts`, `web/components/shell/new-task-dialog.tsx`, `web/lib/copy/chat.ts`
- Modify: `web/components/icons.tsx` (`NeosMarkIcon` 추가), `web/components/message.tsx` (`SparklesIcon` 두 곳 → `NeosMarkIcon`)
- Modify: `web/components/greeting.tsx`, `web/components/suggested-actions.tsx`, `web/components/multimodal-input.tsx`, `web/components/chat.tsx`, `web/components/chat-header.tsx`, `web/components/app-sidebar.tsx`
- Test: `web/tests/source/new-task.test.ts`

**Interfaces:**
- Consumes: `useOpenAgent()`(Task 10), `AgentAutonomySelector`, `AutonomyLevel`
- Produces:
  - `type TaskMode = "search" | "deep_analysis" | "coding" | "agent"`, `TASK_MODES: readonly TaskMode[]`, `type TaskDestination = { kind: "route"; href: string } | { kind: "agent" }`, `destinationFor(mode: TaskMode): TaskDestination`
  - `NewTaskDialog({ open: boolean; onOpenChange: (open: boolean) => void })`
  - `chatCopy.modes: Record<TaskMode, { label; description; example? }>`, `chatCopy.greeting`
  - `SuggestedActions` 의 새 props: `{ setInput: (value: string) => void }`(sendMessage · chatId · selectedVisibilityType 은 지운다)
  - `MultimodalInput` 의 새 props: `autonomyLevel?: AutonomyLevel; onAutonomyChange?: (level: AutonomyLevel) => void`

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `web/tests/source/new-task.test.ts`

```ts
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { destinationFor, TASK_MODES } from "@/components/shell/task-modes";
import { chatCopy } from "@/lib/copy/chat";

test("each mode has a destination; deep analysis goes to a new chat (BE routing picks DA)", () => {
  assert.deepEqual(TASK_MODES, ["search", "deep_analysis", "coding", "agent"]);
  assert.deepEqual(destinationFor("search"), { kind: "route", href: "/" });
  assert.deepEqual(destinationFor("deep_analysis"), { kind: "route", href: "/" });
  assert.deepEqual(destinationFor("coding"), { kind: "route", href: "/code" });
  assert.deepEqual(destinationFor("agent"), { kind: "agent" });
});

test("every mode has Korean copy, and the chat modes carry an example to prefill", () => {
  for (const mode of TASK_MODES) {
    assert.ok(chatCopy.modes[mode].label.length > 0, mode);
    assert.ok(chatCopy.modes[mode].description.length > 0, mode);
  }
  assert.ok(chatCopy.modes.search.example);
  assert.ok(chatCopy.modes.deep_analysis.example);
  assert.match(chatCopy.modes.deep_analysis.description, /자동으로 심층분석/);
});

test("the empty state prefills instead of sending, and the template prompts are gone", () => {
  const actions = readFileSync("components/suggested-actions.tsx", "utf8");
  assert.match(actions, /setInput\(/);
  assert.doesNotMatch(actions, /sendMessage/);
  assert.doesNotMatch(actions, /Dijkstra|Silicon Valley|Next\.js|weather/i);
  const greeting = readFileSync("components/greeting.tsx", "utf8");
  assert.match(greeting, /lang="ko"/);
  assert.match(greeting, /NeosMarkIcon/);
  assert.doesNotMatch(greeting, /무엇을 도와드릴까요/);
});

test("the assistant avatar is the NEOS mark", () => {
  const message = readFileSync("components/message.tsx", "utf8");
  assert.doesNotMatch(message, /SparklesIcon/);
  assert.match(message, /NeosMarkIcon/);
});

test("the autonomy selector moved from the header into the composer toolbar", () => {
  const header = readFileSync("components/chat-header.tsx", "utf8");
  const input = readFileSync("components/multimodal-input.tsx", "utf8");
  const chat = readFileSync("components/chat.tsx", "utf8");
  assert.doesNotMatch(header, /AgentAutonomySelector/);
  assert.match(input, /<AgentAutonomySelector/);
  assert.match(input, /prevProps\.autonomyLevel !== nextProps\.autonomyLevel/);
  assert.match(chat, /onAutonomyChange=\{setAutonomyLevel\}/);
});

test("the sidebar's new task opens the dialog", () => {
  const sidebar = readFileSync("components/app-sidebar.tsx", "utf8");
  assert.match(sidebar, /<NewTaskDialog/);
});
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd web && pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/new-task.test.ts`
Expected: FAIL — 모듈 없음

- [ ] **Step 3: `web/components/shell/task-modes.ts` 와 `web/lib/copy/chat.ts`**

```ts
export type TaskMode = "search" | "deep_analysis" | "coding" | "agent";

export const TASK_MODES = ["search", "deep_analysis", "coding", "agent"] as const satisfies readonly TaskMode[];

export type TaskDestination = { kind: "route"; href: string } | { kind: "agent" };

// 심층분석은 FE 가 요청할 수 없다 — BE 라우팅이 질의를 보고 고른다(spec §4.3).
// 명시적 요청 필드는 3단계 spec 의 BE 변경이다.
export function destinationFor(mode: TaskMode): TaskDestination {
  switch (mode) {
    case "search":
    case "deep_analysis":
      return { kind: "route", href: "/" };
    case "coding":
      return { kind: "route", href: "/code" };
    case "agent":
      return { kind: "agent" };
  }
}
```

`web/lib/copy/chat.ts` — `modes` 를 명시 타입으로 둔다. `as const` 만 쓰면 `chatCopy.modes[mode].example` 이 유니언 접근 오류가 된다:

```ts
import type { TaskMode } from "@/components/shell/task-modes";

type ModeCopy = { readonly label: string; readonly description: string; readonly example?: string };

const modes: Record<TaskMode, ModeCopy> = {
    search: {
      label: "검색",
      description: "여러 에이전트가 웹과 문서를 찾아 출처와 함께 답합니다.",
      example: "2026년 국내 전기차 충전 인프라 현황을 출처와 함께 정리해 줘",
    },
    deep_analysis: {
      label: "심층분석",
      description: "복잡한 조사 질문은 자동으로 심층분석으로 이어지고, 클레임마다 근거를 검증합니다.",
      example: "주요 클라우드 3사의 2026년 AI 인프라 투자 전략을 비교 분석해 줘",
    },
    coding: { label: "코딩", description: "샌드박스에서 코드를 읽고 고치고 테스트합니다." },
    agent: { label: "에이전트에게 맡기기", description: "상시 에이전트와의 대화를 엽니다. 채널 DM 과 같은 맥락입니다." },
};

export const chatCopy = {
  greeting: {
    title: "무엇을 조사하거나 만들까요?",
    subtitle: "검색 · 심층분석 · 코딩 · 상시 에이전트가 한 곳에서 일합니다.",
  },
  newTask: { title: "새 작업", description: "어떤 방식으로 시작할지 고르세요." },
  modes,
} as const;
```

- [ ] **Step 4: NEOS 마크 아이콘** — `web/components/icons.tsx` 끝에 더한다

```tsx
// NEOS 마크 — 연결된 세 노드(멀티에이전트). 템플릿 반짝이 아이콘을 대신한다(spec §3.5).
export const NeosMarkIcon = ({ size = 16 }: { size?: number }) => (
  <svg fill="none" height={size} style={{ color: "currentcolor" }} viewBox="0 0 16 16" width={size}>
    <title>NEOS</title>
    <path d="M8 2.5 L13 11 H3 Z" stroke="currentColor" strokeLinejoin="round" strokeWidth="1.25" />
    <circle cx="8" cy="2.5" fill="currentColor" r="1.75" />
    <circle cx="13" cy="11" fill="currentColor" r="1.75" />
    <circle cx="3" cy="11" fill="currentColor" r="1.75" />
  </svg>
);
```

`web/components/message.tsx`: import 의 `SparklesIcon` 을 `NeosMarkIcon` 으로 바꾸고, 두 곳의 `<SparklesIcon size={14} />` 를 `<NeosMarkIcon size={14} />` 로 바꾼다.

- [ ] **Step 5: 인사말** — `web/components/greeting.tsx` 전체

```tsx
import { motion } from "framer-motion";
import { chatCopy } from "@/lib/copy/chat";
import { NeosMarkIcon } from "./icons";

export const Greeting = () => {
  return (
    <div
      className="mx-auto mt-4 flex size-full max-w-3xl flex-col justify-center px-4 text-center md:mt-16 md:px-8"
      key="overview"
      lang="ko"
    >
      <motion.div
        animate={{ opacity: 1, y: 0 }}
        className="mx-auto mb-4 grid size-11 place-items-center rounded-xl border border-border bg-surface-1 text-primary"
        initial={{ opacity: 0, y: 10 }}
        transition={{ delay: 0.4 }}
      >
        <NeosMarkIcon size={22} />
      </motion.div>
      <motion.h1
        animate={{ opacity: 1, y: 0 }}
        className="font-semibold text-display text-foreground"
        exit={{ opacity: 0, y: 10 }}
        initial={{ opacity: 0, y: 10 }}
        transition={{ delay: 0.5 }}
      >
        {chatCopy.greeting.title}
      </motion.h1>
      <motion.p
        animate={{ opacity: 1, y: 0 }}
        className="mt-2 text-body text-muted-foreground"
        exit={{ opacity: 0, y: 10 }}
        initial={{ opacity: 0, y: 10 }}
        transition={{ delay: 0.6 }}
      >
        {chatCopy.greeting.subtitle}
      </motion.p>
    </div>
  );
};
```

- [ ] **Step 6: 빈 상태 카드** — `web/components/suggested-actions.tsx` 전체

```tsx
"use client";

import { motion } from "framer-motion";
import { BotIcon, Code2Icon, MicroscopeIcon, SearchIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { memo } from "react";
import { useOpenAgent } from "@/components/shell/open-agent-button";
import { destinationFor, TASK_MODES, type TaskMode } from "@/components/shell/task-modes";
import { chatCopy } from "@/lib/copy/chat";

const ICONS: Record<TaskMode, typeof SearchIcon> = {
  search: SearchIcon,
  deep_analysis: MicroscopeIcon,
  coding: Code2Icon,
  agent: BotIcon,
};

// 첫 화면의 네 작업 방식(spec §3.5). 검색 · 심층분석은 입력창을 채우기만 한다 —
// 보내지 않는다. 사용자가 고쳐 보낸다.
function PureSuggestedActions({ setInput }: { setInput: (value: string) => void }) {
  const router = useRouter();
  const { open: openAgent } = useOpenAgent();

  const select = (mode: TaskMode) => {
    const example = chatCopy.modes[mode].example;
    if (example) {
      setInput(example);
      return;
    }
    const destination = destinationFor(mode);
    if (destination.kind === "agent") {
      void openAgent();
      return;
    }
    router.push(destination.href);
  };

  return (
    <div className="grid w-full gap-2 sm:grid-cols-2" data-testid="suggested-actions" lang="ko">
      {TASK_MODES.map((mode, index) => {
        const Icon = ICONS[mode];
        const copy = chatCopy.modes[mode];
        return (
          <motion.button
            animate={{ opacity: 1, y: 0 }}
            className="flex h-auto w-full items-start gap-3 rounded-lg border border-border bg-surface-1 p-3 text-left transition-colors hover:border-primary/40 hover:bg-surface-2"
            data-mode={mode}
            exit={{ opacity: 0, y: 20 }}
            initial={{ opacity: 0, y: 20 }}
            key={mode}
            onClick={() => select(mode)}
            transition={{ delay: 0.05 * index }}
            type="button"
          >
            <Icon aria-hidden className="mt-0.5 size-4 shrink-0 text-primary" />
            <span className="min-w-0">
              <span className="block font-medium text-body-sm">{copy.label}</span>
              <span className="mt-0.5 block text-caption text-muted-foreground">{copy.description}</span>
            </span>
          </motion.button>
        );
      })}
    </div>
  );
}

export const SuggestedActions = memo(PureSuggestedActions);
```

`web/components/multimodal-input.tsx` 의 `<SuggestedActions … />` 호출을 `<SuggestedActions setInput={setInput} />` 로 바꾼다(`chatId` · `selectedVisibilityType` · `sendMessage` props 를 지운다).

- [ ] **Step 7: 자율성 선택기를 컴포저 툴바로 옮긴다**

`web/components/multimodal-input.tsx`:
- import 에 `import { AgentAutonomySelector } from "./agent-autonomy-selector";` 와 `AutonomyLevel` 타입(`import type { …, AutonomyLevel } from "@/lib/types";` — 기존 `@/lib/types` import 에 더한다)
- `PureMultimodalInput` 의 구조분해 목록 끝에 `autonomyLevel, onAutonomyChange,` 를, 타입 목록 끝에 `autonomyLevel?: AutonomyLevel; onAutonomyChange?: (level: AutonomyLevel) => void;` 를 더한다
- `<EffortSelector … />` 바로 뒤(`</PromptInputTools>` 앞)에:

```tsx
            {autonomyLevel !== undefined && onAutonomyChange ? (
              <AgentAutonomySelector autonomyLevel={autonomyLevel} onAutonomyChange={onAutonomyChange} />
            ) : null}
```

- memo 비교 함수의 `if (!equal(prevProps.catalog, nextProps.catalog)) { return false; }` 다음에:

```tsx
    if (prevProps.autonomyLevel !== nextProps.autonomyLevel) {
      return false;
    }
```

`web/components/chat.tsx`: `<ChatHeader … />` 에서 `autonomyLevel={autonomyLevel}` · `onAutonomyChange={setAutonomyLevel}` 두 줄을 지우고, `<MultimodalInput … />` 에 `autonomyLevel={autonomyLevel}` 와 `onAutonomyChange={setAutonomyLevel}` 를 더한다.

`web/components/chat-header.tsx`: `AgentAutonomySelector` · `AutonomyLevel` import, props 의 `autonomyLevel` · `onAutonomyChange`(구조분해와 타입 둘 다), 그리고 `{autonomyLevel !== undefined && onAutonomyChange && ( <AgentAutonomySelector … /> )}` 블록을 지운다.

- [ ] **Step 8: 새 작업 다이얼로그** — `web/components/shell/new-task-dialog.tsx`

```tsx
"use client";

import { BotIcon, Code2Icon, MicroscopeIcon, SearchIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { chatCopy } from "@/lib/copy/chat";
import { useOpenAgent } from "./open-agent-button";
import { destinationFor, TASK_MODES, type TaskMode } from "./task-modes";

const ICONS: Record<TaskMode, typeof SearchIcon> = {
  search: SearchIcon,
  deep_analysis: MicroscopeIcon,
  coding: Code2Icon,
  agent: BotIcon,
};

export function NewTaskDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const router = useRouter();
  const { open: openAgent, opening } = useOpenAgent();

  const choose = async (mode: TaskMode) => {
    const destination = destinationFor(mode);
    if (destination.kind === "agent") {
      await openAgent();
    } else {
      router.push(destination.href);
      router.refresh();
    }
    onOpenChange(false);
  };

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent lang="ko">
        <DialogHeader>
          <DialogTitle>{chatCopy.newTask.title}</DialogTitle>
          <DialogDescription>{chatCopy.newTask.description}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-2 sm:grid-cols-2">
          {TASK_MODES.map((mode) => {
            const Icon = ICONS[mode];
            const copy = chatCopy.modes[mode];
            return (
              <button
                className="flex items-start gap-3 rounded-lg border border-border bg-surface-1 p-3 text-left hover:border-primary/40 hover:bg-surface-2 disabled:opacity-60"
                data-mode={mode}
                disabled={mode === "agent" && opening}
                key={mode}
                onClick={() => choose(mode)}
                type="button"
              >
                <Icon aria-hidden className="mt-0.5 size-4 shrink-0 text-primary" />
                <span>
                  <span className="block font-medium text-body-sm">{copy.label}</span>
                  <span className="mt-0.5 block text-caption text-muted-foreground">{copy.description}</span>
                </span>
              </button>
            );
          })}
        </div>
      </DialogContent>
    </Dialog>
  );
}
```

`web/components/app-sidebar.tsx`: `import { NewTaskDialog } from "@/components/shell/new-task-dialog";` 를 더하고 `const [newTaskOpen, setNewTaskOpen] = useState(false);` 를 둔다. 헤더의 ＋ 버튼 `onClick` 을 `() => { setOpenMobile(false); setNewTaskOpen(true); }` 로 바꾸고, 그 툴팁 문구 `New Chat` 을 `{commonCopy.shell.newTask}` 로 바꾼다. 컴포넌트가 돌려주는 프래그먼트의 `<AlertDialog …>` 앞에 `<NewTaskDialog onOpenChange={setNewTaskOpen} open={newTaskOpen} />` 를 둔다.

- [ ] **Step 9: 전체 소스 테스트와 타입체크를 돌린다**

Run: `cd web && pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/new-task.test.ts tests/source/blueblack-theme.test.ts && pnpm test:source && pnpm typecheck && pnpm lint`
Expected: PASS 전체. `blueblack-theme.test.ts` 는 `greeting.tsx` 의 `lang="ko"`, 입력창의 `neos-blueblack-panel` · `compact-model-selector` 등을 본다 — 이 작업은 그것들을 건드리지 않는다.

- [ ] **Step 10: 커밋한다**

```bash
git add components/shell/task-modes.ts components/shell/new-task-dialog.tsx lib/copy/chat.ts components/icons.tsx components/message.tsx components/greeting.tsx components/suggested-actions.tsx components/multimodal-input.tsx components/chat.tsx components/chat-header.tsx components/app-sidebar.tsx tests/source/new-task.test.ts
git commit -m "feat(web): new task dialog, a four-mode empty state, the NEOS mark, and autonomy in the composer"
```

---

### Task 13: 프리미티브 갤러리

**Files:**
- Create: `web/tests/fixtures/trace/coding.ts`, `web/tests/fixtures/trace/static.ts`
- Create: `web/app/(dev)/layout.tsx`, `web/app/(dev)/dev/trace/page.tsx`, `web/app/(dev)/dev/trace/gallery.tsx`
- Modify: `web/proxy.ts` (개발 모드 `/dev/` 통과)
- Create: `web/tests/e2e/trace-gallery.test.ts`
- Test: `web/tests/source/trace-gallery.test.ts`

**Interfaces:**
- Consumes: `reduceProjectionEvent` · `emptyProjection`, `stepsFromCoding` · `approvalFromCoding` · `verdictFromToolRisk`, 프리미티브 6종
- Produces: `codingGalleryState(): CodingProjectionState`, `codingGallerySteps(): TraceStep[]`, `staticClaims: ClaimView[]`, `staticApproval: ApprovalView`

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `web/tests/source/trace-gallery.test.ts`

```ts
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { codingGallerySteps, codingGalleryState } from "../fixtures/trace/coding";

test("the coding gallery fixture is built by the real reducer, not by hand", () => {
  const state = codingGalleryState();
  assert.equal(state.gap, null, "events must be contiguous");
  assert.equal(state.phases.length, 2);
  assert.ok(state.toolRisksById.t2, "the Jev event was decoded");
  assert.equal(Object.keys(state.approvalsById).length, 1);
});

test("the coding steps carry tools and a verdict through the adapter", () => {
  const [understand, implement] = codingGallerySteps();
  assert.equal(understand.status, "succeeded");
  assert.equal(implement.status, "running");
  assert.ok(implement.items.some((item) => item.kind === "verdict"));
});

test("the gallery is development-only and the proxy lets /dev/ through only in development", () => {
  const page = readFileSync("app/(dev)/dev/trace/page.tsx", "utf8");
  assert.match(page, /process\.env\.NODE_ENV !== "development"/);
  assert.match(page, /notFound\(\)/);
  const proxy = readFileSync("proxy.ts", "utf8");
  const bypass = proxy.indexOf('pathname.startsWith("/dev/")');
  assert.ok(bypass > 0, "bypass branch missing");
  assert.ok(bypass < proxy.indexOf("getToken("), "bypass must come before the auth check");
  assert.match(proxy.slice(bypass - 80, bypass), /isDevelopmentEnvironment/);
});
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd web && pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/trace-gallery.test.ts`
Expected: FAIL — 모듈 없음

- [ ] **Step 3: 코딩 fixture** — `web/tests/fixtures/trace/coding.ts` (실제 리듀서에 실제 이벤트 모양을 통과시킨다)

```ts
import type { TraceStep } from "@/components/trace/types";
import { emptyProjection, reduceProjectionEvent } from "@/features/coding/stream/projection-reducer";
import { stepsFromCoding } from "@/features/coding/trace";
import type { CodingEvent } from "@/features/coding/types/events";
import type { CodingProjectionState } from "@/features/coding/types/projection";

const TASK = "ct_gallery";

function events(): CodingEvent[] {
  const raw: Array<Omit<CodingEvent, "v" | "task_id" | "seq" | "event_id">> = [
    { type: "phase.started", ts: "2026-10-11T00:00:00Z", run_id: "cr_1", payload: { phase: "understand", attempt: 1 } },
    { type: "tool.started", ts: "2026-10-11T00:00:02Z", run_id: "cr_1", tool_call_id: "t1", payload: { name: "read_file.v1" } },
    { type: "tool.completed", ts: "2026-10-11T00:00:03Z", run_id: "cr_1", tool_call_id: "t1", payload: { name: "read_file.v1" } },
    { type: "phase.completed", ts: "2026-10-11T00:00:40Z", run_id: "cr_1", payload: { phase: "understand", attempt: 1 } },
    { type: "phase.started", ts: "2026-10-11T00:00:41Z", run_id: "cr_2", payload: { phase: "implement", attempt: 1 } },
    {
      type: "jev_risk_scored",
      ts: "2026-10-11T00:00:42Z",
      run_id: "cr_2",
      tool_call_id: "t2",
      payload: {
        tool: "execute.v1",
        probability: 0.62,
        band: "mid",
        low_below: 0.3,
        high_at_or_above: 0.8,
        static_outcome: "allow",
        would_be_outcome: "require_approval",
        banded_outcome: "require_approval",
        enforced: false,
        unattended: false,
        model: "jev-1.13.0",
      },
    },
    { type: "tool.started", ts: "2026-10-11T00:00:43Z", run_id: "cr_2", tool_call_id: "t2", payload: { name: "execute.v1" } },
    {
      type: "approval.requested",
      ts: "2026-10-11T00:00:44Z",
      run_id: "cr_2",
      payload: {
        approval_id: "ca_1",
        tool_name: "execute.v1",
        risk: "command",
        requested_at: "2026-10-11T00:00:44Z",
        expires_at: "2026-10-11T00:15:44Z",
        display_summary: { command: "pytest -q tests/test_auth.py" },
      },
    },
  ];
  return raw.map((event, index) => ({
    v: 1,
    task_id: TASK,
    seq: index + 1,
    event_id: `ev_${index + 1}`,
    ...event,
  }));
}

export function codingGalleryState(): CodingProjectionState {
  return events().reduce(reduceProjectionEvent, emptyProjection(TASK));
}

export function codingGallerySteps(): TraceStep[] {
  return stepsFromCoding(codingGalleryState());
}
```

> `reduceProjectionEvent` 는 `appliedSeq + 1` 만 받는다. `emptyProjection` 의 `appliedSeq` 가 0 이므로(2026-10-11 확인) seq 는 1 부터 빈틈없이 간다 — 테스트의 `state.gap === null` 이 그것을 지킨다.

- [ ] **Step 4: 정적 fixture** — `web/tests/fixtures/trace/static.ts` (BE 계약이 아직 없는 클레임 · 질문 — 손으로 짓는다는 것을 이름이 말한다)

```ts
import type { ApprovalView, ClaimView, TraceStep } from "@/components/trace/types";

export const staticClaims: ClaimView[] = [
  {
    id: "c1",
    text: "2026년 2분기 국내 전기차 판매는 전년 대비 18% 늘었다",
    status: "verified",
    sources: [{ url: "https://example.com/ev-q2", title: "분기 판매 보고서", excerpt: "EV sales rose 18% year over year" }],
    verdict: { band: "low", probability: 0.12, mode: "enforced", badge: "jev 0.12 · low", sentence: null },
  },
  { id: "c2", text: "충전기 보급이 판매 증가의 주된 원인이다", status: "unverified", sources: [] },
  {
    id: "c3",
    text: "보조금이 2025년에 폐지됐다",
    status: "rejected",
    sources: [{ url: "https://example.com/subsidy", title: "정책 공고", excerpt: "the subsidy was extended through 2027" }],
  },
];

export const staticApproval: ApprovalView = {
  id: "ca_static",
  toolName: "write_file.v1",
  risk: "workspace_write",
  status: "pending",
  summary: [
    { label: "file path", value: "src/auth.py" },
    { label: "bytes", value: "1240" },
  ],
  expiresAt: "2026-10-11T00:15:00Z",
};

export const staticSteps: TraceStep[] = [
  {
    id: "s_wait",
    label: "사용자 확인",
    status: "waiting",
    items: [{ kind: "question", question: { id: "q1", prompt: "어느 테스트 러너를 쓸까요?", status: "open" } }],
  },
  { id: "s_paused", label: "예산 봉투", status: "paused", items: [{ kind: "note", text: "이번 주 예산을 넘어 멈췄습니다" }] },
  { id: "s_cancel", label: "취소된 탐색", status: "cancelled", items: [] },
];
```

- [ ] **Step 5: 갤러리 라우트**

`web/app/(dev)/layout.tsx` (인증 없는 최소 레이아웃):

```tsx
export default function DevLayout({ children }: { children: React.ReactNode }) {
  return <div className="min-h-dvh bg-background text-foreground">{children}</div>;
}
```

`web/app/(dev)/dev/trace/page.tsx`:

```tsx
import { notFound } from "next/navigation";
import { TraceGallery } from "./gallery";

// spec §6.2 — 개발 모드 전용. 프로덕션 빌드에도 라우트는 있지만 404 다.
export default function TraceGalleryPage() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <TraceGallery />;
}
```

`web/app/(dev)/dev/trace/gallery.tsx`:

```tsx
"use client";

import { ApprovalCard } from "@/components/trace/approval-card";
import { ClaimEvidence } from "@/components/trace/claim-evidence";
import { RunStatus } from "@/components/trace/run-status";
import { TRACE_STATUSES } from "@/components/trace/status";
import { StepTimeline } from "@/components/trace/step-timeline";
import { approvalFromCoding } from "@/features/coding/trace";
import { codingGallerySteps, codingGalleryState } from "@/tests/fixtures/trace/coding";
import { staticApproval, staticClaims, staticSteps } from "@/tests/fixtures/trace/static";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="font-mono text-caption text-muted-foreground uppercase tracking-[0.18em]">{title}</h2>
      {children}
    </section>
  );
}

export function TraceGallery() {
  const state = codingGalleryState();
  const [codingApproval] = Object.values(state.approvalsById);
  const noop = () => {};
  return (
    <main className="mx-auto max-w-4xl space-y-10 px-6 py-10" data-testid="trace-gallery" lang="ko">
      <h1 className="font-semibold text-title">작업 흔적 프리미티브</h1>
      <Section title="RunStatus">
        <div className="flex flex-wrap gap-2">
          {TRACE_STATUSES.map((status) => (
            <RunStatus key={status} status={status} />
          ))}
        </div>
      </Section>
      <Section title="StepTimeline — 코딩 리듀서 + 어댑터">
        <StepTimeline steps={codingGallerySteps()} />
      </Section>
      <Section title="StepTimeline — 정적 상태">
        <StepTimeline steps={staticSteps} />
      </Section>
      <Section title="ApprovalCard">
        {codingApproval ? (
          <ApprovalCard
            actions={[
              { id: "deny", label: "Deny", busyLabel: "Denying…", ariaLabel: "Deny tool request", variant: "outline", disabled: false, onSelect: noop },
              { id: "approve", label: "Approve once", busyLabel: "Approving…", ariaLabel: "Approve tool request", variant: "default", disabled: false, onSelect: noop },
            ]}
            approval={approvalFromCoding(codingApproval, { risk: state.toolRisksById.t2 })}
            eyebrow="Command permission"
            hint="Review this exact request before continuing."
          />
        ) : null}
        <ApprovalCard actions={[]} approval={staticApproval} eyebrow="Workspace permission" hint="Reconnect to decide." warnings={["protected_file"]} />
      </Section>
      <Section title="ClaimEvidence">
        <div className="space-y-4">
          {staticClaims.map((claim) => (
            <ClaimEvidence claim={claim} key={claim.id} />
          ))}
        </div>
      </Section>
    </main>
  );
}
```

> `@/tests/...` 는 `tsconfig.json` 의 `"@/*": ["./*"]` 로 풀린다(2026-10-11 확인).

- [ ] **Step 6: 프록시 우회** — `web/proxy.ts` 의 `export async function proxy(…)` 안, `const { pathname } = request.nextUrl;` 바로 다음 줄

```ts
  // 개발 전용 갤러리(spec §6.2)는 BE 없이 열려야 한다 — 게스트 인증은 BE 를 부른다.
  if (isDevelopmentEnvironment && pathname.startsWith("/dev/")) {
    return NextResponse.next();
  }
```

- [ ] **Step 7: 소스 테스트 통과를 확인한다**

Run: `cd web && pnpm exec tsx --tsconfig tsconfig.test.json --test tests/source/trace-gallery.test.ts && pnpm typecheck && pnpm lint`
Expected: PASS

- [ ] **Step 8: Playwright 스크린샷 스펙** — `web/tests/e2e/trace-gallery.test.ts`

```ts
import { expect, test } from "@playwright/test";

// spec §6.2 — 디자인 리뷰 재료. 비교 게이트는 걸지 않는다.
for (const theme of ["light", "dark"] as const) {
  test(`trace gallery renders in ${theme}`, async ({ page }) => {
    await page.addInitScript((value) => {
      try {
        window.localStorage.setItem("theme", value);
      } catch {
        // 저장소가 막힌 브라우저에서는 시스템 테마로 찍힌다.
      }
    }, theme);
    await page.emulateMedia({ colorScheme: theme });
    await page.goto("/dev/trace");
    await expect(page.getByTestId("trace-gallery")).toBeVisible();
    await expect(page.getByTestId("run-status").first()).toBeVisible();
    await page.screenshot({ fullPage: true, path: `test-results/trace-gallery-${theme}.png` });
  });
}
```

- [ ] **Step 9: 브라우저에서 확인한다**

Run: `cd web && PLAYWRIGHT=True pnpm exec playwright test tests/e2e/trace-gallery.test.ts`
Expected: 2 passed. `test-results/trace-gallery-light.png` · `trace-gallery-dark.png` 가 생긴다. 두 이미지를 직접 열어 본다 — 상태 7종이 서로 구별되는지, 다크에서 글자가 읽히는지, 한글이 Pretendard 로 보이는지. 이상하면 그 관찰을 커밋 메시지에 적는다(이 단계는 게이트가 아니라 리뷰 재료다).

- [ ] **Step 10: 커밋한다**

```bash
git add tests/fixtures/trace app/\(dev\) proxy.ts tests/e2e/trace-gallery.test.ts tests/source/trace-gallery.test.ts
git commit -m "feat(web): development-only trace primitive gallery with light and dark screenshots"
```

---

### Task 14: 최종 검증

**Files:** 없음(검증만). 실패하면 그 원인 작업으로 돌아가 고치고 그 작업의 커밋을 더한다.

- [ ] **Step 1: FE CI 명령을 그대로 돌린다**

Run: `cd web && pnpm lint && pnpm typecheck && pnpm typecheck:tests && pnpm test:source`
Expected: 전부 0 종료. `pnpm test:source` 의 실패 이름을 **이름으로** 본다 — 개수가 아니라(저장소 메모리: 개수가 아니라 이름으로 검증한다).

- [ ] **Step 2: 빌드한다**

Run: `cd web && pnpm build`
Expected: 성공. `/dev/trace` 가 라우트 목록에 있고 프로덕션에서는 404 를 낸다.

- [ ] **Step 3: BE 쪽 — 새 테스트와 CI Ruff 명령을 그대로**

Run(저장소 루트):

```bash
uv run --frozen pytest tests/api/test_fe_surface_inventory.py -q -p no:randomly
uv run --frozen ruff check tests/api/test_fe_surface_inventory.py
uv run --frozen ruff check neos/workflow/deep_analysis neos/coding neos/subagent neos/fsi neos/univer neos/config neos/learn neos/jev tests/workflow/deep_analysis tests/coding tests/subagent tests/fsi tests/univer tests/k_skill tests/security_audit tests/learn tests/jev tests/config tests/conftest.py
uv run --frozen pytest --collect-only tests/workflow tests/api -q | tail -3
```

Expected: 3 passed · 경고 0 · 경고 0 · 수집 오류 없음. (마지막 Ruff 목록은 `.github/workflows/backend-ci.yml` 의 "Ruff" 단계 그대로다 — 바뀌었으면 그 파일이 정본이다.)

- [ ] **Step 4: spec §8 완료 기준을 하나씩 대조한다**

| 기준 | 확인 |
|---|---|
| 1. 원시 팔레트 0곳 | `raw-palette-ban.test.ts` 초록 |
| 2. 라이트·다크 토큰 | `semantic-tokens` · `light-theme` 초록 |
| 3. 템플릿 도구 제거 | `template-tools-removed` 초록 |
| 4. 셸 이동 | `pnpm dev` 로 `/` → 리포트 · 코드 · 에이전트 · 설정 · 활동을 눌러 본다. 자리 공간은 몇 단계인지 말한다 |
| 5. 인박스 | `inbox.test.ts` 초록 + 로그인 상태에서 `/inbox` 가 열린다 |
| 6. 코딩 이식 | `coding-*` 소스 테스트가 수정 없이 초록(`coding-shell.test.ts` 라벨 한 줄 제외) |
| 7. 인벤토리 | BE · FE 양쪽 초록 |
| 8. 갤러리 | Task 13 Step 9 스크린샷 두 장 |
| 9. CI 명령 | Step 1~3 |

- [ ] **Step 5: 남은 일을 기록하고 커밋한다**

로드맵 문서 `docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md` §1 의 트랙 C 행 "남은 것" 칸 끝에 한 문장을 더한다:
`· FE 진화 5단계 중 1단계(기반) 착지(<오늘 날짜>) — [spec](superpowers/specs/2026-10-11-frontend-evolution-foundation-design.md) · 2~5단계는 각자 spec 이 필요하다`

```bash
git add docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md
git commit -m "docs(roadmap): note the FE evolution phase 1 landing on track C"
```

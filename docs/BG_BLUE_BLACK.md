# Blue-Black Frontend Background Redesign

작성일: 2026-05-24
구현 갱신일: 2026-05-25

## 개요

`neos-web`의 채팅 프론트엔드를 기존 짙은 회색 계열에서 **검은색과 검푸른 색을 조합한 다크 작업 공간**으로 재구성하기 위한 디자인/구현 기록이다.

이 개선안은 첨부 레퍼런스 이미지처럼 중앙부에 은은한 블루 블룸이 있고, 주변부는 거의 검정에 가까운 톤으로 가라앉는 시각 언어를 목표로 한다. 단순히 빈 채팅 화면만 꾸미는 것이 아니라, 사이드바, 헤더, 메시지 영역, 입력창, 팝오버까지 하나의 blue-black 시스템으로 묶는 방향이다.

현재 정리 상태:

- 디자인 방향은 **B. 전체 작업공간 블루블랙**으로 확정했다.
- 스펙과 구현 계획은 작성 및 커밋된 이력이 있다.
- 코드 리뷰에서 지적된 누락 사항을 반영해 실제 `web/` 소스에 blue-black theme 변경을 적용했다.
- 검증은 auth/backend에 덜 의존하도록 source-level regression test와 build/lint 확인을 함께 사용한다.

## 디자인 목표

이번 개선의 핵심 목표는 다음과 같다.

1. **짙은 회색 배경 탈피**
   - 기존의 단조로운 gray/zinc 기반 다크 UI를 검정 기반으로 낮춘다.
   - 표면에는 아주 약한 blue undertone을 넣어 깊이감을 만든다.

2. **레퍼런스 이미지의 중앙 블루 블룸 재현**
   - 빈 채팅 화면에서는 중앙부에 검푸른 radial glow를 더 강하게 보여준다.
   - 대화가 시작된 뒤에는 glow를 약하게 유지해 메시지 가독성을 방해하지 않는다.

3. **전체 작업 공간의 일관성**
   - 입력창만 바꾸지 않고 사이드바, 헤더, composer, 모델 선택기, 팝오버까지 같은 토큰을 사용한다.
   - 컴포넌트별 하드코딩된 회색 계열은 필요한 곳만 걷어낸다.

4. **기능 변경 없는 시각 개선**
   - chat, upload, auth, model selection, history 동작은 유지한다.
   - 레이아웃 안정성과 모바일 사용성을 깨지 않는 범위에서 스타일만 조정한다.

## 선택한 방향: 전체 작업공간 블루블랙

초기 비교안은 세 가지였다.

| 안 | 이름 | 특징 | 판단 |
| --- | --- | --- | --- |
| A | 중심광 홈 포커스 | 빈 채팅 화면에만 레퍼런스 이미지 같은 블루 블룸을 강하게 적용 | 홈 화면은 좋지만 대화 화면과 단절될 수 있음 |
| B | 전체 작업공간 블루블랙 | 홈, 메시지, 사이드바, 헤더, 입력창까지 같은 blue-black 톤으로 통합 | 채택 |
| C | 고대비 네온 콘솔 | 검정 비중과 블루 라인/글로우를 강하게 사용 | 개성은 강하지만 장시간 사용 부담이 큼 |

최종 선택은 **B. 전체 작업공간 블루블랙**이다. 이유는 레퍼런스의 분위기를 살리면서도 실제 채팅 업무 화면에서 오래 사용 가능한 밀도를 유지하기 쉽기 때문이다.

## 적용 대상 파일

주요 적용 대상은 `web/` 패키지의 채팅 UI 계층이다.

| 파일 | 역할 | 변경 의도 |
| --- | --- | --- |
| `web/app/globals.css` | 전역 Tailwind/CSS 토큰 | dark token, sidebar token, blue-black utility 추가 |
| `web/app/layout.tsx` | 루트 레이아웃과 브라우저 theme color | dark theme meta color를 새 배경색과 맞춤 |
| `web/components/chat.tsx` | 채팅 shell | 전체 workspace background 적용 |
| `web/components/messages.tsx` | 메시지 스크롤 영역 | 빈 화면 glow와 scroll button 스타일 조정 |
| `web/components/greeting.tsx` | 빈 채팅 greeting | 레퍼런스 이미지에 가까운 중앙 greeting으로 변경 |
| `web/components/multimodal-input.tsx` | composer와 모델 선택 trigger | dark pill/panel 입력창, blue focus/send affordance 적용 |
| `web/components/chat-header.tsx` | 상단 컨트롤 | translucent header와 blue-black border 적용 |
| `web/components/app-sidebar.tsx` | 사이드바 브랜드/액션 | `Chatbot` 라벨을 `NEOS`로 변경하고 sidebar token 사용 |
| `web/tests/e2e/blueblack-theme.test.ts` | 회귀 테스트 | token, utility, class/test hook, mobile selector width 계약 검증 |

## 색상 토큰

전역 dark token은 near-black base와 low-saturation blue surface를 중심으로 구성한다.

| Token | 값 | 용도 |
| --- | --- | --- |
| `--background` | `hsl(225 38% 3%)` | 전체 페이지 배경 |
| `--foreground` | `hsl(220 32% 96%)` | 기본 텍스트 |
| `--card` | `hsl(222 39% 7%)` | 카드, 메시지 주변 표면 |
| `--popover` | `hsl(222 39% 7%)` | 팝오버, 모델 선택기 |
| `--primary` | `hsl(214 100% 58%)` | 주요 액션, 전송 버튼 |
| `--ring` | `hsl(214 100% 62%)` | focus ring |
| `--muted` | `hsl(222 24% 13%)` | 낮은 강조 표면 |
| `--muted-foreground` | `hsl(220 16% 68%)` | placeholder, 보조 텍스트 |
| `--border` | `hsl(220 31% 16%)` | 기본 border |
| `--input` | `hsl(220 31% 16%)` | 입력 표면 border |
| `--sidebar-background` | `hsl(225 38% 5%)` | 사이드바 배경 |
| `--sidebar-accent` | `hsl(220 44% 13%)` | 사이드바 hover/active |

이 값들은 회색 UI를 단순히 어둡게 만드는 대신, 검정에 가까운 바탕 위에 낮은 채도의 파란색 레이어를 쌓는 방식이다.

## 배경 유틸리티

전역 CSS에는 세 가지 유틸리티를 추가했다.

```css
.neos-blueblack-workspace
.neos-blueblack-empty
.neos-blueblack-panel
```

각 유틸리티의 책임은 분리된다.

- `neos-blueblack-workspace`
  - 전체 채팅 shell에 적용한다.
  - near-black base와 넓은 blue radial gradient를 가진다.

- `neos-blueblack-empty`
  - 메시지가 없는 초기 화면에 적용한다.
  - 중앙 greeting 뒤쪽의 블루 블룸을 더 분명하게 만든다.

- `neos-blueblack-panel`
  - composer 같은 입력 패널에 적용한다.
  - dark blue-black fill, soft blue border, subtle shadow를 제공한다.

이렇게 나누면 빈 화면의 장식성과 대화 화면의 가독성을 따로 조절할 수 있다.

## 컴포넌트별 변경 내용

### 1. Chat Shell

`web/components/chat.tsx`의 최상위 채팅 shell에 blue-black workspace class를 적용한다.

의도:

- 전체 화면이 기존 `bg-background` 단색에 머물지 않게 한다.
- 배경 효과를 전역 body가 아니라 채팅 shell에 두어 다른 라우트로 번지는 범위를 제한한다.
- `data-testid="blueblack-workspace"`를 추가해 Playwright에서 regression 확인이 가능하게 한다.

### 2. Empty Chat State

`web/components/messages.tsx`와 `web/components/greeting.tsx`를 함께 조정한다.

의도:

- 빈 채팅 화면에서만 blue bloom을 강하게 보여준다.
- greeting은 레퍼런스 이미지처럼 중앙 정렬과 얇은 타이포그래피를 사용한다.
- 제안 액션과 composer가 greeting을 침범하지 않도록 기존 layout 구조는 유지한다.

예상 copy:

```text
안녕하세요.
무엇을 도와드릴까요?
```

### 3. Composer

`web/components/multimodal-input.tsx`의 `PromptInput`을 dark pill/panel로 재구성한다.

의도:

- composer가 화면 하단에서 검푸른 표면으로 떠 있는 것처럼 보이게 한다.
- focus 상태에서는 blue ring과 border가 선명하게 나타난다.
- 전송 버튼은 `primary` blue affordance를 사용한다.
- compact model selector는 모바일에서 너무 넓지 않도록 `w-[156px] sm:w-[200px]` 형태로 조정한다.

### 4. Header

`web/components/chat-header.tsx`의 header는 불투명한 단색 대신 translucent surface로 만든다.

의도:

- 배경의 검푸른 분위기를 유지하면서도 컨트롤 가독성을 확보한다.
- 상단 경계선은 낮은 opacity의 blue border로 처리한다.

### 5. Sidebar

`web/components/app-sidebar.tsx`와 sidebar token을 같이 조정한다.

의도:

- 사이드바가 회색 panel이 아니라 같은 blue-black workspace의 일부처럼 보이게 한다.
- 브랜드 라벨은 `Chatbot`에서 `NEOS`로 바꾼다.
- delete/new chat icon button은 `sidebar-accent` 기반 hover state를 사용한다.

### 6. CodeMirror / Artifact Surface

`web/app/globals.css`의 CodeMirror dark surface는 `dark:bg-zinc-800` 대신 `dark:bg-card`를 사용한다.

의도:

- 코드 에디터와 artifact 계열 표면이 새 token을 자연스럽게 상속한다.
- 특정 회색 값에 묶이지 않도록 한다.

## 라인별 코드 문서화

아래 라인 번호는 실제 파일의 고정 줄 번호가 아니라, 각 코드 조각 안에서 설명을 위해 붙인 **로컬 라인 번호**다. 실제 구현 시 파일 주변 코드에 따라 줄 번호는 달라질 수 있다.

### 1. `web/app/globals.css` dark token block

```css
01 .dark {
02   --background: hsl(225 38% 3%);
03   --foreground: hsl(220 32% 96%);
04   --card: hsl(222 39% 7%);
05   --card-foreground: hsl(220 32% 96%);
06   --popover: hsl(222 39% 7%);
07   --popover-foreground: hsl(220 32% 96%);
08   --primary: hsl(214 100% 58%);
09   --primary-foreground: hsl(220 40% 98%);
10   --secondary: hsl(222 31% 11%);
11   --secondary-foreground: hsl(218 33% 92%);
12   --muted: hsl(222 24% 13%);
13   --muted-foreground: hsl(220 16% 68%);
14   --accent: hsl(219 43% 15%);
15   --accent-foreground: hsl(216 50% 92%);
16   --destructive: hsl(0 70% 44%);
17   --destructive-foreground: hsl(0 0% 98%);
18   --border: hsl(220 31% 16%);
19   --input: hsl(220 31% 16%);
20   --ring: hsl(214 100% 62%);
21   --chart-1: hsl(214 100% 58%);
22   --chart-2: hsl(190 92% 58%);
23   --chart-3: hsl(252 92% 70%);
24   --chart-4: hsl(158 68% 52%);
25   --chart-5: hsl(38 96% 62%);
26   --sidebar-background: hsl(225 38% 5%);
27   --sidebar-foreground: hsl(220 28% 91%);
28   --sidebar-primary: hsl(214 100% 58%);
29   --sidebar-primary-foreground: hsl(220 40% 98%);
30   --sidebar-accent: hsl(220 44% 13%);
31   --sidebar-accent-foreground: hsl(216 50% 92%);
32   --sidebar-border: hsl(220 33% 14%);
33   --sidebar-ring: hsl(214 100% 62%);
34   --sidebar: hsl(225 38% 5%);
35 }
```

| 라인 | 설명 |
| --- | --- |
| 01 | Tailwind dark variant가 참조하는 `.dark` scope다. 이 블록 안의 token만 바꿔도 대부분의 shadcn 스타일 컴포넌트가 새 색을 상속한다. |
| 02 | 전체 앱의 바탕색이다. 거의 검정에 가까운 deep navy라 기존 짙은 회색보다 더 깊게 보인다. |
| 03 | 기본 본문 텍스트 색이다. blue-black 배경 위에서 충분한 대비를 갖도록 cool white로 둔다. |
| 04-07 | card와 popover 표면이다. 메시지 주변 표면, 모델 선택기, dialog류가 회색이 아니라 blue-black surface로 보이게 한다. |
| 08-09 | primary action 색이다. 전송 버튼, active affordance, 주요 강조 색으로 사용한다. |
| 10-15 | secondary, muted, accent 계층이다. hover, disabled, 보조 UI가 같은 색상 계열 안에서 단계적으로 보이게 만든다. |
| 16-17 | destructive action은 blue-black과 분리되는 red 계열을 유지한다. 삭제/위험 동작의 의미를 잃지 않기 위함이다. |
| 18-20 | border, input, focus ring이다. 얇은 blue-gray border와 선명한 blue focus ring이 keyboard UX를 유지한다. |
| 21-25 | chart token이다. 그래프나 데이터 시각화가 있을 때 새 dark theme와 충돌하지 않게 blue/cyan/purple/green/yellow 계열로 재배치한다. |
| 26-34 | sidebar 전용 token이다. 사이드바를 별도 회색 패널로 두지 않고 전체 작업 공간과 같은 blue-black 계열로 통합한다. |
| 35 | dark token block 종료다. 이후 `@theme`에서 이 값들이 Tailwind color token으로 연결된다. |

### 2. `web/app/globals.css` blue-black utilities

```css
01 @layer utilities {
02   .neos-blueblack-workspace {
03     background:
04       radial-gradient(
05         ellipse 110% 72% at 56% 36%,
06         hsl(224 82% 29% / 0.2),
07         hsl(224 70% 14% / 0.1) 42%,
08         transparent 72%
09       ),
10       linear-gradient(180deg, hsl(225 38% 3%) 0%, hsl(220 38% 2%) 100%);
11   }
12
13   .neos-blueblack-empty {
14     background:
15       radial-gradient(
16         ellipse 76% 50% at 50% 45%,
17         hsl(224 84% 34% / 0.38),
18         hsl(225 58% 13% / 0.26) 42%,
19         transparent 74%
20       );
21   }
22
23   .neos-blueblack-panel {
24     background: hsl(222 42% 7% / 0.92);
25     border-color: hsl(218 48% 24% / 0.72);
26     box-shadow:
27       0 18px 70px rgb(2 8 30 / 0.48),
28       inset 0 1px 0 rgb(255 255 255 / 0.04);
29   }
30 }
```

| 라인 | 설명 |
| --- | --- |
| 01 | Tailwind v4의 utility layer에 커스텀 클래스를 등록한다. 컴포넌트 className에서 바로 사용할 수 있다. |
| 02 | 전체 채팅 workspace용 class다. 라우트 전체가 아니라 chat shell에만 붙여 시각 효과 범위를 제한한다. |
| 03-10 | workspace 배경을 두 레이어로 만든다. 위 radial gradient는 은은한 blue depth, 아래 linear gradient는 near-black base다. Biome formatting 후 실제 파일에서는 두 background layer가 같은 선언 안에서 이어진다. |
| 05 | glow 중심을 정중앙보다 약간 오른쪽 위로 둔다. 레퍼런스 이미지처럼 중앙부가 살아 있지만 UI를 덮지 않게 한다. |
| 06-08 | glow의 시작, 중간, 끝 투명도를 정의한다. active chat에서도 부담스럽지 않게 opacity를 낮춘다. |
| 10 | 페이지의 실제 바닥색이다. 아래로 갈수록 더 검게 가라앉아 입력창 주변이 안정적으로 보인다. |
| 13 | 빈 채팅 화면 전용 class다. 메시지가 없을 때만 더 강한 glow를 보여준다. |
| 16-19 | greeting 뒤쪽에 집중되는 radial bloom이다. workspace보다 opacity를 높여 첫 화면의 인상을 만든다. |
| 23 | composer, prompt panel처럼 떠 있는 표면에 쓰는 class다. |
| 24 | 패널 배경이다. 완전 불투명이 아니라 약간 투명하게 두어 뒤 배경과 자연스럽게 섞인다. |
| 25 | 패널 border다. 회색 선 대신 blue-gray 선으로 새 테마와 맞춘다. |
| 26-28 | outer shadow와 inset highlight다. 패널이 검은 화면 위에 너무 납작하게 붙어 보이지 않게 한다. |
| 30 | utility layer 종료다. |

### 3. `web/app/layout.tsx` browser theme color

```ts
01 const LIGHT_THEME_COLOR = "hsl(0 0% 100%)";
02 const DARK_THEME_COLOR = "hsl(225 38% 3%)";
```

| 라인 | 설명 |
| --- | --- |
| 01 | light mode의 브라우저 chrome 색은 기존 흰색을 유지한다. 이번 작업은 dark UI 개선이므로 light theme는 범위 밖이다. |
| 02 | mobile browser 주소창과 PWA chrome이 새 near-black background와 어울리도록 dark theme color를 교체한다. |

### 4. `web/components/chat.tsx` workspace shell

```tsx
01 <div
02   className="neos-blueblack-workspace overscroll-behavior-contain flex h-dvh min-w-0 touch-pan-y flex-col bg-background"
03   data-testid="blueblack-workspace"
04 >
```

| 라인 | 설명 |
| --- | --- |
| 01 | 기존 single-line div를 multi-line으로 바꿔 test id와 class를 명확히 분리한다. |
| 02 | 새 workspace utility를 가장 앞에 둔다. 뒤의 layout utility들은 기존 height, touch, flex behavior를 보존한다. |
| 03 | Playwright regression test가 배경 shell 존재를 확인할 수 있게 하는 안정적인 selector다. |
| 04 | chat shell 시작이다. 내부의 header, message area, composer dock은 이 배경 위에 배치된다. |

composer dock은 다음처럼 투명하게 둔다.

```tsx
01 <div className="sticky bottom-0 z-1 mx-auto flex w-full max-w-4xl gap-2 border-t-0 bg-transparent px-2 pb-3 md:px-4 md:pb-4">
```

| 라인 | 설명 |
| --- | --- |
| 01 | `bg-background`를 `bg-transparent`로 바꿔 composer 주변에서도 workspace gradient가 이어지게 한다. sticky, sizing, spacing은 그대로 둔다. |

### 5. `web/components/messages.tsx` empty-state glow

```tsx
01 <div
02   className={cn(
03     "relative flex-1 overflow-hidden",
04     messages.length === 0 && "neos-blueblack-empty"
05   )}
06 >
```

| 라인 | 설명 |
| --- | --- |
| 01 | 메시지 영역 wrapper를 multi-line JSX로 바꾼다. |
| 02 | 조건부 class 조합을 위해 `cn`을 사용한다. 이 파일에는 `import { cn } from "@/lib/utils";`가 필요하다. |
| 03 | 기존 `relative flex-1`에 `overflow-hidden`을 더해 glow가 영역 밖으로 어색하게 번지지 않게 한다. |
| 04 | 메시지가 하나도 없을 때만 강한 empty glow를 적용한다. 대화 중에는 콘텐츠 가독성을 우선한다. |
| 05-06 | class 조합과 wrapper 시작을 닫는다. |

scroll-to-bottom 버튼은 다음 기준으로 바꾼다.

```tsx
01 className={`-translate-x-1/2 absolute bottom-4 left-1/2 z-10 rounded-full border border-blue-300/20 bg-card/90 p-2 text-foreground shadow-[0_10px_35px_rgba(2,8,30,0.4)] backdrop-blur-xl transition-all hover:bg-accent hover:text-accent-foreground ${
02   isAtBottom
03     ? "pointer-events-none scale-0 opacity-0"
04     : "pointer-events-auto scale-100 opacity-100"
05 }`}
```

| 라인 | 설명 |
| --- | --- |
| 01 | 버튼 표면을 `bg-background`에서 `bg-card/90`로 바꿔 blue-black panel처럼 보이게 한다. border, shadow, blur도 같은 맥락이다. |
| 02-05 | 기존 show/hide behavior는 유지한다. 시각 스타일만 바꾸고 scroll 동작은 건드리지 않는다. |

### 6. `web/components/greeting.tsx` empty greeting

```tsx
01 <div
02   className="mx-auto mt-4 flex size-full max-w-3xl flex-col justify-center px-4 text-center md:mt-16 md:px-8"
03   key="overview"
04 >
05   <motion.div
06     className="font-light text-2xl text-foreground/90 md:text-3xl"
07   >
08     안녕하세요.
09   </motion.div>
10   <motion.div
11     className="mt-2 text-2xl text-muted-foreground md:text-3xl"
12   >
13     무엇을 도와드릴까요?
14   </motion.div>
15 </div>
```

| 라인 | 설명 |
| --- | --- |
| 01-04 | greeting container다. `text-center`를 추가해 레퍼런스 이미지처럼 중앙 질문형 화면을 만든다. |
| 05-09 | 첫 줄 greeting이다. `font-light`와 `text-foreground/90`로 과하게 굵지 않은 차분한 인상을 만든다. |
| 08 | 한국어 사용 맥락에 맞춰 첫 인사를 짧게 둔다. |
| 10-14 | 두 번째 줄 질문이다. muted color를 사용해 첫 줄보다 한 단계 낮은 위계를 만든다. |
| 13 | 레퍼런스 이미지의 핵심 문장 구조를 NEOS 톤에 맞춰 가져온다. |
| 15 | greeting container 종료다. |

### 7. `web/components/multimodal-input.tsx` composer panel

```tsx
01 <PromptInput
02   className="neos-blueblack-panel rounded-[28px] border p-3 backdrop-blur-xl transition-all duration-200 focus-within:border-blue-300/45 focus-within:ring-1 focus-within:ring-blue-300/35 hover:border-blue-300/30"
03   data-testid="prompt-composer"
04   onSubmit={(event) => {
05     event.preventDefault();
06     if (status !== "ready") {
07       toast.error("Please wait for the model to finish its response!");
08     } else {
09       submitForm();
10     }
11   }}
12 >
```

| 라인 | 설명 |
| --- | --- |
| 01 | 기존 `PromptInput` 컴포넌트는 유지한다. form submit behavior를 재작성하지 않는다. |
| 02 | blue-black panel utility와 rounded pill 스타일을 적용한다. focus-within은 textarea focus 시 composer 전체가 반응하게 만든다. |
| 03 | Playwright test가 composer를 안정적으로 찾을 수 있게 하는 test id다. |
| 04-11 | 기존 submit logic이다. status guard와 toast, submitForm 호출은 그대로 유지한다. |
| 12 | PromptInput 시작 태그 종료다. |

textarea와 버튼류는 다음 방향이다.

```tsx
01 <PromptInputTextarea
02   className="grow resize-none border-0! border-none! bg-transparent p-2 text-foreground text-sm outline-none ring-0 [-ms-overflow-style:none] [scrollbar-width:none] placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-0 focus-visible:ring-offset-0 [&::-webkit-scrollbar]:hidden"
03 />
04
05 <PromptInputSubmit
06   className="size-8 rounded-full bg-primary text-primary-foreground shadow-[0_0_24px_rgba(59,130,246,0.28)] transition-colors duration-200 hover:bg-primary/90 disabled:bg-muted disabled:text-muted-foreground disabled:shadow-none"
07 />
```

| 라인 | 설명 |
| --- | --- |
| 01-03 | textarea는 transparent로 유지하되 `text-foreground`를 명시해 새 token 위에서 글자색이 안정적으로 보이게 한다. |
| 05-07 | send button은 `primary` token 기반 blue affordance를 명확히 드러낸다. disabled 상태에서는 glow를 제거해 클릭 불가 상태가 보이게 한다. |

compact model selector는 모바일 composer에서 넘치지 않도록 다음 폭을 사용한다.

```tsx
01 <Button
02   className="h-8 w-[156px] justify-between px-2 sm:w-[200px]"
03   data-testid="compact-model-selector"
04   variant="ghost"
05 >
```

| 라인 | 설명 |
| --- | --- |
| 01-02 | 모바일 기본 폭은 `156px`, `sm` 이상에서는 `200px`로 둔다. 390px 폭에서 composer 내부 overflow 가능성을 줄이기 위한 조정이다. |
| 03 | source-level regression test가 compact selector 계약을 확인할 수 있게 한다. |
| 04-05 | 기존 ghost button 동작과 trigger 구조는 유지한다. |

### 8. `web/components/chat-header.tsx` translucent header

```tsx
01 <header className="sticky top-0 z-20 flex items-center gap-2 border-blue-300/10 border-b bg-background/65 px-2 py-1.5 backdrop-blur-xl md:px-2">
```

| 라인 | 설명 |
| --- | --- |
| 01 | header를 완전 불투명 배경에서 translucent layer로 바꾼다. `z-20`은 scroll 영역 위에 안정적으로 놓기 위한 값이고, `backdrop-blur-xl`은 배경과 컨트롤 사이의 시각적 분리를 만든다. |

### 9. `web/components/app-sidebar.tsx` sidebar brand

```tsx
01 <Sidebar className="group-data-[side=left]:border-sidebar-border/70 group-data-[side=left]:border-r">
02   ...
03   <span className="cursor-pointer rounded-md px-2 font-semibold text-lg text-sidebar-foreground tracking-normal hover:bg-sidebar-accent hover:text-sidebar-accent-foreground">
04     NEOS
05   </span>
06   ...
07 </Sidebar>
```

| 라인 | 설명 |
| --- | --- |
| 01 | 사이드바 경계선을 token 기반으로 돌린다. 기존 border 제거보다, 낮은 opacity의 border를 두는 편이 blue-black panel 경계를 읽기 쉽다. |
| 02 | 중간의 기존 SidebarHeader, SidebarMenu, Link 구조는 유지한다. |
| 03 | 브랜드 라벨이 sidebar token을 직접 사용하게 한다. hover도 muted gray가 아니라 sidebar accent로 통일한다. |
| 04 | 기존 `Chatbot` generic label을 제품명 `NEOS`로 바꾼다. |
| 05-07 | 라벨과 sidebar 종료 흐름이다. |

### 10. `web/tests/e2e/blueblack-theme.test.ts` regression test

```ts
01 import { readFile } from "node:fs/promises";
02 import { expect, test } from "@playwright/test";
03
04 const readSource = (path: string) => readFile(path, "utf8");
05
06 test.describe("Blue-black dark theme", () => {
07   test("defines the approved dark theme tokens and utilities", async () => {
08     const globals = await readSource("app/globals.css");
09
10     for (const token of [
11       "--background: hsl(225 38% 3%);",
12       "--card: hsl(222 39% 7%);",
13       "--popover: hsl(222 39% 7%);",
14       "--primary: hsl(214 100% 58%);",
15       "--ring: hsl(214 100% 62%);",
16       "--sidebar-background: hsl(225 38% 5%);",
17     ]) {
18       expect(globals).toContain(token);
19     }
20
21     expect(globals).toContain(".neos-blueblack-workspace");
22     expect(globals).toContain(".neos-blueblack-empty");
23     expect(globals).toContain(".neos-blueblack-panel");
24     expect(globals).toContain("radial-gradient(");
25     expect(globals).toContain("dark:bg-card!");
26     expect(globals).not.toContain("dark:bg-zinc-800!");
27   });
28 });
```

| 라인 | 설명 |
| --- | --- |
| 01-04 | Playwright runner 안에서 Node file read를 사용한다. 실제 route 접근이 auth/backend에 묶여 있어, 이 테스트는 소스 계약을 빠르게 검증하는 방식으로 둔다. |
| 06-08 | blue-black theme 관련 test suite와 첫 번째 test다. `globals.css`를 직접 읽어 token과 utility 존재를 확인한다. |
| 10-19 | 승인된 dark token 값이 유지되는지 확인한다. |
| 21-26 | workspace/empty/panel utility, radial gradient, CodeMirror `dark:bg-card` 전환, `dark:bg-zinc-800` 제거를 검증한다. |
| 27-28 | 첫 번째 source-level contract test를 닫는다. |

UI hook 연결 검증은 같은 파일에 다음 test로 둔다.

```ts
01 test("wires the workspace and composer hooks into chat UI", async () => {
02   const chat = await readSource("components/chat.tsx");
03   const input = await readSource("components/multimodal-input.tsx");
04   const sidebar = await readSource("components/app-sidebar.tsx");
05
06   expect(chat).toContain("neos-blueblack-workspace");
07   expect(chat).toContain('data-testid="blueblack-workspace"');
08   expect(chat).toContain("bg-transparent px-2 pb-3");
09
10   expect(input).toContain("neos-blueblack-panel");
11   expect(input).toContain('data-testid="prompt-composer"');
12   expect(input).toContain('data-testid="compact-model-selector"');
13   expect(input).toContain("w-[156px]");
14   expect(input).toContain("sm:w-[200px]");
15
16   expect(sidebar).toContain("border-sidebar-border/70");
17   expect(sidebar).toContain("NEOS");
18 });
```

| 라인 | 설명 |
| --- | --- |
| 01-04 | 관련 컴포넌트 소스를 읽는다. route rendering 대신 source-level hook 존재를 확인한다. |
| 06-08 | chat shell에 workspace class/test id가 붙고 composer dock이 transparent인지 확인한다. |
| 10-14 | composer panel, prompt composer hook, compact model selector hook과 모바일/desktop width token을 확인한다. |
| 16-17 | sidebar border token과 `NEOS` 브랜드 라벨을 확인한다. |
| 18 | test 종료다. |

## 테스트 및 검증 계획

자동 검증은 Playwright runner를 사용하되, 현재 blue-black theme test는 auth/backend 의존성을 피하기 위해 source-level contract test로 둔다.

대상 파일:

```text
web/tests/e2e/blueblack-theme.test.ts
```

검증 항목:

- dark theme CSS token이 승인된 값으로 정의되어 있는지
- `neos-blueblack-workspace`, `neos-blueblack-empty`, `neos-blueblack-panel` utility가 존재하는지
- CodeMirror dark surface가 `dark:bg-card`를 사용하고 `dark:bg-zinc-800`에 묶여 있지 않은지
- chat shell과 composer에 `data-testid="blueblack-workspace"`, `data-testid="prompt-composer"`가 연결되어 있는지
- compact model selector가 `w-[156px] sm:w-[200px]` 계약을 유지하는지
- 사이드바 border token과 `NEOS` 라벨이 소스에 유지되는지

실행 명령:

```bash
pnpm --dir web exec playwright test tests/e2e/blueblack-theme.test.ts --project=e2e
```

기존 채팅 smoke test도 함께 확인한다.

```bash
pnpm --dir web exec playwright test tests/e2e/chat.test.ts --project=e2e
```

단, 기존 chat smoke test는 `/` 접근 시 guest auth/backend 상태에 영향을 받는다. 로컬 백엔드가 떠 있지 않으면 `/api/auth/guest`가 실패할 수 있으므로, blue-black theme 회귀 자체는 위 source-level test로 우선 검증한다.

프로덕션 빌드 확인:

```bash
pnpm --dir web build
```

실제 검증 결과:

| 명령 | 결과 | 비고 |
| --- | --- | --- |
| `pnpm --dir web exec playwright test tests/e2e/blueblack-theme.test.ts --project=e2e` | 통과, 2 passed | source-level contract test |
| `pnpm --dir web exec biome check app/globals.css app/layout.tsx components/chat.tsx components/messages.tsx components/greeting.tsx components/multimodal-input.tsx components/chat-header.tsx components/app-sidebar.tsx tests/e2e/blueblack-theme.test.ts` | 통과 | 관련 파일 formatting/lint 확인 |
| `pnpm --dir web build` | 통과 | 제한된 네트워크에서는 Google Fonts fetch 실패가 있었고, 네트워크 허용 후 통과 |
| `git diff --check` | 통과 | whitespace error 없음 |

수동 브라우저 확인은 시도했지만, 현재 로컬 환경에서는 `/login`과 `/` 접근이 `/api/auth/guest`로 이어지고 백엔드 연결이 거부되어 500으로 막혔다. 따라서 visual QA는 백엔드 dev server 또는 auth mock이 준비된 상태에서 별도로 수행해야 한다.

## 수동 QA 체크리스트

브라우저에서 다음 화면을 확인한다.

- 데스크톱 빈 채팅 화면
  - 중앙 blue bloom이 보이는지
  - greeting과 composer가 겹치지 않는지
  - 전체 톤이 dark gray가 아니라 black/deep-blue로 읽히는지

- 데스크톱 대화 화면
  - 메시지 가독성이 유지되는지
  - 배경 glow가 콘텐츠를 방해하지 않는지
  - scroll-to-bottom 버튼이 새 테마와 어울리는지

- 모바일 폭 약 390px
  - header control이 겹치지 않는지
  - compact model selector가 composer 내부에서 넘치지 않는지
  - 가로 스크롤이 생기지 않는지

- 모델 선택기 / 팝오버
  - popover 배경이 `card`/`popover` token과 일관되는지
  - focus ring이 충분히 보이는지

## 접근성 기준

이번 개선은 어두운 분위기를 강화하지만, 가독성을 희생하지 않는 것을 기준으로 한다.

- primary text는 near-black background 위에서 충분한 대비를 가져야 한다.
- muted text는 placeholder와 보조 라벨로만 사용한다.
- focus ring은 keyboard navigation에서 명확히 보여야 한다.
- 버튼 disabled 상태는 배경과 구분되어야 한다.
- 글자 크기는 viewport width에 따라 임의로 축소하지 않는다.

## 구현 시 주의사항

1. `web/` 소스에는 기능 변경을 넣지 않는다.
   - chat request/response, upload, auth, model selection 로직은 유지한다.

2. 전역 token부터 수정한다.
   - 컴포넌트별 색상을 먼저 바꾸면 하드코딩이 늘어난다.
   - `globals.css` token이 대부분의 변화를 담당해야 한다.

3. 회색 hard-code는 필요한 곳만 제거한다.
   - 예: `dark:bg-zinc-800` 같은 surface 고정값.
   - 모든 `zinc` 사용을 한 번에 제거하는 대규모 리팩터링은 범위 밖이다.

4. `.superpowers/` mockup 산출물은 커밋하지 않는다.
   - visual brainstorming용 임시 산출물이므로 제품 문서나 코드와 분리한다.

5. 현재 문서는 구현 완료 기록을 겸한다.
   - 디자인 결정, 구현 가이드, 실제 반영 내용, 검증 결과를 함께 정리한다.
   - visual QA는 auth/backend 의존성이 준비된 환경에서 추가로 확인한다.

## 최종 기대 결과

개선이 반영된 뒤 사용자는 다음과 같은 첫인상을 받게 된다.

- NEOS가 단순한 회색 챗봇 UI가 아니라 깊이감 있는 AI 작업 공간처럼 보인다.
- 빈 화면은 레퍼런스 이미지처럼 검푸른 중심광을 가진다.
- 대화가 시작된 뒤에도 전체 workspace는 검정과 deep-blue 톤을 유지한다.
- composer, sidebar, header, popover가 같은 디자인 시스템에 속한 것처럼 느껴진다.
- 기존 채팅 기능은 그대로 동작한다.

# Blue-Black Frontend Background Redesign

작성일: 2026-05-24

## 개요

`neos-web`의 채팅 프론트엔드를 기존 짙은 회색 계열에서 **검은색과 검푸른 색을 조합한 다크 작업 공간**으로 재구성하기 위한 디자인/구현 기록이다.

이 개선안은 첨부 레퍼런스 이미지처럼 중앙부에 은은한 블루 블룸이 있고, 주변부는 거의 검정에 가까운 톤으로 가라앉는 시각 언어를 목표로 한다. 단순히 빈 채팅 화면만 꾸미는 것이 아니라, 사이드바, 헤더, 메시지 영역, 입력창, 팝오버까지 하나의 blue-black 시스템으로 묶는 방향이다.

현재 정리 상태:

- 디자인 방향은 **B. 전체 작업공간 블루블랙**으로 확정했다.
- 스펙과 구현 계획은 작성 및 커밋된 이력이 있다.
- 실제 `web/` 소스 반영은 별도 구현 단계에서 진행해야 한다.

관련 커밋:

- `f165e64 docs: add neos web blue-black design spec`
- `35c4be3 docs: add neos web blue-black implementation plan`

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

전역 CSS에는 세 가지 유틸리티를 추가하는 계획이다.

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

## 테스트 및 검증 계획

자동 검증은 Playwright e2e test를 추가하는 방식이 적합하다.

대상 파일:

```text
web/tests/e2e/blueblack-theme.test.ts
```

검증 항목:

- dark theme CSS token이 승인된 값으로 노출되는지
- `data-testid="blueblack-workspace"`가 렌더링되는지
- `data-testid="prompt-composer"`가 렌더링되는지
- 사이드바 라벨 `NEOS`가 보이는지

실행 명령:

```bash
pnpm --dir web exec playwright test tests/e2e/blueblack-theme.test.ts --project=e2e
```

기존 채팅 smoke test도 함께 확인한다.

```bash
pnpm --dir web exec playwright test tests/e2e/chat.test.ts --project=e2e
```

프로덕션 빌드 확인:

```bash
pnpm --dir web build
```

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

5. 현재 문서는 구현 완료 보고서가 아니다.
   - 디자인 결정과 구현 가이드를 통합한 문서다.
   - 실제 source 반영 후에는 이 문서의 상태를 `구현 완료`로 갱신할 수 있다.

## 최종 기대 결과

개선이 반영되면 사용자는 다음과 같은 첫인상을 받게 된다.

- NEOS가 단순한 회색 챗봇 UI가 아니라 깊이감 있는 AI 작업 공간처럼 보인다.
- 빈 화면은 레퍼런스 이미지처럼 검푸른 중심광을 가진다.
- 대화가 시작된 뒤에도 전체 workspace는 검정과 deep-blue 톤을 유지한다.
- composer, sidebar, header, popover가 같은 디자인 시스템에 속한 것처럼 느껴진다.
- 기존 채팅 기능은 그대로 동작한다.

# 프론트엔드 진화 — 1단계: 기반 (디자인 언어 · 셸 · 작업 흔적 프리미티브 · 표면 인벤토리)

- 날짜: 2026-10-11
- 상태: 설계 승인(섹션 1~4, 2026-10-11) · 스펙 검토 대기
- 범위: 다섯 단계 FE 진화 로드맵의 **1단계**. 2~5단계(챗 · 리포트 · 에이전트 · 코드 통합)는 각자 별도 spec 이다(§7)
- 대상: **외부 사용자용 제품**(사용자 결정 2026-10-11). 첫 출하 표면은 챗+멀티에이전트 검색 · 심층분석 · 코딩 에이전트 ·
  상시 에이전트 넷 전부다
- 접근: A안 — 공통 기반을 먼저 깔고 표면을 차례로 올린다(사용자 선택). B안(표면 먼저, 디자인 나중)은 템플릿 위에 화면을 쌓아
  리디자인 비용을 표면 수만큼 늘리고, C안(챗만 새로)은 네 표면 중 셋을 미루므로 버렸다

## 1. 배경 — 진단 (코드 대조 2026-10-11, `ead2efb5`)

> 로컬 웹·API 서버가 떠 있지 않아 **화면은 보지 않았다.** 아래 디자인 판단은 코드·토큰 독해다. §6.2 갤러리가 이 공백을 닫는다.

### 1.1 따라온 것 — 계약 층과 `/code`

- FE↔BE 이벤트 어휘는 fixture 세 쌍으로 양방향 고정돼 있다 — `tests/fixtures/{deep_analysis,coding}_event_kinds.json`,
  `chat_stream_event_types.json`. 모델 카탈로그는 `web/lib/ai/catalog.generated.ts` CI 재생성 diff 로 고정된다
- 코딩 UI(`web/features/coding/`)가 가장 많이 진화했다: phase 타임라인, 출력 원장, 워크스페이스 독(파일 트리 · diff · 터미널),
  steer, 샌드박스 상태, 재접속 복원, 승인 카드의 Jev 판정(`tool-risk.ts`)

### 1.2 따라오지 못한 것

| 영역 | BE | FE (2026-10-11) |
|---|---|---|
| Q 상시 에이전트 | 에이전트 · 활동 · 스레드 · 트리거 · 질문 · 알림 대상 · 멈춤, 비밀 · 기기 브리지 · 승인 규칙 — 엔드포인트 약 30개 | 사이드바 "Agent" 진입점 하나(`web/lib/standing-agent-api.ts`). 설계 문서들이 FE 를 미뤘다 — Q2 "규칙 UI — API 만 있다", Q9 §2.6 "FE 작업은 필요하지 않다" |
| 심층분석 | 검증 클레임 · 인용 · Jev 판정자(L6) | 카운터 카드 + 최종 markdown(`components/deep-analysis-status.tsx`). 클레임↔근거 연결 없음. `components/elements/inline-citation.tsx` 는 **쓰는 곳이 없다**. run 목록 API 도 없다(`neos/api/handlers/deep_analysis_handlers.py` 는 생성 · 이벤트 · 재개뿐) |
| 그래프 · 서브에이전트(G · I) | 설계 그래프 · 노드 서브에이전트 | 노드마다 접힌 Tool 카드 한 줄(`components/message.tsx` workflow_agents 블록). `@xyflow/react` 는 의존성에만 있다 |
| Jev | 도구 위험 · 감시자 · 인용 판정 | 코딩 승인 카드의 영문 배지 한 줄 |
| 챗 표면 | 멀티에이전트 워크플로우 | Vercel AI Chatbot 템플릿 그대로 — `getWeather` · `requestSuggestions` 도구와 렌더러, 반짝이 아바타, 템플릿 인사말(`components/greeting.tsx`). 챗 SSE 의 `function_call` 은 **워크플로우 노드 단위뿐**이라(`neos/api/adapters/stream_adapter.py` 120행 부근) 검색 질의 · 가져온 URL · 출처가 실려 오지 않는다 |
| 디자인 언어 | — | 상태 색 하드코딩 약 170곳(`text-green-600` 류, 2026-10-11 grep). 시맨틱 상태 토큰 없음. 다크는 승인된 blue-black(`blueblack-theme.test.ts`), **라이트는 shadcn 기본 zinc** — 두 모드가 다른 제품처럼 보인다. Geist 에 한글 글리프가 없어 한국어가 OS 시스템 폰트로 떨어진다. 챗은 한국어, `/code` 는 영어 |

**요약:** BFF 와 계약은 BE 와 함께 진화했지만 **제품 표면은 코딩 하나만** 진화했다. 첨단 에이전트 서비스와의 가장 큰 격차는
토큰이 아니라 **에이전트가 일하는 과정과 근거를 보여 주는 화면**(작업 단계 · 도구 활동 · 인용 근거 · 백그라운드 작업 인박스)이다.

### 1.3 구조적 원인

"FE 작업 불필요"는 각 Q 설계 문서 안에서 그 자리에 맞게 내려졌다. 그것들이 쌓여 구조적 공백이 됐다. 계약 fixture 는
"이벤트를 처리하는가(`handled`)"만 묻고 "사용자가 볼 수 있는가"는 묻지 않는다 — `neos:graph_subagent` 는 `handled: true` 인데
화면에는 한 줄이다. §6.1 인벤토리가 이 원인을 겨눈다.

## 2. 목표와 비목표

**목표 (1단계)**
1. 시맨틱 토큰 · 라이트 테마 · 한국어 서체 · 문구 사전으로 디자인 언어를 하나로 만든다(§3)
2. 네 작업 공간과 활동 인박스를 가진 공통 셸을 세운다(§4)
3. 네 표면이 공유할 작업 흔적 프리미티브 6종과 출처 무관 표시 모델을 만들고, 코딩 쪽에서 실사용으로 검증한다(§5)
4. FE 표면 인벤토리와 프리미티브 갤러리로 공백과 화면을 눈에 보이게 한다(§6)

**비목표 (이번 스펙 밖)**
- 런타임 i18n(언어 전환). 문구 사전만 키로 쓸 수 있게 둔다
- 인박스 실시간 푸시. 폴링으로 시작한다
- 그래프 캔버스 시각화(`@xyflow`). 2단계 이후 `StepTimeline` 으로 부족하다는 증거가 생기면 다시 다룬다
- 2~5단계의 표면 작업과 그 BE 변경(SSE 확장 · DA 목록 API 등)
- 픽셀 비교 시각 회귀 게이트

## 3. 디자인 언어

### 3.1 시맨틱 토큰 층

shadcn 토큰(`--primary` · `--muted` …)은 유지하고 그 위에 의미 토큰 네 묶음을 `app/globals.css` 의 `:root` 와 `.dark` 에 더한다.
`@theme` 에 `--color-*` 별칭을 등록해 Tailwind 유틸리티(`text-status-running` 등)로 쓴다.

| 묶음 | 토큰 | 쓰는 곳 |
|---|---|---|
| 작업 상태 | `--status-{running, waiting, paused, success, warning, danger, idle}` (옅은 배경은 별도 토큰 없이 Tailwind 불투명도 수식어 `bg-status-running/10`) | `RunStatus` · `StepTimeline` · 기존 하드코딩 상태 색 |
| 근거 | `--evidence-{verified, unverified, rejected}` | `ClaimEvidence` · DA 카운터 |
| 위험 대역 | `--risk-{low, mid, high, blocked}` | `VerdictBadge`(코딩 · DA · 감시자 공통) |
| 표면 깊이 | `--surface-{1, 2, 3}` | 패널 · 카드 · 카드 안 영역 |

`TraceStatus`(§5.2)와 `--status-*` 는 매핑 표 하나(`components/trace/status.ts`)로 1:1 연결한다. `queued`→`idle`,
`succeeded`→`success`, `failed`→`danger`, `cancelled`→`idle` 이고 나머지는 이름이 같다.

**금지 규칙:** `components/` · `features/` · `app/` 의 `.tsx` 에서 원시 팔레트 상태 클래스
(`(text|bg|border|ring|from|via|to)-(red|green|amber|yellow|blue|purple|emerald|orange|rose|sky|indigo)-\d{2,3}`)를 소스 테스트로 금지한다
(`web/tests/source/semantic-tokens.test.ts`). `components/ui/` (shadcn 원자)와 `components/icons.tsx` 는 검사 대상에서 빼되, 빼는 목록은
테스트 안에 이름으로 고정한다. **예외 하나:** 승인된 blue-black 다크 장식 클래스(`blueblack-theme.test.ts` 가 고정하는
`dark:border-blue-300/*` 류 — `chat-header.tsx` · `messages.tsx` · `multimodal-input.tsx`)는 `(파일, 클래스)` 쌍의 허용 목록으로 둔다.

**상태가 아닌 장식색의 치환:** `/code` 는 amber 를 상태가 아닌 강조색(타임라인 그라데이션, 아이콘 강조)으로도 쓴다. 장식 용도는
`--primary` 로 옮긴다 — `/code` 의 강조색이 amber 에서 블루로 바뀌는 **의도된 시각 변화**다(두 앱을 한 브랜드로, §3.2). 상태 용도는
§3.1 표의 토큰으로 간다.

### 3.2 라이트 테마

다크 blue-black 과 같은 색상 계열(primary 214°)로 라이트 토큰을 다시 정한다. 배경은 순백 대신 약간 푸른 기가 도는 흰색,
`--primary` 는 다크와 같은 hue 의 진한 판. `blueblack-theme.test.ts` 옆에 라이트 토큰 테스트를 더한다. 구체 값은 갤러리(§6.2)에서
두 모드를 나란히 보고 정한다 — 이 스펙은 "같은 hue 계열" 과 "대비 WCAG AA(본문 4.5:1)" 두 조건만 고정한다.

### 3.3 서체와 타입 스케일

- 라틴: Geist / Geist Mono (현행 유지)
- 한글: **Pretendard**, npm `pretendard@1.3.9`(OFL-1.1, `github.com/orioncactus/pretendard`, 2026-10-11 레지스트리 확인)를 정확한 버전으로
  고정하고 `next/font/local` 이 `node_modules` 의 **KS X 1001 서브셋 정적 woff2 네 굵기**(400 · 500 · 600 · 700, 각 약 270KB)를 읽는다.
  단일 가변 woff2 는 약 2MB 이고 동적 서브셋은 `unicode-range` CSS 1,700여 조각이라 `next/font` 로 표현되지 않는다 — 그래서 가변
  대신 정적 서브셋이다. 서브셋 밖의 드문 음절은 시스템 폰트로 떨어진다(받아들인 한계)
- `--font-sans: var(--font-geist), var(--font-pretendard), system-ui, sans-serif`
- 타입 스케일 6단계 토큰: `--text-{caption, body-sm, body, title-sm, title, display}` (크기 · 줄높이 짝). 본문 줄높이는 한글
  가독성을 위해 1.65 이상

> 패키지·폰트 출처는 설치 전에 레지스트리·원본 저장소에서 이름을 확인한다(메모리: 패키지 이름은 인덱스에서 확인).

### 3.4 문구 사전

- 사용자에게 보이는 문구를 표면별 사전으로 모은다: `web/lib/copy/<표면>.ts`. 파일은 그 표면을 만드는 단계가 만든다 —
  1단계는 `common`(셸 · 상태 · 자리 화면) · `code` · `chat` · `inbox`, `reports` · `agents` 는 3 · 4단계
- 각 파일은 `as const` 객체 하나를 export 한다. 키는 의미 이름(`code.stream.restoreFailed`)이고 값은 한국어
- `/code` 의 영문 사용자 문구는 5단계에서 이 사전으로 옮긴다. 1단계는 **새로 만드는 컴포넌트(셸 · 인박스 · 프리미티브)만** 사전을
  쓰고, 이식하는 코딩 승인 카드 · Jev 배지(§5.4)의 문구도 함께 사전으로 옮긴다. 단 **그 둘의 값은 1단계에서 지금의 영문 그대로 둔다** —
  코딩 소스 테스트가 aria-label(`Approve tool request` 등)과 배지 문자열(`jev 0.62 · mid`, `shadow`)을 고정하고 있어, 번역은 §5.4 회귀
  기준과 충돌한다. 번역은 5단계에서 테스트와 함께 한다
- 개발자 진단용 문자열(로그 · 에러 코드)은 사전에 넣지 않는다

### 3.5 템플릿 정체성 제거

- `web/lib/ai/tools/get-weather.ts` · `request-suggestions.ts` 와 렌더러(`components/weather.tsx`, `message.tsx` 의
  `tool-getWeather` · `tool-requestSuggestions` 분기) · 관련 타입(`lib/types.ts` 의 `ChatTools`)을 지운다. 두 도구는 **이미 죽은 코드다** —
  BFF 챗 라우트(`app/(chat)/api/chat/route.ts`)는 둘을 등록하지 않는다(2026-10-11 grep). 그래서 모델 행동은 바뀌지 않는다.
  `createDocument` · `updateDocument` 렌더 분기는 아티팩트 경로가 쓰므로 남긴다
- 반짝이 아바타를 NEOS 마크로 바꾼다(`components/icons.tsx` 에 SVG 하나)
- 첫 화면(`greeting.tsx` · `suggested-actions.tsx`)은 네 작업 방식(검색 · 심층분석 · 코딩 · 에이전트에게 맡기기)을 보여 주는 빈 상태로
  바꾼다. 검색 · 심층분석 카드는 **이미 있는 입력창에 예시 질의를 채운다**(보내지 않는다 — 사용자가 고쳐 보낸다). 코딩 카드는 `/code`
  로, 에이전트 카드는 에이전트 대화로 간다(§4.3 의 목적지와 같다). 첫 화면이 이미 대화 공간이라 컴포저 다이얼로그를 다시 여는 것은
  같은 자리로 돌아올 뿐이기 때문이다

### 3.6 모션

`--motion-{fast, base, slow}` (120 / 200 / 320ms) 세 단계와 이징 하나. `prefers-reduced-motion: reduce` 에서 이동 · 맥동은 끄고
불투명도 전환만 남긴다. 상태 맥동(`animate-pulse`) 은 `running` 상태에만 쓴다.

## 4. 앱 셸과 정보 구조

### 4.1 하나의 셸

`(chat)` · `(code)` 두 레이아웃을 공통 셸 컴포넌트(`components/shell/app-shell.tsx`) 위로 올린다. 라우트 그룹은 유지하고 각 그룹의
`layout.tsx` 가 같은 셸을 쓴다. 사이드바(`components/app-sidebar.tsx`)는 다음 구조로 바꾼다.

```
＋ 새 작업
◎ 활동 (n)
──────────
대화 · 리포트 · 코드 · 에이전트      ← 공간 내비게이션
──────────
최근 항목                           ← 현재 공간의 이력
──────────
설정 · 계정
```

| 공간 | 라우트 | 최근 항목 출처 | 1단계 상태 |
|---|---|---|---|
| 대화 | `/`, `/chat/[id]` | 기존 history | 동작 |
| 리포트 | `/reports` | DA run 목록 | **자리만** — 목록 API 가 3단계에서 생긴다. 빈 상태에 "곧 제공" 대신 채팅에서 시작한 심층분석이 대화 안에 있다는 안내 |
| 코드 | `/code`, `/code/tasks/[id]` | `GET /coding/tasks` (`CodingTaskList compact`) | 동작 |
| 에이전트 | `/agents` | `GET /standing-agents` | **자리만** — 관리 화면은 4단계. 1단계는 기존 "에이전트 대화 열기" 동작을 이 공간의 첫 행동으로 둔다 |
| 설정 | `/settings` | — | **자리만** — 규칙 · 비밀 · 기기 · 알림은 4단계 |

"자리만" 인 공간은 빈 상태 컴포넌트 하나(`components/shell/space-placeholder.tsx`)를 공유하며, 그 공간이 몇 단계에서 채워지는지
인벤토리(§6.1) 항목과 같은 문구로 말한다.

### 4.2 활동 인박스

사람이 나서야 할 일을 한 곳에 모은다. 1단계 항목 종류:

| 종류 | 출처 (BE) |
|---|---|
| 승인 · 질문 대기 | `GET /coding/tasks` 중 `status` 가 `waiting_approval` · `waiting_user` 인 작업(`neos/coding/domain/models.py` `CodingTaskStatus`). **에이전트가 사람에게 묻는 질문(Q9 묻고 기다리기)은 여기로 온다** — 상시 에이전트의 작업도 사용자 소유 코딩 작업이다(`neos/standing/tasks.py` `open_agent_task` 의 `owner_id=agent.owner_id`) |
| 멈춤 | `GET /coding/tasks` 중 `paused`(Q10b 봉투 멈춤은 작업을 멈춘다), `GET /standing-agents` 중 `status == "paused"`(Q5b 감시자 멈춤 등 — 사유는 4단계에서 보인다) |
| 실패 | `GET /coding/tasks` 중 `failed` |

> ⚠️ `GET /standing-agents/{id}/questions` 는 **에이전트의 질문이 아니다** — 사용자가 등록하는 cron 기반 "상시 질문"(Q3)이다.
> 인박스 출처가 아니다(2026-10-11 코드 대조로 바로잡음).

- BFF `GET /api/inbox` 가 위 두 호출을 병렬로 부르고(fan-out) `InboxItem[]` 로 정규화해 돌려준다. 새 BE 엔드포인트는 만들지 않는다.
  `GET /coding/tasks` 는 최근 활동 순 최대 50건이므로(`clamp_task_list_limit`) BFF 는 `limit=50` 으로 부른다 — 그보다 오래된 대기 작업은
  1단계 인박스에 보이지 않는다(받아들인 한계, 4단계 spec 이 BE 필터로 닫는다).
  상태 문자열은 BFF 한 곳(`lib/inbox/normalize.ts`)에서만 해석한다. 출처 하나가 실패해도 나머지는
  돌려주고, 실패한 출처를 `degraded: string[]` 로 함께 싣는다 — 실패를 빈 목록으로 숨기지 않는다
- 기능이 꺼진 출처(404 · 기능 off)는 실패가 아니라 "없음"이다(`openAgentConversation` 의 404 처리와 같은 규칙)
- 클라이언트는 30초 폴링 + 창 포커스 시 즉시 갱신. 배지는 항목 수
- 인박스는 `/inbox` 페이지다(사이드바 "활동" 이 연다). 시트가 아니라 페이지인 이유: 모바일에서는 사이드바 자체가 시트라 시트 안의
  시트가 되고, 페이지는 링크로 공유·새로고침된다
- 1단계 인박스는 **보기와 이동**만 한다. 항목을 누르면 그 작업 화면으로 간다. 인박스 안에서 답하기 · 승인하기는 4단계(질문) ·
  코딩 승인 카드가 이미 있는 작업 화면의 몫이다
- 챗 `approval_request` 는 스트림 안에서만 살아 있어 BE 에 조회 경로가 없다 → 1단계 인박스에서 뺀다(인벤토리에 이유 기록)

```ts
type InboxItem = {
  id: string;                 // `${source}:${sourceId}`
  source: "task_waiting" | "task_paused" | "task_failed" | "agent_paused";
  title: string;              // 문구 사전에서
  status: TraceStatus;        // waiting | paused | failed
  href: string;               // 이동 목적지
  createdAt: string;
};
```

### 4.3 새 작업 컴포저

"＋ 새 작업" 과 첫 화면 카드는 같은 컴포저를 연다. 1단계 범위는:
- 모드 칩 넷(검색 · 심층분석 · 코딩 · 에이전트에게 맡기기)과 각 모드의 목적지 라우팅
  - 검색 → 새 대화, 심층분석 → 새 대화, 코딩 → `/code` 새 작업, 에이전트 → 에이전트 대화
  - **심층분석은 FE 가 요청할 수 없다** — 지금은 BE 라우팅이 질의를 보고 DA 를 고른다(챗 요청 스키마
    `app/(chat)/api/chat/schema.ts` 에 DA 필드가 없다). 그래서 1단계의 심층분석 칩은 새 대화로 가고 "복잡한 조사 질문은 자동으로
    심층분석으로 이어진다" 는 안내만 붙인다. 명시적 DA 요청 필드는 3단계(리포트) spec 의 BE 변경이다
- 흩어진 모델 선택 · effort · 자율성 선택기를 컴포저 툴바 한 곳으로 모은다(컴포넌트는 기존 것을 재사용)

컴포저 내부 입력(첨부 · 슬래시 명령 등)은 기존 `multimodal-input.tsx` 를 그대로 쓴다. 2단계에서 다시 다룬다.

### 4.4 모바일

기존 `Sheet` 사이드바 유지. 인박스는 사이드바의 "활동" 항목으로 `/inbox` 페이지를 연다(§4.2). 코드 독의 모바일 탭 전환은 5단계.

## 5. 작업 흔적(trace) 프리미티브

### 5.1 경계

```
출처                                    어댑터 (순수 함수)         표시 모델          프리미티브
코딩 투영 CodingProjectionState ──┐
챗 메시지 UIMessage + metadata ───┤──► 출처별 to*Trace() ──► TraceStep[] 등 ──► components/trace/*
DA 진행 DeepAnalysisProgress ─────┤     (기능 폴더에 둔다)     (출처 무관)        (상태 · fetch 없음)
상시 에이전트 /activity ──────────┘
```

- 프리미티브는 **표시 모델만** 받는다. 스트림 · 소켓 · BFF 를 모른다. 내부 UI 상태(펼침 등)만 가진다
- 어댑터는 순수 함수이고 새 상태 저장소를 만들지 않는다 — 기존 투영 · 메시지에서 그때그때 유도한다
- 코딩 원장 투영과 AI SDK `parts` 의 모델 차이는 **어댑터 안에서만** 흡수한다
- 문장은 함수, 색은 토큰: "이 판정이 이 호출에 무슨 뜻인가" 를 말하는 문장 함수(`describeToolRisk` 류)는 출처마다 어댑터 옆에 둔다.
  프리미티브는 문장을 지어내지 않는다

### 5.2 표시 모델 (`web/components/trace/types.ts`)

```ts
export type TraceStatus =
  | "queued" | "running" | "waiting" | "paused"
  | "succeeded" | "failed" | "cancelled";

export type TraceStep = {
  id: string;
  label: string;
  status: TraceStatus;
  startedAt?: string;
  endedAt?: string;
  items: TraceItem[];
  children?: TraceStep[];   // depth-1 만. 서브에이전트 런타임의 depth-1 제약을 따른다
};

export type TraceItem =
  | { kind: "tool"; call: ToolActivityView }
  | { kind: "approval"; approval: ApprovalView }
  | { kind: "verdict"; verdict: VerdictView }
  | { kind: "evidence"; claim: ClaimView }
  | { kind: "question"; question: QuestionView }
  | { kind: "note"; text: string };

export type ToolActivityView = {
  id: string; name: string; status: TraceStatus;
  summary?: string;          // 어댑터가 지은 한 줄
  preview?: string;          // 결과 미리보기
  deniedReason?: string;
};

export type ApprovalView = {
  id: string; toolName: string;
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
  badge: string;             // 고정부 — 늘 보인다
  sentence: string | null;   // 의미 문장 — 어댑터의 문장 함수가 짓는다
};

export type ClaimView = {
  id: string; text: string;
  status: "verified" | "unverified" | "rejected";
  sources: { url: string; title?: string; excerpt?: string }[];
  verdict?: VerdictView;     // L6 판정자
};

export type QuestionView = { id: string; prompt: string; status: "open" | "answered" | "expired" };
```

이 타입은 초안이 아니라 **1단계가 고정하는 계약**이다. 필드를 더하는 것은 이후 단계에서 자유롭지만, 2~5단계가 필드를 빼거나
의미를 바꾸려면 그 단계 spec 이 이유를 적는다.

### 5.3 프리미티브 6종 (`web/components/trace/`)

| 프리미티브 | 추출 원본 | 받는 것 |
|---|---|---|
| `StepTimeline` | `features/coding/components/phase-timeline.tsx` · `phase-card.tsx` | `TraceStep[]` |
| `ToolActivity` | `components/elements/tool.tsx` + `CodingToolView` 렌더 | `ToolActivityView` |
| `ApprovalCard` | `features/coding/components/coding-approval-card.tsx` | `ApprovalView` + 행동 콜백(`onApprove` · `onDeny`) |
| `VerdictBadge` | `features/coding/components/tool-risk.ts` 의 배지 · 모드 | `VerdictView` |
| `ClaimEvidence` | `components/elements/inline-citation.tsx`(현재 미사용) | `ClaimView` |
| `RunStatus` | `deep-analysis-status.tsx` `headerState` + 코딩 run 상태 | `TraceStatus` + 선택적 행동(재개 · 정지) |

`StepTimeline` 은 `items` 의 kind 별로 나머지 프리미티브를 고른다. 모르는 kind 는 렌더하지 않고 개발 모드에서만 경고한다.

### 5.4 1단계가 실제로 옮기는 범위

- 프리미티브 6종 + `status.ts` 매핑
- **코딩 어댑터** `web/features/coding/trace.ts`: `CodingApprovalView`+`CodingToolRiskView` → `ApprovalView`/`VerdictView`,
  `CodingToolView` → `ToolActivityView`, phase → `TraceStep`
- `CodingApprovalCard` 를 `ApprovalCard` 위의 얇은 래퍼로 바꾼다. 승인 API 호출 · 낙관 갱신 등 행동은 래퍼에 남는다
- Jev 배지 렌더를 `VerdictBadge` 로 바꾼다. `toolRiskBadge` · `toolRiskMode` · `describeToolRisk` 는 **삭제하지 않고** 어댑터가
  `VerdictView.badge` · `mode` · `sentence` 를 채우는 데 쓴다 — 판정 문장의 정본은 계속 그 함수들이다
- 나머지 코딩 컴포넌트(phase 타임라인 · 원장 · 도구 행)의 전환은 5단계

**회귀 기준:** 기존 코딩 소스 테스트(`web/tests/source/coding-*.test.ts(x)`)를 고치지 않고 전부 통과해야 한다. 테스트가 DOM 문자열을
고정하는 탓에 고쳐야 한다면, 고친 테스트마다 "무엇이 같은 의미로 남았는가" 를 커밋 메시지에 적는다.

## 6. 계약과 검증

### 6.1 FE 표면 인벤토리

`tests/fixtures/fe_surface_inventory.json` 을 새로 둔다. 사용자에게 의미가 있는 BE 라우터 그룹을 **FastAPI `tags` 단위**로 적고,
각 태그는 `surface` 또는 `reason` 중 정확히 하나를 가진다.

```json
{
  "$comment": ["FE 표면 인벤토리 정본. 읽는 곳: tests/api/test_fe_surface_inventory.py · web/tests/source/fe-surface-inventory.test.ts"],
  "tags": [
    { "tag": "Coding Agent", "surface": { "routes": ["/code", "/code/tasks/[taskId]"], "bff": ["app/(code)/api/coding/tasks/route.ts"] } },
    { "tag": "Standing Agent Triggers", "reason": "4단계(에이전트) 예정 — API 만 있다" },
    { "tag": "Authentication", "reason": "BFF 내부 사용 — 사용자 표면이 아니다" }
  ]
}
```

- **BE 테스트** `tests/api/test_fe_surface_inventory.py`: BE 의 태그 집합을 만들고 인벤토리와 **정확히 일치**하는지 본다.
  인벤토리에 없는 태그도, BE 에 없는 인벤토리 태그도 빨갛다. 태그 집합은 **런타임 순회가 아니라 AST 스캔**으로 만든다 —
  `neos/main.py` 와 `neos/api/**` 에서 `APIRouter(...)` · `include_router(...)` · `_include_router_for_runtime(...)` 호출의 리터럴 `tags`
  를 모은다(`test_chat_stream_event_types.py` 와 같은 방식). 런타임 순회는 **설정에 따라 마운트가 달라져** 결과가 흔들린다 — 2026-10-11 실측에서
  `Coding Approval Rules` 는 마운트되지 않았고 상시 에이전트 태그는 개발 프로파일이 켜서 보였다. 리터럴이 아닌 `tags` 가 있으면 테스트가
  빨갛다(조용히 건너뛰지 않는다). 2026-10-11 기준 정적 태그는 31개다. 첫 단언으로 이웃 태그(`Coding Agent`, `Coding Agent WebSocket`)가
  보이는지 확인한다
- **FE 테스트** `web/tests/source/fe-surface-inventory.test.ts`: `surface.bff` 의 각 경로 파일이 존재하는지, `surface.routes` 의 각
  라우트가 `app/**/page.tsx` 로 존재하는지, `surface` 와 `reason` 이 동시에 있거나 둘 다 없는 항목이 없는지 본다
- 태그 단위인 이유: 엔드포인트 단위면 화면 하나에 묶이는 경로마다 줄이 생겨 `reason` 이 기계적으로 채워진다(메모리: 낡은 면제
  플래그는 가드를 조용히 끈다). `reason` 에 단계가 적힌 항목은 그 단계 spec 이 `surface` 로 바꿀 책임을 진다
- 디버그 전용 라우터(비디버그에서 제거되는 chat/query/workflow WS 등)는 `reason` 에 "디버그 전용" 으로 적는다

### 6.2 프리미티브 갤러리

- 개발 모드 전용 페이지 `web/app/(dev)/dev/trace/page.tsx`. `process.env.NODE_ENV !== "development"` 면 `notFound()`.
  `web/proxy.ts` 의 catch-all matcher 가 `/dev/*` 도 게스트 인증으로 돌려보내므로(게스트 생성은 BE 를 부른다), 개발 모드에서만
  `/dev/` 를 통과시키는 분기를 둔다 — 갤러리는 BE 없이 열려야 한다
- 프리미티브 6종을 fixture 표시 모델로 그린다. fixture 는 `web/tests/fixtures/trace/*.ts` 에 두고 소스 테스트와 공유한다.
  코딩 fixture 는 실제 코딩 이벤트 fixture 를 코딩 어댑터에 통과시킨 결과로 만든다(손으로 지은 표시 모델만 쓰지 않는다)
- 라이트 · 다크는 같은 페이지를 테마만 바꿔 두 번 찍는다 — 다크 토큰이 `.dark` 클래스에 걸려 있어(`globals.css` `@custom-variant dark`)
  한 페이지에 두 테마를 나란히 그리려면 라이트 토큰을 되돌리는 별도 클래스가 필요해지기 때문이다
- Playwright 스펙 `web/tests/e2e/trace-gallery.test.ts` 가 두 모드 스크린샷을 `web/test-results/` 아래에 남긴다. **비교 게이트는 걸지 않는다**
  — 디자인 리뷰 재료다
- 갤러리 라우트는 인벤토리 대상이 아니다(BE 태그가 아니므로)

### 6.3 소스 테스트 목록 (새로)

| 테스트 | 고정하는 것 |
|---|---|
| `semantic-tokens.test.ts` | `--status-*` 가 `:root` 와 `.dark` 양쪽에 있다 · 근거·위험·표면 토큰이 상태·기본 토큰을 가리킨다 · `@theme` 별칭 · 모션 |
| `raw-palette-ban.test.ts` | 원시 팔레트 색 클래스 금지(§3.1) · 허용 목록이 낡지 않았다 |
| `light-theme.test.ts` | 라이트 토큰이 primary hue 214° 계열이다 · 본문·보조·상태 글자가 배경 대비 4.5:1 이상(다크의 버튼 글자 쌍은 승인된 값이라 제외) |
| `trace-status.test.ts` | `TraceStatus` 7개가 모두 토큰으로 매핑된다 |
| `trace-primitives.test.tsx` | 6종 정적 렌더(`renderToStaticMarkup`) — 모르는 kind 무시, `VerdictView.sentence: null` 이면 배지만 |
| `coding-trace-adapter.test.ts` | 코딩 이벤트 fixture → 표시 모델. `describeToolRisk` 결과가 `sentence` 로 그대로 간다 |
| `inbox.test.ts` | 출처 하나 실패 → 나머지 + `degraded`, 404 → 없음, 둘 다 401 → 401, 시간 초과 → `degraded` |
| `template-tools-removed.test.ts` | `getWeather` · `requestSuggestions` 가 도구 등록부와 렌더러에 없다 |
| `fe-surface-inventory.test.ts` | §6.1 |

## 7. 단계 로드맵 (각 단계는 독립 spec → plan → 구현)

| 단계 | 내용 | BE 의존 |
|---|---|---|
| **1. 기반** (이 spec) | §3~§6 | 없음 |
| **2. 챗** | 워크플로우 단계를 `StepTimeline` 으로, 도구 호출을 `ToolActivity` 로, 출처를 `ClaimEvidence` 로. 새 작업 컴포저 내부 입력 | **챗 SSE 확장** — 도구 단위 이벤트 · 출처 이벤트 + `chat_stream_event_types.json` 갱신 |
| **3. 리포트** | `/reports` 목록 · 상세, 클레임↔근거 발췌 뷰, L6 판정 배지, 재개 | **`GET /deep-analysis` 목록 API.** 클레임 · 발췌 · 판정이 `job_completed` 에 없으면 리포트 상세 API |
| **4. 에이전트** | `/agents` 관리(트리거 · 예산 · 멈춤 · 활동), 인박스에서 질문 답하기(Q9), `/settings` 4종(규칙 · 비밀 · 기기 · 알림) | 없음(API 존재) — BFF 라우트만 |
| **5. 코드 통합** | 문구 사전 이식(한국어화), 남은 코딩 컴포넌트의 프리미티브 전환, 모바일 독 탭 | 없음 |

2단계와 3단계의 BE 변경은 각자 이벤트 fixture 짝 규칙을 거친다. 1단계 기반이 먼저 서 있으면 BE 를 바꾸자마자 화면이 따라온다.

## 8. 완료 기준 (1단계)

1. `semantic-tokens.test.ts` 초록 — 원시 팔레트 상태 클래스 0곳(제외 목록은 테스트에 이름으로)
2. 라이트 · 다크 토큰 테스트 초록
3. 템플릿 도구 2종이 등록부 · 렌더러 · 타입에서 사라졌다
4. 셸에서 네 공간 · 설정 · 인박스로 이동할 수 있다. "자리만" 공간은 빈 상태가 몇 단계에서 채워지는지 말한다
5. `GET /api/inbox` 가 §4.2 규칙대로 동작한다(소스 테스트)
6. 코딩 승인 카드 · Jev 배지가 공통 프리미티브 위에서 그려지고, 기존 코딩 소스 테스트가 전부 초록(§5.4 회귀 기준)
7. 인벤토리 테스트 BE · FE 양쪽 초록
8. 갤러리가 개발 모드에서 열리고 Playwright 가 두 모드 스크린샷을 남긴다
9. CI 명령을 로컬에서 그대로 통과한다 — `pnpm lint` · `pnpm typecheck` · `pnpm test:source`, 그리고 BE 테스트를 더하므로 backend-ci 의
   Ruff 명령과 경로 목록 그대로(메모리: CI 의 Ruff 명령을 로컬에서 그대로 돌린다)

## 9. 위험과 대응

| 위험 | 대응 |
|---|---|
| 코딩 소스 테스트가 DOM 문자열을 고정해 이식이 테스트 수정을 부른다 | §5.4 회귀 기준 — 고친 테스트마다 같은 의미로 남은 것을 적는다 |
| 하드코딩 색 치환이 의도된 예외(차트 · 구문 강조)까지 건드린다 | 제외 목록을 테스트에 이름으로 고정하고, 차트는 기존 `--chart-*` 를 쓴다 |
| 템플릿 도구 제거가 다른 경로를 깬다 | 두 도구는 등록되지 않은 죽은 코드다(§3.5). `ChatTools` 타입을 지울 때 `tool-createDocument` 류 분기가 같은 타입에 기대는지 `pnpm typecheck` 로 확인한다 |
| 인박스 팬아웃이 출처 수만큼 BE 호출을 늘린다 | 30초 폴링 + 포커스 갱신만. 출처별 타임아웃을 두고 늦은 출처는 `degraded` 로 |
| 셸 통합이 `(code)` 의 기존 레이아웃 동작(독 크기 등)을 깬다 | 셸은 본문 영역에 관여하지 않는다 — 사이드바 · 상단 바만 소유한다 |

# LLM 기반 인라인 시각화 채팅 시스템 구현 가이드

> **마지막 갱신:** 2026-05-30
> 이 문서는 NEOS 인라인 시각화 기능의 구현 가이드이자 레퍼런스입니다.
> 일반적인 Next.js + Vercel AI SDK 패턴(섹션 1-4)과 NEOS 실제 구현 패턴(섹션 5-6)을 모두 포함합니다.
> 현재 NEOS 구현은 `ChatStreamPipeline` + `ChunkEventDispatcher` 기반의 커스텀 SSE 경로를 사용합니다.

---

## 1. Next.js 기술 스택

### 핵심 기술 구성

| 계층 | 기술 | 역할 |
|------|------|------|
| 프레임워크 | Next.js 14+ (App Router) | 풀스택 프레임워크 |
| LLM 통신 | Vercel AI SDK (`ai`) | 스트리밍 응답, 도구 호출 추상화 |
| LLM 프로바이더 | `@ai-sdk/anthropic` 또는 `@ai-sdk/openai` | Claude/GPT API 연동 |
| 다이어그램 렌더링 | `mermaid` (커스텀 SVG 렌더러) | 플로우차트, 시퀀스 다이어그램 |
| 차트 | `recharts` | 데이터 시각화 |
| 마크다운 파싱 | `react-markdown` + `remark-gfm` | 마크다운 렌더링 |
| 스타일링 | Tailwind CSS + shadcn/ui | UI 컴포넌트 |
| 상태 관리 | React `useState`/`useReducer` | 채팅 상태 |

### NEOS 현재 구현 스냅샷 (2026-05-30)

| 항목 | 현재 코드 기준 | 위치 |
|------|----------------|------|
| 프론트엔드 | Next.js 16.2.6, React 19.0.1 | `web/package.json` |
| AI SDK | `ai` 5.0.108, `@ai-sdk/react` 2.0.109 | `web/package.json` |
| 마크다운 렌더링 | `streamdown` 래퍼 (`Response`) | `web/components/elements/response.tsx` |
| 다이어그램 | `mermaid` 11.15.0 | `web/package.json`, `web/components/mermaid-diagram.tsx` |
| 차트 | `recharts` 3.8.1 | `web/package.json`, `web/components/data-chart.tsx` |
| SSE 처리 | 커스텀 OpenResponses/Neos 이벤트 파서 | `web/hooks/use-chat-stream.ts` |
| BE 스트림 경로 | `ChatStreamPipeline` + `ChunkEventDispatcher` | `neos/api/services/` |

### 패키지 설치

```bash
npx create-next-app@latest ai-viz-chat --typescript --tailwind --app
cd ai-viz-chat

# 핵심 의존성
npm install ai @ai-sdk/anthropic
npm install react-markdown remark-gfm
npm install mermaid
npm install recharts
npm install zod  # 구조화된 출력 스키마 검증용
```

---

## 2. 에이전트 ↔ 프론트엔드 통신 방식

### 2.1 스트리밍 아키텍처 (핵심)

```
[프론트엔드]                    [Next.js API Route]              [LLM API]
     │                              │                              │
     │── POST /api/chat ──────────→ │                              │
     │   { messages[] }             │── streamText() ─────────────→│
     │                              │                              │
     │                              │←── SSE 스트림 (토큰 단위) ───│
     │←── ReadableStream ──────────│                              │
     │   (텍스트 + 도구 호출 혼합)   │                              │
     │                              │                              │
     │  [파싱] 텍스트 → 렌더링       │                              │
     │  [파싱] 도구 호출 → 시각화     │                              │
```

### 2.2 Vercel AI SDK 기반 통신 패턴

**서버 (Route Handler):**

```typescript
// app/api/chat/route.ts
import { anthropic } from "@ai-sdk/anthropic";
import { streamText, tool } from "ai";
import { z } from "zod";

export async function POST(req: Request) {
  const { messages } = await req.json();

  const result = streamText({
    model: anthropic("claude-sonnet-4-20250514"),
    system: SYSTEM_PROMPT,
    messages,
    tools: {
      renderDiagram: tool({
        description: "Mermaid 다이어그램을 생성하여 시각화합니다",
        parameters: z.object({
          title: z.string(),
          mermaidCode: z.string(),
          description: z.string().optional(),
        }),
      }),
      renderChart: tool({
        description: "데이터 차트를 생성합니다",
        parameters: z.object({
          type: z.enum(["bar", "line", "pie"]),
          data: z.array(z.object({
            label: z.string(),
            value: z.number(),
          })),
          title: z.string(),
        }),
      }),
    },
  });

  return result.toDataStreamResponse();
}
```

**클라이언트:**

```typescript
// app/page.tsx
"use client";
import { useChat } from "ai/react";
import { MessageRenderer } from "@/components/MessageRenderer";

export default function Chat() {
  const { messages, input, handleInputChange, handleSubmit, isLoading } =
    useChat({ api: "/api/chat" });

  return (
    <div>
      {messages.map((msg) => (
        <MessageRenderer key={msg.id} message={msg} />
      ))}
      <form onSubmit={handleSubmit}>
        <input value={input} onChange={handleInputChange} />
      </form>
    </div>
  );
}
```

### 2.3 통신 프로토콜 상세

Vercel AI SDK의 `Data Stream Protocol`은 SSE를 통해 다음 타입의 청크를 전송합니다:

| 접두사 | 의미 | 용도 |
|--------|------|------|
| `0:` | 텍스트 토큰 | 일반 응답 텍스트 |
| `9:` | 도구 호출 시작 | 시각화 도구 호출 감지 |
| `a:` | 도구 호출 결과 | 도구 실행 완료 |
| `e:` | 에러 | 오류 처리 |
| `d:` | 완료 | 스트림 종료 |

클라이언트의 `useChat` 훅이 이 프로토콜을 자동 파싱하여 `messages` 배열에 텍스트와 도구 호출을 분리하여 저장합니다.

---

## 3. 다이어그램 생성 에이전트 구현

### 3.1 시스템 프롬프트 설계

```typescript
const SYSTEM_PROMPT = `
당신은 콘텐츠 분석 및 시각화 전문 에이전트입니다.

## 핵심 역할
사용자가 제공하는 블로그 글, 문서, URL의 내용을 분석하여:
1. 핵심 내용을 구조화된 텍스트로 요약
2. 적절한 시각화 도구를 호출하여 인라인 다이어그램/차트 생성

## 시각화 판단 기준
다음 패턴이 감지되면 반드시 도구를 호출하세요:
- 단계별 프로세스 → renderDiagram (flowchart)
- 비교/대조 → renderChart (bar) 또는 renderDiagram
- 시간순 변화 → renderChart (line)
- 구성 비율 → renderChart (pie)
- 시스템 구조 → renderDiagram (architecture)
- 인과 관계 → renderDiagram (flowchart)

## 도구 호출 규칙
- 텍스트 설명 사이사이에 도구를 호출하세요 (끝에 몰아서 X)
- 하나의 응답에 여러 도구를 호출할 수 있습니다
- Mermaid 문법은 최신 버전을 사용하세요

## Mermaid 코드 작성 규칙
- 노드 텍스트에 특수문자 사용 시 따옴표로 감싸기
- 한글 지원 확인
- 색상/스타일은 classDef로 정의
`;
```

### 3.2 메시지 렌더러 (도구 호출 결과 시각화)

```typescript
// components/MessageRenderer.tsx
"use client";
import { Message } from "ai";
import { MermaidDiagram } from "./MermaidDiagram";
import { DataChart } from "./DataChart";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface Props {
  message: Message;
}

export function MessageRenderer({ message }: Props) {
  if (message.role === "user") {
    return <div className="user-bubble">{message.content}</div>;
  }

  return (
    <div className="assistant-message">
      {/* 텍스트 파트 렌더링 */}
      {message.content && (
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {message.content}
        </ReactMarkdown>
      )}

      {/* 도구 호출 결과 렌더링 — Strategy Pattern */}
      {message.toolInvocations?.map((invocation) => {
        if (invocation.state !== "result") return null;

        switch (invocation.toolName) {
          case "renderDiagram":
            return (
              <MermaidDiagram
                key={invocation.toolCallId}
                code={invocation.args.mermaidCode}
                title={invocation.args.title}
                description={invocation.args.description}
              />
            );
          case "renderChart":
            return (
              <DataChart
                key={invocation.toolCallId}
                type={invocation.args.type}
                data={invocation.args.data}
                title={invocation.args.title}
              />
            );
          default:
            return null;
        }
      })}
    </div>
  );
}
```

### 3.3 Mermaid 렌더링 컴포넌트

```typescript
// components/MermaidDiagram.tsx
"use client";
import { useEffect, useState } from "react";

// 모듈 레벨 싱글톤 — initialize()는 테마 변경 시에만 재호출
let mermaidInitialized = false;
let mermaidInitializedTheme: "dark" | "neutral" | null = null;

interface Props {
  code: string;
  title?: string;
  description?: string;
}

export function MermaidDiagram({ code, title, description }: Props) {
  const [svgContent, setSvgContent] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // 언마운트 후 setState 호출 방지 (메모리 누수 차단)
    let cancelled = false;

    async function render() {
      try {
        // 동적 import — Next.js SSR 환경에서 window 접근 오류 방지
        const mermaid = (await import("mermaid")).default;

        // 다크모드 감지: document 클래스로 테마 결정
        const isDark = document.documentElement.classList.contains("dark");
        const currentTheme: "dark" | "neutral" = isDark ? "dark" : "neutral";

        // 테마가 바뀌었거나 미초기화 시에만 initialize() 재호출
        if (!mermaidInitialized || mermaidInitializedTheme !== currentTheme) {
          mermaid.initialize({
            startOnLoad: false,
            theme: currentTheme,
            // "strict": HTML 노드 비허용 — LLM 생성 코드의 XSS 경로 차단
            securityLevel: "strict",
            fontFamily: "inherit",
          });
          mermaidInitialized = true;
          mermaidInitializedTheme = currentTheme;
        }

        const id = `mermaid-${Math.random().toString(36).slice(2)}`;
        const { svg } = await mermaid.render(id, code);

        if (!cancelled) {
          setSvgContent(svg);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Diagram render error");
        }
      }
    }

    render();
    return () => { cancelled = true; };
  }, [code]);

  if (error) {
    return (
      <div className="rounded-md border border-destructive/50 bg-destructive/5 p-3 my-2">
        <p className="text-xs text-muted-foreground mb-1">Diagram render failed</p>
        <pre className="text-xs font-mono text-foreground/70 whitespace-pre-wrap overflow-auto max-h-40">
          {code}
        </pre>
      </div>
    );
  }

  return (
    <div className="my-2 rounded-lg border bg-card p-3 shadow-sm overflow-auto">
      {title && (
        <p className="text-sm font-medium text-foreground mb-2">{title}</p>
      )}
      {svgContent ? (
        <div
          // biome-ignore lint/security/noDangerouslySetInnerHtml: mermaid SVG output is sanitized via securityLevel:"strict"
          dangerouslySetInnerHTML={{ __html: svgContent }}
          className="flex justify-center"
        />
      ) : (
        <div className="h-20 flex items-center justify-center">
          <span className="text-xs text-muted-foreground animate-pulse">Rendering diagram...</span>
        </div>
      )}
      {description && (
        <p className="text-xs text-muted-foreground mt-2">{description}</p>
      )}
    </div>
  );
}
```

### 3.4 프로젝트 구조

```
ai-viz-chat/
├── app/
│   ├── api/
│   │   └── chat/
│   │       └── route.ts          # LLM 스트리밍 엔드포인트
│   ├── layout.tsx
│   └── page.tsx                  # 채팅 UI
├── components/
│   ├── ChatInput.tsx             # 입력 폼
│   ├── MessageRenderer.tsx       # 메시지 + 시각화 라우터
│   ├── MermaidDiagram.tsx        # Mermaid SVG 렌더러
│   └── DataChart.tsx             # Recharts 래퍼
├── lib/
│   ├── prompts.ts                # 시스템 프롬프트
│   └── tools.ts                  # 도구 정의 (Zod 스키마)
└── package.json
```

---

## 4. 코딩 에이전트용 작업 프롬프트

아래 프롬프트를 코딩 에이전트(Claude Code, Cursor 등)에 그대로 전달하여 프로젝트를 생성할 수 있습니다.

---

```
# 프로젝트: LLM 기반 인라인 시각화 채팅 앱

## 개요
사용자가 블로그 URL이나 텍스트를 입력하면, LLM이 내용을 분석하고
텍스트 요약과 함께 Mermaid 다이어그램, 차트를 인라인으로 생성하는 채팅 앱.

## 기술 스택
- Next.js 14+ (App Router, TypeScript)
- Vercel AI SDK (`ai`, `@ai-sdk/anthropic`)
- Mermaid.js (다이어그램 렌더링)
- Recharts (데이터 차트)
- react-markdown + remark-gfm (마크다운 렌더링)
- Tailwind CSS + shadcn/ui (스타일링)
- Zod (도구 파라미터 스키마 검증)

## 구현 요구사항

### 1. API Route (`app/api/chat/route.ts`)
- Vercel AI SDK의 `streamText`로 Claude API 호출
- 두 가지 tool 정의:
  - `renderDiagram`: Mermaid 코드 생성 (title, mermaidCode, description?)
  - `renderChart`: 차트 데이터 생성 (type: bar|line|pie, data[], title)
- 시스템 프롬프트에 시각화 판단 기준을 명시
- 환경변수: ANTHROPIC_API_KEY

### 2. 채팅 UI (`app/page.tsx`)
- `useChat` 훅으로 메시지 상태 관리
- 다크 모드 지원
- 메시지 입력 폼 (하단 고정)
- 로딩 인디케이터

### 3. 메시지 렌더러 (`components/MessageRenderer.tsx`)
- 텍스트: react-markdown으로 렌더링
- toolInvocations 배열 순회하며 도구별 컴포넌트 분기
- Strategy Pattern: toolName → 렌더링 컴포넌트 매핑

### 4. Mermaid 컴포넌트 (`components/MermaidDiagram.tsx`)
- 동적 import(`await import("mermaid")`)로 Next.js SSR 오류 방지
- 모듈 레벨 `mermaidInitialized` 플래그 + `mermaidInitializedTheme`으로 테마 전환 시에만 재초기화
- `document.documentElement.classList.contains("dark")`로 다크모드 감지 → `theme: "dark"/"neutral"` 전환
- `securityLevel: "strict"` — LLM 생성 코드의 HTML 노드 XSS 경로 차단
- `cancelled` 플래그로 언마운트 후 `setState` 방지 (메모리 누수 차단)
- SVG를 state로 저장 후 `dangerouslySetInnerHTML`로 주입 (`useRef` DOM 직접 조작 X)
- 에러 시 원본 코드 + 오류 메시지 fallback 표시

### 5. 차트 컴포넌트 (`components/DataChart.tsx`)
- Recharts로 bar/line/pie 차트 렌더링
- 반응형 컨테이너 (ResponsiveContainer)
- BarChart: `Cell` 컴포넌트로 항목별 색상 부여 (단색 X)
- PieChart: Cell + Legend 포함
- `data.length === 0` 시 빈 차트 대신 "No data available" 메시지 표시

### 6. 도구 정의 분리 (`lib/tools.ts`)
- Zod 스키마로 도구 파라미터 타입 정의
- `description`은 optional — LLM이 생략해도 렌더링 정상 동작

### 7. 시스템 프롬프트 (`lib/prompts.ts`)
- 콘텐츠 분석 + 시각화 판단 규칙 포함
- 텍스트 사이사이에 도구 호출하도록 지시
- Mermaid 문법 규칙 포함

## 설계 원칙
- 컴포넌트는 단일 책임 원칙 준수
- 도구 렌더링은 Strategy Pattern으로 확장 가능하게
- 에러 바운더리로 시각화 실패가 전체 UI를 깨뜨리지 않도록
- 모든 타입은 TypeScript로 명시

## 디렉토리 구조
app/
  api/chat/route.ts
  layout.tsx
  page.tsx
components/
  ChatInput.tsx
  MessageRenderer.tsx
  MermaidDiagram.tsx
  DataChart.tsx
lib/
  prompts.ts
  tools.ts

## 실행
환경변수 ANTHROPIC_API_KEY 설정 후 `npm run dev`
```

---

## 5. 핵심 개념 요약

### 왜 Tool Use (Function Calling) 방식인가?

일반 텍스트 응답에서 Mermaid 코드블록을 파싱하는 방식도 가능하지만, Tool Use가 더 나은 이유:

| | 코드블록 파싱 | Tool Use |
|---|---|---|
| **구조화** | 정규식으로 추출 (깨지기 쉬움) | JSON 스키마로 보장 |
| **타입 안전성** | 없음 | Zod/Pydantic 스키마로 검증 |
| **메타데이터** | 제목/설명 별도 파싱 필요 | 파라미터로 함께 전달 |
| **확장성** | 새 시각화 추가 시 파서 수정 | 새 tool 정의만 추가 |
| **스트리밍** | 불완전한 코드블록 처리 어려움 | SDK가 완료된 호출만 전달 |

### NEOS 실제 데이터 흐름 (현재 코드 기준)

NEOS는 Vercel AI SDK의 `toolInvocations` 대신 **커스텀 SSE 이벤트 + 메시지 metadata** 방식을 사용합니다.

```
[BE] POST /conversations/{conversation_id}/messages/stream
    → chat_handlers.stream_message()
    → ChatStreamPipeline.run()
    → SystemPromptBuilder(...).with_artifacts().with_inline_vis().build()
        → INLINE_VIS_ENABLED=true이면 system prompt + get_inline_vis_tools() 추가
    → resolve_llm_strategy()
        → StandardStreamStrategy: builder가 만든 tools 목록을 그대로 사용
        → ToolSearchStreamStrategy: registry core_tools를 사용하고 builder tools 인자는 무시
    → LLM chunk: {type: "tool_use", tool_name: "renderDiagram", tool_input: ...}
    → ChunkEventDispatcher._handle_tool_use()
        → _handle_inline_vis()
        → execute_inline_vis_tool()
        → MermaidVizData / ChartVizData Pydantic 검증
        → NeosInlineVizEvent(viz_id, viz_type, data)
        → StreamAccumulator.inline_viz_list에 DB 저장용 metadata 누적
        → format_sse_event() → SSE: data: {"type":"neos:inline_viz", ...}

[FE] web/hooks/use-chat-stream.ts
    → isNeosInlineVizEvent(eventData)
    → inlineVizEntrySchema.safeParse(rawEntry)  # Zod 런타임 검증
    → assistantMessage.metadata.inline_visualizations에 append
    → updateMessage()

[FE] web/components/message.tsx
    → message.metadata.inline_visualizations.map()
    → viz_type === "mermaid" → <MermaidDiagram code={...} />
    → viz_type === "chart"   → <DataChart type={...} data={...} />
```

#### 현재 구현 파일 맵

| 계층 | 파일 | 역할 |
|------|------|------|
| 설정 | `neos/config/settings.py` | `INLINE_VIS_ENABLED`, `INLINE_VIS_SYSTEM_PROMPT` 정의 |
| 도구 정의 | `neos/tools/inline_vis_tools.py` | Anthropic tool-use 형식의 `renderDiagram`, `renderChart` 스키마 |
| 도구 실행 | `neos/tools/inline_vis_tool_handler.py` | 도구 입력을 내부 `{type: "inline_viz"}` 이벤트로 변환 |
| 시스템 프롬프트/도구 조립 | `neos/api/services/chat_system_prompt_builder.py` | feature flag가 켜진 경우 prompt와 tool 목록에 inline-vis 추가 |
| 스트림 라우팅 | `neos/api/services/chat_stream_pipeline.py` | 시스템 프롬프트/도구 구성, LLM 스트림 실행, assistant metadata 저장 |
| chunk 디스패치 | `neos/api/services/chat_chunk_dispatcher.py` | `tool_use` chunk를 inline-vis/artifact/disabled 경로로 분기 |
| BE 이벤트 모델 | `neos/api/models/open_responses.py` | `NeosInlineVizEvent`, `NeosInlineVizErrorEvent`, Pydantic data model |
| FE 이벤트 타입 | `web/lib/open-responses-types.ts` | `neos:inline_viz` 타입과 type guard |
| FE 런타임 검증 | `web/lib/types.ts`, `web/hooks/use-chat-stream.ts` | `messageMetadataSchema`에서 추출한 Zod 스키마로 SSE payload 검증 |
| FE 렌더링 | `web/components/message.tsx` | assistant message metadata의 시각화 목록 렌더링 |
| FE 시각화 컴포넌트 | `web/components/mermaid-diagram.tsx`, `web/components/data-chart.tsx` | Mermaid SVG 렌더링, Recharts 렌더링 |

#### UI 배치 주의사항

현재 프론트 구현은 `neos:inline_viz` 이벤트를 스트림 중간에 수신하더라도, 렌더링 시에는 `message.parts` 텍스트 렌더링 후 `message.metadata.inline_visualizations`를 한 번에 출력합니다. 따라서 현재 UX는 "응답 메시지 안의 인라인 시각화 블록"에 가깝고, 문단 사이에 정확히 삽입되는 true interleaving은 아닙니다.

문단 사이 삽입이 필요하면 SSE 이벤트 수신 시점의 텍스트 part 위치를 함께 저장하거나, `inline_visualizations`를 metadata가 아니라 message part 계층에 삽입하는 구조가 필요합니다.

#### Tool Search 경로 주의사항

`TOOL_SEARCH_ENABLED && ARTIFACTS_ENABLED`가 모두 `true`이면 `ToolSearchStreamStrategy`가 선택됩니다. 이 전략은 `SystemPromptBuilder`가 만든 `tools` 인자를 사용하지 않고 `_get_core_tools_cached()`의 registry core tools를 사용합니다. 현재 코드의 registry sync는 artifact tools만 core tool로 등록하므로, inline-vis 도구를 Tool Search 경로에서도 항상 노출하려면 다음 중 하나가 필요합니다.

- `renderDiagram` / `renderChart`를 registry core tool(`defer_loading=False`)로 동기화
- `ToolSearchStreamStrategy.create_stream()`에서 builder tools와 core tools를 병합
- inline-vis가 필요한 환경에서는 `TOOL_SEARCH_ENABLED=false`로 표준 tool-calling 경로 사용

---

## 6. 프로덕션 품질을 위한 설계 결정

### Mermaid securityLevel

| 값 | 동작 | 추천 상황 |
|---|---|---|
| `"strict"` | HTML 노드 비허용, SVG만 | **LLM 생성 코드** (기본값 권장) |
| `"loose"` | 임의 HTML 노드 허용 | 신뢰된 환경, 내부 도구 한정 |
| `"sandbox"` | iframe 격리 렌더링 | 사용자 직접 입력이 다이어그램 코드에 도달하는 경우 |

LLM 생성 코드는 직접적인 XSS 경로는 낮지만 **프롬프트 인젝션**을 통한 우회 가능성이 있으므로 `"strict"`를 기본으로 사용한다.

### Mermaid 다크모드 테마

`theme: "neutral"` 고정 시 다크모드에서 SVG 내부가 흰 배경으로 렌더링되어 시각적 불일치 발생.
`document.documentElement.classList.contains("dark")`로 테마를 감지하여 `"dark"/"neutral"` 간 전환한다.

```typescript
// 테마 변경 시에만 재초기화 — 싱글톤 플래그로 불필요한 initialize() 차단
let mermaidInitialized = false;
let mermaidInitializedTheme: "dark" | "neutral" | null = null;

const isDark = document.documentElement.classList.contains("dark");
const currentTheme = isDark ? "dark" : "neutral";

if (!mermaidInitialized || mermaidInitializedTheme !== currentTheme) {
  mermaid.initialize({ theme: currentTheme, securityLevel: "strict", ... });
  mermaidInitialized = true;
  mermaidInitializedTheme = currentTheme;
}
```

### Zod 스키마 — discriminated union

도구별 데이터 구조가 다를 때 `z.discriminatedUnion`을 사용하면:
- `viz_type` 값 기반으로 런타임 검증 스키마가 자동 선택됨
- TypeScript가 narrowing을 자동 처리 → 렌더링 컴포넌트에서 `as` 캐스팅 불필요

```typescript
// web/lib/types.ts
z.discriminatedUnion("viz_type", [
  z.object({
    id: z.string(),
    viz_type: z.literal("mermaid"),
    data: z.object({ title: z.string(), mermaidCode: z.string(), description: z.string().optional() }),
  }),
  z.object({
    id: z.string(),
    viz_type: z.literal("chart"),
    data: z.object({
      title: z.string(),
      type: z.enum(["bar", "line", "pie"]),
      data: z.array(z.object({ label: z.string(), value: z.number() })),
    }),
  }),
])
```

**SSE 이벤트 파싱 시점에 동일 스키마 재사용:**

```typescript
// messageMetadataSchema의 스키마를 SSE 경계에서도 재사용 → 단일 소스 검증
const inlineVizEntrySchema = messageMetadataSchema.shape.inline_visualizations.unwrap().element;

const parseResult = inlineVizEntrySchema.safeParse(rawEntry);
if (!parseResult.success) {
  console.error("[InlineViz] 검증 실패:", parseResult.error.flatten());
} else {
  // TypeScript narrowing 자동 적용 — as 캐스팅 불필요
  assistantMessage.metadata.inline_visualizations.push(parseResult.data);
}
```

### Pydantic typed union — BE 경계 검증

BE에서 `data: Dict[str, Any]`를 그대로 전달하면 클라이언트에서 `undefined.something` 에러가 발생할 수 있다.
현재 BE 모델은 `viz_type` 필드를 event 레벨에 두고, `data` 필드는 `Union[MermaidVizData, ChartVizData]`로 타입화한다. `ChunkEventDispatcher`에서 `viz_type`에 맞는 Pydantic 모델로 먼저 검증하므로 잘못된 페이로드를 BE에서 조기 차단한다.

```python
# neos/api/models/open_responses.py
class MermaidVizData(BaseModel):
    title: str
    mermaidCode: str
    description: Optional[str] = None   # optional — FE 스키마와 정렬

class ChartDataPoint(BaseModel):
    label: str
    value: float

class ChartVizData(BaseModel):
    title: str
    type: Literal["bar", "line", "pie"]
    data: list[ChartDataPoint]

class NeosInlineVizEvent(BaseModel):
    type: Literal["neos:inline_viz"] = "neos:inline_viz"
    viz_id: str
    viz_type: Literal["mermaid", "chart"]
    data: Union[MermaidVizData, ChartVizData]  # Dict[str, Any] 대신 typed union
```

```python
# neos/api/services/chat_chunk_dispatcher.py — 도구 이벤트 처리
if viz_type == "mermaid":
    validated_data = MermaidVizData(**raw_data)       # 검증 실패 시 ValidationError
else:
    validated_data = ChartVizData(title=..., type=..., data=...)

inline_viz_event = NeosInlineVizEvent(viz_id=..., viz_type=viz_type, data=validated_data)
viz_entry = inline_viz_event.model_dump()   # 수동 딕셔너리 구성 대신 model_dump() 재사용
```

### 타입 정렬 상태와 남은 드리프트

현재 의도된 계약은 `renderDiagram.description`을 optional로 취급하는 것이다.

| 경계 | 현재 상태 |
|------|-----------|
| Anthropic tool schema | `required: ["title", "mermaidCode"]` — `description` optional |
| BE Pydantic | `MermaidVizData.description: Optional[str] = None` |
| FE Zod runtime schema | `description: z.string().optional()` |
| FE React props | `description?: string` |
| FE TypeScript interface | `web/lib/open-responses-types.ts`의 `MermaidVizData.description`은 아직 `string`으로 선언됨 |

런타임 경계는 optional로 정렬되어 있으므로 실제 스트림 처리는 안전하다. 다만 다음 코드 정리 시 `web/lib/open-responses-types.ts`의 interface도 `description?: string`으로 맞추면 정적 타입과 런타임 계약이 완전히 일치한다.

### Non-fatal 에러 이벤트 전파

시각화 도구 실패 시 스트림을 종료하지 않고 별도 에러 이벤트로 클라이언트에 알린다.
기존 `ResponseFailedEvent`(스트림 종료)와 달리 채팅 응답은 계속 흐른다.

```python
# BE: neos/api/models/open_responses.py
class NeosInlineVizErrorEvent(BaseModel):
    type: Literal["neos:inline_viz_error"] = "neos:inline_viz_error"
    tool_name: str
    error: str

# neos/api/services/chat_chunk_dispatcher.py — 에러 처리
elif event_type == "error":
    error_event = NeosInlineVizErrorEvent(tool_name=tool_name, error=err_msg)
    yield format_sse_event(error_event)   # 스트림 중단 없이 에러만 전송
```

```typescript
// FE: use-chat-stream.ts
else if (isNeosInlineVizErrorEvent(eventData)) {
  console.warn(`[InlineViz] ${eventData.tool_name} 렌더링 실패: ${eventData.error}`);
  // toast 알림은 추후 UX 개선 시 추가
}
```

### Feature flag 조합과 변수 초기화

여러 feature flag가 독립적으로 같은 변수를 조건부로 수정하는 패턴에서는,
변수를 반드시 플래그 블록 **이전에** 기본값으로 초기화해야 한다.

```python
# 안전한 패턴
tools: list = []
if FEATURE_A_ENABLED:
    tools = get_feature_a_tools()
if FEATURE_B_ENABLED:
    tools = tools + get_feature_b_tools()  # FEATURE_A가 꺼져도 안전
```

현재 리팩터링된 경로에서는 `SystemPromptBuilder`가 이 패턴을 캡슐화한다.

```python
# neos/api/services/chat_system_prompt_builder.py
def with_inline_vis(self) -> "SystemPromptBuilder":
    if app_settings.INLINE_VIS_ENABLED:
        self._parts.append(app_settings.INLINE_VIS_SYSTEM_PROMPT)
        self._tools.extend(get_inline_vis_tools())
    return self
```

**Feature flag 비활성화 시 도구 호출 방어:**

LLM이 이전 세션의 system prompt 캐시로 `renderDiagram`을 호출할 수 있다.
`else` 분기 없이 방어 로직을 추가하지 않으면 아티팩트 핸들러가 unknown tool 에러를 일으킨다.

```python
# neos/api/services/chat_chunk_dispatcher.py
if app_settings.INLINE_VIS_ENABLED and is_inline_vis_tool(tool_name):
    # 정상 처리
    ...
elif is_inline_vis_tool(tool_name):
    # INLINE_VIS_ENABLED=false인데 LLM이 호출한 경우 — 명시적 스킵
    logger.warning(f"[InlineVis] {tool_name} called but INLINE_VIS_ENABLED=false. Skipping.")
else:
    # 아티팩트 도구 처리
    ...
```

### React.memo 비교 함수 주의사항

React.memo의 두 번째 인자(비교 함수)에서 반환값의 의미:
- `true` = "같다" → **재렌더링 안 함**
- `false` = "다르다" → **재렌더링 필요**

직관과 반대다. 모든 조건 검사를 통과한 후 최종 반환값이 `false`이면 memo 최적화가 완전히 무효화된다.

```typescript
const MemoizedPreviewMessage = memo(
  PurePreviewMessage,
  (prevProps, nextProps) => {
    if (prevProps.isLoading !== nextProps.isLoading) return false;     // 다르면 재렌더링
    if (!equal(prevProps.message.metadata, nextProps.message.metadata)) return false;
    // ...
    return true;  // ← 모두 같으면 재렌더링 안 함 (false가 아님!)
  }
);
```

### BarChart 항목별 색상 — Cell 컴포넌트

`<Bar fill={CHART_COLORS[0]} />`으로 단색을 지정하면 모든 막대가 동일색으로 표시된다.
`Cell` 컴포넌트를 사용하면 항목별로 색상을 순환 적용할 수 있다.

```typescript
<Bar dataKey="value" radius={[3, 3, 0, 0]}>
  {chartData.map((_, index) => (
    <Cell
      key={`bar-cell-${index}`}
      fill={CHART_COLORS[index % CHART_COLORS.length]}
    />
  ))}
</Bar>
```

PieChart는 이미 동일 패턴을 사용하므로 일관성이 유지된다.

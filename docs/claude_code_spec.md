# 클로드 코드 소스 코드 분석서

> 분석 대상: `claude code source code (2026-03-31)`
> 분석 일자: 2026-04-01
> 총 소스 파일: 약 1,884개 (TypeScript + React)

Anthropic의 Claude Code 전체 소스 코드가 노출되었습니다. 본 장에서는 해당 소스 코드에 대한 심층 분석 내용을 공유합니다. 다만, 소스 코드 분석서임에도 불구하고 유출된 소스 코드는 단 한 줄도 직접 공개하지 않습니다. 대신 전체 구조, 기능, 동작 흐름을 중심으로 분석을 진행했습니다. 소스 코드 분석서 공유에 대한 공정성 논란의 여지가 있을 수 있으나, Claude Code를 보다 깊이 이해하고 효과적으로 활용하는 데 도움이 될 것이라는 판단 하에 공유드립니다.

---

## 요약: 세 문장으로 이해하기

Claude Code는 사용자의 자연어 요청을 받아 AI가 어떤 도구를 써야 하는지 판단하고, 권한 확인을 거쳐 안전하게 실행한 후, 결과를 다시 AI에게 돌려주는 루프를 핵심으로 한다. 이 루프를 감싸는 시스템들(인증, 설정, 상태 관리, MCP, 플러그인, 브리지, 코디네이터)이 다양한 환경과 사용 사례를 지원한다. 모든 설계 결정은 안전성(위험한 작업 차단), 성능(스트리밍, 병렬 실행, 캐싱), 확장성(도구, 스킬, 플러그인, MCP)의 세 가지 원칙을 따른다.

---

## 1. Claude Code란 무엇인가

Claude Code는 Anthropic이 만든 공식 CLI(터미널 명령줄) 도구다. 사용자가 터미널에서 Claude AI와 대화하면서 코드를 읽고, 수정하고, 실행할 수 있게 해준다. 단순한 챗봇이 아니라, 파일을 직접 편집하고, 셸 명령을 실행하고, 웹을 검색하고, 외부 서비스와 연동하는 "AI 소프트웨어 엔지니어"에 가깝다.

비유하자면, 일반적인 AI 챗봇이 "전화 상담원"이라면, Claude Code는 "현장에 직접 와서 일하는 엔지니어"다. 상담원은 조언만 줄 수 있지만, 현장 엔지니어는 실제로 장비를 만지고 문제를 고칠 수 있다. Claude Code가 바로 그런 존재다 — 사용자의 컴퓨터에서 직접 파일을 열어보고, 코드를 수정하고, 테스트를 실행한다.

기술적으로는 TypeScript로 작성되었고, 터미널 UI는 React 기반의 TUI(Terminal User Interface) 프레임워크인 Ink를 사용한다. 상태 관리는 Zustand 라이브러리를 채택했으며, 빌드 시스템은 bun을 사용해서 사용하지 않는 코드를 자동으로 제거(tree-shaking)한다.

---

## 2. 전체 구조를 한눈에 보기

Claude Code의 동작은 크게 네 단계로 요약할 수 있다. 이 네 단계를 이해하면 1,884개 파일 각각이 어디에 속하는지 자연스럽게 파악할 수 있다.

```
+---------------------+
|   User types in     |
|   the terminal      |
+---------+-----------+
          |
          v
+---------------------+     Phase 1: STARTUP
|     main.tsx        |     - Auth (OAuth / API key / Bedrock / Vertex)
|  (initialization)   |     - Model selection
|                     |     - Load settings & feature gates
+---------+-----------+     - Collect Git status + CLAUDE.md
          |
          v
+---------------------+     Phase 2: QUERY LOOP
|     query.ts        |     - Send messages to Claude API (streaming)
|   (core engine)     |<-+  - Receive response token by token
|                     |  |  - Detect tool_use blocks in response
+---------+-----------+  |
          |              |
          v              |
+---------------------+  |  Phase 3: TOOL EXECUTION
|   Tool Pipeline     |  |  - Validate input (Zod schema)
|  (45+ built-in      |  |  - Check permissions (rules + classifier)
|   tools + MCP)      |  |  - Execute tool (Bash, Read, Edit, ...)
+---------+-----------+  |  - Return result to API
          |              |
          +--------------+  (loop until no more tool_use)
          |
          v
+---------------------+     Phase 4: DISPLAY
|   Ink TUI (React)   |     - Render messages, diffs, progress
|  terminal display   |     - Show tool results
+---------------------+     - Await next user input
```

**첫째, 시작과 초기화.** 사용자가 터미널에서 Claude Code를 실행하면, 프로그램이 인증을 처리하고, 어떤 AI 모델을 쓸지 결정하고, 사용자 설정을 불러오고, 현재 프로젝트의 Git 상태와 CLAUDE.md 파일 같은 컨텍스트를 수집한다.

**둘째, 대화 루프.** 사용자가 메시지를 입력하면, 그 메시지를 Claude API에 보내고, 스트리밍으로 응답을 받는다. 응답 중에 "파일을 읽어라", "명령을 실행해라" 같은 도구 사용 요청이 포함되어 있으면, 해당 도구를 실행하고 결과를 다시 API에 보낸다. 이 과정이 더 이상 도구를 쓸 필요가 없을 때까지 반복된다.

**셋째, 도구 실행.** 파일 읽기, 파일 수정, 셸 명령 실행, 웹 검색 등 45개 이상의 도구가 내장되어 있다. 각 도구는 실행 전에 입력 검증과 권한 확인을 거치며, 위험한 작업은 사용자에게 확인을 요청한다.

**넷째, 결과 표시.** 터미널에 대화 내용, 도구 실행 결과, 파일 변경 사항 등을 보기 좋게 렌더링한다.

이 네 단계의 핵심은 2단계와 3단계 사이의 루프다. 사용자가 "이 버그를 고쳐줘"라고 한 번 입력하면, Claude Code는 내부적으로 파일을 읽고(도구 실행) → AI가 분석하고 → 파일을 수정하고(도구 실행) → AI가 검증하고 → 테스트를 실행하고(도구 실행) → 결과를 확인하는 과정을 여러 턴에 걸쳐 자동으로 반복한다. 사용자 입장에서는 한 번 요청하면 결과만 받지만, 내부에서는 수많은 API 호출과 도구 실행이 일어나는 것이다.

---

## 3. 실행 모드

Claude Code는 하나의 프로그램이지만, 상황에 따라 여러 모드로 동작한다. 이것은 마치 하나의 자동차가 도로에서는 일반 모드, 오프로드에서는 4WD 모드, 주차할 때는 저속 모드로 전환되는 것과 같다. 핵심 엔진(query.ts)은 동일하지만, 입력과 출력을 처리하는 방식이 달라진다.

```
                    +------------------+
                    |   Claude Code    |
                    +--------+---------+
                             |
        +----------+-----------+-----------+----------+
        |          |           |           |          |
        v          v           v           v          v
   +---------+ +--------+ +----------+ +--------+ +--------+
   |  REPL   | |Headless| |Coordinator| |Bridge | |Kairos  |
   |  Mode   | | Mode   | |  Mode    | | Mode  | | Mode   |
   +---------+ +--------+ +----------+ +--------+ +--------+
   Interactive  No UI,     Leader +     Local CLI  Always-on
   terminal UI  SDK/pipe   Workers      <-> Cloud  assistant
```

**REPL 모드**는 가장 일반적인 대화형 모드다. 터미널에 React 기반 UI가 렌더링되고, 사용자가 메시지를 입력하고 응답을 받는다.

**헤드리스 모드**는 UI 없이 프로그래밍 방식으로 실행되는 모드다. Agent SDK나 파이프라인에서 Claude Code를 사용할 때 이 모드가 쓰인다. QueryEngine이라는 클래스가 이 모드의 핵심이며, 쿼리 루프를 감싸서 외부 프로그램이 쉽게 호출할 수 있게 해준다.

**코디네이터 모드**는 하나의 "리더" 에이전트가 여러 "워커" 에이전트를 동시에 관리하는 멀티에이전트 모드다. 리더가 작업을 분배하고, 워커들이 병렬로 파일을 조사하거나 코드를 수정한 뒤, 리더가 결과를 종합한다.

**브리지 모드**는 로컬 터미널의 Claude Code를 클라우드의 claude.ai 웹 인터페이스와 연결하는 모드다. 웹에서 입력한 명령이 로컬 환경에서 실행되고, 결과가 다시 웹으로 전송된다.

**어시스턴트 모드(Kairos)**는 상시 대기하는 프로액티브 어시스턴트 모드이고, **데몬 모드**는 백그라운드에서 실행되는 모드, **뷰어 모드**는 원격 세션을 읽기 전용으로 관찰하는 모드다.

어떤 모드를 사용하든 내부의 핵심 엔진은 동일하다. 차이점은 "사용자 입력을 어디서 받느냐"(터미널 키보드? SDK 호출? 웹 인터페이스?)와 "결과를 어디에 보여주느냐"(터미널 UI? JSON 스트림? 웹 페이지?)에 있다. 이렇게 입출력 레이어를 분리한 덕분에, 하나의 코드베이스로 다양한 환경을 지원할 수 있다.

---

## 4. 시작과 초기화 과정

### 4.1 main.tsx — 모든 것의 출발점

main.tsx는 약 800KB에 달하는 거대한 단일 파일이다. 보통 소프트웨어 엔지니어링에서는 파일을 작게 나누는 것이 좋은 관행이지만, 여기서는 의도적으로 하나의 큰 파일을 선택했다. 이유는 시작 성능 때문이다. 여러 파일로 나누면 파일마다 디스크 읽기 작업이 발생하는데, 하나의 파일로 합치면 한 번의 읽기로 끝나므로 시작 시간을 줄일 수 있다. CLI 도구는 사용자가 실행할 때마다 처음부터 시작하기 때문에, 시작 속도가 사용자 경험에 직접적인 영향을 미친다.

시작 과정은 여섯 단계로 나뉜다.

```
main.tsx startup sequence
=========================

[1] Parallel I/O prefetch            (saves ~65ms)
    |-- MDM subprocess read
    |-- macOS Keychain prefetch
    |                                   These run WHILE
    v                                   heavy imports load (~135ms)
[2] Conditional module loading
    |-- feature('COORDINATOR_MODE') --> load or skip
    |-- feature('KAIROS')           --> load or skip
    |                                   Dead code eliminated at build time
    v
[3] Early settings load
    |-- Parse --settings CLI flag
    |-- --bare flag? --> skip CLAUDE.md, skills, hooks
    |
    v
[4] Authentication
    |-- Try OAuth token              (claude.ai subscribers)
    |-- Try API key                  (ANTHROPIC_API_KEY)
    |-- Try AWS Bedrock              (sts:AssumeRole)
    |-- Try Google Vertex AI         (GoogleAuth)
    |-- Try Azure Foundry            (DefaultAzureCredential)
    |
    v
[5] Model resolution
    |-- User-specified model?  --> use it
    |-- Subscription tier?     --> Max/Team Premium = Opus
    |                              Others = Sonnet
    v
[6] Build initial state --> Launch REPL or Headless mode
```

**1단계: 병렬 I/O 사전 실행.** 프로그램이 시작되자마자, 무거운 모듈 임포트가 진행되는 약 135밀리초 동안 병렬로 두 가지 작업을 미리 시작한다. 하나는 MDM(Mobile Device Management) 설정 읽기이고, 다른 하나는 macOS 키체인에서 인증 토큰을 미리 가져오는 것이다. 이렇게 하면 약 65밀리초를 절약할 수 있다.

**2단계: 조건부 모듈 로딩.** 코디네이터 모드, 어시스턴트 모드 같은 선택적 기능들은 해당 기능이 활성화되었을 때만 관련 코드를 불러온다. bun 빌드 시스템의 "피처 게이트"라는 메커니즘을 사용하는데, 비활성화된 기능의 코드는 빌드 결과물에서 아예 제거된다.

**3단계: 설정 조기 로딩.** CLI 인수에서 설정 파일 경로를 먼저 파싱해서, 이후 모든 로직에서 올바른 설정을 사용할 수 있게 한다.

**4단계: 인증.** 다섯 가지 인증 방식을 우선순위에 따라 시도한다.

**5단계: 모델 해석.** 어떤 AI 모델을 사용할지 결정한다. 사용자가 명시적으로 지정한 모델이 있으면 그것을 쓰고, 없으면 구독 등급에 따라 기본 모델이 선택된다.

**6단계: 초기 상태 구성 후 REPL 실행.** 모든 준비가 끝나면 초기 상태 객체를 만들고, 선택된 모드에 따라 REPL을 실행하거나 헤드리스 모드로 진입한다.

### 4.2 컨텍스트 수집

모든 대화에는 두 가지 컨텍스트가 주입된다.

```
Context injection (memoized for session lifetime)
==================================================

System Context                    User Context
+--------------------------+      +--------------------------+
| Git branch: main         |      | CLAUDE.md files          |
| Default branch: main     |      | (project instructions)   |
| Git status (max 2000ch)  |      |                          |
| Recent commits           |      | Today's date             |
| Git user name            |      |                          |
+--------------------------+      +--------------------------+
        |                                  |
        +----------------+-----------------+
                         |
                         v
                Injected into every
                API conversation turn
```

**시스템 컨텍스트**는 현재 Git 브랜치, 기본 브랜치, Git 상태, 최근 커밋, Git 사용자 이름 등을 포함한다. 이 정보들은 병렬로 수집되며, Git 상태가 너무 길면 2,000자에서 잘라낸다. 한 번 수집되면 세션이 끝날 때까지 캐시된다.

**사용자 컨텍스트**는 프로젝트의 CLAUDE.md 파일들과 오늘 날짜를 포함한다. CLAUDE.md는 프로젝트별 지침 파일로, Claude Code가 해당 프로젝트에서 어떻게 동작해야 하는지를 담고 있다.

컨텍스트가 중요한 이유는, AI가 "지금 어떤 프로젝트에서 작업하고 있는지"를 알아야 적절한 도움을 줄 수 있기 때문이다. 예를 들어 Git 상태를 알면 "어떤 파일이 변경되었는지"를 파악해서 커밋 메시지를 작성할 수 있고, CLAUDE.md를 읽으면 "이 프로젝트에서는 테스트를 pytest로 실행한다"는 지침을 따를 수 있다.

---

## 5. 쿼리 루프 — 핵심 엔진

### 5.1 기본 구조

query.ts(약 68KB)는 Claude Code의 심장이다. 다른 모든 시스템(도구, 권한, 훅, 상태 관리 등)은 이 파일을 중심으로 동작한다.

"비동기 제너레이터"라는 패턴을 사용하는데, 이를 이해하기 위해 두 가지 방식을 비교해보자. 일반적인 방식은 레스토랑에서 모든 음식이 준비될 때까지 기다렸다가 한꺼번에 서빙하는 것과 같다. 제너레이터 방식은 준비되는 대로 하나씩 내오는 것과 같다. Claude Code는 후자를 사용한다. API 응답이 글자 단위로 도착하는 즉시 화면에 표시할 수 있어서, 사용자는 AI가 "타이핑하는 것"을 실시간으로 볼 수 있다.

### 5.2 턴(Turn)의 처리 흐름

쿼리 루프는 무한 반복문으로 구성되어 있으며, 매 반복(턴)마다 다음 과정을 거친다.

```
Query Loop: one turn
=====================

+--[1. Message Preprocessing]-------------------------------+
|                                                           |
|  Snip Compact -----> remove old messages entirely         |
|  Microcompact -----> shrink tool_use blocks inline        |
|  Context Collapse -> stage collapse operations            |
|  Auto-Compact -----> summarize if near token limit        |
|                      (threshold = context_window - 13000) |
+----------------------------+------------------------------+
                             |
                             v
+--[2. API Streaming Call]----------------------------------+
|                                                           |
|  Send: messages + system prompt + tools schema            |
|  Receive: streaming response (token by token)             |
|                                                           |
|  If model overloaded --> switch to fallback model          |
+----------------------------+------------------------------+
                             |
                             v
+--[3. Error Withholding & Recovery]-----------------------+
|                                                           |
|  413 Prompt Too Long:                                     |
|    try collapse drain --> try reactive compact --> fail    |
|                                                           |
|  Max Output Tokens:                                       |
|    escalate 8K->64K --> retry up to 3 times --> fail      |
+----------------------------+------------------------------+
                             |
                             v
+--[4. Tool Execution]--------------------------------------+
|                                                           |
|  Safe tools (Read, Grep, Glob):                           |
|    --> run up to 10 in parallel                           |
|                                                           |
|  Unsafe tools (Edit, Bash, Write):                        |
|    --> run one at a time, sequentially                    |
|                                                           |
|  Large results --> persist to disk, pass reference        |
+----------------------------+------------------------------+
                             |
                             v
+--[5. Post-processing]-------------------------------------+
|                                                           |
|  Run Stop Hooks (validation)                              |
|  Check token budget                                       |
|  Check max turns limit                                    |
|                                                           |
|  tool_use in response?                                    |
|    YES --> build new State, go back to step 1             |
|    NO  --> exit loop, return to user                      |
+-----------------------------------------------------------+
```

**1단계: 메시지 전처리.** 대화가 길어지면 토큰이 부족해지므로, 오래된 메시지를 정리하는 여러 전략이 적용된다. "Snip Compact"는 오래된 메시지를 통째로 제거하고, "Microcompact"는 도구 사용 블록을 인라인으로 축소하며, "Auto-Compact"는 토큰 한계에 근접하면 대화 전체를 AI에게 요약시킨다.

**2단계: API 호출.** 전처리된 메시지, 시스템 프롬프트, 사용자 컨텍스트, 도구 스키마를 Claude API에 보낸다. 응답은 스트리밍으로 도착하며, 텍스트 조각이 도착할 때마다 즉시 사용자에게 표시된다.

**3단계: 에러 보류와 복구.** 복구 가능한 에러는 사용자에게 바로 보여주지 않고 일단 "보류(withholding)"한다. 413 에러의 경우 먼저 컨텍스트 축소를 시도하고, 그래도 안 되면 전체 대화 요약을 시도하며, 그래도 안 되면 비로소 에러를 표면화한다. 출력 토큰 초과는 한도를 8K에서 64K로 에스컬레이션하고, 최대 3번까지 이어쓰기를 시도한다.

**4단계: 도구 실행.** 동시에 실행해도 안전한 도구들은 최대 10개까지 병렬로, 안전하지 않은 도구는 하나씩 순차적으로 실행한다. 결과가 너무 크면 디스크 파일로 저장하고 참조만 넘긴다.

**5단계: 후처리.** Stop Hook을 실행하고, 예산과 턴 제한을 확인한다. 도구 사용이 있었으면 다음 턴으로, 없으면 루프를 종료한다.

**구체적인 예시로 이해하기.** 사용자가 "auth.ts의 버그를 고쳐줘"라고 입력하면, 실제로 이런 일이 벌어진다.

```
Example: "Fix the bug in auth.ts"
====================================

Turn 1:  AI: "Let me read the file first."
         --> tool_use: FileRead("auth.ts")
         --> result: [file contents returned]

Turn 2:  AI: "I see a null check missing on line 42. Let me fix it."
         --> tool_use: FileEdit("auth.ts", old="user.name", new="user?.name")
         --> result: "Edit applied successfully"

Turn 3:  AI: "Let me verify the fix by running tests."
         --> tool_use: Bash("npm test -- auth.test.ts")
         --> result: "All 12 tests passed"

Turn 4:  AI: "Done! I fixed the null check on line 42. The issue was
         that `user.name` could crash when `user` is undefined.
         All tests pass."
         --> no tool_use --> loop exits, response shown to user
```

이 전체 과정에서 사용자는 처음에 한 번 입력하고 결과만 기다린다. 내부에서는 4번의 턴이 돌았고, 3번의 도구가 실행되었으며, 4번의 API 호출이 발생했다.

---

## 6. QueryEngine — SDK용 래퍼

QueryEngine은 query.ts의 쿼리 루프를 외부 프로그램이 쉽게 사용할 수 있게 감싼 클래스다.

```
External Program (Agent SDK, etc.)
      |
      v
+--[QueryEngine]----------------------------------+
|                                                  |
|  submitMessage("Fix the bug in auth.ts")         |
|      |                                           |
|      +--> Save transcript to disk (crash-safe)   |
|      |                                           |
|      +--> query() generator loop                 |
|      |      |                                    |
|      |      +--> yield SDKMessage (streaming)    |
|      |      +--> yield SDKMessage ...            |
|      |      +--> yield SDKMessage ...            |
|      |                                           |
|      +--> Accumulate usage (tokens, cost)        |
|      +--> Check budget (maxBudgetUsd)            |
|      +--> yield SDKResult (final)                |
|                                                  |
|  State persisted across turns:                   |
|    - mutableMessages[]                           |
|    - totalUsage                                  |
|    - permissionDenials[]                         |
+--------------------------------------------------+
```

핵심 동작은 이렇다. 사용자 메시지를 받으면, 먼저 대화 기록을 디스크에 저장한다. 이것이 중요한 이유는, 만약 API 호출 중에 프로세스가 강제 종료되어도 사용자 메시지까지는 복구할 수 있기 때문이다. 그 다음 쿼리 루프를 호출하고, 각 이벤트를 SDK가 이해할 수 있는 메시지 형식으로 변환하여 내보낸다. 비용 예산이 설정되어 있으면 누적 비용이 예산을 초과하는 순간 자동으로 중단한다.

---

## 7. 도구(Tool) 시스템

### 7.1 도구란 무엇인가

"도구"는 Claude가 외부 세계와 상호작용하기 위한 수단이다. 이것은 Claude Code에서 가장 중요한 개념이다.

Claude AI는 그 자체로는 텍스트만 생성할 수 있다. 파일을 읽거나, 코드를 실행하거나, 인터넷을 검색하는 것은 불가능하다. 그래서 Claude Code가 "다리" 역할을 한다. AI가 "이 파일을 읽어야겠다"고 판단하면, "FileRead 도구를 {path: 'auth.ts'}로 실행해달라"는 형식의 요청을 생성한다. Claude Code는 이 요청을 받아서 실제로 파일을 읽고, 그 내용을 AI에게 돌려준다. AI는 그 내용을 보고 다음 행동을 결정한다.

이런 구조 덕분에 AI의 능력은 "어떤 도구가 제공되느냐"에 따라 확장된다. 45개 이상의 내장 도구가 있으며, MCP(Model Context Protocol)를 통해 GitHub, Slack, 데이터베이스 같은 외부 도구도 추가할 수 있다.

### 7.2 도구의 공통 구조

모든 도구는 동일한 인터페이스를 따른다.

```
Every Tool has:
+-----------------------------------------------------------------+
|  name          "BashTool", "FileEditTool", ...                  |
|  inputSchema   Zod schema defining required/optional inputs     |
|  call()        The actual execution function                    |
|  description() Text shown to AI so it knows when to use it     |
|                                                                 |
|  checkPermissions()   Can this run in current context?          |
|  validateInput()      Is the input semantically valid?          |
|  isConcurrencySafe()  Safe to run alongside other tools?        |
|  isReadOnly()         Does it modify anything?                  |
|  maxResultSizeChars   Over this limit -> persist to disk        |
|  render*()            React components for terminal UI          |
+-----------------------------------------------------------------+
```

### 7.3 도구 등록과 조립

모든 도구는 tools.ts에 특정 순서로 등록된다. 순서가 중요한 이유는 API의 프롬프트 캐싱 안정성 때문이다. 도구 순서가 바뀌면 캐시가 무효화되어 비용이 증가한다.

```
Tool Assembly Pipeline
======================

getAllBaseTools()                     44+ tools registered
      |
      v
Feature gate filter                  Remove disabled features
      |                              (COORDINATOR, KAIROS, etc.)
      v
Deny rules filter                    Remove user-blocked tools
      |
      v
Mode filter                          SIMPLE mode: only Bash, Read, Edit
      |
      v
Built-in tools (sorted by name)
      |
      +------> assembleToolPool() <------+
                      |                   |
                      v              MCP tools
               Merged tool list      (sorted by name)
               (built-in first,
                dedup by name)
```

등록 후에는 여러 단계의 필터링을 거친다. 피처 게이트에 의해 비활성화된 도구가 제거되고, 사용자의 거부 규칙으로 금지된 도구가 제거되고, 현재 모드에 맞지 않는 도구가 제거된다. MCP 도구가 있으면 이름순 정렬 후 병합한다.

### 7.4 주요 도구 설명

```
Tool Categories
===============

File Operations     Shell          Search          Web
+-------------+  +---------+   +-----------+   +----------+
| FileRead    |  | Bash    |   | Grep      |   | WebFetch |
| FileEdit    |  |         |   | Glob      |   | WebSearch|
| FileWrite   |  |         |   | ToolSearch|   |          |
| NotebookEdit|  |         |   |           |   |          |
+-------------+  +---------+   +-----------+   +----------+

Agent/Team          Planning        Tasks           Skill
+-------------+  +-----------+   +----------+   +----------+
| Agent       |  | EnterPlan |   | TaskCreate|  | Skill    |
| SendMessage |  | ExitPlan  |   | TaskGet   |  |          |
| TeamCreate  |  |           |   | TaskUpdate|  |          |
| TeamDelete  |  |           |   | TaskList  |  |          |
+-------------+  +-----------+   +----------+   +----------+
```

**BashTool** — 셸 명령을 실행한다. 가장 강력하지만 동시에 가장 위험한 도구다. `rm -rf /` 같은 명령이 실행되면 시스템이 파괴될 수 있기 때문이다. 이를 방지하기 위해 Tree-sitter라는 파서로 명령어의 구조를 분석하고, 허용 목록에 있는 구문만 통과시키는 "기본 거부(fail-closed)" 설계를 채택했다. 즉, "안전하다고 증명된 것만 허용"하고, 판단할 수 없으면 차단한다. 명령 실행이 15초를 초과하면 자동으로 백그라운드 태스크로 전환되어 사용자가 다른 작업을 할 수 있고, 2초마다 진행 상황을 보고한다.

**AgentTool** — "다른 AI를 고용하는" 도구다. 복잡한 작업을 만나면, 메인 AI가 서브에이전트(작은 AI 일꾼)를 만들어서 부분 작업을 위임한다. 서브에이전트는 다섯 가지 방식으로 실행될 수 있다: 같은 프로세스에서 즉시 실행, 백그라운드에서 비동기 실행, tmux 패널에 별도 팀메이트로 스폰, 격리된 Git 워크트리에서 안전하게 실행, 또는 클라우드 환경에서 원격 실행. 서브에이전트는 부모보다 제한된 권한을 받아 안전성을 확보한다.

**FileEditTool** — 파일의 특정 문자열을 교체한다. 퍼지 매칭으로 의도한 위치를 찾고, 인코딩과 줄바꿈을 보존하며, Git diff를 생성한다.

**GrepTool** — ripgrep 기반 텍스트 검색. 세 가지 출력 모드(content, files_with_matches, count)와 기본 250개 결과 제한을 지원한다.

---

## 8. 도구 실행 오케스트레이션

### 8.1 실행 파이프라인 10단계

하나의 도구가 실행되기까지 10개의 단계를 거친다. 이렇게 단계가 많은 이유는 안전성 때문이다. AI가 "rm -rf /"를 실행하려 하면, 중간 단계에서 반드시 걸러내야 한다. 각 단계는 서로 다른 관점에서 "이 작업을 실행해도 괜찮은가?"를 확인한다.

```
Tool Execution Pipeline (for each tool_use block)
==================================================

[1] Lookup tool by name ---> not found? try aliases
              |
[2] Check abort signal ---> user pressed Ctrl+C? exit
              |
[3] Validate input (Zod) -> bad format? friendly error
              |
[4] Run PreToolUse hooks -> hook says block? stop here
              |
[5] Check permissions -----> deny? ask user? auto-classify?
              |
[6] Execute tool.call() ---> the actual work happens here
              |
[7] Map result to API format
              |
[8] Persist if oversized --> save to disk, return reference
              |
[9] Run PostToolUse hooks
              |
[10] Log telemetry event
```

### 8.2 동시성 모델

여러 도구가 한 번에 요청되면, "파티셔닝 알고리즘"이 도구들을 배치로 나눈다.

```
Tool Concurrency: Partitioning Algorithm
=========================================

Input:  [Read] [Grep] [Glob] [Edit] [Read] [Read] [Bash]
         safe   safe   safe  UNSAFE  safe   safe  UNSAFE

Batch 1: [Read, Grep, Glob]  --> parallel (up to 10)
Batch 2: [Edit]              --> serial (alone)
Batch 3: [Read, Read]        --> parallel
Batch 4: [Bash]              --> serial (alone)
```

연속된 동시성 안전 도구들은 하나의 배치로 묶여 최대 10개까지 병렬 실행된다. 비안전 도구를 만나면 새 배치가 시작되고, 해당 도구만 단독으로 실행된다.

이 설계가 중요한 이유는 속도와 안전성의 균형 때문이다. 세 개의 파일을 동시에 읽는 것은 안전하다(읽기는 아무것도 변경하지 않으니까). 하지만 파일 편집은 다른 편집과 동시에 실행하면 충돌할 수 있다. 그래서 "안전한 것은 빠르게 병렬로, 위험한 것은 천천히 하나씩"이라는 원칙을 따른다.

### 8.3 스트리밍 도구 실행기

API 응답이 아직 스트리밍 중일 때부터 이미 도착한 도구 사용 블록의 실행을 시작하는 최적화가 있다.

```
Streaming Tool Executor (overlaps API streaming + execution)
=============================================================

Time --->

API stream:   [...text...][tool_use A][...text...][tool_use B][done]
                              |                        |
Execution:              start A                   start B
                        |..running..|done     |..running..|done
                                                                |
Collect:                                            drain remaining
```

에러가 발생하면 아직 실행 중인 형제 도구들을 중단시키는 안전 메커니즘도 갖추고 있다.

---

## 9. 명령어(Command) 시스템

명령어는 사용자가 슬래시(`/`)로 시작하는 입력을 통해 호출하는 기능이다. 도구(Tool)가 "AI가 사용하는 기능"이라면, 명령어(Command)는 "사용자가 직접 사용하는 기능"이다. 80개 이상의 명령어가 있다.

```
Command Types
=============

/commit, /review ...       /settings, /doctor ...    /help ...
+-------------------+      +-------------------+     +-----------+
| Prompt Command    |      | Local Command     |     | Slash Cmd |
| Expands to a      |      | Renders JSX UI    |     | Can be    |
| system prompt for |      | in the terminal   |     | either    |
| the AI to follow  |      |                   |     | type      |
+-------------------+      +-------------------+     +-----------+

Additional sources:
  +-- Plugin commands   (from ~/.claude/plugins/)
  +-- Skill commands    (from ~/.claude/skills/)
  +-- MCP commands      (from connected MCP servers)
```

**프롬프트 명령어**는 AI에게 전달할 프롬프트로 확장되는 명령어다. 예를 들어 `/commit`은 "현재 변경 사항을 분석하고 커밋 메시지를 작성하라"는 프롬프트로 확장된다. **로컬 명령어**는 React 컴포넌트를 렌더링하는 UI 기반 명령어다. 플러그인, 스킬, MCP 서버도 자체 명령어를 등록할 수 있다.

---

## 10. 태스크(Task) 시스템

태스크는 백그라운드에서 실행되는 비동기 작업을 관리하는 시스템이다. "지금 당장 결과가 필요하지 않은 작업"을 백그라운드로 보내서, 사용자가 다른 일을 하는 동안 처리되게 하는 것이 목적이다. 예를 들어 대규모 테스트 실행이나 서브에이전트의 독립적인 조사 작업이 여기에 해당한다.

```
Task Lifecycle
==============

Spawn                  Register               Run in background
(BashTool async,  -->  AppState.tasks[id]  --> output -> disk file
 AgentTool, etc.)      status: "running"       progress reported
                                                     |
                                                     v
                       AI reads output          Completion
                       via TaskOutputTool  <--  status: "completed"
                                                or "failed" / "killed"

Task Types:
  b________ = local_bash          (shell command)
  a________ = local_agent         (in-process sub-agent)
  r________ = remote_agent        (cloud execution)
  t________ = in_process_teammate (team member)
  w________ = local_workflow      (workflow script)
  m________ = monitor_mcp         (MCP server watch)
  d________ = dream               (async continuation)
```

각 태스크는 고유 ID(유형 접두사 + 8자리 랜덤 문자)를 가지며, 출력을 디스크 파일로 리디렉션한다. 상태는 `pending`, `running`, `completed`, `failed`, `killed` 중 하나다.

---

## 11. 상태 관리

### 11.1 AppState — 글로벌 상태

Claude Code의 모든 글로벌 상태는 AppState라는 하나의 큰 타입으로 정의된다. "상태(state)"란 프로그램이 현재 기억하고 있는 모든 정보를 말한다 — 어떤 모델을 쓰고 있는지, 어떤 태스크가 실행 중인지, 어떤 플러그인이 활성화되어 있는지 등.

"불변(Immutable)" 제약이 적용되어 있다. 이는 상태를 직접 수정할 수 없고, 항상 새로운 객체를 만들어야 한다는 뜻이다. 비유하자면, 문서를 직접 지우고 고치는 대신 항상 새 복사본을 만드는 것과 같다. 이렇게 하면 "이전 상태"와 "새 상태"를 비교하여 무엇이 변했는지 정확히 알 수 있고, 예측하기 어려운 버그를 방지할 수 있다.

```
AppState (DeepImmutable)
========================

+-- Settings & Config ----+  +-- UI State -----------+
|  settings               |  |  expandedView         |
|  mainLoopModel          |  |  statusLineText       |
|  toolPermissionContext   |  |  spinnerTip           |
+-------------------------+  +------------------------+

+-- Agent / Team ---------+  +-- Tasks ---------------+
|  agentNameRegistry      |  |  tasks (mutable!)      |
|  teamContext            |  |  foregroundedTaskId     |
|  viewingAgentTaskId     |  |                        |
+-------------------------+  +------------------------+

+-- MCP -----------------+   +-- Plugins -------------+
|  clients[]             |   |  enabled[]             |
|  tools[]               |   |  disabled[]            |
|  commands[]            |   |  errors[]              |
|  resources{}           |   |                        |
+------------------------+   +------------------------+

+-- Bridge / Remote -----+   +-- Feature Flags -------+
|  replBridgeConnected   |   |  kairosEnabled         |
|  remoteSessionUrl      |   |  fastMode              |
|  connectionStatus      |   |  effortValue           |
+------------------------+   +------------------------+
```

### 11.2 상태 변경의 부수효과

상태가 변경될 때 자동으로 발생하는 부수효과들이 있다. 권한 모드가 변경되면 CCR과 SDK 리스너에게 알린다. 모델이 변경되면 설정 파일에 영속화한다. 설정이 변경되면 인증 캐시를 무효화하여 다음 API 호출에서 새 자격증명을 사용하게 한다.

---

## 12. 서비스 레이어

서비스 레이어는 핵심 엔진과 외부 세계(API, MCP 서버, 디스크 등) 사이의 중간 계층이다. 핵심 엔진이 "무엇을 해야 하는지"를 결정한다면, 서비스 레이어는 "어떻게 외부와 통신하는지"를 담당한다.

### 12.1 API 클라이언트와 재시도

API 클라이언트는 Claude API와의 모든 통신을 담당하며, 약 3,000줄에 달한다. 주요 역할은 세 가지다. **베타 기능 조립**은 사용하는 모델의 능력에 따라 `thinking`, `tool_search` 같은 기능을 동적으로 활성화한다. **프롬프트 캐싱**은 시스템 프롬프트와 도구 스키마를 1시간 동안 캐시하여 API 비용을 절감한다. **도구 스키마 정규화**는 내부 Tool 객체를 API가 이해할 수 있는 JSON 형식으로 변환한다.

네트워크 통신은 항상 실패할 수 있으므로, 에러 유형별로 다른 재시도 전략을 적용한다.

```
API Retry Strategy
==================

Error        Action
-----        ------
429          retry-after < 500ms? wait & retry (preserve cache)
(rate limit) otherwise: disable fast mode, switch to standard model

529          3 consecutive? switch to fallback model
(overloaded) non-foreground tasks: give up immediately

401          force-refresh OAuth token, recreate client
(auth fail)

ECONNRESET   disable keep-alive, recreate client
EPIPE

Persistent   retry forever with exponential backoff
mode (ANT)   up to 6 hours total (unattended sessions only)
```

### 12.2 자동 압축 서비스

대화가 길어지면 컨텍스트 윈도우(AI가 한 번에 기억할 수 있는 텍스트의 한계)에 도달한다. 자동 압축 서비스는 토큰 사용량이 임계값(유효 윈도우 - 13,000 토큰)을 넘으면 자동으로 작동한다.

```
Auto-Compact Flow
=================

Token usage > threshold?
      |
      v
Circuit breaker check (3 consecutive failures = stop trying)
      |
      v
Try session memory compact first (preserves granularity)
      |
      | failed?
      v
Full conversation compact:
  1. Strip images (save tokens)
  2. Group messages by API round
  3. Generate summary via forked sub-agent
  4. Replace old messages with summary
  5. Restore top 5 referenced files (50K token budget)
  6. Re-inject skills (25K budget, 5K per skill)
```

### 12.3 MCP 프로토콜 서비스

MCP(Model Context Protocol)는 외부 도구와 리소스를 Claude Code에 통합하는 표준 프로토콜이다. 내장 도구만으로는 모든 상황을 커버할 수 없기 때문에, MCP를 통해 GitHub API, 데이터베이스 쿼리, Slack 메시지 전송 같은 외부 기능을 "플러그인처럼" 추가할 수 있다.

```
MCP Server Connection States
=============================

Connected ----> Failed -----> NeedsAuth
    ^             |               |
    |             v               v
    +------- Pending <-----------+
              (retry: 1s -> 30s exponential backoff, max 5 attempts)

Transport Types:
  Stdio ------> spawn local process
  SSE/HTTP ---> connect to remote server
  WebSocket --> bidirectional communication
  SDK --------> built-in server
  Claude.ai --> proxy relay
```

### 12.4 비용 추적

비용은 메모리 내에서 실시간으로 누적되고, 세션 종료 시 프로젝트 설정에 영속화된다. 모델별로 입력/출력/캐시 토큰이 세분화되어 추적되며, 어드바이저 비용도 재귀적으로 합산된다.

---

## 13. 권한(Permission) 시스템

### 13.1 왜 권한 시스템이 필요한가

Claude Code는 사용자 컴퓨터에서 파일을 수정하고 명령을 실행할 수 있다. 이는 강력하지만 위험하다. AI가 잘못된 판단으로 중요한 파일을 삭제하거나, 의도치 않은 명령을 실행할 수 있기 때문이다. 권한 시스템은 "어떤 도구를, 어떤 입력으로, 실행해도 되는가"를 판단하는 게이트키퍼 역할을 한다.

### 13.2 권한 모드와 확인 파이프라인

```
Permission Pipeline
===================

Tool use request arrives
      |
[1]   v
validateInput()            Is the input semantically valid?
      |
[2]   v
checkPermissions()         Tool-specific rules
      |                    (e.g. file path in allowed dirs?)
[3]   v
Run PreToolUse hooks       User-defined hooks can block
      |
[4]   v
Match against rules        +-- alwaysAllow rules --> APPROVE
      |                    +-- alwaysDeny rules  --> DENY
      |                    +-- alwaysAsk rules   --> ASK USER
      |
[5]   v  (no rule matched)
Which permission mode?
      |
      +-- Default mode --> ASK USER (show prompt)
      |
      +-- Auto mode ----> AI Classifier (2-stage)
      |                     Stage 1: Fast (streaming)
      |                     Stage 2: Thinking (deep analysis)
      |                       |
      |                       +-- safe --> APPROVE
      |                       +-- risky -> ASK USER
      |
      +-- Plan mode ----> read-only tools only
      |
      +-- Bypass mode --> APPROVE everything

Rule sources (highest to lowest priority):
  Local settings > Project settings > User settings > Flags > Policy
```

**Default 모드**는 읽기 전용 작업은 자동 승인하고, 위험한 작업은 사용자에게 확인한다.

**Auto 모드**는 AI 분류기가 2단계(빠른 판단 + 심층 분석)로 위험도를 평가한다. 분류기가 "이건 안전하다"고 판단하면 사용자 확인 없이 바로 실행된다.

**Plan 모드**는 코드를 실제로 변경하지 않고, 읽기 전용 도구만 허용하는 "계획 수립 전용" 모드다. AI가 코드를 분석하고 계획을 세우지만, 실행은 사용자가 승인한 후에만 이루어진다.

**Bypass 모드**는 모든 것을 자동 승인한다. 개발 환경에서 빠르게 작업할 때 사용하며, 프로덕션 환경에서는 사용하지 않아야 한다.

---

## 14. 훅(Hook) 시스템

훅은 특정 이벤트가 발생했을 때 자동으로 실행되는 사용자 정의 동작이다. 예를 들어 "Bash 도구가 실행되기 전에 항상 특정 보안 검사를 수행하라"거나, "파일이 수정될 때마다 린터를 자동 실행하라"는 규칙을 만들 수 있다.

```
Hook Event Timeline
====================

SessionStart                                        Stop
    |                                                |
    v                                                v
[session begins]                               [AI response done]
    |                                                |
    |   UserPromptSubmit                             |
    |       |                                        |
    v       v                                        |
    |   [user types message]                         |
    |       |                                        |
    |       |   PreToolUse    PostToolUse            |
    |       |       |              |                 |
    v       v       v              v                 v
----+-------+-------+--------------+-----------------+----> time
            |       |              |
            |   [tool executes]    |
            |                      |
            |   PostToolUseFailure (if tool failed)
            |
        PermissionRequest (when permission needed)
        Notification (when alert fires)

Hook Response Controls:
  continue: false  --> stop current operation
  decision: block  --> deny the tool execution
  updatedInput     --> modify tool input before execution
  additionalContext --> inject extra context
```

**PreToolUse**는 도구 실행 직전에 실행되어 승인/차단/입력 수정이 가능하다. **PostToolUse**는 실행 직후 결과 검증에 쓰인다. **UserPromptSubmit**은 사용자 입력 시 추가 컨텍스트를 주입한다. **Stop**은 응답 완료 후 검증을 수행한다.

---

## 15. 스킬(Skill)과 플러그인(Plugin) 시스템

### 15.1 스킬

스킬은 재사용 가능한 작업 템플릿이다. 도구(Tool)가 "파일 읽기", "명령 실행" 같은 원자적(atomic) 동작이라면, 스킬은 "코드 리뷰", "PR 생성", "보안 검토" 같은 복합적인 작업 흐름이다.

```
Tools vs Skills vs Plugins vs Commands
========================================

Tool       Low-level, atomic action        "Read this file"
           Used by AI automatically         "Run this command"

Skill      High-level, reusable template   "Review this code"
           Invoked by user as /command      "Create a commit"

Plugin     Package of skills + hooks +     "GitHub integration"
           MCP servers bundled together     "Slack integration"

Command    User-facing / shortcut          /help, /settings, /model
           Can be prompt-type or UI-type
```

```
Skill System
============

Disk-based skills                     Bundled skills
(user-created)                        (built into binary)

~/.claude/skills/                     src/skills/bundled/
.claude/skills/                       registerBundledSkill()
     |                                     |
     v                                     v
+----------+    YAML frontmatter:    +----------+
| commit.md|    name, description,   | simplify |
| review.md|    whenToUse, tools,    | commit   |
| ...      |    model, paths         | ...      |
+----------+                         +----------+
     |                                     |
     +------------------+------------------+
                        |
                        v
               Available as /commands
               Full content loaded only on invocation
               (name + description sent to AI normally)
```

디스크 기반 스킬은 마크다운 파일로 존재하며, YAML 프론트매터로 메타데이터를 정의한다. 번들 스킬은 프로그램에 내장되어 있다. 토큰 효율성을 위해, 스킬의 전체 내용은 호출 시에만 로딩된다.

### 15.2 플러그인

플러그인은 스킬보다 상위 개념으로, 스킬, 훅, MCP 서버를 하나의 패키지로 묶은 것이다.

```
Plugin = Skills + Hooks + MCP Servers (bundled together)
=========================================================

BuiltinPlugin
+--------------------------------------------+
|  name: "github-integration"                |
|                                            |
|  skills:     [pr-review, autofix-pr, ...]  |
|  hooks:      { PreToolUse: [...] }         |
|  mcpServers: { github: { command: ... } }  |
|                                            |
|  isAvailable()  --> conditional availability|
|  defaultEnabled --> on/off by default       |
+--------------------------------------------+

User controls via /plugin command or settings.json
```

플러그인의 에러 처리는 20가지 이상의 구체적 유형(일반 에러, 매니페스트 파싱 에러, MCP 설정 오류, LSP 서버 충돌, 정책 차단 등)으로 세분화되어 있다.

---

## 16. UI 레이어

### 16.1 자체 제작 TUI 프레임워크 (Ink)

Claude Code의 터미널 UI는 React를 기반으로 한 자체 제작 TUI 프레임워크를 사용한다. 웹 브라우저 대신 터미널 문자 그리드에 렌더링한다는 차이만 있을 뿐, 개발 방식은 웹 React와 동일하다.

```
Ink TUI Rendering Pipeline
===========================

React component update
      |
      v
Reconciler calculates diff  (custom react-reconciler)
      |
      v
Yoga layout engine           (Flexbox for terminal)
calculates positions
      |
      v
Render to screen buffer      Double buffering:
+------------------+         +------------------+
| back frame (new) |  diff   | front frame (old)|
|                  | ------> |                  |
+------------------+  only   +------------------+
                      changed
                      cells
      |
      v
Write ANSI to terminal       Throttled at FRAME_INTERVAL_MS

Memory optimization:
  CharPool ------> intern strings (one copy of "hello")
  StylePool -----> intern ANSI codes + pre-serialized transitions
  HyperlinkPool -> intern URLs
  Dirty tracking > skip unchanged subtrees
```

프레임워크의 핵심 최적화 기법:

- **이중 버퍼링**: "현재 화면"과 "다음 화면" 두 개의 버퍼를 유지하고, 변경된 셀만 출력
- **객체 풀링**: 같은 문자열/스타일을 하나만 저장하고 인덱스로 참조하여 메모리 절약
- **더티 추적**: 변경된 부분만 다시 그려 불필요한 렌더링 방지
- **프레임 조절**: 업데이트 빈도를 제한하여 터미널이 느려지는 것을 방지

### 16.2 화면 구성

```
REPL Screen Layout
===================

+---------------------------------------------------+
|  Logo Header (memoized, rarely re-renders)         |
+---------------------------------------------------+
|                                                     |
|  Message List (virtualized)                         |
|  +-----------------------------------------------+ |
|  | User: Fix the bug in auth.ts                   | |
|  |                                                | |
|  | Assistant: I'll look at the file...            | |
|  |   [Read] auth.ts                               | |
|  |   [Edit] auth.ts (line 42)                     | |
|  |   Done! Fixed the null check.                  | |
|  +-----------------------------------------------+ |
|                                                     |
+---------------------------------------------------+
|  Task/Teammate Panel (toggle with Ctrl+T)          |
|  [task a3f2k1m9: running] [task b1c4d7e8: done]   |
+---------------------------------------------------+
|  Prompt Input                                       |
|  > mode: prompt | bash                              |
|  > [type here...]           [autocomplete dropdown] |
|  > status bar: model, tokens, cost                  |
+---------------------------------------------------+
```

### 16.3 키바인딩 시스템

```
Keybinding Contexts
====================

Global:       Ctrl+C = interrupt,  Ctrl+D = exit,  Ctrl+T = tasks
Chat:         Enter = submit,  Up/Down = history
Autocomplete: Tab = accept,  Esc = dismiss,  Up/Down = navigate
Transcript:   Ctrl+O = toggle,  q = exit

Chord support:  Ctrl+K -> Ctrl+S  (two-key sequence)
                First key enters "chord started" state
                Second key completes the action

Customizable via ~/.claude/keybindings.json
```

---

## 17. 브리지(Bridge) 시스템

브리지는 로컬 터미널의 Claude Code를 클라우드의 Claude Remote Runtime(CCR)에 연결하는 시스템이다. 33개의 소스 파일로 구성된 복잡한 서브시스템이다.

```
Bridge Architecture
====================

claude.ai (web)               Local Machine
+----------------+            +---------------------------+
|  User types    |            |  Bridge (bridgeMain.ts)   |
|  in browser    |            |                           |
|       |        |            |  [1] Register environment |
|       v        |   poll     |  [2] Poll for work -------|---+
|  CCR Backend   |<-----------|  [3] Spawn session -------|   |
|  stores work   |            |  [4] ACK work             |   |
|       |        |  results   |  [5] Heartbeat loop       |   |
|       |        |----------->|  [6] Archive on done      |   |
+-------+--------+            +---------------------------+   |
        |                              |                      |
        v                              v                      |
+----------------+            +------------------+            |
|  Web UI shows  |            |  Child process   |<-----------+
|  results       |            |  (Claude Code)   |
+----------------+            |  executes locally|
                              +------------------+

Multi-session: up to 32 parallel sessions
Dedup: BoundedUUIDSet (circular buffer, fixed memory)

Token Refresh:
  CCR v1: OAuth token, direct refresh
  CCR v2: Session JWT (~5h55m), reconnect to server for new token
          Pre-scheduled 5 minutes before expiry

Backoff:
  Connection errors: 2s -> 120s (cap), give up after 10 min
  General errors:    500ms -> 30s (cap)
  Shutdown grace:    SIGTERM, then SIGKILL after 30s
```

브리지의 핵심은 "폴링 루프"다. 환경을 등록한 후, 주기적으로 서버에 작업이 있는지 물어본다. 작업이 있으면 자식 프로세스로 세션을 스폰하고, 하트비트로 세션을 유지하며, 완료되면 아카이브한다. 최대 32개의 병렬 세션을 관리할 수 있다.

---

## 18. 원격(Remote) 세션 관리

원격 세션 관리자는 단일 CCR 세션에 WebSocket으로 연결하여 메시지를 스트리밍한다.

```
Remote Session WebSocket
=========================

wss://api.anthropic.com/v1/sessions/ws/{sessionId}/subscribe

State Machine:

closed ---(connect)---> connecting ---(onopen)---> connected
  ^                                                    |
  |                                                    |
  +---------(close/error, max 5 retries)---------------+

Reconnection:
  - General disconnect: max 5 attempts, 2s delay
  - Session not found (4001): 3 retries (transient during compaction)
  - Auth failure (4003): no retry
  - Ping/Pong every 30s to detect stale connections

Permission flow:
  Server: "Can this tool run?" --> Client: show prompt to user
  Client: "Allow" or "Deny"   --> Server: proceed or skip
```

**브리지**는 "공항 컨트롤 타워"와 같다 — 여러 세션의 이착륙을 관리한다. **원격 세션 관리자**는 "조종석의 통신 장비"와 같다 — 하나의 세션과 관제탑 사이의 실시간 통신을 담당한다.

---

## 19. 코디네이터(Coordinator) 모드

코디네이터 모드는 하나의 "리더" 에이전트가 여러 "워커" 에이전트를 관리하는 멀티에이전트 오케스트레이션 시스템이다.

```
Coordinator Architecture
=========================

                +-------------------+
                |  LEADER (main)    |
                |  - AgentTool      |  Does NOT edit code directly.
                |  - SendMessage    |  Delegates everything.
                |  - TaskStop       |
                +--------+----------+
                         |
          +--------------+--------------+
          |              |              |
          v              v              v
   +------------+ +------------+ +------------+
   | WORKER 1   | | WORKER 2   | | WORKER 3   |
   | QueryEngine| | QueryEngine| | QueryEngine|
   |            | |            | |            |
   | Read, Grep | | Edit, Bash | | Read, Test |
   | WebFetch   | | Write      | | Grep       |
   +------------+ +------------+ +------------+
    (isolated)    (isolated)     (isolated)
    permissions   permissions    permissions

Work Phases:

[1] Research     Multiple workers in parallel
    (parallel)   Each explores different files/angles
        |
[2] Synthesis    Leader reads all results
    (sequential) Leader MUST understand (no delegation)
        |
[3] Implement    Workers modify code
    (per-area)   One area at a time to avoid conflicts
        |
[4] Verify       Workers run tests in parallel
    (parallel)   Independent test suites
```

리더 에이전트는 직접 코드를 수정하지 않고, 워커에게 작업을 분배하는 것에 집중한다. 각 워커는 독립된 QueryEngine 인스턴스로 실행되며, 자체적인 도구 풀과 권한 컨텍스트를 가진다. 종합 단계에서 리더는 반드시 워커의 결과를 직접 이해해야 한다 — 위임은 금지된다.

---

## 20. 메모리(Memory) 시스템

메모리 시스템은 대화가 끝나도 유지되는 영속적인 정보 저장소다. 중요한 정보를 파일로 저장해두고, 다음 대화에서 자동으로 불러온다.

```
Memory System Structure
========================

~/.claude/projects/{project-slug}/memory/
|
+-- MEMORY.md              (index file, max 200 lines / 25KB)
|   |
|   +-- "- [User role](user_role.md) -- senior Go dev, new to React"
|   +-- "- [Testing](feedback_testing.md) -- use real DB, not mocks"
|   +-- "- [Merge freeze](project_freeze.md) -- until 2026-03-05"
|   +-- "- [Bug tracker](reference_linear.md) -- Linear INGEST project"
|
+-- user_role.md           (type: user)
+-- feedback_testing.md    (type: feedback)
+-- project_freeze.md      (type: project)
+-- reference_linear.md    (type: reference)

Memory Types:

+----------+--------------------------------------------------+
| user     | Who the user is. Role, expertise, preferences.   |
|          | "Deep Go expertise, new to React"                |
+----------+--------------------------------------------------+
| feedback | How to work. Corrections AND confirmations.      |
|          | "Use real DB in tests, not mocks.                |
|          |  Why: mock/prod divergence broke migration"      |
+----------+--------------------------------------------------+
| project  | What's happening. Goals, deadlines, decisions.   |
|          | "Merge freeze until 2026-03-05 for mobile release"|
+----------+--------------------------------------------------+
| reference| Where to look. Pointers to external systems.     |
|          | "Pipeline bugs tracked in Linear INGEST project" |
+----------+--------------------------------------------------+

NOT saved: code patterns, architecture, git history,
           debugging recipes, anything already in CLAUDE.md
```

각 메모리 파일은 마크다운 형식이며, 상단 YAML 프론트매터로 이름, 설명, 유형을 명시한다. 단순히 규칙만 기록하는 게 아니라, "왜(Why)"와 "어떻게 적용(How to apply)"도 함께 기록하여 엣지 케이스에서도 올바르게 판단할 수 있게 한다.

---

## 21. 타입 시스템과 상수

### 21.1 핵심 타입 정의

Claude Code의 타입 시스템은 `types/` 디렉토리에 중앙 집중적으로 정의되어 있다. 메시지 타입은 사용자/어시스턴트/시스템/진행/첨부/도구결과로 구분된다. 권한 타입(62KB)은 모드, 규칙 소스, 규칙 값, 결정(허용/거부/질문)이 세밀하게 타입화되어 있다. ID 타입은 `SessionId`와 `AgentId`를 브랜딩 타입으로 정의하여 혼용을 방지한다.

### 21.2 설정 소스 우선순위

```
Settings Priority (highest to lowest)
======================================

[1] Local     .claude/settings.local.json    (editable)
[2] Project   .claude/settings.json          (editable)
[3] User      ~/.claude/settings.json        (editable)
[4] Flags     flag file                      (read-only)
[5] Policy    enterprise policy              (read-only)
```

---

## 22. 유틸리티 모듈

**Bash 보안 (888KB, 18파일)** — Tree-sitter 파서로 셸 명령어의 AST를 분석한다. 허용 목록에 있는 노드 타입만 통과시키는 "기본 거부(fail-closed)" 설계다. 명령어 치환, 변수 확장, 리디렉션을 모두 분석한다.

**샌드박스** — 도구 실행을 격리된 환경에서 수행한다. `//path`는 절대 루트, `/path`는 설정 파일 기준 상대, `~/path`는 홈 디렉토리를 의미한다.

**토큰 계산** — `tokenCountWithEstimation()`이 핵심으로, 마지막 API 응답의 정확한 토큰 수에 이후 메시지의 추정치를 더한다. 자동 압축, 세션 메모리, 임계값 확인 등에 사용된다.

**스웜/팀 관리** — 팀 파일(TeamFile)을 통해 에이전트 간 협업을 관리한다. 인프로세스 러너는 메시지 라우팅, 도구 필터링, 권한 동기화를 처리한다.

**글로벌 세션 상태 (56KB)** — 세션 ID, 누적 비용, API 지속시간, 모델별 사용량, 등록된 훅, 에이전트 색상 맵 등을 세션 수명 동안 유지한다.

---

## 23. 핵심 설계 패턴

Claude Code 전반에서 반복적으로 나타나는 설계 패턴 여덟 가지. 이 패턴들을 이해하면 코드의 어떤 부분을 보더라도 빠르게 파악할 수 있다.

```
Design Patterns Summary
========================

[1] Generator Streaming     query() yields events one-by-one
                            --> real-time display of AI "thinking"

[2] Feature Gate            bun:bundle dead-code elimination
    Dead Code Removal       --> disabled features removed at build time

[3] Memoized Context        getSystemContext(), getUserContext()
                            --> computed once, cached for session

[4] Withhold & Recover      Buffer recoverable errors (413, max tokens)
                            --> try auto-fix before showing to user

[5] Lazy Import             Wrap in function to avoid circular deps
                            --> loaded only when actually called

[6] Immutable State         DeepImmutable + Zustand
                            --> predictable state changes

[7] Interruption            Save transcript BEFORE query loop
    Resilience              --> crash mid-API = resume from last message

[8] Dependency Injection    query() receives deps parameter
                            --> mockable for tests, swappable per mode
```

---

## 24. 전체 데이터 흐름 요약

```
End-to-End Data Flow
=====================

User runs "claude" in terminal
      |
      v
main.tsx
+-- Auth (OAuth / API key / Bedrock / Vertex)
+-- Model resolution (Opus for Max, Sonnet for others)
+-- Load settings + feature gates
+-- Collect context (Git status + CLAUDE.md)  [memoized]
+-- Build tool pool (built-in + MCP)
+-- Launch REPL  (or headless QueryEngine)
      |
      v
User types: "Fix the bug in auth.ts"
      |
      v
Normalize message for API
      |
      v
query() generator loop  <-----------------------------------------+
|                                                                  |
+-- [Pre-process] snip / microcompact / auto-compact if needed     |
+-- [API call] stream response from Claude API                     |
+-- [Error?] withhold & recover (413 -> compact, max_tok -> retry) |
+-- [Tool use?]                                                    |
|     YES --> permission check --> execute tool --> collect result  |
|             (pipeline: validate -> hooks -> rules -> classifier) -+
|     NO  --> display final response
|
+-- Record transcript to disk
+-- Track cost (per model: input/output/cache tokens)
+-- Await next user input
```

사용자가 터미널에서 Claude Code를 실행하면, `main.tsx`가 인증, 모델 해석, 설정 로딩, 컨텍스트 수집을 수행한 후 REPL을 시작한다. 사용자가 메시지를 입력하면, 메시지가 정규화되어 Claude API에 스트리밍으로 전송된다. 응답이 도착하면 텍스트는 즉시 화면에 표시되고, 도구 사용 요청은 권한 확인을 거쳐 실행된다. 도구 결과는 다시 API에 전달되고, 이 과정이 AI가 더 이상 도구를 사용하지 않을 때까지 반복된다. 대화가 길어지면 자동 압축이 작동하고, 에러가 발생하면 자동 복구가 시도된다. 모든 과정에서 비용이 추적되며, 세션이 끝나면 기록이 영속화된다.

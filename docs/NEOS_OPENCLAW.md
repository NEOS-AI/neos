# NEOS × OpenClaw 기능 병합 기술 백서

> 버전: 1.0.1 | 작성일: 2026-05-09

---

## 목차

1. [개요](#1-개요)
2. [병합 전략 원칙](#2-병합-전략-원칙)
3. [Phase별 구현 상세](#3-phase별-구현-상세)
   - [Phase 1 — 멀티채널 어댑터 레이어](#phase-1--멀티채널-어댑터-레이어)
   - [Phase 2 — 실행 승인 시스템](#phase-2--실행-승인-시스템execution-approval)
   - [Phase 4 — Cron 스케줄 스킬](#phase-4--cron-스케줄-스킬)
   - [Phase 5 — 모델 프로바이더 플러그인](#phase-5--모델-프로바이더-플러그인)
   - [Phase 8 — A2UI (Agent-to-UI)](#phase-8--a2ui-agent-to-ui)
4. [전체 데이터 흐름 다이어그램](#4-전체-데이터-흐름-다이어그램)
5. [DB 마이그레이션 참조](#5-db-마이그레이션-참조)
6. [설정 참조 테이블](#6-설정-참조-테이블)

---

## 1. 개요

### OpenClaw란

OpenClaw는 "AI assistant app"이 아니라 **personal AI orchestration OS/framework**다. 핵심 구조는 다음 삼각형으로 요약된다:

```
┌─────────────────────────────────────────────────────────────────┐
│                         OpenClaw 아키텍처                         │
│                                                                  │
│   [채널] WhatsApp/Telegram/Discord       [디바이스] iOS/macOS/…  │
│          │                                         │             │
│          ▼                                         ▼             │
│   ┌─────────────────────────────────────────────────────┐       │
│   │                      Gateway                         │       │
│   │  sessions · routing · auth · credentials             │       │
│   │  execution approval · control-ui                     │       │
│   └──────────────────────┬──────────────────────────────┘       │
│                           │                                      │
│                           ▼                                      │
│   ┌──────────────────────────────────────────────────────┐      │
│   │              Embedded Agent Runtime                   │      │
│   │  tools · memory · context · model switching          │      │
│   └──────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

### NEOS의 적용 철학

NEOS는 OpenClaw의 **개념 모델**을 채택하되, **기술 스택**을 NEOS의 기존 기반(FastAPI + LangGraph + Celery)으로 재해석했다.

| OpenClaw 개념 | NEOS 구현 |
|---------------|-----------|
| Gateway (중앙 라우팅) | `ChannelGateway` + `CircuitBreaker` |
| Embedded Agent Runtime | LangGraph `StateGraph` + `MultiAgentWorkflow` |
| Sessions | LangGraph `PostgresSaver` Checkpointer |
| Tool 계층 | `BaseSkill` 기반 스킬 시스템 |
| Execution Approval | LangGraph `interrupt_before` 패턴 |
| Plugin/Extension | `ModelProviderBase` ABC 레지스트리 |
| Memory/Context Engine | `neos/memory/` (short-term/episodic/long-term) |
| Control UI | Next.js 프론트엔드 + SSE 스트리밍 |
| A2UI (Agent renders UI) | `UIFrameGenerator` + `UIFrameForm` React 컴포넌트 |
| Cron Tool | `CronSkill` + Celery Beat 폴러 |

---

## 2. 병합 전략 원칙

### 원칙 1: Phase-based 점진적 병합

각 기능을 독립된 Phase(1~8)로 분리하여 기존 기능에 영향 없이 순차 병합했다. 각 Phase는 피처 플래그(`*_ENABLED`)로 활성화를 제어하여 **롤백 없이 기능을 비활성화**할 수 있다.

### 원칙 2: LangGraph를 런타임 핵심으로 유지

OpenClaw의 subprocess 기반 Agent Runtime을 LangGraph `StateGraph`로 대체했다. 세션 지속성은 PostgreSQL Checkpointer가 담당하며, 모든 에이전트 상태는 `AgentState` TypedDict로 단일 진실 공급원을 유지한다.

### 원칙 3: 채널 → Gateway → Workflow 단방향 흐름

외부 채널 메시지가 `ChannelGateway.dispatch()`를 통해 NEOS 워크플로우로 전달되고, 워크플로우 결과가 해당 채널로 반환되는 단방향 흐름을 강제한다. HTTP 왕복 없이 프로세스 내 직접 함수 호출을 사용한다.

### 원칙 4: ABC 기반 확장점 명시화

모든 확장 지점(`ChannelAdapterBase`, `ModelProviderBase`, `BaseSkill`)을 추상 기본 클래스로 명시화하여, 새 채널·모델·스킬 추가가 기존 코드 수정 없이 가능하도록 설계했다.

---

## 3. Phase별 구현 상세

---

### Phase 1 — 멀티채널 어댑터 레이어

**목표:** 단일 NEOS 워크플로우를 WhatsApp/Telegram/Discord/Slack 등 다양한 채널에서 호출 가능하도록 추상화 레이어 구축.

#### 핵심 파일

| 파일 | 역할 |
|------|------|
| `neos/api/channels/base.py` | `ChannelAdapterBase` ABC + `ChannelMessage` 데이터클래스 |
| `neos/api/channels/adapters/telegram.py` | Telegram Bot API 어댑터 (완전 구현) |
| `neos/api/channels/adapters/discord.py` | Discord 어댑터 (완전 구현) |
| `neos/api/channels/adapters/slack.py` | Slack 어댑터 (완전 구현, Socket Mode) |
| `neos/api/channels/gateway.py` | `ChannelGateway` — 채널 라우팅 + Circuit Breaker |
| `db/migrations/021_add_channel_source.sql` | `query_history`에 `channel_source`, `external_channel_id` 컬럼 추가 |

#### 아키텍처

```
외부 채널 메시지
      │
      ▼
ChannelAdapterBase.receive_message()  ──► ChannelMessage 정규화
      │
      ▼
ChannelGateway.dispatch()
  ├── circuit_breaker.call(_run_workflow)
  │         │
  │         ▼
  │   multi_agent_workflow.execute_workflow()
  │         │
  │         ▼
  │   result["final_response"]
  │         │
  │         ▼
  └── ChannelAdapterBase.send_response(channel_id, response)
            │
            ▼
      채널로 응답 전송

  [비동기 부수 효과]
  _record_channel_source() → query_history UPDATE
```

#### ChannelAdapterBase 인터페이스

```python
class ChannelAdapterBase(ABC):
    channel_type: str                                     # 채널 식별자

    async def start(self) -> None: ...                    # 봇 시작 (폴링/웹훅)
    async def stop(self) -> None: ...                     # 봇 종료
    async def receive_message(self, raw: Any) -> ChannelMessage: ...
    async def send_response(self, channel_id: str, content: str) -> None: ...
```

#### TelegramAdapter 구현 특징

- `python-telegram-bot>=21.0` (asyncio-native) 사용
- `asyncio.create_task()`로 uvicorn 이벤트 루프와 polling 루프 공유
- 4096자 초과 응답은 자동 분할 전송
- 타이핑 인디케이터(`send_action("typing")`)로 UX 개선
- 폴링 태스크 종료 콜백으로 예기치 않은 오류 로깅

#### DiscordAdapter 구현 특징

- `discord.py>=2.3.0` 사용 (ImportError 발생 시 경고 후 graceful skip)
- `Intents.message_content = True` 필요 — Discord Developer Portal에서 활성화 필수
- `asyncio.create_task(client.start(token))`으로 uvicorn 루프 공유
- 2000자(Discord 단일 메시지 최대) 초과 응답은 자동 분할 전송
- `channel.typing()` 컨텍스트 매니저로 입력 중 표시

#### SlackAdapter 구현 특징

- `slack-bolt>=1.18.0` (AsyncApp + AsyncSocketModeHandler) 사용 (ImportError 발생 시 경고 후 graceful skip)
- Socket Mode 사용 — 추가 HTTP 포트 불필요, `xapp-` 접두사 App-Level Token 필요
- `asyncio.create_task(handler.start_async())`으로 uvicorn 루프 공유
- 3000자(안전 한도, 공식 4000자) 초과 응답은 자동 분할 전송
- `client.chat_postMessage()` 경유 응답, `say()` 미사용

#### DB 변경 (021)

```sql
ALTER TABLE query_history
    ADD COLUMN IF NOT EXISTS channel_source VARCHAR(50) DEFAULT 'api',
    ADD COLUMN IF NOT EXISTS external_channel_id VARCHAR(500);
CREATE INDEX IF NOT EXISTS idx_qh_channel_source ON query_history(channel_source);
```

#### 채널 활성화 설정

```bash
# Telegram
CHANNEL_TELEGRAM_ENABLED=true
CHANNEL_TELEGRAM_BOT_TOKEN=<your_bot_token>

# Discord (discord.py>=2.3.0 필요, Developer Portal > Message Content Intent 활성화 필요)
CHANNEL_DISCORD_ENABLED=true
CHANNEL_DISCORD_BOT_TOKEN=<your_discord_bot_token>

# Slack (slack-bolt>=1.18.0 필요, Socket Mode + App-Level Token 필요)
CHANNEL_SLACK_ENABLED=true
CHANNEL_SLACK_BOT_TOKEN=<xoxb-your-bot-token>
CHANNEL_SLACK_APP_TOKEN=<xapp-your-app-token>

# 공통 (채널 요청을 NEOS 사용자 계정에 매핑)
CHANNEL_BOT_USER_ID=<neos_service_account_user_id>
```

---

### Phase 2 — 실행 승인 시스템(Execution Approval)

**목표:** 민감 스킬 실행 전 사용자 승인을 요구하는 Human-in-the-Loop 흐름 구현. Allowlist를 통해 반복 승인 부담 최소화.

#### 핵심 파일

| 파일 | 역할 |
|------|------|
| `neos/workflow/processors/approval_processor.py` | LangGraph 노드: 승인 결정 라우팅 |
| `neos/api/handlers/approval_handlers.py` | `POST /api/v1/approval/respond`, `GET /api/v1/approval/stream/{session_id}` |
| `db/migrations/022_add_tool_approval_allowlist.sql` | `tool_approval_allowlist` 테이블 |

#### LangGraph interrupt_before 패턴

```
SKILL_TOOL_SELECTOR
    │ (민감 스킬 감지 + allowlist 없음)
    ▼
[interrupt_before=EXECUTION_APPROVAL]
    │
    │ 1. SSE "approval_request" 이벤트 발행
    │    { request_id, skill_name, description }
    │
    │ 2. 사용자: POST /api/v1/approval/respond
    │    { session_id, request_id, decision: "approved"|"rejected",
    │      add_to_allowlist: bool }
    │
    │ 3. graph.aupdate_state({ approval_decision: decision })
    │
    │ 4. asyncio.create_task(_resume())
    │      graph.astream(None, config)  ← 재개
    │
    ▼
EXECUTION_APPROVAL 노드 실행 (ApprovalProcessor.process())
    ├─ "approved" → pending_approvals 초기화 → HYPOTHESIS_GENERATION
    └─ "rejected" → final_response 설정 → RESPONSE_GENERATOR
```

> ⚠️ `interrupt_before` 패턴은 Checkpointer가 활성화된 경로에서만 동작한다.
> `execute_workflow(use_checkpointer=False)` 호출 시 승인 인터럽트는 발동하지 않는다.

#### ApprovalProcessor 상태 변경

| 필드 | approved | rejected |
|------|----------|---------|
| `pending_approvals` | `[]` | `[]` |
| `approval_decision` | `None` (초기화) | `None` (초기화) |
| `approval_outcome` | `"approved"` | `"rejected"` |
| `final_response` | 변경 없음 | 거부 메시지 설정 |

#### 재개 흐름 (approval_handlers.py)

`_resume()` 코루틴이 `asyncio.create_task()`로 백그라운드에서 실행되며, `graph.astream(None, config)`으로 checkpointer에 저장된 상태에서 재개된다. 결과는 `stream_manager.add_event()`로 push되고, 클라이언트는 `GET /api/v1/approval/stream/{session_id}`로 SSE 재구독하여 최종 응답을 수신한다.

#### DB 변경 (022)

```sql
CREATE TABLE IF NOT EXISTS tool_approval_allowlist (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    skill_name VARCHAR(100) NOT NULL,
    auto_approved BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, skill_name)
);
```

#### 설정

```bash
EXECUTION_APPROVAL_ENABLED=true
APPROVAL_REQUIRED_SKILLS=api_call,file_processing,task_creation,code_execution
APPROVAL_TIMEOUT_SECONDS=60
```

---

### Phase 4 — Cron 스케줄 스킬

**목표:** 사용자의 자연어 반복 작업 요청을 DB 기반 스케줄로 등록하고, Celery Beat 폴러가 지정 시각에 워크플로우를 자동 실행.

#### 핵심 파일

| 파일 | 역할 |
|------|------|
| `neos/skills/builtin/cron/skill.py` | `CronSkill` — 스케줄 등록 스킬 |
| `neos/skills/builtin/cron/parser.py` | 자연어 → cron 표현식 파서 |
| `neos/tasks/scheduled_task_runner.py` | Celery 폴러 + 워크플로우 실행 태스크 |
| `neos/api/handlers/scheduled_tasks_handlers.py` | CRUD REST API |
| `db/migrations/023_add_scheduled_tasks.sql` | `scheduled_tasks` 테이블 |

#### 전체 흐름

```
사용자: "매일 오전 9시 TSLA 주가 분석해줘"
    │
    ▼
QueryClassifier → IntentType.TASK_SCHEDULING
    │
    ▼
CronSkill.execute()
    │
    ├─ parse_schedule("매일 오전 9시 ...") → cron_expression="0 9 * * *"
    │    (규칙 기반 패턴 매칭: 한국어/영어 6가지 패턴)
    │
    ├─ _extract_task_query() → "TSLA 주가 분석해줘"
    │    (시간 표현 제거 정규식)
    │
    ├─ croniter(cron_expr, now).get_next() → next_run_at 계산
    │
    └─ DB: scheduled_tasks INSERT
         { id, user_id, title, query, cron_expression, timezone,
           channel_type, channel_id, is_active, next_run_at }

    [매 1분: Celery Beat crontab(minute="*")]
    │
    ▼
poll_and_run_scheduled_tasks()
    │
    ├─ SELECT ... WHERE is_active=TRUE AND next_run_at <= NOW()
    │  WITH FOR UPDATE SKIP LOCKED  ← 다중 워커 중복 방지
    │
    ├─ run_workflow_task.delay(task_id)  ← 비동기 제출
    │
    └─ next_run_at = croniter(expr, now).get_next()  ← 갱신

    [run_workflow_task Celery 워커]
    │
    ▼
_run_workflow(query, user_id) → multi_agent_workflow.execute_workflow()
    │
    └─ channel_type != "api" → _send_to_channel(type, id, result)
```

#### 자연어 파서 지원 패턴

| 입력 예 | cron 표현식 |
|---------|------------|
| `매일 오전 9시` | `0 9 * * *` |
| `매일 오후 3시 30분` | `30 15 * * *` |
| `매주 월요일 오전 9시` | `0 9 * * 1` |
| `매시간` | `0 * * * *` |
| `매 30분마다` | `*/30 * * * *` |
| `every day at 9:00 am` | `0 9 * * *` |
| `every tuesday at 14:00` | `0 14 * * 2` |

#### DB 변경 (023)

```sql
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         VARCHAR(255) NOT NULL REFERENCES users(user_id),
    title           VARCHAR(500) NOT NULL,
    query           TEXT         NOT NULL,
    cron_expression VARCHAR(100) NOT NULL,
    timezone        VARCHAR(100) NOT NULL DEFAULT 'UTC',
    channel_type    VARCHAR(50)  NOT NULL DEFAULT 'api',
    channel_id      VARCHAR(500),
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    last_run_at     TIMESTAMP,
    next_run_at     TIMESTAMP    NOT NULL,
    run_count       INTEGER      NOT NULL DEFAULT 0,
    last_error      TEXT,
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP    NOT NULL DEFAULT NOW()
);
-- 폴러 쿼리 최적화: partial index (is_active=TRUE)
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_next_run
    ON scheduled_tasks (next_run_at) WHERE is_active = TRUE;
```

#### Celery Beat 설정 (`neos/workflow/celery_app.py`)

```python
beat_schedule = {
    "poll-scheduled-tasks": {
        "task": "neos.tasks.poll_scheduled_tasks",
        "schedule": crontab(minute="*"),      # 매 1분
    },
    "cleanup-expired-ui-frames": {
        "task": "neos.tasks.cleanup_expired_ui_frames",
        "schedule": crontab(minute=0),         # 매 시간 정각
    },
}
```

#### 설정

```bash
CRON_ENABLED=true
CRON_DEFAULT_TIMEZONE=UTC
CRON_MAX_TASKS_PER_USER=20
```

---

### Phase 5 — 모델 프로바이더 플러그인

**목표:** OpenClaw의 다중 모델 프로바이더 구조(Anthropic/OpenAI/Ollama/Gemini 등)를 ABC 기반 레지스트리 패턴으로 NEOS에 이식. 런타임에 프로바이더를 교체 가능하도록 설계.

#### 핵심 파일

| 파일 | 역할 |
|------|------|
| `neos/providers/base.py` | `ModelProviderBase` ABC |
| `neos/providers/anthropic.py` | Anthropic (Claude, Thinking Blocks 지원) |
| `neos/providers/openai.py` | OpenAI (GPT 계열) |
| `neos/providers/gemini.py` | Google Gemini |
| `neos/providers/ollama.py` | Ollama (로컬 LLM, langchain-ollama 선택적) |
| `neos/utils/llm_factory.py` | 레지스트리 기반 팩토리 (`LLMFactory`) |

#### ModelProviderBase 인터페이스

```python
class ModelProviderBase(ABC):
    @abstractmethod
    def create_llm(self, model: str, temperature: float,
                   max_tokens: int, **kwargs) -> BaseLanguageModel: ...
    @abstractmethod
    def list_models(self) -> List[str]: ...
    @abstractmethod
    def get_provider_name(self) -> str: ...
    def validate_config(self) -> bool: return True  # 오버라이드 가능
```

#### LLMFactory 레지스트리 패턴

```python
# neos/utils/llm_factory.py
class LLMFactory:
    _providers: Dict[str, Type[ModelProviderBase]] = {
        "anthropic": AnthropicProvider,
        "openai":    OpenAIProvider,
        "gemini":    GeminiProvider,
        "ollama":    OllamaProvider,
    }

    @classmethod
    def create_llm(cls, provider: str, model: str, **kwargs) -> BaseLanguageModel:
        provider_cls = cls._providers[provider]
        return provider_cls().create_llm(model, **kwargs)

    @classmethod
    def register_provider(cls, name: str, provider_cls: Type[ModelProviderBase]):
        """런타임 프로바이더 등록 (플러그인 확장점)"""
        cls._providers[name] = provider_cls
```

#### 신규 프로바이더 추가 방법

1. `ModelProviderBase`를 상속한 클래스 작성 (`neos/providers/custom.py`)
2. `LLMFactory.register_provider("custom", CustomProvider)` 호출
3. `LLM_PROVIDER=custom` 환경변수 설정

#### 설정

```bash
LLM_PROVIDER=anthropic          # 기본 프로바이더
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_DEFAULT_MODEL=llama3.1:8b
```

---

### Phase 8 — A2UI (Agent-to-UI)

**목표:** OpenClaw의 Control UI 개념을 확장하여, AI 에이전트가 직접 사용자 인터페이스(폼/위젯)를 동적으로 생성하고 사용자 입력을 받아 다음 워크플로우 단계로 전달하는 A2UI(Agent-to-UI) 시스템 구현.

#### 핵심 파일

| 파일 | 역할 |
|------|------|
| `neos/workflow/processors/ui_frame_generator.py` | `UIFrameGenerator` — Claude tool_use로 UIFrame JSON 생성 |
| `neos/api/handlers/ui_submit_handlers.py` | `POST /api/v1/ui/submit` — 폼 제출 처리 |
| `neos/api/models/ui_components.py` | `UIFrame` Pydantic 모델 |
| `web/components/ui-frame/UIFrameForm.tsx` | 폼 렌더러 (8가지 컴포넌트 타입) |
| `web/components/ui-frame/UIFrameRenderer.tsx` | UIFrame SSE 이벤트 수신 → 폼 표시 |
| `web/app/(chat)/api/ui-submit/route.ts` | 백엔드 SSE 프록시 Route Handler |
| `web/lib/open-responses-types.ts` | `UIFramePayload`, `NeosUIFrameEvent` TypeScript 타입 |
| `db/migrations/024_add_ui_frame_sessions.sql` | `ui_frame_sessions` 테이블 |

#### 전체 A2UI 흐름

```
사용자 쿼리 (needs_ui=True 감지)
    │
    ▼
QueryClassifier → needs_ui=True
    │
    ▼  [A2UI_ENABLED=true + needs_ui=true → 단락 경로]
UI_FRAME_GENERATOR 노드
    │
    ├─ UIFrameGenerator.generate(state)
    │    │
    │    ├─ _call_llm(query, context, session_id)
    │    │    └─ Claude tool_use "generate_ui_frame"
    │    │         → { intent, components[] }
    │    │
    │    ├─ UIFrame Pydantic 검증 (실패 시 fallback 단일 텍스트 필드)
    │    │
    │    ├─ _save_frame_session(frame_id, ..., expires_at)
    │    │    └─ DB: ui_frame_sessions INSERT
    │    │
    │    └─ event_handler.on_ui_frame(ui_frame_dict)
    │         └─ SSE: event=ui_frame, data={ frame_id, components, ... }
    │
    ▼ [UI_FRAME_GENERATOR → END]

    [FE: UIFrameRenderer가 SSE "ui_frame" 이벤트 수신]
    │
    ▼
UIFrameForm 렌더링
  (text_field / date_picker / time_picker / select /
   multi_select / slider / checkbox / button)
    │
    │ [사용자 폼 입력 후 제출]
    ▼
POST /api/ui-submit (Next.js Route Handler)
    └─ auth() → callBackendAPI → POST /api/v1/ui/submit
         │
         ├─ DB: ui_frame_sessions 조회 (frame_id → original_query)
         │
         ├─ 새 워크플로우 invoke
         │    state = { query: original_query,
         │              ui_submission: form_values,
         │              needs_ui: False }
         │
         └─ SSE 스트림 프록시 (응답을 FE로 전달)

    [UIFrameForm: SSE "completed" 이벤트 → resultText 표시]
```

#### 지원 컴포넌트 타입

| 타입 | 설명 | 분류 | 프론트엔드 컴포넌트 |
|------|------|------|------------------|
| `text_field` | 텍스트 입력 | 입력형 | `TextField.tsx` |
| `date_picker` | 날짜 선택 | 입력형 | `DatePicker.tsx` |
| `time_picker` | 시간 선택 | 입력형 | `TimePicker.tsx` |
| `select` | 단일 선택 드롭다운 | 입력형 | `SelectField.tsx` |
| `multi_select` | 다중 선택 드롭다운 | 입력형 | `MultiSelect.tsx` |
| `slider` | 범위 슬라이더 | 입력형 | `SliderField.tsx` |
| `checkbox` | 체크박스 | 입력형 | `CheckboxField.tsx` |
| `file_upload` | 파일 업로드 | 입력형 | `FileUpload.tsx` |
| `button` | 버튼 | 액션형 | `ButtonField.tsx` |
| `form` | 폼 컨테이너 | 액션형 | `Form.tsx` |
| `card` | 카드 표시 | 표시형 | `Card.tsx` |
| `chart` | 차트 표시 | 표시형 | `Chart.tsx` |
| `table` | 테이블 표시 | 표시형 | `Table.tsx` |
| `progress` | 진행률 표시 | 표시형 | `Progress.tsx` |
| `divider` | 구분선 | 표시형 | Shadcn `Separator` |

#### UIFrame tool_use 스키마 (Claude에게 전달)

```json
{
  "name": "generate_ui_frame",
  "input_schema": {
    "properties": {
      "intent": { "type": "string" },
      "components": {
        "items": {
          "properties": {
            "id":            { "type": "string" },
            "type":          { "enum": ["text_field", "date_picker", ...] },
            "label":         { "type": "string" },
            "placeholder":   { "type": "string" },
            "required":      { "type": "boolean" },
            "options":       { "type": "array" },
            "min/max/step":  { "type": "number" },
            "default_value": {}
          }
        }
      }
    }
  }
}
```

#### DB 변경 (024)

```sql
CREATE TABLE IF NOT EXISTS ui_frame_sessions (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    frame_id        UUID         UNIQUE NOT NULL,
    session_id      VARCHAR(255) NOT NULL,
    user_id         VARCHAR(255) REFERENCES users(user_id) ON DELETE SET NULL,
    conversation_id UUID,
    original_query  TEXT         NOT NULL,
    frame_data      JSONB        DEFAULT '{}',   -- 디버깅용 전체 UIFrame JSON
    expires_at      TIMESTAMP    NOT NULL,
    created_at      TIMESTAMP    DEFAULT NOW()
);
```

#### 설정

```bash
A2UI_ENABLED=true                             # 피처 플래그
A2UI_LLM_MODEL=claude-haiku-4-5-20251001      # UIFrame 생성 모델
A2UI_MAX_COMPONENTS=10                        # 최대 컴포넌트 수
A2UI_FRAME_TIMEOUT=300                        # 세션 만료 시간(초)
```

---

## 4. 전체 데이터 흐름 다이어그램

```mermaid
graph TD
    %% 외부 채널 진입점
    TG[Telegram Bot] -->|polling| TGA[TelegramAdapter]
    DC[Discord Bot] -->|polling| DCA[DiscordAdapter stub]
    SL[Slack Bot] -->|events| SLA[SlackAdapter stub]
    API[REST API /api/v1/chat] --> GW

    TGA -->|ChannelMessage| GW[ChannelGateway]
    DCA -->|ChannelMessage| GW
    SLA -->|ChannelMessage| GW

    %% Gateway → Workflow
    GW -->|execute_workflow| WF[MultiAgentWorkflow LangGraph]

    %% 워크플로우 내부 핵심 분기
    WF --> QC[QueryClassifier]
    QC -->|needs_ui=true + A2UI_ENABLED| UFG[UIFrameGenerator]
    QC -->|pending_approval| EA[EXECUTION_APPROVAL interrupt_before]
    QC -->|normal| STS[SKILL_TOOL_SELECTOR]

    %% A2UI 경로
    UFG -->|SSE ui_frame| FE_FORM[UIFrameForm FE]
    FE_FORM -->|POST /ui/submit| UIS[ui_submit_handler]
    UIS -->|new invoke needs_ui=false| WF

    %% Approval 경로
    EA -->|SSE approval_request| USER[사용자]
    USER -->|POST /approval/respond| AH[approval_handler]
    AH -->|aupdate_state + astream None| AP[ApprovalProcessor]
    AP -->|approved| STS
    AP -->|rejected| RG[ResponseGenerator]

    %% 정상 경로
    STS --> HG[HypothesisGeneration]
    HG --> RES[Research Pipeline]
    RES --> RG

    %% 스케줄러
    CB[Celery Beat 매 1분] --> POLL[poll_and_run_scheduled_tasks]
    POLL -->|run_workflow_task.delay| WF
    WF -->|final_response| CH_SEND[채널 전송]

    %% DB
    WF --> DB[(PostgreSQL)]
    POLL --> DB
    UFG --> DB
    AH --> DB

    %% 설정
    LF[LLMFactory 레지스트리] -->|AnthropicProvider| WF
    LF -->|OpenAIProvider| WF
    LF -->|OllamaProvider| WF
    LF -->|GeminiProvider| WF
```

---

## 5. DB 마이그레이션 참조

| 파일 | Phase | 변경 내용 |
|------|-------|----------|
| `db/migrations/021_add_channel_source.sql` | Phase 1 | `query_history`에 `channel_source`, `external_channel_id` 추가 |
| `db/migrations/022_add_tool_approval_allowlist.sql` | Phase 2 | `tool_approval_allowlist` 테이블 신규 생성 |
| `db/migrations/023_add_scheduled_tasks.sql` | Phase 4 | `scheduled_tasks` 테이블 신규 생성 (업데이트 트리거 포함) |
| `db/migrations/024_add_ui_frame_sessions.sql` | Phase 8 | `ui_frame_sessions` 테이블 신규 생성 |

마이그레이션 적용 순서:

```bash
# Alembic으로 자동 적용
alembic upgrade head

# 또는 수동 적용 (순서 중요)
psql $DATABASE_URL -f db/migrations/021_add_channel_source.sql
psql $DATABASE_URL -f db/migrations/022_add_tool_approval_allowlist.sql
psql $DATABASE_URL -f db/migrations/023_add_scheduled_tasks.sql
psql $DATABASE_URL -f db/migrations/024_add_ui_frame_sessions.sql
```

---

## 6. 설정 참조 테이블

### 전체 환경변수 목록 (OpenClaw 병합 관련)

| 변수 | 기본값 | Phase | 설명 |
|------|--------|-------|------|
| `CHANNEL_TELEGRAM_ENABLED` | `false` | 1 | Telegram 채널 활성화 |
| `CHANNEL_TELEGRAM_BOT_TOKEN` | — | 1 | Telegram Bot API 토큰 |
| `CHANNEL_DISCORD_ENABLED` | `false` | 1 | Discord 채널 활성화 |
| `CHANNEL_DISCORD_BOT_TOKEN` | — | 1 | Discord Bot 토큰 |
| `CHANNEL_SLACK_ENABLED` | `false` | 1 | Slack 채널 활성화 (Socket Mode) |
| `CHANNEL_SLACK_BOT_TOKEN` | — | 1 | Slack Bot 토큰 |
| `CHANNEL_SLACK_APP_TOKEN` | — | 1 | Slack App 소켓 모드 토큰 |
| `CHANNEL_BOT_USER_ID` | — | 1 | 채널 요청 매핑용 서비스 계정 ID |
| `EXECUTION_APPROVAL_ENABLED` | `false` | 2 | 실행 승인 시스템 활성화 |
| `APPROVAL_REQUIRED_SKILLS` | (목록) | 2 | 승인 필요 스킬 이름 목록 |
| `APPROVAL_TIMEOUT_SECONDS` | `60` | 2 | 승인 대기 타임아웃 (초) |
| `CRON_ENABLED` | `true` | 4 | Cron 스케줄 스킬 활성화 |
| `CRON_DEFAULT_TIMEZONE` | `UTC` | 4 | 기본 타임존 |
| `CRON_MAX_TASKS_PER_USER` | `20` | 4 | 사용자당 최대 스케줄 태스크 수 |
| `LLM_PROVIDER` | `anthropic` | 5 | 기본 LLM 프로바이더 |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | 5 | Ollama 서버 URL |
| `OLLAMA_DEFAULT_MODEL` | `llama3.1:8b` | 5 | Ollama 기본 모델 |
| `A2UI_ENABLED` | `false` | 8 | A2UI 피처 플래그 |
| `A2UI_LLM_MODEL` | `claude-haiku-4-5-20251001` | 8 | UIFrame 생성 LLM 모델 |
| `A2UI_MAX_COMPONENTS` | `10` | 8 | UIFrame 최대 컴포넌트 수 |
| `A2UI_FRAME_TIMEOUT` | `300` | 8 | UI 세션 만료 시간 (초) |

### 권장 활성화 순서 (프로덕션)

```bash
# 1단계: 채널 어댑터 (Telegram / Discord / Slack 모두 구현 완료)
CHANNEL_TELEGRAM_ENABLED=true
# CHANNEL_DISCORD_ENABLED=true   # discord.py>=2.3.0 설치 후 활성화
# CHANNEL_SLACK_ENABLED=true     # slack-bolt>=1.18.0 설치 후 활성화

# 2단계: 실행 승인 (보안 강화)
EXECUTION_APPROVAL_ENABLED=true

# 3단계: Cron 스케줄 (기본 활성화 상태)
CRON_ENABLED=true

# 4단계: 모델 프로바이더 (필요 시 교체)
LLM_PROVIDER=anthropic

# 5단계: A2UI — 충분한 테스트 후 마지막으로 활성화
A2UI_ENABLED=true
```

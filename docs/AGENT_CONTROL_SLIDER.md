# Agent Control Slider

작성일: 2026-05-17  

## 개요

Agent Control Slider는 사용자가 요청 단위로 에이전트 워크플로우의 자율성 수준을 제어하는 기능이다. 채팅 헤더의 selector에서 `Manual`, `Assisted`, `Autonomous` 중 하나를 고르면 해당 값이 프론트엔드 요청, 백엔드 API 계층, LangGraph workflow state, approval interrupt, cache key까지 전달된다.

이 기능의 핵심 목표는 단순한 UI 옵션이 아니라 실행 정책 제어다. 즉, 같은 질문이라도 자율성 레벨에 따라 다음 동작이 달라진다.

- 에이전트/스킬/도구 실행 전 사용자 승인을 요구할지
- HyperDeep/ROMA 같은 recursive research 경로에 자동 진입할지
- adaptive replan을 자동 수행할지
- cache hit를 어느 정책 범위에서 허용할지

최종 구현은 1차/2차 코드 리뷰 지적사항을 반영해, 특히 Manual 모드가 실제 실행 대상인 `required_agents`를 승인 게이트로 막도록 보강했다.

## 자율성 레벨

| Level | 이름 | 의미 | 주요 동작 |
| --- | --- | --- | --- |
| `0` | Manual | 에이전트 액션 전 사용자 승인을 요구한다. | `required_agents`, `selected_skills`, `selected_tools` 실행 계획을 승인 대상으로 계산한다. HyperDeep/ROMA 자동 진입과 autonomous replan을 차단한다. |
| `1` | Assisted | 민감하거나 설정된 액션만 승인받는다. 기본값이다. | `settings.APPROVAL_REQUIRED_SKILLS`에 포함된 액션만 approval 대상이다. |
| `2` | Autonomous | 가능한 작업을 중단 없이 자동 진행한다. | approval 대상 목록을 비운다. recursive research와 replan을 허용한다. |

값 해석 규칙은 다음과 같다.

- 요청 값이 없으면 `settings.DEFAULT_AUTONOMY_LEVEL`을 사용한다.
- `0`, `1`, `2` 및 문자열 `"0"`, `"1"`, `"2"`는 유효값으로 처리한다.
- 범위를 벗어난 값이나 파싱할 수 없는 값은 안전 기본값인 `ASSISTED(1)`로 fallback한다.
- 저장된 사용자 preference가 `"bad"` 같은 비정상 문자열이어도 조회 API는 500을 내지 않고 `ASSISTED(1)`로 fallback한다.

## 전체 흐름

```text
Chat header selector
  -> useAgentAutonomy()
  -> localStorage + /api/autonomy-preference
  -> /api/chat or /api/v1/query or /api/v1/query/stream
  -> WorkflowService.resolve_autonomy_level()
  -> MultiAgentWorkflow._create_initial_state()
  -> AutonomyPolicy
  -> approval gate / routing / cache scope
```

채팅 경로에서는 다음 흐름도 추가된다.

```text
Workflow approval interrupt
  -> NeosApprovalRequestEvent
  -> message approval card
  -> POST /api/approval/respond
  -> backend POST /api/v1/approval/respond
  -> GET /api/approval/stream/{sessionId}
  -> backend GET /api/v1/approval/stream/{session_id}
  -> resumed workflow result appended to current assistant message
```

## 주요 특징

### 1. Manual 모드의 실제 실행 게이트

2차 코드 리뷰 전에는 approval 대상 계산이 `selected_skills`만 보고 있었다. 하지만 실제 오케스트레이터 실행은 `required_agents`를 기준으로 진행되기 때문에, `required_agents=["realtime_info_search"]`가 있어도 `selected_skills=[]`이면 Manual 모드에서 검색 에이전트가 승인 없이 실행될 수 있었다.

현재 구현은 `AutonomyPolicy.get_approval_required_actions()`로 승인 대상 계산을 통합한다.

승인 대상 입력:

- `required_agents`: query classifier가 선택한 workflow agent 목록
- `selected_skills`: skill selector가 선택한 skill 목록
- `selected_tools`: tool selector가 선택한 tool 목록

Manual 모드에서는 위 실행 계획 전체를 승인 대상으로 본다. Assisted 모드에서는 실행 계획 중 `settings.APPROVAL_REQUIRED_SKILLS`에 포함된 액션만 승인 대상으로 본다. Autonomous 모드에서는 빈 목록을 반환한다.

관련 파일:

- `neos/workflow/autonomy/policy.py`
- `neos/workflow/graph.py`
- `tests/test_workflow_graph.py`

### 2. Approval interrupt와 resume

LangGraph의 checkpointer 기반 interrupt를 사용해 approval flow를 구성한다.

1. `skill_tool_selector` 노드가 실행 계획을 만든다.
2. `AutonomyPolicy`가 승인 필요 액션을 계산한다.
3. allowlist에 없는 액션이면 `pending_approvals`를 state에 설정한다.
4. graph가 `execution_approval` 노드 진입 전 interrupt된다.
5. SSE 또는 chat stream으로 approval request가 전달된다.
6. 사용자가 승인/거부하면 backend approval API가 graph state를 업데이트하고 resume한다.

Approval request 구조:

```json
{
  "request_id": "uuid",
  "skill_name": "realtime_info_search",
  "params": {},
  "timeout_seconds": 300,
  "requested_at": "2026-05-17T00:00:00"
}
```

Backend approval API:

```text
POST /api/v1/approval/respond
GET  /api/v1/approval/stream/{session_id}
```

Frontend proxy routes:

```text
POST /api/approval/respond
GET  /api/approval/stream/{sessionId}
```

관련 파일:

- `neos/api/handlers/approval_handlers.py`
- `neos/api/services/chat_stream_pipeline.py`
- `web/app/(chat)/api/approval/respond/route.ts`
- `web/app/(chat)/api/approval/stream/[sessionId]/route.ts`
- `web/components/message.tsx`

### 3. Chat UI approval UX

Chat stream이 `neos:approval_request` 이벤트를 받으면 assistant message metadata에 다음 값을 저장한다.

```ts
{
  responseStatus: "incomplete",
  approval_requests: ApprovalRequest[],
  approval_session_id: string
}
```

메시지 UI는 approval card를 렌더링하고 `Approve`, `Reject` 버튼을 제공한다. 사용자가 응답하면 frontend는 Next.js route handler를 통해 backend approval API를 호출하고, 이어서 resume stream을 구독한다. resumed workflow가 완료되면 현재 assistant message의 text part를 최종 응답으로 갱신하고 approval card를 비운다.

Interrupted 상태의 assistant placeholder도 DB에 저장한다. 따라서 새로고침 후에도 pending approval 표시를 복원할 수 있다.

관련 파일:

- `neos/api/services/chat_stream_pipeline.py`
- `web/hooks/use-chat-stream.ts`
- `web/components/message.tsx`
- `web/lib/types.ts`
- `web/lib/open-responses-types.ts`

### 4. REST query interrupted 응답 처리

REST `/api/v1/query`는 approval interrupt 결과를 일반 성공 응답으로 강제 변환하지 않는다. Manual/Assisted 모드에서 approval이 필요한 경우 `202 Accepted`와 함께 interrupted payload를 반환한다.

예시 응답:

```json
{
  "success": true,
  "interrupted": true,
  "response": null,
  "session_id": "session-id",
  "metadata": {},
  "execution_time_ms": 42,
  "quality_score": 0.0,
  "errors": [],
  "pending_approvals": [
    {
      "request_id": "approval-id",
      "skill_name": "realtime_info_search"
    }
  ]
}
```

이 응답은 클라이언트가 approval API를 통해 resume해야 하는 상태를 명확히 표현한다.

관련 파일:

- `neos/api/services/query_service.py`
- `neos/api/handlers/query_handlers.py`
- `tests/api/services/test_query_service_autonomy_cache.py`
- `tests/api/handlers/test_query_handlers_autonomy.py`

### 5. Checkpointer/stateless graph 캐시 분리

Approval interrupt는 checkpointer graph에서만 정상 동작한다. 기존에는 `MultiAgentWorkflow`가 graph를 하나만 전역 캐시해, 프로세스에서 stateless graph가 먼저 초기화되면 이후 checkpointer 요청도 stateless graph를 재사용할 위험이 있었다.

현재는 `use_checkpointer` 값별로 graph를 분리해 캐시한다.

```python
self._graphs_by_checkpointer: dict[bool, Any] = {}
```

`_ensure_graph_initialized(use_checkpointer=...)`는 요청한 mode의 graph를 가져오거나 새로 compile하고, `self.graph`를 현재 요청 mode의 graph로 설정한다.

관련 파일:

- `neos/workflow/graph.py`
- `tests/test_workflow_graph.py`

### 6. Cache scope와 bypass cache

자율성 레벨은 실행 정책이므로 cache key와 smart cache metadata에도 포함된다.

반영 범위:

- QueryService outer cache key에 `autonomy_level` 포함
- workflow Redis cache key에 `autonomy_level` 포함
- smart cache 저장 metadata에 `autonomy_level` 포함
- smart cache 조회 시 `metadata_filter={"autonomy_level": level}` 적용

`bypass_cache=True`는 outer query cache뿐 아니라 workflow 내부 smart cache와 Redis cache 조회도 건너뛴다. 따라서 Manual 검증, E2E 테스트, 새 실행 강제 요청에서 이전 정책의 cached response가 approval을 우회하지 않는다.

관련 파일:

- `neos/api/services/query_service.py`
- `neos/api/services/workflow_service.py`
- `neos/workflow/graph.py`
- `neos/utils/smart_cache_manager.py`
- `tests/api/services/test_query_service_autonomy_cache.py`
- `tests/test_workflow_graph.py`

### 7. Preference 저장과 fallback

사용자 preference는 기존 `users.preferences` JSONB 컬럼에 저장한다.

Backend API:

```text
GET /api/v1/autonomy/preference
PUT /api/v1/autonomy/preference
```

Frontend proxy:

```text
GET /api/autonomy-preference
PUT /api/autonomy-preference
```

Frontend hook은 `localStorage`와 backend preference를 동기화한다.

- localStorage key: `neos_autonomy_level`
- backend 조회 실패 또는 미인증 시 `{ autonomy_level: null, source: "fallback" }`를 반환한다.
- hook은 `null`을 서버 저장값으로 취급하지 않으므로 기존 localStorage 선택을 덮어쓰지 않는다.

관련 파일:

- `neos/api/handlers/autonomy_handlers.py`
- `web/hooks/use-agent-autonomy.ts`
- `web/app/(chat)/api/autonomy-preference/route.ts`
- `db/migrations/030_add_autonomy_preferences.sql`

## Backend 구현 상세

### Domain model

`AutonomyLevel`은 `int, Enum`으로 정의되어 Pydantic request, JSON, LangGraph state와 호환된다.

```python
class AutonomyLevel(int, Enum):
    MANUAL = 0
    ASSISTED = 1
    AUTONOMOUS = 2
```

`AgentState`에는 `autonomy_level: Optional[int]`가 추가되어 workflow state 안에서 정책 판단에 사용된다.

### Policy

`AutonomyPolicy`는 자율성 레벨을 workflow policy로 변환한다.

주요 메서드:

- `get_approval_required_skills()`
- `get_approval_required_actions(required_agents, selected_skills, selected_tools)`
- `requires_approval(skill_name)`
- `allows_recursive_research()`
- `allows_autonomous_replan()`
- `description()`

`get_approval_required_skills()`는 기존 설정 기반 approval 대상 목록을 레벨별로 계산한다. `get_approval_required_actions()`는 실제 실행 계획을 기준으로 이번 요청에서 승인해야 하는 action만 반환한다.

### Routing

라우팅 정책은 `routing/` 모듈로 분리되어 있다.

- `neos/workflow/routing/orchestrator_router.py`
- `neos/workflow/routing/quality_router.py`

Manual 모드에서는 다음 자동화가 차단된다.

- HyperDeep recursive route
- ROMA recursive route
- adaptive replan

Approval pending 상태는 오케스트레이터 라우팅보다 우선한다.

### WorkflowService

`WorkflowService`는 API 계층과 `multi_agent_workflow` 사이의 실행 래퍼다.

역할:

- request preference에서 autonomy level parsing
- invalid value safe fallback
- `bypass_cache`를 workflow input에 명시 전달
- `use_checkpointer=True` 경로에서 approval interrupt를 받을 수 있게 호출

### Stream handlers

SSE `/api/v1/query/stream`은 `body.preferences`를 기준으로 `bypass_cache`와 `autonomy_level`을 읽는다. 기존 FastAPI `Request` 객체에서 `preferences`를 읽던 오류는 제거되었다.

WebSocket query stream도 `preferences.autonomy_level`을 workflow 실행에 전달한다.

## Frontend 구현 상세

### Selector

`AgentAutonomySelector`는 채팅 헤더에 통합되어 있다.

사용자에게 보이는 의미:

- Manual: Ask before agent actions
- Assisted: Ask for sensitive actions
- Autonomous: Run agent actions without prompts

관련 파일:

- `web/components/agent-autonomy-selector.tsx`
- `web/components/chat-header.tsx`
- `web/components/chat.tsx`

### Hook

`useAgentAutonomy()`는 다음 책임을 가진다.

- 기본값 `1`
- localStorage 복원
- backend preference 조회
- selector 변경 시 localStorage와 backend preference 업데이트
- backend 조회 실패 시 localStorage 선택 유지

관련 파일:

- `web/hooks/use-agent-autonomy.ts`

### Chat request pipeline

채팅 요청은 다음 경로로 autonomy level을 전달한다.

```text
useChatStream({ autonomyLevel })
  -> POST /api/chat { autonomy_level }
  -> backend chat stream request metadata.autonomy_level
  -> ChatStreamPipeline._run_workflow(... autonomy_level)
  -> MultiAgentWorkflow.execute_workflow()
```

관련 파일:

- `web/hooks/use-chat-stream.ts`
- `web/app/(chat)/api/chat/schema.ts`
- `web/app/(chat)/api/chat/route.ts`
- `neos/api/services/chat_stream_pipeline.py`

## API 요약

### Query

```http
POST /api/v1/query
Content-Type: application/json

{
  "query": "최신 AI 뉴스를 검색해줘",
  "session_id": "session-id",
  "autonomy_level": 0,
  "preferences": {
    "bypass_cache": true
  }
}
```

Approval이 필요 없으면 일반 `QueryResponse`를 반환한다. Approval이 필요하면 `202 Accepted`와 interrupted payload를 반환한다.

### Query Stream

```http
POST /api/v1/query/stream
Content-Type: application/json

{
  "query": "최신 AI 뉴스를 검색해줘",
  "session_id": "session-id",
  "autonomy_level": 0,
  "preferences": {
    "bypass_cache": true
  },
  "stream_options": {
    "include_heartbeat": true
  }
}
```

Approval이 필요하면 SSE로 `approval_request` 이벤트가 전달된다.

### Preference

```http
GET /api/v1/autonomy/preference
PUT /api/v1/autonomy/preference
```

PUT body:

```json
{
  "autonomy_level": 2
}
```

### Approval

```http
POST /api/v1/approval/respond
GET /api/v1/approval/stream/{session_id}
```

POST body:

```json
{
  "session_id": "session-id",
  "request_id": "approval-id",
  "decision": "approved",
  "add_to_allowlist": false,
  "skill_name": "realtime_info_search"
}
```

## 주요 파일 목록

Backend:

- `neos/workflow/enums.py`
- `neos/workflow/state.py`
- `neos/workflow/autonomy/policy.py`
- `neos/workflow/autonomy/middleware.py`
- `neos/workflow/routing/orchestrator_router.py`
- `neos/workflow/routing/quality_router.py`
- `neos/workflow/graph.py`
- `neos/api/services/workflow_service.py`
- `neos/api/services/query_service.py`
- `neos/api/services/chat_stream_pipeline.py`
- `neos/api/handlers/query_handlers.py`
- `neos/api/handlers/workflow_stream_handlers.py`
- `neos/api/handlers/autonomy_handlers.py`
- `neos/api/handlers/approval_handlers.py`
- `neos/api/models/query_models.py`
- `neos/api/models/open_responses.py`
- `neos/utils/smart_cache_manager.py`
- `db/migrations/030_add_autonomy_preferences.sql`

Frontend:

- `web/lib/types.ts`
- `web/lib/open-responses-types.ts`
- `web/lib/stream-types.ts`
- `web/hooks/use-agent-autonomy.ts`
- `web/hooks/use-chat-stream.ts`
- `web/components/agent-autonomy-selector.tsx`
- `web/components/chat-header.tsx`
- `web/components/chat.tsx`
- `web/components/message.tsx`
- `web/components/elements/tool.tsx`
- `web/app/(chat)/api/autonomy-preference/route.ts`
- `web/app/(chat)/api/approval/respond/route.ts`
- `web/app/(chat)/api/approval/stream/[sessionId]/route.ts`
- `web/app/(chat)/api/chat/schema.ts`
- `web/app/(chat)/api/chat/route.ts`

Tests:

- `tests/workflow/autonomy/test_policy.py`
- `tests/workflow/routing/test_autonomy_routing.py`
- `tests/api/services/test_workflow_service.py`
- `tests/api/services/test_query_service_autonomy_cache.py`
- `tests/api/services/test_chat_stream_pipeline_autonomy.py`
- `tests/api/handlers/test_query_handlers_autonomy.py`
- `tests/api/handlers/test_workflow_stream_handlers_autonomy.py`
- `tests/api/handlers/test_autonomy_handlers.py`
- `tests/test_workflow_graph.py`

## 테스트 및 검증

최종 수정 후 확인한 focused backend test:

```bash
python -m pytest \
  tests/api/services/test_workflow_service.py \
  tests/workflow/autonomy/test_policy.py \
  tests/workflow/routing/test_autonomy_routing.py \
  tests/api/services/test_query_service_autonomy_cache.py \
  tests/api/services/test_chat_stream_pipeline_autonomy.py \
  tests/api/handlers/test_query_handlers_autonomy.py \
  tests/api/handlers/test_workflow_stream_handlers_autonomy.py \
  tests/api/handlers/test_autonomy_handlers.py \
  tests/test_workflow_graph.py::TestWorkflowGraphCreation::test_ensure_graph_initializes_checkpointer_modes_separately \
  tests/test_workflow_graph.py::TestCacheManagement::test_manual_approval_uses_required_agents_even_without_selected_skills \
  tests/test_workflow_graph.py::TestCacheManagement::test_execute_workflow_bypass_cache_skips_cache_reads \
  -q
```

결과:

```text
26 passed
```

Frontend type check:

```bash
pnpm exec tsc --noEmit
```

결과:

```text
exit code 0
```

Python compile check:

```bash
python -m compileall neos/workflow neos/api neos/config/settings.py
```

결과:

```text
exit code 0
```

Whitespace check:

```bash
git diff --check
```

결과:

```text
exit code 0
```

참고: local test fixture가 DB 초기화를 시도하면서 sandbox 권한 관련 로그를 출력할 수 있다. 위 focused suite는 해당 로그와 무관하게 exit code 0으로 통과했다.

## 운영 설정

기본 자율성 레벨은 환경 변수로 지정한다.

```env
DEFAULT_AUTONOMY_LEVEL=1
```

값:

- `0`: Manual
- `1`: Assisted
- `2`: Autonomous

Execution approval 자체는 기존 설정을 따른다.

- `EXECUTION_APPROVAL_ENABLED`
- `APPROVAL_REQUIRED_SKILLS`
- `APPROVAL_TIMEOUT_SECONDS`

Manual/Assisted 모드의 approval interrupt가 실제로 동작하려면 checkpointer graph가 필요하다. Chat pipeline과 query workflow는 checkpointer 경로를 사용한다.

## 구현상 주의점

### Manual은 "모든 Python 노드 중단"이 아니다

Manual은 workflow 내부의 모든 함수 호출을 중단하는 모드가 아니다. 사용자가 승인해야 하는 범위는 실행 계획에 포함된 agent/skill/tool action이다. query classification, context processing, response formatting 같은 내부 graph node는 approval 대상이 아니다.

### Cache는 실행 정책의 일부다

자율성 레벨이 다른 요청은 approval 정책이 다르므로 cache를 공유하면 안 된다. 따라서 cache key와 smart cache metadata에 `autonomy_level`이 들어간다.

### Invalid 값은 안전하게 낮춘다

운영 기본값이 `2`인 환경에서도 malformed request가 Autonomous로 승격되면 안 된다. 그래서 "값 없음"은 configured default, "잘못된 값"은 Assisted로 처리한다.

### Chat approval은 resume stream까지 한 세트다

Approval card를 보여주는 것만으로는 Manual 모드가 완성되지 않는다. 사용자가 approve/reject를 누른 뒤 backend workflow를 resume하고, resume stream의 final response를 현재 assistant message에 반영해야 한다.

## 남은 확인/후속 작업

아래 항목은 코드상 경로가 마련되어 있으나, 실제 환경에서 E2E로 확인하면 좋다.

- 실제 DB에 `db/migrations/030_add_autonomy_preferences.sql` 적용
- 브라우저에서 Chat header selector 시각 확인
- Manual 모드에서 approval card 표시 후 approve/reject resume 확인
- REST `/api/v1/query`의 `202 interrupted` 응답을 API client에서 처리하는 UX 정리
- staging 환경에서 `/api/v1/query/stream` Manual/Assisted/Autonomous별 cache miss/hit와 approval event 확인
